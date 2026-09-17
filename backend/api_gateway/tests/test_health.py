"""
GET /health del gateway (g4B42Q) - debe responder 200 SIN autenticacion,
sin importar el orden de declaracion de rutas.

Bug real confirmado 16 sep 2026: "/health" cumple tambien el patron del
proxy generico "/{service}" (con service="health") declarado mas arriba
en main.py. Starlette hace match en orden de declaracion, no por
especificidad, asi que con /health declarado DESPUES del catch-all (como
estaba antes de este fix), el catch-all lo interceptaba primero y exigia
Depends(verify_token) -> 401 sin token, en vez de 200.

Test a nivel ASGI real (no llamar a health() directo) porque el bug es
de ORDEN de rutas - llamar al handler directamente pasaria siempre,
sin importar el bug.
"""
from httpx import ASGITransport, AsyncClient

import main


async def test_health_devuelve_200_sin_authorization_header():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"service": "gateway", "status": "ok"}


async def test_health_no_lo_intercepta_el_proxy_generico():
    """Confirma explicitamente que NO es el proxy generico ("/{service}")
    quien respondio - si lo fuera, "health" tendria que existir en
    SERVICES (no existe) y el intento habria devuelto 404 "Servicio
    'health' no encontrado", no el body real de health()."""
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert "health" not in main.SERVICES
    assert resp.status_code == 200
    assert resp.json().get("detail") is None
