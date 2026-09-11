"""
Rate limiting de POST /auth/password/change (zg325Wk).

Reproduce el escenario de la tarjeta: JWT valido + intentos repetidos con
la contrasena ACTUAL incorrecta -> debe bloquear tras el limite, con el
MISMO status/mensaje/Retry-After que /auth/login, y un cambio exitoso
resetea el contador.

Usa el Redis REAL del contenedor auth (redis://redis:6379/1) - solo toca
las 2 llaves del identificador de prueba, que limpia antes y despues. La BD
y el JWT se mockean (dependency_overrides).
"""
import bcrypt
import main
import pytest
import pytest_asyncio
import redis_client
from httpx import ASGITransport, AsyncClient
from main import cambiar_password, verify_token  # noqa: F401 (verify_token se usa como key de override)

RFC_TEST = "AUTO010101TST"
PWD_ACTUAL_OK = "CorrectaActual1"
_HASH_OK = bcrypt.hashpw(PWD_ACTUAL_OK.encode(), bcrypt.gensalt()).decode()
_IDENT_RL = f"pwchange:{RFC_TEST}"


class _FakeUsuario:
    def __init__(self):
        self.rfc_personal = RFC_TEST
        self.password_hash = _HASH_OK


class _FakeResult:
    def scalar_one_or_none(self):
        return _FakeUsuario()


class _FakeSession:
    async def execute(self, stmt):
        return _FakeResult()

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def _fake_get_db():
    yield _FakeSession()


def _fake_token():
    return {"sub": RFC_TEST, "nombre": "T", "email": "t@t.mx"}


async def _limpiar(r):
    await r.delete(
        redis_client._key_intentos(_IDENT_RL),
        redis_client._key_bloqueo(_IDENT_RL),
        redis_client._key_intentos(RFC_TEST),   # el de login "puro", para el test de aislamiento
        redis_client._key_bloqueo(RFC_TEST),
        redis_client._key_revocado_desde(RFC_TEST),  # zg3ehbA
    )


@pytest_asyncio.fixture(autouse=True)
async def _entorno():
    # pytest-asyncio crea un event loop nuevo por test; redis_client._redis es
    # un singleton de modulo que quedaria atado al loop del primer test. Se
    # resetea para que cada test cree su propia conexion en su propio loop.
    redis_client._redis = None
    main.app.dependency_overrides[main.get_db] = _fake_get_db
    main.app.dependency_overrides[verify_token] = _fake_token
    r = await redis_client.get_redis()
    await _limpiar(r)
    yield
    await _limpiar(r)
    main.app.dependency_overrides.clear()
    await r.aclose()
    redis_client._redis = None


def _cliente():
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


async def _post(ac, password_actual, nueva="NuevaSegura123"):
    return await ac.post(
        "/auth/password/change",
        json={"password_actual": password_actual, "nueva_password": nueva},
        headers={"Authorization": "Bearer x"},
    )


async def test_password_actual_incorrecta_bloquea_tras_el_limite_como_login():
    async with _cliente() as ac:
        # Los primeros MAX_INTENTOS_LOGIN fallos siguen respondiendo 401
        for i in range(redis_client.MAX_INTENTOS_LOGIN):
            r = await _post(ac, "malaMala1")
            assert r.status_code == 401, f"intento {i+1}: {r.status_code} {r.text}"
            assert r.json()["detail"] == "La contraseña actual no coincide"

        # El SIGUIENTE encuentra el bloqueo activo -> 429, mismo formato que login
        r = await _post(ac, "malaMala1")
        assert r.status_code == 429
        assert r.json()["detail"].startswith("Demasiados intentos fallidos. Intenta de nuevo en ")
        assert r.json()["detail"].endswith(" minutos.")
        retry = int(r.headers["Retry-After"])
        assert 0 < retry <= redis_client.BLOQUEO_LOGIN_SEGUNDOS

        # aunque manden la contrasena CORRECTA, sigue bloqueado
        r = await _post(ac, PWD_ACTUAL_OK)
        assert r.status_code == 429


async def test_mismo_mensaje_y_status_que_login():
    # Fuerza el bloqueo directo en redis (como si login lo hubiera puesto)
    r = await redis_client.get_redis()
    await r.set(redis_client._key_bloqueo(_IDENT_RL), "1", ex=redis_client.BLOQUEO_LOGIN_SEGUNDOS)
    async with _cliente() as ac:
        resp = await _post(ac, PWD_ACTUAL_OK)
    seg = await redis_client.segundos_bloqueado(_IDENT_RL)
    esperado_login = f"Demasiados intentos fallidos. Intenta de nuevo en {seg // 60 + 1} minutos."
    assert resp.status_code == 429
    assert resp.json()["detail"] == esperado_login
    assert resp.headers["Retry-After"] == str(seg)


async def test_cambio_exitoso_resetea_el_contador():
    r = await redis_client.get_redis()
    async with _cliente() as ac:
        # 3 fallos (por debajo del limite)
        for _ in range(3):
            assert (await _post(ac, "malaMala1")).status_code == 401
        assert int(await r.get(redis_client._key_intentos(_IDENT_RL))) == 3

        # cambio correcto -> 200
        ok = await _post(ac, PWD_ACTUAL_OK)
        assert ok.status_code == 200
        assert ok.json()["mensaje"] == "Contraseña actualizada correctamente."

        # contador y bloqueo borrados
        assert await r.get(redis_client._key_intentos(_IDENT_RL)) is None
        assert await r.get(redis_client._key_bloqueo(_IDENT_RL)) is None

        # y por lo tanto vuelve a permitir intentos desde cero
        assert (await _post(ac, "malaMala1")).status_code == 401
        assert int(await r.get(redis_client._key_intentos(_IDENT_RL))) == 1


async def test_bloqueo_de_pwchange_no_bloquea_el_login_del_mismo_rfc():
    async with _cliente() as ac:
        for _ in range(redis_client.MAX_INTENTOS_LOGIN + 1):
            await _post(ac, "malaMala1")
    r = await redis_client.get_redis()
    # el identificador con prefijo esta bloqueado...
    assert await r.get(redis_client._key_bloqueo(_IDENT_RL)) is not None
    # ...pero el identificador "puro" que usaria login (RFC sin prefijo) NO
    assert await r.get(redis_client._key_bloqueo(RFC_TEST)) is None
    assert await r.get(redis_client._key_intentos(RFC_TEST)) is None


# ─── revocado_desde (zg3ehbA) ───────────────────────────────────────────────

async def test_cambio_exitoso_escribe_revocado_desde_con_ttl():
    import time

    r = await redis_client.get_redis()
    assert await r.get(redis_client._key_revocado_desde(RFC_TEST)) is None  # nada antes

    antes = int(time.time())
    async with _cliente() as ac:
        ok = await _post(ac, PWD_ACTUAL_OK)
    despues = int(time.time())
    assert ok.status_code == 200

    # se escribio en el identificador SIN el prefijo pwchange: (token["sub"]
    # tal cual, no identificador_rl) - es lo que va a leer el Gateway con
    # payload["sub"].
    valor = await r.get(redis_client._key_revocado_desde(RFC_TEST))
    assert valor is not None
    assert antes <= int(valor) <= despues

    ttl = await r.ttl(redis_client._key_revocado_desde(RFC_TEST))
    assert 0 < ttl <= redis_client.REVOCACION_TTL_SEGUNDOS
    # TTL realmente cerca del maximo esperado (2h), no un valor arbitrario
    assert ttl > redis_client.REVOCACION_TTL_SEGUNDOS - 10


async def test_revocar_desde_y_obtener_revocado_desde_son_consistentes():
    """Test directo del helper (sin pasar por el endpoint), mismo estilo
    que ya se usaria para probar segundos_bloqueado/registrar_intento_fallido."""
    ident = f"helper-test:{RFC_TEST}"
    r = await redis_client.get_redis()
    try:
        assert await redis_client.obtener_revocado_desde(ident) is None
        await redis_client.revocar_desde(ident)
        valor = await redis_client.obtener_revocado_desde(ident)
        assert isinstance(valor, int) and valor > 0
        ttl = await r.ttl(redis_client._key_revocado_desde(ident))
        assert 0 < ttl <= redis_client.REVOCACION_TTL_SEGUNDOS
    finally:
        await r.delete(redis_client._key_revocado_desde(ident))
