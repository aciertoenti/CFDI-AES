import re
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Factura, get_db
from shared.internal_key import require_internal_key
from shared.negocio_id import requerir_negocio_id

app = FastAPI(title="CFDI – Reportes", version="2.0.0")

_MES_REGEX = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_RANGO_MAXIMO_MESES = 36  # 3 anios - tope arbitrario para no dejar el rango abierto a cualquier tamano


def _parsear_mes(valor: str, nombre_param: str) -> tuple[int, int]:
    m = _MES_REGEX.match(valor)
    if not m:
        raise HTTPException(
            status_code=422,
            detail=f"'{nombre_param}' invalido: '{valor}' - formato esperado YYYY-MM (ej. '2026-01')",
        )
    return int(m.group(1)), int(m.group(2))


def _rango_meses(anio_desde: int, mes_desde: int, anio_hasta: int, mes_hasta: int) -> list[tuple[int, int]]:
    inicio = anio_desde * 12 + (mes_desde - 1)
    fin = anio_hasta * 12 + (mes_hasta - 1)
    if fin < inicio:
        raise HTTPException(status_code=422, detail="'hasta' no puede ser anterior a 'desde'")
    if fin - inicio >= _RANGO_MAXIMO_MESES:
        raise HTTPException(status_code=422, detail=f"Rango maximo soportado: {_RANGO_MAXIMO_MESES} meses")
    resultado = []
    for i in range(inicio, fin + 1):
        anio, mes_idx = divmod(i, 12)  # mes_idx es 0-indexado (0=enero)
        resultado.append((anio, mes_idx + 1))
    return resultado


@app.get("/reportes/mensual", dependencies=[Depends(require_internal_key)])
async def reporte_mensual(
    desde: str = Query(..., description="Mes inicial del rango (inclusive), formato YYYY-MM. Ej: '2026-01'"),
    hasta: str = Query(..., description="Mes final del rango (inclusive), formato YYYY-MM. Ej: '2026-08'"),
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """
    Reporte mensual con datos reales (decisiones tomadas el 20 ago 2026,
    tarjeta PVTI_lAHOBYC0Os4BfCxZzg2m00E; implementado el 21 ago 2026).
    Reemplaza el mock anterior - contrato nuevo, incompatible a proposito
    con el mock viejo (nunca tuvo consumidor real: auditoria del 20 ago
    confirmo 0 resultados de "reportes"/"8004" en frontend/App.jsx).

    CONTRATO:
    - Input: rango INCLUSIVE de meses via `desde`/`hasta` (YYYY-MM), no un
      solo (anio, mes) como el mock viejo - el frontend necesita varios
      meses seguidos para una grafica multi-mes.
    - Output: `{"negocio_id", "desde", "hasta", "meses": [...]}`, con un
      objeto por CADA mes del rango en `meses` (incluye meses sin ninguna
      factura, con vigente/cancelada en 0 - un hueco en el array
      complicaria una grafica de barras/lineas continua). Cada objeto:
      `{"anio", "mes", "vigente": {"total", "count"}, "cancelada": {"total", "count"}}`.
    - vigente/cancelada SEPARADOS explicitamente (semantica decidida el 20
      ago) - NUNCA sumados en un solo total, a diferencia del calculo
      actual del frontend (App.jsx:ReporteMensual, useFacturas() + reduce
      sin filtrar por estado). Ese frontend sigue sin cambios en este
      commit - conectarlo a este endpoint queda pendiente para despues
      (fuera de alcance aqui, solo backend).
    - Solo existen 2 valores reales de Factura.estado hoy (confirmado por
      grep en facturacion/main.py): "Vigente" y "Cancelada". Cualquier
      otro valor caeria en el bucket "cancelada" por default, pero no hay
      ningun caso real de eso hoy.

    X-Negocio-Id SI aplica aqui (a diferencia de la ronda de X-Internal-Key
    del 20 ago en addenda_aes/reportes, donde no habia datos reales
    por-negocio que aislar) - ahora si los hay: facturas reales con
    negocio_id propio. Mismo patron fail-closed que el resto de endpoints
    multi-tenant (requerir_negocio_id: 400 sin header valido o invalido).

    X-Internal-Key sigue aplicando igual que en la ronda anterior (bloquea
    bypass directo del Gateway) - sin cambios en ese mecanismo, solo se
    confirma que sigue funcionando con el contrato nuevo.
    """
    negocio_id = requerir_negocio_id(x_negocio_id)
    anio_desde, mes_desde = _parsear_mes(desde, "desde")
    anio_hasta, mes_hasta = _parsear_mes(hasta, "hasta")
    meses = _rango_meses(anio_desde, mes_desde, anio_hasta, mes_hasta)

    inicio_dt = date(anio_desde, mes_desde, 1)
    anio_fin_exclusivo, mes_fin_exclusivo = (anio_hasta + 1, 1) if mes_hasta == 12 else (anio_hasta, mes_hasta + 1)
    fin_dt = date(anio_fin_exclusivo, mes_fin_exclusivo, 1)

    stmt = (
        select(
            func.date_trunc("month", Factura.fecha_timbrado).label("mes_trunc"),
            Factura.estado,
            func.sum(Factura.total).label("total"),
            func.count().label("count"),
        )
        .where(
            Factura.negocio_id == negocio_id,
            Factura.fecha_timbrado >= inicio_dt,
            Factura.fecha_timbrado < fin_dt,
        )
        .group_by("mes_trunc", Factura.estado)
    )
    result = await db.execute(stmt)
    filas = result.all()

    agregados = {
        (anio, mes): {"vigente": {"total": 0.0, "count": 0}, "cancelada": {"total": 0.0, "count": 0}}
        for anio, mes in meses
    }
    for mes_trunc, estado, total, count in filas:
        clave = (mes_trunc.year, mes_trunc.month)
        if clave not in agregados:
            continue
        bucket = "vigente" if estado == "Vigente" else "cancelada"
        agregados[clave][bucket] = {"total": float(total), "count": count}

    return {
        "negocio_id": negocio_id,
        "desde": desde,
        "hasta": hasta,
        "meses": [{"anio": anio, "mes": mes, **agregados[(anio, mes)]} for anio, mes in meses],
    }


@app.get("/health")
async def health():
    return {"service": "reportes", "status": "ok"}
