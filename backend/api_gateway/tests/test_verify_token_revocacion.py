"""
Revocacion de JWT en verify_token() (zg3ehbA) - api_gateway/main.py.

Cubre los 4 casos pedidos, todos llamando verify_token() directamente (no
se arma un servidor real ni se llama a Redis real - se mockea main._get_redis
y, para el caso de excepcion, tambien main.logger).
"""
import time
from unittest.mock import MagicMock

import jwt
import main
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


def _token(*, sub="RAHP7112093H0", iat=None, exp_delta=3600):
    payload = {"sub": sub, "exp": int(time.time()) + exp_delta}
    if iat is not None:
        payload["iat"] = iat
    return jwt.encode(payload, main.JWT_SECRET, algorithm=main.JWT_ALGORITHM)


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class _FakeRedisValor:
    """.get() devuelve un valor fijo (o None), sin tocar Redis real."""

    def __init__(self, valor):
        self._valor = valor

    async def get(self, key):
        return self._valor


class _FakeRedisExplota:
    """.get() lanza, simulando timeout/connection error."""

    async def get(self, key):
        raise TimeoutError("Redis no responde")


async def test_iat_anterior_a_revocado_desde_es_401():
    ahora = int(time.time())
    token = _token(iat=ahora - 3600)  # emitido hace 1h
    main._get_redis = lambda: _FakeRedisValor(str(ahora - 60))  # revocado hace 60s (DESPUES del iat)

    with pytest.raises(HTTPException) as exc:
        await main.verify_token(_creds(token))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Token revocado, inicia sesión de nuevo"


async def test_iat_posterior_a_revocado_desde_pasa():
    ahora = int(time.time())
    token = _token(iat=ahora)  # recien emitido
    main._get_redis = lambda: _FakeRedisValor(str(ahora - 3600))  # revocado hace 1h (ANTES del iat)

    payload = await main.verify_token(_creds(token))
    assert payload["sub"] == "RAHP7112093H0"


async def test_token_sin_iat_pasa_compatibilidad_tokens_viejos():
    token = _token(iat=None)  # sin iat, como los JWT emitidos antes de zg3ehbA
    # ni siquiera deberia consultar Redis, pero lo dejamos "revocado" a
    # proposito para confirmar que igual pasa (no hay base de comparacion).
    main._get_redis = lambda: _FakeRedisValor(str(int(time.time())))

    payload = await main.verify_token(_creds(token))
    assert "iat" not in payload


async def test_redis_lanza_excepcion_fail_open_y_loguea_warning(monkeypatch):
    ahora = int(time.time())
    token = _token(iat=ahora - 3600)
    main._get_redis = lambda: _FakeRedisExplota()

    mock_warning = MagicMock()
    monkeypatch.setattr(main.logger, "warning", mock_warning)

    # NO debe lanzar - fail-open: el token pasa aunque Redis truene.
    payload = await main.verify_token(_creds(token))
    assert payload["sub"] == "RAHP7112093H0"

    assert mock_warning.called
    mensaje = mock_warning.call_args[0][0]
    assert "revocacion JWT" in mensaje
    assert "fail-open" in mensaje


async def test_redis_timeout_lento_tambien_fail_open(monkeypatch):
    """Ademas de una excepcion inmediata, confirma el timeout explicito:
    un Redis que tarda mas de REDIS_REVOCACION_TIMEOUT_SEGUNDOS debe
    tratarse igual que una excepcion (fail-open), no colgar el request."""
    import asyncio

    class _FakeRedisLento:
        async def get(self, key):
            await asyncio.sleep(main.REDIS_REVOCACION_TIMEOUT_SEGUNDOS + 5)
            return "no deberia llegar aqui"

    ahora = int(time.time())
    token = _token(iat=ahora - 3600)
    main._get_redis = lambda: _FakeRedisLento()
    monkeypatch.setattr(main, "REDIS_REVOCACION_TIMEOUT_SEGUNDOS", 0.2)

    mock_warning = MagicMock()
    monkeypatch.setattr(main.logger, "warning", mock_warning)

    inicio = time.monotonic()
    payload = await main.verify_token(_creds(token))
    duracion = time.monotonic() - inicio

    assert payload["sub"] == "RAHP7112093H0"
    assert duracion < 1.0  # no espero los 5s simulados
    assert mock_warning.called


@pytest.fixture(autouse=True)
def _restaurar_get_redis():
    original = main._get_redis
    yield
    main._get_redis = original
