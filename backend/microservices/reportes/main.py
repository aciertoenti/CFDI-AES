from fastapi import FastAPI, Query
from typing import Optional

app = FastAPI(title="CFDI – Reportes", version="2.0.0")

@app.get("/reportes/mensual")
async def reporte_mensual(
    anio: int = 2025,
    mes: int = Query(ge=1, le=12),
    cliente_rfc: Optional[str] = None,
):
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
