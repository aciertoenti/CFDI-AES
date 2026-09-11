"""
Redis compartido para TRES mecanismos de este servicio, todos con TTL
nativo (no requieren tabla ni migracion de Alembic - ver docs/migraciones.md,
esto no es esquema versionado, es estado efimero por diseno):

1. Rate limiting de login (5 intentos fallidos consecutivos -> bloqueo de
   15 min), contado por identificador de login (RFC/usuario), NO por IP.
2. Tokens de un solo uso para recuperacion de contrasena (30 min de vida).
3. Revocacion de JWT por "revocado desde" (zg3ehbA): NO es una blacklist por
   token individual (jti) - se guarda, por identificador (rfc_personal), el
   timestamp del ULTIMO evento que invalida cualquier sesion previa (hoy:
   cambio de contrasena). El Gateway (api_gateway/main.py:verify_token)
   compara el iat de cada JWT contra este timestamp: iat anterior ->
   token revocado, aunque su firma y exp sigan siendo validos.

Mismo patron que whatsapp_bot/services/session_store.py (redis.asyncio,
singleton modulo, fallback silencioso si Redis no esta disponible) - a
diferencia de las sesiones de conversacion del bot, aqui NO hay fallback en
memoria DENTRO de este servicio: si Redis esta caido, fail-closed (rechazar)
es mas seguro que fail-open (dejar pasar login sin rate limit, o tokens de
reset que nunca expiran). Ver comentario en cada funcion. La UNICA excepcion
a fail-closed en todo este mecanismo esta en el LECTOR (Gateway,
verify_token), no aqui - ver el razonamiento fail-open documentado alla.
"""
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/1")

_redis: Optional[aioredis.Redis] = None

MAX_INTENTOS_LOGIN = 5
BLOQUEO_LOGIN_SEGUNDOS = 15 * 60  # 15 minutos
CONTADOR_LOGIN_TTL_SEGUNDOS = 60 * 60  # ventana de 1h para que intentos abandonados no vivan para siempre

MAX_SOLICITUDES_RESET_POR_IP = 10
VENTANA_RESET_IP_SEGUNDOS = 60 * 60  # 1 hora

TOKEN_RESET_TTL_SEGUNDOS = 30 * 60  # 30 minutos


async def get_redis() -> aioredis.Redis:
    """
    A diferencia de whatsapp_bot (que tolera Redis caido con fallback en
    memoria, porque perder una sesion de conversacion es de bajo riesgo),
    aqui se deja que la excepcion suba - fail-closed. Rate limiting de login
    y tokens de reset son controles de seguridad: si Redis no responde,
    es mejor rechazar la operacion (500) que aceptarla sin proteccion.
    """
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


def _key_intentos(identificador: str) -> str:
    return f"auth:login_fail_count:{identificador}"


def _key_bloqueo(identificador: str) -> str:
    return f"auth:login_blocked:{identificador}"


async def segundos_bloqueado(identificador: str) -> Optional[int]:
    """None si no esta bloqueado. Si lo esta, cuantos segundos faltan
    (para el header Retry-After)."""
    r = await get_redis()
    ttl = await r.ttl(_key_bloqueo(identificador))
    return ttl if ttl > 0 else None


async def registrar_intento_fallido(identificador: str) -> None:
    """
    Incrementa el contador de fallos consecutivos. Al llegar a
    MAX_INTENTOS_LOGIN, activa el bloqueo de 15 min - el intento que causa
    el bloqueo (el 5to) sigue respondiendo 401 normal (credenciales
    invalidas), es el 6to el que encuentra el bloqueo ya activo y recibe
    429. No es un error: asi lo confirma el propio caller antes de que el
    bloqueo exista.
    """
    r = await get_redis()
    key = _key_intentos(identificador)
    intentos = await r.incr(key)
    if intentos == 1:
        await r.expire(key, CONTADOR_LOGIN_TTL_SEGUNDOS)
    if intentos >= MAX_INTENTOS_LOGIN:
        await r.set(_key_bloqueo(identificador), "1", ex=BLOQUEO_LOGIN_SEGUNDOS)


async def resetear_intentos(identificador: str) -> None:
    """Login exitoso - limpia tanto el contador como un bloqueo activo
    (si alguien fallo 5 veces, espero los 15 min, y en su 6to intento real
    acierta, no debe quedar un bloqueo fantasma de la ventana anterior)."""
    r = await get_redis()
    await r.delete(_key_intentos(identificador), _key_bloqueo(identificador))


# ─── Revocacion de JWT por "revocado desde" (zg3ehbA) ───────────────────────
# auth:revocado_desde:{rfc_personal} - por AHORA el unico disparador real es
# el cambio de contrasena (cambiar_password, main.py) - ver PARTE 4 del
# diseño (zg3ehbA) para los otros 2 disparadores previstos:
#
#   - Usuario desactivado/borrado -> escribiria aqui mismo,
#     auth:revocado_desde:{rfc_personal}. NO IMPLEMENTADO: hoy no existe
#     ningun endpoint que desactive/borre un Usuario, y el modelo Usuario
#     (database.py) ni siquiera tiene columna 'estado' - haria falta
#     migracion + endpoint antes de poder engancharlo aqui.
#   - Negocio desactivado/borrado -> escribiria una key DISTINTA,
#     auth:revocado_desde:negocio:{negocio_id} (revoca a TODOS los usuarios
#     de ese negocio de un solo golpe, no uno por uno) - el Gateway tendria
#     que comparar el iat del token contra AMBAS keys (la de su rfc_personal
#     Y la de su negocio_id) y rechazar si es anterior a cualquiera de las
#     dos. NO IMPLEMENTADO: hoy no existe ningun endpoint que desactive/
#     borre un Negocio (administracion/main.py) - Negocio.estado SI existe
#     en el modelo (default "Activo"), pero nada lo escribe todavia. Ademas
#     administracion no tiene conexion a Redis hoy (a diferencia de este
#     servicio) - haria falta agregarla, mismo patron que se agrega aqui
#     para el Gateway.
#
# Este modulo (redis_client.py) es intencionalmente el unico lugar de
# auth_usuarios que sabe escribir revocado_desde - cuando existan los otros
# 2 disparadores, deberian reusar exactamente estas 2 funciones (o su
# patron), no reinventar el formato de la key.

REVOCACION_TTL_SEGUNDOS = 2 * 60 * 60  # 2h: margen sobre el exp maximo del JWT (1h) - pasada esa ventana, ningun token vivo pudo haberse emitido antes de la revocacion, la key ya no aporta nada


def _key_revocado_desde(identificador: str) -> str:
    return f"auth:revocado_desde:{identificador}"


async def revocar_desde(identificador: str) -> None:
    """Marca 'ahora' como el punto de corte: cualquier JWT con iat anterior
    a este momento deja de ser valido para `identificador` (rfc_personal),
    aunque su firma y exp sigan siendo correctos. TTL acotado (ver
    REVOCACION_TTL_SEGUNDOS) - no hace falta que la key viva para siempre,
    solo mientras pueda existir un JWT emitido antes de ella."""
    r = await get_redis()
    ahora = int(datetime.now(timezone.utc).timestamp())
    await r.set(_key_revocado_desde(identificador), ahora, ex=REVOCACION_TTL_SEGUNDOS)


async def obtener_revocado_desde(identificador: str) -> Optional[int]:
    """Timestamp (epoch segundos) del ultimo evento de revocacion para
    `identificador`, o None si nunca se revoco (o la key ya expiro - ver
    REVOCACION_TTL_SEGUNDOS, en ese caso ya no hay ningun JWT vivo que
    pudiera haberse emitido antes)."""
    r = await get_redis()
    valor = await r.get(_key_revocado_desde(identificador))
    return int(valor) if valor is not None else None


def _key_reset_ip(ip: str) -> str:
    return f"auth:reset_request_ip:{ip}"


async def permitir_solicitud_reset(ip: str) -> bool:
    """True si la IP todavia no llego al limite de MAX_SOLICITUDES_RESET_POR_IP
    en la ventana de 1h - incrementa el contador en el mismo paso (cuenta
    esta llamada), asi que debe usarse una sola vez por request real, antes
    de procesar nada mas."""
    r = await get_redis()
    key = _key_reset_ip(ip)
    intentos = await r.incr(key)
    if intentos == 1:
        await r.expire(key, VENTANA_RESET_IP_SEGUNDOS)
    return intentos <= MAX_SOLICITUDES_RESET_POR_IP


def _key_token_reset(token: str) -> str:
    return f"auth:reset_token:{token}"


async def crear_token_reset(rfc_personal: str) -> str:
    """Token opaco (no JWT a proposito): un JWT es autocontenido y no se
    puede invalidar antes de su expiracion sin un denylist aparte - un
    token de un solo uso necesita poder invalidarse en el momento exacto
    en que se usa, asi que un valor aleatorio que vive en Redis (borrado al
    consumirse) es mas simple y mas correcto para este caso que un JWT."""
    r = await get_redis()
    token = secrets.token_urlsafe(32)
    await r.set(_key_token_reset(token), rfc_personal, ex=TOKEN_RESET_TTL_SEGUNDOS)
    return token


async def consumir_token_reset(token: str) -> Optional[str]:
    """GETDEL atomico (Redis >= 6.2, redis-py >= 4.0): lee y borra en una
    sola operacion, para que dos requests concurrentes con el mismo token
    (ej. el usuario da doble-click en "Cambiar contrasena") no puedan
    consumirlo ambas - la segunda siempre encuentra la llave ya borrada.
    Devuelve el rfc_personal dueno del token, o None si el token no existe,
    ya expiro, o ya se uso (las 3 causas colapsan a la misma respuesta -
    ver nota en el endpoint, nunca se distingue el motivo al caller)."""
    r = await get_redis()
    return await r.getdel(_key_token_reset(token))
