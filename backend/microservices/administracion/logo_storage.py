"""
Almacenamiento del logo de white-label por Negocio (zg2mOhE).

Bucket PUBLICO a proposito - decision de diseno DISTINTA a
sat_descarga_client.py (paquetes SAT, privados) y a
facturacion/storage_client.py (XML/PDF, presigned/expiran): un logo de
marca no es un dato fiscal sensible, esta pensado para mostrarse en una
pagina PUBLICA sin sesion (PortalAutofacturacion.jsx). Una URL firmada
que expira rompería el portal silenciosamente semanas despues de
configurar el logo - una politica de lectura anonima sobre un bucket
dedicado (nunca el mismo que cfdi-xmls/cfdi-descargas-sat) da una URL
estable para siempre, sin ese riesgo.

object_key = str(negocio_id) (sin extension): el Content-Type real lo
carga el objeto en MinIO (put_object(content_type=...)), no la URL - asi
un negocio puede cambiar de PNG a SVG sin dejar un archivo huerfano ni
cambiar su URL guardada en negocios.logo_url.
"""
import io
import json
import os
from functools import lru_cache

from minio import Minio

MINIO_URL = os.environ.get("MINIO_URL", "http://minio:9000")
MINIO_PUBLIC_URL = os.environ.get("MINIO_PUBLIC_URL", MINIO_URL)
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio_secret")
MINIO_REGION = os.environ.get("MINIO_REGION", "us-east-1")
BUCKET_LOGOS = os.environ.get("MINIO_BUCKET_LOGOS", "cfdi-logos-negocios")

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2MB


def _politica_lectura_publica(bucket: str) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{bucket}/*"],
        }],
    })


@lru_cache
def _minio_client() -> Minio:
    endpoint = MINIO_URL.replace("http://", "").replace("https://", "")
    secure = MINIO_URL.startswith("https://")
    client = Minio(
        endpoint,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=secure,
        region=MINIO_REGION,
    )
    if not client.bucket_exists(BUCKET_LOGOS):
        client.make_bucket(BUCKET_LOGOS)
    client.set_bucket_policy(BUCKET_LOGOS, _politica_lectura_publica(BUCKET_LOGOS))
    return client


def validar_logo(contenido: bytes) -> str:
    """Valida tamano y formato REAL por magic bytes - nunca confia en el
    Content-Type que declare el cliente (un cliente API directo, saltandose
    el navegador, puede mandar cualquier header y cualquier contenido).
    Devuelve el content_type real detectado, o lanza ValueError con un
    mensaje apto para regresar en un 422."""
    if not contenido:
        raise ValueError("El archivo esta vacio")
    if len(contenido) > MAX_LOGO_BYTES:
        raise ValueError(f"El logo no debe exceder {MAX_LOGO_BYTES // (1024 * 1024)}MB")

    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    # SVG es texto XML, sin magic bytes binarios. Tolera BOM UTF-8 y
    # espacios/prolog <?xml ...?> antes de la etiqueta <svg> real.
    inicio = contenido[:2048].lstrip(b"\xef\xbb\xbf").lstrip()
    if (inicio.startswith(b"<?xml") or inicio.startswith(b"<svg")) and b"<svg" in inicio:
        return "image/svg+xml"

    raise ValueError("Formato no soportado - solo PNG, JPG o SVG")


def subir_logo(negocio_id: int, contenido: bytes, content_type: str) -> str:
    """Sube el logo (bucket publico, sobreescribe el objeto previo del
    mismo negocio) y devuelve la URL publica permanente."""
    client = _minio_client()
    client.put_object(
        BUCKET_LOGOS,
        str(negocio_id),
        data=io.BytesIO(contenido),
        length=len(contenido),
        content_type=content_type,
    )
    return f"{MINIO_PUBLIC_URL}/{BUCKET_LOGOS}/{negocio_id}"
