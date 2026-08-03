"""
Cliente de almacenamiento (MinIO, compatible S3) para XML/PDF de CFDI timbrados.

Decision de diseno: URLs firmadas (presigned), no bucket publico. Los XML/PDF
contienen datos fiscales reales (RFC, montos, nombre) - exponerlos con acceso
publico permanente es un riesgo de privacidad que no se justifica todavia.
Si mas adelante whatsapp_bot necesita mandarlos directo a Meta sin pasar por
un fetch propio, se puede reevaluar (el README del bot ya documentaba esto
como un supuesto pendiente de confirmar).
"""
import os
from datetime import timedelta
from functools import lru_cache

from minio import Minio

MINIO_URL = os.environ.get("MINIO_URL", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio_secret")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "cfdi-xmls")
PRESIGNED_URL_EXPIRY = timedelta(days=7)


@lru_cache
def get_client() -> Minio:
    endpoint = MINIO_URL.replace("http://", "").replace("https://", "")
    secure = MINIO_URL.startswith("https://")
    client = Minio(endpoint, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=secure)
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    return client


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
    return client.presigned_get_object(MINIO_BUCKET, object_name, expires=PRESIGNED_URL_EXPIRY)


def subir_xml(uuid: str, xml_bytes: bytes) -> str:
    return _subir(f"{uuid}.xml", xml_bytes, "application/xml")


def subir_pdf(uuid: str, pdf_bytes: bytes) -> str:
    return _subir(f"{uuid}.pdf", pdf_bytes, "application/pdf")


def url_xml(uuid: str) -> str:
    """Regenera una URL firmada para un XML ya subido (no vuelve a subirlo)."""
    return get_client().presigned_get_object(MINIO_BUCKET, f"{uuid}.xml", expires=PRESIGNED_URL_EXPIRY)


def url_pdf(uuid: str) -> str:
    """Regenera una URL firmada para un PDF ya subido (no vuelve a subirlo)."""
    return get_client().presigned_get_object(MINIO_BUCKET, f"{uuid}.pdf", expires=PRESIGNED_URL_EXPIRY)
