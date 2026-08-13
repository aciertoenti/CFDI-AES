from typing import Optional

from fastapi import HTTPException


def requerir_negocio_id(x_negocio_id: Optional[str]) -> int:
    """
    Fail-closed para todas las operaciones multi-tenant (lecturas y
    escrituras por igual, incluido crear_emisor - fix de seguridad: antes
    tenia un fallback permisivo al "Negocio por defecto (pre-tenants)" via
    resolver_negocio_id(), ahora eliminada). Una llamada sin X-Negocio-Id
    valido (llamada directa al servicio, bypass del Gateway, header ausente
    por error) se rechaza en vez de asumir un Negocio - un fallback abierto
    significaria que cualquiera podria crear/ver datos de otro Negocio con
    solo omitir el header.

    Compartido entre administracion/facturacion/auth_usuarios (12 ago 2026,
    refactor/shared-negocio-id) - antes existia una copia identica en cada
    uno de los 3 servicios.
    """
    if not x_negocio_id:
        raise HTTPException(
            status_code=400,
            detail="Falta X-Negocio-Id - esta llamada requiere pasar por el Gateway con un token valido",
        )
    try:
        return int(x_negocio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Negocio-Id invalido")
