"""
Tests de obtener_plan_negocio() (facturacion/main.py) - zg33XEQ.

Confirma que limite_facturas_mes viene de administracion (GET
/admin/negocios/{id}) y que TODOS los caminos de fallo son fail-closed:
nunca se defaultea a un limite local.

NO se llama a administracion real: se mockea main.httpx.AsyncClient.
"""
import httpx
import main
import pytest
from fastapi import HTTPException
from main import PlanNegocio, obtener_plan_negocio


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class _FakeClient:
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


def _patch_client(monkeypatch, *, resp=None, raise_exc=None):
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(resp=resp, raise_exc=raise_exc),
    )


# ─── happy path ────────────────────────────────────────────────────────────

async def test_devuelve_plan_y_limite_del_response(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(json_data={
        "id": 3, "plan": "contador", "limite_emisores": 5, "limite_facturas_mes": 100,
    }))
    out = await obtener_plan_negocio(3)
    assert isinstance(out, PlanNegocio)
    assert out.plan == "contador"
    assert out.limite_facturas_mes == 100


async def test_plan_se_normaliza_a_minusculas(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(json_data={
        "plan": "DESPACHO", "limite_facturas_mes": 500,
    }))
    out = await obtener_plan_negocio(1)
    assert out.plan == "despacho"
    assert out.limite_facturas_mes == 500


async def test_limite_string_se_castea_a_int(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(json_data={
        "plan": "basico", "limite_facturas_mes": "50",
    }))
    out = await obtener_plan_negocio(1)
    assert out.limite_facturas_mes == 50 and isinstance(out.limite_facturas_mes, int)


# ─── fail-closed: sin limite_facturas_mes NO se defaultea ──────────────────

async def test_response_sin_limite_facturas_mes_lanza_502(monkeypatch):
    # 200 OK, trae plan pero NO trae limite_facturas_mes -> 502, sin default
    _patch_client(monkeypatch, resp=_FakeResp(json_data={"id": 3, "plan": "basico"}))
    with pytest.raises(HTTPException) as exc:
        await obtener_plan_negocio(3)
    assert exc.value.status_code == 502
    assert "limite de facturas" in exc.value.detail


async def test_response_con_limite_facturas_mes_null_lanza_502(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(json_data={
        "plan": "basico", "limite_facturas_mes": None,
    }))
    with pytest.raises(HTTPException) as exc:
        await obtener_plan_negocio(3)
    assert exc.value.status_code == 502


# ─── fail-closed: fallos preexistentes siguen igual ───────────────────────

async def test_status_no_200_lanza_502(monkeypatch):
    _patch_client(monkeypatch, resp=_FakeResp(status_code=500, text="boom"))
    with pytest.raises(HTTPException) as exc:
        await obtener_plan_negocio(3)
    assert exc.value.status_code == 502


async def test_administracion_caido_lanza_502(monkeypatch):
    _patch_client(monkeypatch, raise_exc=httpx.RequestError("connection refused"))
    with pytest.raises(HTTPException) as exc:
        await obtener_plan_negocio(3)
    assert exc.value.status_code == 502
    assert "No se pudo consultar el plan" in exc.value.detail
