"""
Cliente de almacenamiento (MinIO, compatible S3) para XML/PDF de CFDI timbrados.

Decision de diseno: URLs firmadas (presigned), no bucket publico. Los XML/PDF
contienen datos fiscales reales (RFC, montos, nombre) - exponerlos con acceso
publico permanente es un riesgo de privacidad que no se justifica todavia.
Si mas adelante whatsapp_bot necesita mandarlos directo a Meta sin pasar por
un fetch propio, se puede reevaluar (el README del bot ya documentaba esto
como un supuesto pendiente de confirmar).

Endpoint de conexion vs. endpoint de firma (21 ago 2026, tarjeta
PVTI_lAHOBYC0Os4BfCxZzg1IacA - solucion TEMPORAL de prueba con Tailscale
Funnel, no arquitectura final de produccion): minio-py firma las URLs
presignadas de forma local (SigV4, sin round-trip real al servidor) usando
el endpoint del cliente que las genera - por eso basta con un SEGUNDO
cliente de solo-firma apuntando al hostname PUBLICO (MINIO_PUBLIC_URL) para
que la URL resultante sea valida quando algo externo (Meta, un navegador)
la use, sin tener que rutear las subidas internas (put_object) por
internet. Si MINIO_PUBLIC_URL no esta definido, cae a MINIO_URL (mismo
comportamiento que antes de este cambio, un solo endpoint para todo).
"""
import os
from datetime import timedelta
from functools import lru_cache

from minio import Minio

MINIO_URL = os.environ.get("MINIO_URL", "http://minio:9000")
MINIO_PUBLIC_URL = os.environ.get("MINIO_PUBLIC_URL", MINIO_URL)
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio_secret")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "cfdi-xmls")
PRESIGNED_URL_EXPIRY = timedelta(days=7)


def _build_client(url: str) -> Minio:
    endpoint = url.replace("http://", "").replace("https://", "")
    secure = url.startswith("https://")
    return Minio(endpoint, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=secure)


@lru_cache
def get_client() -> Minio:
    """Cliente interno (red de Docker) - subidas y gestion de bucket. Nunca
    sale a internet, mas rapido y no depende de que el tunel publico este
    arriba para poder timbrar/guardar."""
    client = _build_client(MINIO_URL)
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    return client


@lru_cache
def get_public_client() -> Minio:
    """
    Cliente SOLO para firmar URLs presignadas de lectura contra el
    hostname publico (MINIO_PUBLIC_URL). Nunca hace una conexion real -
    presigned_get_object() es una operacion local (SigV4), no una llamada
    de red al endpoint configurado aqui.
    """
    return _build_client(MINIO_PUBLIC_URL)


def _subir(object_name: str, data: bytes, content_type: str) -> str:
    import io

    client = get_client()
    client.put_object(
        MINIO_BUCKET,
        object_name,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return get_public_client().presigned_get_object(MINIO_BUCKET, object_name, expires=PRESIGNED_URL_EXPIRY)


def subir_xml(uuid: str, xml_bytes: bytes) -> str:
    return _subir(f"{uuid}.xml", xml_bytes, "application/xml")


def subir_pdf(uuid: str, pdf_bytes: bytes) -> str:
    return _subir(f"{uuid}.pdf", pdf_bytes, "application/pdf")


def url_xml(uuid: str) -> str:
    """Regenera una URL firmada (publica) para un XML ya subido (no vuelve a subirlo)."""
    return get_public_client().presigned_get_object(MINIO_BUCKET, f"{uuid}.xml", expires=PRESIGNED_URL_EXPIRY)


def url_pdf(uuid: str) -> str:
    """Regenera una URL firmada (publica) para un PDF ya subido (no vuelve a subirlo)."""
    return get_public_client().presigned_get_object(MINIO_BUCKET, f"{uuid}.pdf", expires=PRESIGNED_URL_EXPIRY)
