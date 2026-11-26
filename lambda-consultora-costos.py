"""
Lambda que consulta la AWS Price List API y devuelve los costos de un servicio:
  - Corto plazo: On-Demand (pago por uso).
  - Largo plazo: Reserved (1 y 3 años; No Upfront / Partial Upfront / All Upfront).

Evento de entrada (invocacion directa o API Gateway con body JSON / query string):
{
  "service": "ec2",                 # codigo (AmazonEC2) o alias/nombre ("ec2", "s3", "lambda", "rds")
  "region": "us-east-1",            # opcional, por defecto us-east-1
  "filters": {"instanceType": "t3.micro", "operatingSystem": "Linux"},  # opcional, atributos del producto
  "max_results": 10,                # opcional, por defecto 10 (maximo 100)
  "list_services": false            # opcional, true devuelve los codigos de servicio disponibles
}

Permisos IAM requeridos: pricing:DescribeServices, pricing:GetProducts, pricing:GetAttributeValues.
La API de Pricing solo existe en us-east-1, ap-south-1 y eu-central-1.
"""

import json
import os
from decimal import Decimal, InvalidOperation

import boto3
from botocore.exceptions import BotoCoreError, ClientError

PRICING_REGION = os.environ.get("PRICING_API_REGION", "us-east-1")
DEFAULT_REGION = os.environ.get("DEFAULT_REGION", "us-east-1")
HOURS_PER_MONTH = Decimal("730")
HOURS_PER_YEAR = Decimal("8760")

# Alias comunes -> ServiceCode oficial
SERVICE_ALIASES = {
    "ec2": "AmazonEC2",
    "s3": "AmazonS3",
    "rds": "AmazonRDS",
    "lambda": "AWSLambda",
    "dynamodb": "AmazonDynamoDB",
    "cloudfront": "AmazonCloudFront",
    "ebs": "AmazonEC2",
    "elasticache": "AmazonElastiCache",
    "redshift": "AmazonRedshift",
    "sqs": "AWSQueueService",
    "sns": "AmazonSNS",
    "eks": "AmazonEKS",
    "cloudwatch": "AmazonCloudWatch",
    "opensearch": "AmazonES",
    "bedrock": "AmazonBedrock",
}

_client = None


def _pricing():
    global _client
    if _client is None:
        _client = boto3.client("pricing", region_name=PRICING_REGION)
    return _client


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _parse_event(event):
    """Acepta invocacion directa o API Gateway (body / queryStringParameters)."""
    if not isinstance(event, dict):
        return {}
    params = {}
    if event.get("queryStringParameters"):
        params.update(event["queryStringParameters"])
    body = event.get("body")
    if body:
        try:
            params.update(json.loads(body) if isinstance(body, str) else body)
        except json.JSONDecodeError:
            raise ValueError("El body no es JSON valido.")
    if not params:
        params = event
    if isinstance(params.get("filters"), str):
        params["filters"] = json.loads(params["filters"])
    return params


def _list_services():
    services = []
    paginator = _pricing().get_paginator("describe_services")
    for page in paginator.paginate():
        services.extend(s["ServiceCode"] for s in page["Services"])
    return sorted(services)


def _resolve_service(name):
    """Resuelve alias o coincidencia parcial al ServiceCode oficial."""
    key = name.strip().lower()
    if key in SERVICE_ALIASES:
        return SERVICE_ALIASES[key]
    services = _list_services()
    for code in services:
        if code.lower() == key:
            return code
    matches = [c for c in services if key in c.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"Servicio '{name}' no encontrado. Usa list_services=true.")
    raise ValueError(f"Servicio '{name}' ambiguo. Coincidencias: {matches[:15]}")


def _get_products(service_code, region, filters, max_results):
    flt = [{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}]
    for field, value in (filters or {}).items():
        flt.append({"Type": "TERM_MATCH", "Field": field, "Value": str(value)})

    products, token = [], None
    while len(products) < max_results:
        kwargs = {
            "ServiceCode": service_code,
            "Filters": flt,
            "MaxResults": min(100, max_results - len(products)),
        }
        if token:
            kwargs["NextToken"] = token
        resp = _pricing().get_products(**kwargs)
        products.extend(json.loads(p) for p in resp.get("PriceList", []))
        token = resp.get("NextToken")
        if not token:
            break
    return products


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal(0)


def _price_dimensions(term):
    """Devuelve lista simplificada de dimensiones de precio de un term."""
    dims = []
    for d in term.get("priceDimensions", {}).values():
        usd = _dec(d.get("pricePerUnit", {}).get("USD", "0"))
        dims.append(
            {
                "description": d.get("description"),
                "unit": d.get("unit"),
                "begin_range": d.get("beginRange"),
                "end_range": d.get("endRange"),
                "usd": float(usd),
            }
        )
    return dims


def _summarize_on_demand(terms):
    out = []
    for term in terms.get("OnDemand", {}).values():
        dims = _price_dimensions(term)
        entry = {"plan": "On-Demand", "plazo": "corto", "precios": dims}
        hourly = [d for d in dims if d["unit"] in ("Hrs", "Hour", "hours") and d["usd"] > 0]
        if hourly:
            h = _dec(hourly[0]["usd"])
            entry["estimado_mensual_usd"] = float(h * HOURS_PER_MONTH)
            entry["estimado_anual_usd"] = float(h * HOURS_PER_YEAR)
        out.append(entry)
    return out


def _summarize_reserved(terms, on_demand_hourly):
    out = []
    for term in terms.get("Reserved", {}).values():
        attrs = term.get("termAttributes", {})
        years = 3 if attrs.get("LeaseContractLength", "").startswith("3") else 1
        dims = _price_dimensions(term)
        upfront = sum((_dec(d["usd"]) for d in dims if d["unit"] == "Quantity"), Decimal(0))
        hourly = sum((_dec(d["usd"]) for d in dims if d["unit"] in ("Hrs", "Hour", "hours")), Decimal(0))
        total = upfront + hourly * HOURS_PER_YEAR * years
        entry = {
            "plan": f"Reserved {attrs.get('LeaseContractLength')} / {attrs.get('PurchaseOption')}",
            "plazo": "largo",
            "tipo_oferta": attrs.get("OfferingClass"),
            "duracion": attrs.get("LeaseContractLength"),
            "opcion_pago": attrs.get("PurchaseOption"),
            "pago_inicial_usd": float(upfront),
            "precio_hora_usd": float(hourly),
            "costo_total_termino_usd": float(total),
            "equivalente_mensual_usd": float(total / (years * 12)),
        }
        if on_demand_hourly and on_demand_hourly > 0:
            od_total = on_demand_hourly * HOURS_PER_YEAR * years
            entry["ahorro_vs_on_demand_pct"] = round(float((od_total - total) / od_total * 100), 2)
        out.append(entry)
    out.sort(key=lambda e: e["costo_total_termino_usd"])
    return out


def _summarize_product(product):
    attrs = product.get("product", {}).get("attributes", {})
    terms = product.get("terms", {})
    on_demand = _summarize_on_demand(terms)

    od_hourly = None
    for e in on_demand:
        if "estimado_mensual_usd" in e:
            od_hourly = _dec(e["estimado_mensual_usd"]) / HOURS_PER_MONTH
            break

    keep = (
        "instanceType", "operatingSystem", "tenancy", "preInstalledSw", "capacitystatus",
        "databaseEngine", "deploymentOption", "volumeType", "storageClass", "usagetype",
        "location", "servicename", "productFamily", "vcpu", "memory",
    )
    descr = {k: attrs[k] for k in keep if k in attrs}
    descr["sku"] = product.get("product", {}).get("sku")
    descr["productFamily"] = product.get("product", {}).get("productFamily")

    return {
        "producto": descr,
        "corto_plazo": on_demand,
        "largo_plazo": _summarize_reserved(terms, od_hourly),
    }


def lambda_handler(event, context):
    try:
        params = _parse_event(event)

        if params.get("list_services") in (True, "true", "True", "1"):
            return _response(200, {"servicios": _list_services()})

        service = params.get("service")
        if not service:
            return _response(400, {"error": "Falta el parametro 'service'."})

        region = params.get("region", DEFAULT_REGION)
        filters = params.get("filters") or {}
        if not isinstance(filters, dict):
            return _response(400, {"error": "'filters' debe ser un objeto."})
        try:
            max_results = max(1, min(int(params.get("max_results", 10)), 100))
        except (TypeError, ValueError):
            return _response(400, {"error": "'max_results' debe ser un entero."})

        service_code = _resolve_service(service)
        products = _get_products(service_code, region, filters, max_results)
        if not products:
            return _response(
                404,
                {
                    "error": "Sin resultados. Ajusta 'region' o 'filters'.",
                    "service_code": service_code,
                    "region": region,
                },
            )

        return _response(
            200,
            {
                "service_code": service_code,
                "region": region,
                "moneda": "USD",
                "total_productos": len(products),
                "nota": "Los Savings Plans no se incluyen en get_products; ver Savings Plans Pricing API.",
                "resultados": [_summarize_product(p) for p in products],
            },
        )
    except ValueError as e:
        return _response(400, {"error": str(e)})
    except (ClientError, BotoCoreError) as e:
        return _response(502, {"error": f"Error consultando AWS Pricing: {e}"})
    except Exception as e:  # noqa: BLE001
        return _response(500, {"error": f"Error interno: {e}"})


if __name__ == "__main__":
    # Prueba local: requiere credenciales AWS con permisos de pricing:*
    print(json.dumps(
        lambda_handler({"service": "ec2", "filters": {"instanceType": "t3.micro", "operatingSystem": "Linux",
                                                        "tenancy": "Shared", "preInstalledSw": "NA",
                                                        "capacitystatus": "Used"}, "max_results": 1}, None),
        indent=2, ensure_ascii=False))
