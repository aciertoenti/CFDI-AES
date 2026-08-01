"""
Almacenamiento de sesiones de conversación en Redis.
TTL de 30 min (configurable en settings.session_ttl_seconds).
La sesión incluye el estado de la máquina de estados y los datos capturados.
"""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis

from core.config import settings
from core.logging import get_logger
from models.schemas import EstadoConversacion
from services.state_machine import DatosCapturados, SessionContext

logger = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None
_memory_sessions: dict[str, dict] = {}


async def get_redis() -> Optional[aioredis.Redis]:
    global _redis
    if _redis is not None:
        return _redis

    try:
        _redis = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        return _redis
    except Exception as exc:
        logger.warning("session.redis_unavailable", error=str(exc))
        return None


def _session_key(wa_id: str) -> str:
    return f"bot:session:{wa_id}"


async def load_session(wa_id: str) -> SessionContext:
    """Carga la sesión desde Redis o, si no está disponible, desde memoria local."""
    redis_client = await get_redis()
    if redis_client is not None:
        try:
            raw = await redis_client.get(_session_key(wa_id))
            if raw:
                data = json.loads(raw)
                return SessionContext(
                    wa_id=wa_id,
                    estado=EstadoConversacion(data.get("estado", EstadoConversacion.INICIO)),
                    datos=DatosCapturados.from_dict(data.get("datos", {})),
                    opt_in=data.get("opt_in", False),
                    intentos_rfc=data.get("intentos_rfc", 0),
                )
        except Exception as exc:
            logger.error("session.load_error", wa_id=wa_id, error=str(exc))

    raw = _memory_sessions.get(wa_id)
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return SessionContext(
                wa_id=wa_id,
                estado=EstadoConversacion(data.get("estado", EstadoConversacion.INICIO)),
                datos=DatosCapturados.from_dict(data.get("datos", {})),
                opt_in=data.get("opt_in", False),
                intentos_rfc=data.get("intentos_rfc", 0),
            )
        except Exception as exc:
            logger.error("session.load_error", wa_id=wa_id, error=str(exc))

    return SessionContext(wa_id=wa_id)


async def save_session(ctx: SessionContext) -> None:
    """Guarda la sesión en Redis cuando esté disponible; si no, usa memoria local."""
    data = {
        "estado": ctx.estado.value,
        "datos": ctx.datos.to_dict(),
        "opt_in": ctx.opt_in,
        "intentos_rfc": ctx.intentos_rfc,
    }

    redis_client = await get_redis()
    if redis_client is not None:
        try:
            await redis_client.setex(
                _session_key(ctx.wa_id),
                settings.session_ttl_seconds,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception as exc:
            logger.error("session.save_error", wa_id=ctx.wa_id, error=str(exc))

    _memory_sessions[ctx.wa_id] = data


async def delete_session(wa_id: str) -> None:
    """Elimina la sesión de Redis o de la memoria local."""
    redis_client = await get_redis()
    if redis_client is not None:
        try:
            await redis_client.delete(_session_key(wa_id))
        except Exception as exc:
            logger.error("session.delete_error", wa_id=wa_id, error=str(exc))

    _memory_sessions.pop(wa_id, None)
