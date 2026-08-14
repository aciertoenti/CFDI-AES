from typing import Optional
import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

# Clave servicio-a-servicio (#42) - mismo mecanismo que whatsapp_bot ya usa
# contra facturacion (ver whatsapp_bot/core/security.py). Distinta de
# X-Negocio-Id: esta protege endpoints que ningun caller fuera del Gateway
# deberia poder alcanzar directo, no rutas con contexto de tenant.
#
# Compartida entre facturacion/administracion/ia/auth_usuarios (14 ago 2026,
# refactor/shared-internal-key) - antes existia una copia identica en cada
# uno de los primeros 3 servicios (el mismo patron que ya se aplico con
# requerir_negocio_id el 12 ago 2026, ver backend/shared/negocio_id.py).
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")

_internal_api_key_header = APIKeyHeader(name="X-Internal-Key", auto_error=False)


def require_internal_key(api_key: Optional[str] = Security(_internal_api_key_header)) -> str:
    if not INTERNAL_API_KEY or not api_key or api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clave interna inválida o ausente")
    return api_key
