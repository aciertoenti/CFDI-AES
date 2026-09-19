"""
Tests de GET/POST /admin/negocios/{id}/notificaciones - alerta "plan cerca
del limite" (zg6k9Ok, primera alerta proactiva). Generacion LAZY, sin
scheduler: el propio GET es el disparador.

Mezcla los 2 patrones ya usados en esta suite:
  - mockea main.httpx.AsyncClient para simular facturas_mes (mismo patron
    que test_resumen_negocio.py) - no depende de facturacion real.
  - usa Postgres real (AsyncSessionLocal) para la tabla notificaciones - el
    UNIQUE(negocio_id, tipo, periodo) y el ON CONFLICT DO UPDATE (g7sjeM,
    19 sep 2026 - antes DO NOTHING, ver el hallazgo real de mensaje
    congelado) son justamente lo que hay que probar contra la BD real, un
    mock no lo cubriria (mismo criterio que test_listar_emisores_orden.py).
"""
import asyncio
from datetime import datetime, timedelta

import httpx
import main
import pytest
import pytest_asyncio
from database import AsyncSessionLocal, Negocio, Notificacion, engine
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _pool_por_test():
    # Mismo bug/fix ya documentado en test_listar_emisores_orden.py: el
    # pool de engine queda atado al event loop del primer test.
    await engine.dispose()
    yield


class _FakeHttpResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class _FakeHttpClient:
    def __init__(self, *, resp=None, raise_exc=None):
        self._resp = resp
        self._raise = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        if self._raise is not None:
            raise self._raise
        return self._resp


def _patch_facturacion(monkeypatch, *, facturas_mes, canceladas_mes=0):
    resp = _FakeHttpResp(json_data={"facturas_mes": facturas_mes, "canceladas_mes": canceladas_mes})
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **k: _FakeHttpClient(resp=resp))


@pytest.fixture
async def negocio_temporal():
    """Plan 'emprendedor' -> limite_facturas_mes=25 (PLAN_LIMITS), numeros
    chicos y faciles de razonar en los asserts."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST notificaciones", plan="emprendedor")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(Notificacion.__table__.delete().where(Notificacion.negocio_id == negocio_id))
        await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
        await session.commit()


# ─── umbral del 80% ──────────────────────────────────────────────────────

async def test_bajo_el_80_por_ciento_no_genera_notificacion(negocio_temporal, monkeypatch):
    _patch_facturacion(monkeypatch, facturas_mes=10)  # 10/25 = 40%
    async with AsyncSessionLocal() as session:
        out = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    assert out == []


async def test_80_por_ciento_o_mas_genera_notificacion_con_mensaje_correcto(negocio_temporal, monkeypatch):
    _patch_facturacion(monkeypatch, facturas_mes=21)  # 21/25 = 84%
    async with AsyncSessionLocal() as session:
        out = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    assert len(out) == 1
    n = out[0]
    assert n.tipo == "plan_cerca_limite"
    assert n.mensaje == "Has usado el 84% de tus facturas incluidas este mes (21 de 25)."
    assert n.leida is False
    assert n.periodo == datetime.now().strftime("%Y-%m")


# ─── idempotencia: 2 llamadas secuenciales no duplican ─────────────────────

async def test_dos_llamadas_secuenciales_no_duplican(negocio_temporal, monkeypatch):
    _patch_facturacion(monkeypatch, facturas_mes=22)
    async with AsyncSessionLocal() as session:
        await main.listar_notificaciones(negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal))
    async with AsyncSessionLocal() as session:
        out = await main.listar_notificaciones(negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal))
    assert len(out) == 1


# ─── race condition REAL: 2 llamadas concurrentes, no solo en teoria ───────

async def test_llamadas_concurrentes_no_duplican_por_el_unique_constraint(negocio_temporal, monkeypatch):
    """2 sesiones/conexiones REALES disparadas con asyncio.gather - el
    UNIQUE(negocio_id, tipo, periodo) + ON CONFLICT DO NOTHING es lo que
    debe evitar el duplicado, no un lock de aplicacion (no hay ninguno)."""
    _patch_facturacion(monkeypatch, facturas_mes=23)

    async def _una_llamada():
        async with AsyncSessionLocal() as session:
            return await main.listar_notificaciones(
                negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
            )

    await asyncio.gather(_una_llamada(), _una_llamada())

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Notificacion).where(Notificacion.negocio_id == negocio_temporal)
        )
        filas = result.scalars().all()
    assert len(filas) == 1, "2 requests concurrentes insertaron un duplicado - el UNIQUE no esta protegiendo"


# ─── g7sjeM: el mensaje se actualiza dentro del mismo periodo, "leida" no ──

async def test_mensaje_se_actualiza_si_el_conteo_cambia(negocio_temporal, monkeypatch):
    """Antes (ON CONFLICT DO NOTHING): el mensaje quedaba congelado con el
    valor de la primera llamada. Ahora (DO UPDATE): la segunda llamada,
    con un conteo real distinto, debe actualizar el mensaje - misma fila
    (mismo id, mismo UNIQUE), no una nueva."""
    _patch_facturacion(monkeypatch, facturas_mes=21)  # 21/25 = 84%
    async with AsyncSessionLocal() as session:
        primera = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    assert primera[0].mensaje == "Has usado el 84% de tus facturas incluidas este mes (21 de 25)."
    id_original = primera[0].id

    _patch_facturacion(monkeypatch, facturas_mes=24)  # 24/25 = 96% - conteo real cambio
    async with AsyncSessionLocal() as session:
        segunda = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    assert len(segunda) == 1, "debe seguir siendo 1 sola fila, no una nueva"
    assert segunda[0].id == id_original
    assert segunda[0].mensaje == "Has usado el 96% de tus facturas incluidas este mes (24 de 25)."


async def test_actualizar_mensaje_no_resetea_leida(negocio_temporal, monkeypatch):
    """Si el usuario ya marco la notificacion como leida, un recalculo del
    mensaje (conteo real distinto) NO debe resetear leida a False - eso
    seria spam/regresion, exactamente lo que ON CONFLICT DO NOTHING evitaba
    y que DO UPDATE (sin "leida" en set_) debe seguir evitando."""
    _patch_facturacion(monkeypatch, facturas_mes=21)
    async with AsyncSessionLocal() as session:
        creadas = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    async with AsyncSessionLocal() as session:
        await main.marcar_notificacion_leida(
            negocio_id=negocio_temporal, notif_id=creadas[0].id, db=session, x_negocio_id=str(negocio_temporal),
        )

    _patch_facturacion(monkeypatch, facturas_mes=25)  # 25/25 = 100% - conteo real cambio
    async with AsyncSessionLocal() as session:
        out = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    assert len(out) == 1
    assert out[0].mensaje == "Has usado el 100% de tus facturas incluidas este mes (25 de 25)."
    assert out[0].leida is True, "el recalculo del mensaje reseteo leida a False - regresion real"


# ─── periodo: una notificacion de un mes anterior no bloquea la del mes actual ──

async def test_notificacion_de_mes_anterior_no_bloquea_la_del_mes_actual(negocio_temporal, monkeypatch):
    periodo_anterior = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    periodo_actual = datetime.now().strftime("%Y-%m")
    assert periodo_anterior != periodo_actual  # sanity check del propio test

    async with AsyncSessionLocal() as session:
        vieja = Notificacion(
            negocio_id=negocio_temporal,
            tipo="plan_cerca_limite",
            mensaje="Has usado el 92% de tus facturas incluidas el mes pasado (23 de 25).",
            periodo=periodo_anterior,
            leida=True,
            created_at=datetime.utcnow() - timedelta(days=35),
        )
        session.add(vieja)
        await session.commit()

    _patch_facturacion(monkeypatch, facturas_mes=24)  # 24/25 = 96% este mes
    async with AsyncSessionLocal() as session:
        out = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )

    assert len(out) == 2, "el periodo anterior no debe impedir crear la del periodo actual"
    periodos = {n.periodo for n in out}
    assert periodos == {periodo_anterior, periodo_actual}
    # mas reciente primero (created_at desc)
    assert out[0].periodo == periodo_actual


# ─── POST marcar-leida ──────────────────────────────────────────────────────

async def test_marcar_leida_actualiza_el_campo(negocio_temporal, monkeypatch):
    _patch_facturacion(monkeypatch, facturas_mes=21)
    async with AsyncSessionLocal() as session:
        creadas = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    notif_id = creadas[0].id

    async with AsyncSessionLocal() as session:
        actualizada = await main.marcar_notificacion_leida(
            negocio_id=negocio_temporal, notif_id=notif_id, db=session, x_negocio_id=str(negocio_temporal),
        )
    assert actualizada.leida is True


async def test_marcar_leida_de_notificacion_de_otro_negocio_es_404(negocio_temporal, monkeypatch):
    _patch_facturacion(monkeypatch, facturas_mes=21)
    async with AsyncSessionLocal() as session:
        creadas = await main.listar_notificaciones(
            negocio_id=negocio_temporal, db=session, x_negocio_id=str(negocio_temporal),
        )
    notif_id = creadas[0].id

    from fastapi import HTTPException
    async with AsyncSessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            await main.marcar_notificacion_leida(
                negocio_id=negocio_temporal, notif_id=notif_id, db=session, x_negocio_id="999999",
            )
    assert exc.value.status_code == 404
