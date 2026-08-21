from fastapi import Depends, FastAPI, Query
from typing import Optional

from shared.internal_key import require_internal_key

app = FastAPI(title="CFDI – Reportes", version="2.0.0")

@app.get("/reportes/mensual", dependencies=[Depends(require_internal_key)])
async def reporte_mensual(
    anio: int = 2025,
    mes: int = Query(ge=1, le=12),
    cliente_rfc: Optional[str] = None,
):
    """
    Sin X-Negocio-Id: el endpoint devuelve datos mock (ver tarjeta 229036865,
    dimensionamiento 20 ago 2026) - no toca ninguna base de datos ni filtra
    por negocio todavia, ni siquiera usa cliente_rfc en la respuesta.
    X-Internal-Key si aplica (bloquea bypass directo del Gateway).
    """
    return {
        "anio": anio,
        "mes": mes,
        "cliente_rfc": cliente_rfc,
        "total_emitido": 145000.00,
        "total_cancelado": 5800.00,
        "count_vigentes": 12,
        "count_canceladas": 2,
    }

@app.get("/health")
async def health():
    return {"service": "reportes", "status": "ok"}
