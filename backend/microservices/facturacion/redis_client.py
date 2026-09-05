"""
Redis para rate limiting del endpoint publico de autofacturacion individual
de tickets (POST /facturas/tickets/{qr_token}/facturar, zg5b-ZE pieza 5,
05 sep 2026).

Mismo patron que auth_usuarios/redis_client.py (redis.asyncio, singleton de
modulo, fail-closed si Redis no responde) - NO se importa aquel modulo
directo: auth_usuarios y facturacion son builds Docker independientes con
build-context distinto (misma razon documentada en fiscal_catalogo.py).
Este servicio ya tiene REDIS_URL en el compose (redis://redis:6379/0) y
depends_on: redis, solo faltaba el cliente.

TTL nativo de Redis - NO requiere tabla ni migracion de Alembic (mismo
criterio que auth_usuarios: es estado efimero por diseno, no esquema
versionado).

Fail-closed: si Redis no responde, la excepcion sube y el endpoint
responde 500. Para un limitador de intentos, rechazar cuando el control
no esta disponible es mas seguro que dejar pasar intentos ilimitados
contra Finkok (mismo criterio que el rate limit de login).
"""
import os
from typing import Optional

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_redis: Optional[aioredis.Redis] = None

# 5 intentos por qr_token cada 10 min - un ticket real necesita 1 intento
# exitoso; varios reintentos legitimos ocurren solo si el receptor se
# equivoco al teclear su RFC/regimen y el PAC lo rechazo. 5 cubre eso con
# holgura y frena el abuso (fuerza bruta de datos fiscales de terceros,
# o martilleo del PAC) desde un qr_token filtrado.
MAX_INTENTOS_FACTURAR = 5
VENTANA_FACTURAR_SEGUNDOS = 10 * 60


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


def _key_intentos_facturar(qr_token: str) -> str:
    return f"facturacion:ticket_facturar_intentos:{qr_token}"


async def permitir_intento_facturar(qr_token: str) -> bool:
    """
    True si este qr_token todavia no llego a MAX_INTENTOS_FACTURAR dentro
    de la ventana - incrementa el contador en el mismo paso (cuenta esta
    llamada), asi que debe llamarse UNA sola vez por request real, antes
    del claim atomico y de cualquier llamada a Finkok. El 6to intento en
    <10 min devuelve False.
    """
    r = await get_redis()
    key = _key_intentos_facturar(qr_token)
    intentos = await r.incr(key)
    if intentos == 1:
        await r.expire(key, VENTANA_FACTURAR_SEGUNDOS)
    return intentos <= MAX_INTENTOS_FACTURAR
