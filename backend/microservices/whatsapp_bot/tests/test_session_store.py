import pytest
from unittest.mock import AsyncMock

from services import session_store
from services.state_machine import EstadoConversacion


@pytest.mark.asyncio
async def test_load_session_returns_fresh_context_when_redis_is_unavailable(monkeypatch):
    session_store._memory_sessions.clear()
    monkeypatch.setattr(session_store, "get_redis", AsyncMock(return_value=None))

    ctx = await session_store.load_session("wa_test")

    assert ctx.wa_id == "wa_test"
    assert ctx.estado == EstadoConversacion.INICIO


@pytest.mark.asyncio
async def test_save_session_uses_memory_fallback_when_redis_is_unavailable(monkeypatch):
    session_store._memory_sessions.clear()
    monkeypatch.setattr(session_store, "get_redis", AsyncMock(return_value=None))

    ctx = session_store.SessionContext(wa_id="wa_test", estado=EstadoConversacion.CAPTURA_RFC)
    await session_store.save_session(ctx)

    assert session_store._memory_sessions["wa_test"]["estado"] == EstadoConversacion.CAPTURA_RFC.value
