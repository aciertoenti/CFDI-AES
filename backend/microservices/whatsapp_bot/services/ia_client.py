"""Cliente HTTP hacia el microservicio ia (identificación de proveedores)."""
from __future__ import annotations
import httpx
from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

_EXT_MAP = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/webp": "webp", "application/pdf": "pdf",
}

async def identificar_proveedor(contenido: bytes, mime_type: str) -> dict:
    ext = _EXT_MAP.get(mime_type, "jpg")
    filename = f"ticket.{ext}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.ia_url}/ia/identificar-proveedor",
            headers={"X-Internal-Key": settings.internal_api_key},
            files={"file": (filename, contenido, mime_type)},
        )
        if not resp.is_success:
            logger.error("ia_client.identificar_proveedor.error",
                         status=resp.status_code, body=resp.text[:500])
            resp.raise_for_status()
        logger.info("ia_client.identificar_proveedor.success", status=resp.status_code)
        return resp.json()
