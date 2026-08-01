"""
Autenticación interna entre microservicios.
Usa API key en el header X-Internal-Key para llamadas servicio-a-servicio.
El CSD/llave privada NUNCA se toca aquí — vive únicamente en facturacion-service.
"""
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from core.config import settings

_api_key_header = APIKeyHeader(name="X-Internal-Key", auto_error=False)


def require_internal_key(api_key: str | None = Security(_api_key_header)) -> str:
    """
    Dependencia FastAPI para rutas internas (servicio-a-servicio).
    Uso: @router.post("/...", dependencies=[Depends(require_internal_key)])
    """
    if not api_key or api_key != settings.internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clave interna inválida o ausente",
        )
    return api_key
