import json
import boto3
 
# La API de precios de AWS solo está disponible en us-east-1
pricing_client = boto3.client('pricing', region_name='us-east-1')
 
 
def obtener_precio_lambda(region='US East (N. Virginia)'):
    """Obtiene el precio por GB-segundo de AWS Lambda."""
    try:
        respuesta = pricing_client.get_products(
            ServiceCode='AWSLambda',
            Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region},
                {'Type': 'TERM_MATCH', 'Field': 'group', 'Value': 'AWS-Lambda-Duration'},
            ],
            MaxResults=1
        )
        if respuesta['PriceList']:
            precio_json = json.loads(respuesta['PriceList'][0])
            terms = precio_json['terms']['OnDemand']
            for term in terms.values():
                for dimension in term['priceDimensions'].values():
                    return {
                        'servicio': 'AWS Lambda',
                        'descripcion': dimension['description'],
                        'precio_usd': dimension['pricePerUnit']['USD'],
                        'unidad': dimension['unit']
                    }
    except Exception as e:
        return {'servicio': 'AWS Lambda', 'error': str(e)}
 
 
def obtener_precio_dynamodb(region='US East (N. Virginia)'):
    """Obtiene el precio de escritura por WCU de DynamoDB."""
    try:
        respuesta = pricing_client.get_products(
            ServiceCode='AmazonDynamoDB',
            Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region},
                {'Type': 'TERM_MATCH', 'Field': 'group', 'Value': 'DDB-WriteUnits'},
            ],
            MaxResults=1
        )
        if respuesta['PriceList']:
            precio_json = json.loads(respuesta['PriceList'][0])
            terms = precio_json['terms']['OnDemand']
            for term in terms.values():
                for dimension in term['priceDimensions'].values():
                    return {
                        'servicio': 'Amazon DynamoDB',
                        'descripcion': dimension['description'],
                        'precio_usd': dimension['pricePerUnit']['USD'],
                        'unidad': dimension['unit']
                    }
    except Exception as e:
        return {'servicio': 'Amazon DynamoDB', 'error': str(e)}
 
 
def obtener_precio_s3(region='US East (N. Virginia)'):
    """Obtiene el precio de almacenamiento por GB de S3."""
    try:
        respuesta = pricing_client.get_products(
            ServiceCode='AmazonS3',
            Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region},
                {'Type': 'TERM_MATCH', 'Field': 'storageClass', 'Value': 'General Purpose'},
                {'Type': 'TERM_MATCH', 'Field': 'volumeType', 'Value': 'Standard'},
            ],
            MaxResults=1
        )
        if respuesta['PriceList']:
            precio_json = json.loads(respuesta['PriceList'][0])
            terms = precio_json['terms']['OnDemand']
            for term in terms.values():
                for dimension in term['priceDimensions'].values():
                    return {
                        'servicio': 'Amazon S3',
                        'descripcion': dimension['description'],
                        'precio_usd': dimension['pricePerUnit']['USD'],
                        'unidad': dimension['unit']
                    }
    except Exception as e:
        return {'servicio': 'Amazon S3', 'error': str(e)}
 
 
def obtener_precio_api_gateway(region='US East (N. Virginia)'):
    """Obtiene el precio por millón de llamadas a API Gateway."""
    try:
        respuesta = pricing_client.get_products(
            ServiceCode='AmazonApiGateway',
            Filters=[
                {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region},
            ],
            MaxResults=1
        )
        if respuesta['PriceList']:
            precio_json = json.loads(respuesta['PriceList'][0])
            terms = precio_json['terms']['OnDemand']
            for term in terms.values():
                for dimension in term['priceDimensions'].values():
                    return {
                        'servicio': 'Amazon API Gateway',
                        'descripcion': dimension['description'],
                        'precio_usd': dimension['pricePerUnit']['USD'],
                        'unidad': dimension['unit']
                    }
    except Exception as e:
        return {'servicio': 'Amazon API Gateway', 'error': str(e)}
 
 
def lambda_handler(event, context):
    """
    Recibe una lista de servicios a consultar y devuelve sus precios vigentes.
    Ejemplo de input:
    {
        "servicios": ["lambda", "dynamodb", "s3", "apigateway"],
        "region": "US East (N. Virginia)"
    }
    """
    servicios = event.get('servicios', ['lambda', 'dynamodb', 's3', 'apigateway'])
    region = event.get('region', 'US East (N. Virginia)')
 
    precios = []
 
    for servicio in servicios:
        servicio = servicio.lower()
        if servicio == 'lambda':
            precios.append(obtener_precio_lambda(region))
        elif servicio == 'dynamodb':
            precios.append(obtener_precio_dynamodb(region))
        elif servicio == 's3':
            precios.append(obtener_precio_s3(region))
        elif servicio == 'apigateway':
            precios.append(obtener_precio_api_gateway(region))
        else:
            precios.append({'servicio': servicio, 'error': 'Servicio no soportado'})
 
    return {
        'statusCode': 200,
        'body': json.dumps({
            'region': region,
            'precios': precios
        }, ensure_ascii=False)
    }
 