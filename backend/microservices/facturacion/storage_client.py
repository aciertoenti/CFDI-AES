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
Funnel, no arquitectura final de produccion): la idea es un SEGUNDO cliente
de solo-firma apuntando al hostname PUBLICO (MINIO_PUBLIC_URL) para que la
URL resultante sea valida cuando algo externo (Meta, un navegador) la use,
sin tener que rutear las subidas internas (put_object) por internet. Si
MINIO_PUBLIC_URL no esta definido, cae a MINIO_URL (mismo comportamiento
que antes de este cambio, un solo endpoint para todo).

CORRECCION 21 ago 2026 (mismo dia, incidente post-merge): el comentario
original de este archivo decia que presigned_get_object() "nunca hace una
conexion real" - eso es FALSO sin region= explicito. Minio._get_region()
solo evita el round-trip de red si el region ya esta fijo en el cliente;
si no, ejecuta un GetBucketLocation real contra el endpoint configurado
(ver minio/api.py). Con MINIO_PUBLIC_URL apuntando a un hostname de
Tailscale Funnel obsoleto, ese round-trip fallaba (DNS/TLS) y tronaba el
timbrado completo con 502. region="us-east-1" (default de este MinIO, sin
MINIO_REGION configurado en el server) hace que _get_region() retorne de
inmediato sin tocar la red - soluciona la causa raiz real de hoy, sea cual
sea el endpoint publico configurado.

Encima de eso, get_public_client() se usa con try/except en las funciones
de abajo: si aun con region= fijo el endpoint publico falla por cualquier
otra razon de red (Funnel caido, TLS, lo que sea), se degrada a la URL
interna (get_client()) en vez de romper el timbrado. Es resiliencia ante
el endpoint publico en si, no un sustituto del fix de region=.
"""
import logging
import os
from datetime import timedelta
from functools import lru_cache

from minio import Minio

logger = logging.getLogger("facturacion.storage_client")

MINIO_URL = os.environ.get("MINIO_URL", "http://minio:9000")
MINIO_PUBLIC_URL = os.environ.get("MINIO_PUBLIC_URL", MINIO_URL)
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio_secret")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "cfdi-xmls")
MINIO_REGION = os.environ.get("MINIO_REGION", "us-east-1")
PRESIGNED_URL_EXPIRY = timedelta(days=7)


def _build_client(url: str) -> Minio:
    endpoint = url.replace("http://", "").replace("https://", "")
    secure = url.startswith("https://")
    return Minio(
        endpoint,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=secure,
        region=MINIO_REGION,
    )


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
    hostname publico (MINIO_PUBLIC_URL). Con region= fijo (ver arriba) la
    firma es local (SigV4, sin round-trip de red) - pero el endpoint
    publico en si puede fallar por otras razones (DNS, TLS, tunel caido);
    para eso existe el fallback en _presigned_url_publica() de abajo.
    """
    return _build_client(MINIO_PUBLIC_URL)


def _presigned_url_publica(object_name: str) -> str:
    """
    Intenta firmar contra el endpoint publico; si falla por cualquier
    razon de red (DNS, TLS, timeout, lo que sea), degrada al endpoint
    interno (get_client()) en vez de romper el timbrado o la consulta.
    Cuando esto pasa queda un warning en logs para notar que el tunel
    publico esta caido sin que rompa nada para el usuario.
    """
    try:
        return get_public_client().presigned_get_object(MINIO_BUCKET, object_name, expires=PRESIGNED_URL_EXPIRY)
    except Exception as e:
        logger.warning(
            "storage_client.endpoint_publico_fallo objeto=%s error=%s - degradando a URL interna (MINIO_URL)",
            object_name, e,
        )
        return get_client().presigned_get_object(MINIO_BUCKET, object_name, expires=PRESIGNED_URL_EXPIRY)


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
    return _presigned_url_publica(object_name)


def subir_xml(uuid: str, xml_bytes: bytes) -> str:
    return _subir(f"{uuid}.xml", xml_bytes, "application/xml")


def subir_pdf(uuid: str, pdf_bytes: bytes) -> str:
    return _subir(f"{uuid}.pdf", pdf_bytes, "application/pdf")


def url_xml(uuid: str) -> str:
    """Regenera una URL firmada (publica) para un XML ya subido (no vuelve a subirlo)."""
    return _presigned_url_publica(f"{uuid}.xml")


def url_pdf(uuid: str) -> str:
    """Regenera una URL firmada (publica) para un PDF ya subido (no vuelve a subirlo)."""
    return _presigned_url_publica(f"{uuid}.pdf")
