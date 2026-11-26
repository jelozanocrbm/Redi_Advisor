import json
import boto3
import urllib.parse
import uuid
import io
from datetime import datetime, timezone
 
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('dynamoadvisor')
 
BUCKET_UPLOADS = 'appupload-rediadvisor'
 
 
def extraer_texto(contenido_bytes, nombre_archivo):
    """Extrae el texto del archivo según su extensión."""
    nombre = nombre_archivo.lower()
 
    if nombre.endswith('.txt'):
        return contenido_bytes.decode('utf-8', errors='ignore')
 
    elif nombre.endswith('.pdf'):
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(contenido_bytes))
        texto = ''
        for pagina in reader.pages:
            texto += pagina.extract_text() or ''
        return texto
 
    elif nombre.endswith('.docx'):
        import docx
        doc = docx.Document(io.BytesIO(contenido_bytes))
        return '\n'.join([parrafo.text for parrafo in doc.paragraphs])
 
    else:
        return contenido_bytes.decode('utf-8', errors='ignore')
 
 
def lambda_handler(event, context):
    try:
        # Obtener datos del evento de S3
        registro = event['Records'][0]['s3']
        bucket = registro['bucket']['name']
        key = urllib.parse.unquote_plus(registro['object']['key'])
 
        print(f"Archivo recibido: s3://{bucket}/{key}")
 
        # Descargar el archivo desde S3
        respuesta = s3_client.get_object(Bucket=bucket, Key=key)
        contenido_bytes = respuesta['Body'].read()
 
        # Extraer el nombre del archivo
        nombre_archivo = key.split('/')[-1]
 
        # Extraer el sessionId del path si existe (ej: session-abc123/archivo.pdf)
        # Si no viene en el path, generamos uno nuevo
        partes = key.split('/')
        if len(partes) > 1 and partes[0].startswith('session-'):
            session_id = partes[0].replace('session-', '')
        else:
            session_id = str(uuid.uuid4())
 
        # Extraer el texto del archivo
        texto_extraido = extraer_texto(contenido_bytes, nombre_archivo)
 
        if not texto_extraido.strip():
            raise ValueError("No se pudo extraer texto del archivo.")
 
        print(f"Texto extraído: {len(texto_extraido)} caracteres")
 
        # Guardar en DynamoDB con sessionId (partition key) y fileId (sort key)
        item = {
            'sessionId': session_id,
            'fileId': nombre_archivo,
            'contenido': texto_extraido,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'estado': 'disponible'
        }
 
        table.put_item(Item=item)
        print(f"Guardado en DynamoDB con sessionId: {session_id}, fileId: {nombre_archivo}")
 
        # Eliminar el archivo del S3 (temporal según RN-09)
        s3_client.delete_object(Bucket=BUCKET_UPLOADS, Key=key)
        print(f"Archivo eliminado del S3: {key}")
 
        return {
            'statusCode': 200,
            'body': json.dumps({
                'mensaje': 'Archivo procesado correctamente',
                'sessionId': session_id,
                'fileId': nombre_archivo,
                'caracteres_extraidos': len(texto_extraido)
            })
        }
 
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }