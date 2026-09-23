"""
Decision explicita por Content-Type en el proxy generico (reporte 185/C4,
22 sep 2026) - reemplaza el fallback anterior basado en excepcion
(intentar resp.json(), asumir binario si fallaba) por 3 ramas explicitas:
  1. Content-Type application/json -> camino JSON existente, sin cambios.
  2. Content-Type en CONTENT_TYPES_BINARIOS_PERMITIDOS (lista cerrada,
     hoy solo application/pdf) -> passthrough de bytes, status code real
     del downstream, SOLO 4 headers (Content-Type, Content-Disposition,
     X-Content-Type-Options, Content-Length).
  3. Cualquier otro Content-Type -> 502, sin exponer el cuerpo.

Mismo patron ya usado en test_password_reset_xff.py: ASGITransport +
AsyncClient contra main.app real, mockeando main.httpx.AsyncClient para
controlar la respuesta "del downstream" sin un servicio real corriendo.
Requiere JWT real (la ruta generica SI exige verify_token, a diferencia
de /auth/password-reset/request) - mismo _token() que
test_verify_token_revocacion.py.
"""
import time

import jwt
import main
from httpx import ASGITransport, AsyncClient


def _token(*, sub="RAHP7112093H0", exp_delta=3600):
    payload = {"sub": sub, "exp": int(time.time()) + exp_delta, "iat": int(time.time())}
    return jwt.encode(payload, main.JWT_SECRET, algorithm=main.JWT_ALGORITHM)


class _FakeRedisSinRevocacion:
    async def get(self, key):
        return None


class _FakeHttpResp:
    def __init__(self, status_code=200, headers=None, content=b"", json_data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no es JSON")
        return self._json_data


class _FakeHttpClient:
    def __init__(self, respuesta):
        self._respuesta = respuesta

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, content=None, **kwargs):
        return self._respuesta


def _mockear_downstream(monkeypatch, respuesta):
    class _FakeHttpxModule:
        def AsyncClient(self, *a, **k):
            return _FakeHttpClient(respuesta)
    monkeypatch.setattr(main, "httpx", _FakeHttpxModule())


async def _pedir(path="/admin/algo", headers=None):
    todos_headers = {"Authorization": f"Bearer {_token()}"}
    if headers:
        todos_headers.update(headers)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=todos_headers)


async def test_json_sin_cambios(monkeypatch):
    monkeypatch.setattr(main, "_get_redis", lambda: _FakeRedisSinRevocacion())
    _mockear_downstream(monkeypatch, _FakeHttpResp(
        status_code=200, headers={"content-type": "application/json"}, json_data={"ok": True},
    ))
    resp = await _pedir()
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_json_con_charset_sigue_siendo_json(monkeypatch):
    """content-type real de FastAPI/uvicorn incluye "; charset=utf-8" -
    la comparacion debe ignorar ese sufijo, no exigir el string exacto."""
    monkeypatch.setattr(main, "_get_redis", lambda: _FakeRedisSinRevocacion())
    _mockear_downstream(monkeypatch, _FakeHttpResp(
        status_code=201, headers={"content-type": "application/json; charset=utf-8"}, json_data={"id": 1},
    ))
    resp = await _pedir()
    assert resp.status_code == 201
    assert resp.json() == {"id": 1}


async def test_pdf_passthrough_con_headers_correctos(monkeypatch):
    monkeypatch.setattr(main, "_get_redis", lambda: _FakeRedisSinRevocacion())
    contenido_pdf = b"%PDF-1.4\ncontenido de prueba"
    _mockear_downstream(monkeypatch, _FakeHttpResp(
        status_code=200,
        headers={
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="x.pdf"',
            "x-content-type-options": "nosniff",
            "content-length": str(len(contenido_pdf)),
            "server": "uvicorn",  # NO debe pasar - no esta en la lista de 4
            "date": "Tue, 22 Sep 2026 00:00:00 GMT",  # NO debe pasar
        },
        content=contenido_pdf,
    ))
    resp = await _pedir()
    assert resp.status_code == 200
    assert resp.content == contenido_pdf
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'attachment; filename="x.pdf"'
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["content-length"] == str(len(contenido_pdf))
    # Headers FUERA de la lista de 4 no deben reenviarse tal cual (mas
    # alla de los que Starlette agrega por su cuenta como "server"/"date"
    # propios de la respuesta ASGI, que no vienen de nuestro passthrough).
    assert resp.headers.get("server") != "uvicorn"


async def test_texto_html_da_502_sin_exponer_el_cuerpo(monkeypatch):
    """Content-Type fuera de la lista blanca (ni JSON ni el binario
    permitido) - 502, y el cuerpo real del downstream (que podria traer
    detalles internos de otro servicio) nunca llega al cliente."""
    monkeypatch.setattr(main, "_get_redis", lambda: _FakeRedisSinRevocacion())
    _mockear_downstream(monkeypatch, _FakeHttpResp(
        status_code=500,
        headers={"content-type": "text/html; charset=utf-8"},
        content=b"<html><body>Internal Server Error con detalles sensibles</body></html>",
    ))
    resp = await _pedir()
    assert resp.status_code == 502
    assert b"detalles sensibles" not in resp.content
    assert b"<html>" not in resp.content


async def test_204_sin_content_type_pasa_204_no_502(monkeypatch):
    """Regresion real encontrada en la verificacion E2E de este mismo
    cambio (reporte 185/C6): un 204 (DELETE .../documentos/{id}) NUNCA
    trae Content-Type - sin este caso aparte, caia en la rama final y
    devolvia 502 para un borrado que si tuvo exito. Confirmado con un
    _FakeHttpResp sin ningun header content-type, igual que el 204 real."""
    monkeypatch.setattr(main, "_get_redis", lambda: _FakeRedisSinRevocacion())
    _mockear_downstream(monkeypatch, _FakeHttpResp(status_code=204, headers={}, content=b""))
    resp = await _pedir()
    assert resp.status_code == 204
    assert resp.content == b""


async def test_pdf_con_status_de_error_conserva_el_status(monkeypatch):
    """Un 404 real del downstream (ej. 'documento no encontrado') con
    Content-Type application/pdf en la lista blanca debe seguir pasando
    por el camino binario, preservando el 404 real - no un 200 falso ni
    un 502 que oculte el codigo real."""
    monkeypatch.setattr(main, "_get_redis", lambda: _FakeRedisSinRevocacion())
    _mockear_downstream(monkeypatch, _FakeHttpResp(
        status_code=404,
        headers={"content-type": "application/pdf"},
        content=b"",
    ))
    resp = await _pedir()
    assert resp.status_code == 404
