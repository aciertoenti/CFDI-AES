"""
Tests de GET /admin/negocios/{id}/resumen - Dashboard "Mi cuenta" (zg6k9Pw).

Primer test suite de administracion. Cubre:
  - _calcular_porcentaje_cancelacion() (funcion pura, sin DB/HTTP)
  - obtener_resumen_negocio() con facturacion caido -> degradacion parcial
    (facturas_mes/porcentaje_cancelacion_mes en null, advertencias, NUNCA
    un error generico), no solo con facturacion respondiendo bien.

NO se llama a facturacion real: se mockea main.httpx.AsyncClient (mismo
patron que facturacion/tests/test_obtener_plan_negocio.py). NO se usa
Postgres real: db es un fake minimo (mismo patron que
auth_usuarios/tests/test_password_change_rate_limit.py).
"""
import httpx
import main
import pytest
from fastapi import HTTPException
from main import (
    NegocioResumenResponse,
    _calcular_porcentaje_cancelacion,
    obtener_resumen_negocio,
)


# ─── _calcular_porcentaje_cancelacion (funcion pura) ────────────────────────

def test_sin_facturas_este_mes_no_divide_entre_cero():
    assert _calcular_porcentaje_cancelacion(facturas_mes=0, canceladas_mes=0) == 0.0


def test_todas_canceladas_da_100():
    assert _calcular_porcentaje_cancelacion(facturas_mes=5, canceladas_mes=5) == 100.0


def test_ninguna_cancelada_da_0():
    assert _calcular_porcentaje_cancelacion(facturas_mes=8, canceladas_mes=0) == 0.0


def test_porcentaje_parcial_redondeado_a_1_decimal():
    # 1/3 = 33.333...% -> redondeado a 33.3
    assert _calcular_porcentaje_cancelacion(facturas_mes=3, canceladas_mes=1) == 33.3


# ─── obtener_resumen_negocio() - integracion con degradacion parcial ───────

class _FakeNegocio:
    def __init__(self, id, plan):
        self.id = id
        self.plan = plan


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, negocio):
        self._negocio = negocio

    async def execute(self, stmt):
        return _FakeScalarResult(self._negocio)


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

    async def get(self, url, headers=None):
        if self._raise is not None:
            raise self._raise
        return self._resp


def _patch_facturacion(monkeypatch, *, resp=None, raise_exc=None):
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda *a, **k: _FakeHttpClient(resp=resp, raise_exc=raise_exc),
    )


async def test_facturacion_caido_degrada_sin_tumbar_el_endpoint(monkeypatch):
    """El caso pedido explicitamente: facturacion no responde -> el
    endpoint NO lanza, devuelve 200-equivalente con campos en null +
    advertencia, y limite_plan sigue presente (viene de PLAN_LIMITS,
    no de facturacion)."""
    _patch_facturacion(monkeypatch, raise_exc=httpx.RequestError("connection refused"))
    db = _FakeDB(_FakeNegocio(id=1, plan="contador"))

    out = await obtener_resumen_negocio(negocio_id=1, db=db, x_negocio_id="1")

    assert isinstance(out, NegocioResumenResponse)
    assert out.facturas_mes is None
    assert out.porcentaje_cancelacion_mes is None
    assert out.timbres_disponibles is None
    assert out.limite_plan == main.PLAN_LIMITS["contador"]["facturas_mes"]
    assert out.advertencias == ["no se pudo obtener datos de facturación"]


async def test_facturacion_status_no_200_tambien_degrada(monkeypatch):
    _patch_facturacion(monkeypatch, resp=_FakeHttpResp(status_code=500))
    db = _FakeDB(_FakeNegocio(id=1, plan="basico"))

    out = await obtener_resumen_negocio(negocio_id=1, db=db, x_negocio_id="1")

    assert out.facturas_mes is None
    assert out.advertencias == ["no se pudo obtener datos de facturación"]


async def test_happy_path_calcula_porcentaje_real(monkeypatch):
    _patch_facturacion(monkeypatch, resp=_FakeHttpResp(json_data={
        "facturas_mes": 10, "canceladas_mes": 2,
    }))
    db = _FakeDB(_FakeNegocio(id=1, plan="despacho"))

    out = await obtener_resumen_negocio(negocio_id=1, db=db, x_negocio_id="1")

    assert out.facturas_mes == 10
    assert out.porcentaje_cancelacion_mes == 20.0
    assert out.limite_plan == main.PLAN_LIMITS["despacho"]["facturas_mes"]
    assert out.advertencias == []


async def test_negocio_ajeno_es_404_no_403():
    db = _FakeDB(_FakeNegocio(id=1, plan="basico"))
    with pytest.raises(HTTPException) as exc:
        await obtener_resumen_negocio(negocio_id=2, db=db, x_negocio_id="1")
    assert exc.value.status_code == 404


async def test_negocio_inexistente_es_404():
    db = _FakeDB(None)  # simula scalar_one_or_none() -> None
    with pytest.raises(HTTPException) as exc:
        await obtener_resumen_negocio(negocio_id=1, db=db, x_negocio_id="1")
    assert exc.value.status_code == 404
