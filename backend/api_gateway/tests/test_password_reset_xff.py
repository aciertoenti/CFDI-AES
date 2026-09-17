"""
X-Forwarded-For real que llega al downstream (auth_usuarios) desde
password_reset_request_proxy() - g4CnlY, 17 sep 2026.

Bug real confirmado con requests reales contra el stack completo (no
solo de codigo): con TRUST_PROXY_XFF en False (default, sin actualizar
tras agregar el proxy real de nginx el 05 sep), el Gateway ignoraba el
X-Forwarded-For que nginx ya mandaba bien y usaba request.client.host -
que via nginx es la IP del CONTENEDOR de nginx, la MISMA para todo el
trafico real. Efecto: el rate-limit de password-reset (10/hora, en
auth_usuarios, que lee xff.split(",")[0]) paso de "spoofeable por el
cliente" (26 ago) a "compartido entre TODOS los usuarios reales" (05
sep) sin que nadie lo notara.

Fix real (17 sep 2026): frontend/nginx.conf ahora manda
X-Forwarded-For: $remote_addr (su propia vista del cliente TCP, no
spoofeable via headers) + TRUST_PROXY_XFF=true en el Gateway (seguro
ahora porque ese header ya no lo controla el cliente). Este archivo
cubre la logica de reenvio en si (el codigo Python de main.py no
cambio - ya sabia hacer esto bien desde el 30 ago, solo estaba
apagado); la prueba real end-to-end con 2 IPs simuladas agotando su
propio limite sin bloquearse mutuamente se corrio a mano contra el
stack real (Redis: 2 keys auth:reset_request_ip:<ip> independientes,
cada una 10/10 + 429 en el intento 11) - no reproducida aqui porque
requeriria un Redis real + auth_usuarios real, fuera del alcance de un
test unitario del Gateway.
"""
from httpx import ASGITransport, AsyncClient

import main


class _FakeHttpResp:
    def __init__(self, status_code=202, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {"detail": "ok"}

    def json(self):
        return self._json_data


class _FakeHttpClient:
    """Captura los headers reales que password_reset_request_proxy()
    construyo y le iba a mandar a auth_usuarios - eso es lo que este
    test necesita inspeccionar, no la respuesta en si."""

    def __init__(self, capturados):
        self._capturados = capturados

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, content=None, **kwargs):
        self._capturados["headers"] = headers
        return _FakeHttpResp()


def _mockear_httpx(monkeypatch):
    capturados = {}

    class _FakeHttpxModule:
        def AsyncClient(self, *a, **k):
            return _FakeHttpClient(capturados)

    monkeypatch.setattr(main, "httpx", _FakeHttpxModule())
    return capturados


async def test_trust_proxy_xff_true_respeta_el_primer_valor_confiable(monkeypatch):
    """Con TRUST_PROXY_XFF=true (el valor real de hoy en docker-compose.yml)
    y un X-Forwarded-For entrante (lo que nginx manda tras el fix: su
    propia vista del cliente TCP), el Gateway debe reencadenarlo como
    PRIMER valor - auth_usuarios lee xff.split(",")[0], asi que ese
    primer valor es el que decide el bucket de rate-limit."""
    monkeypatch.setattr(main, "TRUST_PROXY_XFF", True)
    capturados = _mockear_httpx(monkeypatch)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/password-reset/request",
            json={"email": "prueba@noexiste.test"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

    assert resp.status_code == 202
    xff_enviado = capturados["headers"]["X-Forwarded-For"]
    primer_valor = xff_enviado.split(",")[0].strip()
    assert primer_valor == "203.0.113.10"


async def test_trust_proxy_xff_false_descarta_el_xff_entrante(monkeypatch):
    """Con TRUST_PROXY_XFF=false (comportamiento seguro por default para
    cualquier despliegue donde no se confirme que TODO el trafico pasa
    por un proxy que sanitiza el header primero) el valor entrante debe
    descartarse por completo, sin importar lo que diga."""
    monkeypatch.setattr(main, "TRUST_PROXY_XFF", False)
    capturados = _mockear_httpx(monkeypatch)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/password-reset/request",
            json={"email": "prueba@noexiste.test"},
            headers={"X-Forwarded-For": "203.0.113.10, 9.9.9.9"},
        )

    assert resp.status_code == 202
    xff_enviado = capturados["headers"]["X-Forwarded-For"]
    # Ninguno de los valores que mando el "cliente" debe sobrevivir.
    assert "203.0.113.10" not in xff_enviado
    assert "9.9.9.9" not in xff_enviado
    assert "," not in xff_enviado  # un solo valor: la IP TCP real, sin encadenar


async def test_trust_proxy_xff_true_sin_xff_entrante_usa_solo_ip_real(monkeypatch):
    """TRUST_PROXY_XFF=true no basta por si solo - si no llego ningun
    X-Forwarded-For (ej. alguien le pega directo al Gateway sin pasar
    por nginx), no hay nada que reencadenar; debe usarse solo la IP TCP
    real, igual que en el caso False."""
    monkeypatch.setattr(main, "TRUST_PROXY_XFF", True)
    capturados = _mockear_httpx(monkeypatch)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/password-reset/request",
            json={"email": "prueba@noexiste.test"},
        )

    assert resp.status_code == 202
    xff_enviado = capturados["headers"]["X-Forwarded-For"]
    assert "," not in xff_enviado
    assert xff_enviado != ""
