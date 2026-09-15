"""
Tests de GET /auth/me (Perfil.jsx deja de leer datos de usuario del JWT
decodificado client-side, ahora vienen de este endpoint real).

Mismo patron que test_password_change_rate_limit.py: AsyncClient real
contra main.app (ASGITransport, no llamada directa a la funcion) + BD
mockeada via dependency_overrides. A diferencia de ese archivo, aqui NO
se toca Redis (este endpoint no tiene rate limiting), asi que no hace
falta el fixture de limpieza de Redis.
"""
from datetime import datetime

import main
import pytest
from httpx import ASGITransport, AsyncClient
from main import verify_token

RFC_TEST = "AUTO010101TST"


class _FakeUsuario:
    def __init__(self, *, usuario="TESTUSR"):
        self.id = 42
        self.email = "test@example.mx"
        self.rfc_personal = RFC_TEST
        self.usuario = usuario
        self.nombre = "Test Nombre Completo"
        self.rol = "admin"
        self.created_at = datetime(2026, 3, 15, 10, 30, 0)
        # Presente en el ORM real (Usuario.password_hash es NOT NULL) -
        # el test de "200 real" confirma explicitamente que esto NUNCA
        # llega al JSON de respuesta.
        self.password_hash = "NUNCA-DEBE-APARECER-EN-LA-RESPUESTA"


class _FakeResult:
    def __init__(self, usuario):
        self._usuario = usuario

    def scalar_one_or_none(self):
        return self._usuario


class _FakeSession:
    def __init__(self, usuario):
        self._usuario = usuario

    async def execute(self, stmt):
        return _FakeResult(self._usuario)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _fake_get_db_factory(usuario):
    async def _fake_get_db():
        yield _FakeSession(usuario)
    return _fake_get_db


def _fake_token():
    return {"sub": RFC_TEST, "nombre": "Test Nombre Completo", "email": "test@example.mx"}


@pytest.fixture(autouse=True)
def _limpiar_overrides():
    yield
    main.app.dependency_overrides.clear()


def _cliente():
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


# ─── 200: usuario real, confirma los 7 campos exactos ──────────────────────

async def test_200_devuelve_los_7_campos_exactos_sin_password_hash():
    main.app.dependency_overrides[main.get_db] = _fake_get_db_factory(_FakeUsuario())
    main.app.dependency_overrides[verify_token] = _fake_token

    async with _cliente() as ac:
        r = await ac.get("/auth/me", headers={"Authorization": "Bearer x"})

    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"id", "email", "rfc_personal", "usuario", "nombre", "rol", "created_at"}
    assert data["id"] == 42
    assert data["email"] == "test@example.mx"
    assert data["rfc_personal"] == RFC_TEST
    assert data["usuario"] == "TESTUSR"
    assert data["nombre"] == "Test Nombre Completo"
    assert data["rol"] == "admin"
    assert data["created_at"].startswith("2026-03-15T10:30:00")
    # El hallazgo explicito pedido: password_hash NUNCA en la respuesta,
    # ni como campo propio ni colado en ningun valor.
    assert "password_hash" not in data
    assert "NUNCA-DEBE-APARECER-EN-LA-RESPUESTA" not in r.text


# ─── 200: usuario=null viaja como null, no se omite ni truena ──────────────

async def test_200_con_usuario_null_viaja_como_null():
    main.app.dependency_overrides[main.get_db] = _fake_get_db_factory(_FakeUsuario(usuario=None))
    main.app.dependency_overrides[verify_token] = _fake_token

    async with _cliente() as ac:
        r = await ac.get("/auth/me", headers={"Authorization": "Bearer x"})

    assert r.status_code == 200
    data = r.json()
    assert "usuario" in data  # presente en el JSON, no omitido
    assert data["usuario"] is None
    # el resto de los campos sigue completo, esto no tumba nada mas
    assert data["rfc_personal"] == RFC_TEST


# ─── 401: sin token / token invalido ────────────────────────────────────────

async def test_401_token_invalido():
    """Header Authorization presente pero con un JWT que no verifica -
    dispara la rama real de verify_token (jwt.InvalidTokenError), sin
    override de esa dependencia."""
    main.app.dependency_overrides[main.get_db] = _fake_get_db_factory(_FakeUsuario())
    # verify_token NO se sobreescribe - corre el codigo real contra un
    # token que no es un JWT valido.
    async with _cliente() as ac:
        r = await ac.get("/auth/me", headers={"Authorization": "Bearer esto-no-es-un-jwt-real"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Token inválido"


async def test_401_sin_authorization_header():
    """Confirmado empiricamente (no asumido): con esta version de
    FastAPI/Starlette, HTTPBearer() (default auto_error=True, ver
    `security = HTTPBearer()` en main.py) responde 401 "Not authenticated"
    cuando el header Authorization esta ausente por completo - ocurre
    ANTES de que verify_token() se ejecute (nunca ve un token que
    clasificar). Coincide con el 401 que da un token presente pero
    invalido (test de arriba) - incialmente se asumio que seria 403 (el
    comportamiento historico de HTTPBearer en versiones viejas de
    FastAPI), pero correr el caso real corrigio esa suposicion antes de
    dejarla en el test."""
    main.app.dependency_overrides[main.get_db] = _fake_get_db_factory(_FakeUsuario())
    async with _cliente() as ac:
        r = await ac.get("/auth/me")  # sin header Authorization
    assert r.status_code == 401
    assert r.json()["detail"] == "Not authenticated"


# ─── 404: rfc_personal del token no existe en BD ────────────────────────────

async def test_404_si_rfc_del_token_no_existe_en_bd():
    """Token valido (firma-wise) con un sub que ya no tiene fila en
    Usuario - caso real: cuenta borrada entre el login (JWT vive hasta
    1h) y esta llamada. La BD fake devuelve None, no una excepcion."""
    main.app.dependency_overrides[main.get_db] = _fake_get_db_factory(None)
    main.app.dependency_overrides[verify_token] = _fake_token

    async with _cliente() as ac:
        r = await ac.get("/auth/me", headers={"Authorization": "Bearer x"})

    assert r.status_code == 404
    assert r.json()["detail"] == "Usuario no encontrado"
