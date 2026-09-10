"""
Tests del manejo de "Claude respondio sin texto utilizable" en ia/main.py
(zg4pAxA): un bloque `thinking` vacio + stop_reason=max_tokens, sin ningun
bloque de texto.

NO se llama a la API real: se mockean los helpers factorizados
main._post_claude y main._stream_eventos_claude.
"""
import main
import pytest
from main import ClaudeRespuestaVaciaError, call_claude, stream_claude

# Respuesta real observada (zg4pAxA, detectar_anomalias 27 ago): solo thinking.
RESP_THINKING_VACIO = {
    "content": [{"type": "thinking", "thinking": "", "signature": "abc"}],
    "stop_reason": "max_tokens",
}
RESP_TEXT_VACIO = {  # bloque text presente pero string vacio/whitespace
    "content": [{"type": "text", "text": "   "}],
    "stop_reason": "max_tokens",
}
RESP_OK = {
    "content": [{"type": "text", "text": "HOLA MUNDO"}],
    "stop_reason": "end_turn",
}


class _FakePost:
    """Sustituye a main._post_claude. Devuelve `respuestas[i]` en la i-esima
    llamada (repite la ultima si se piden mas)."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    async def __call__(self, payload):
        i = min(self.llamadas, len(self.respuestas) - 1)
        self.llamadas += 1
        return self.respuestas[i]


class _FakeStream:
    """Sustituye a main._stream_eventos_claude. `intentos[i]` es la lista de
    eventos SSE (dicts ya parseados) que emite la i-esima llamada."""

    def __init__(self, *intentos):
        self.intentos = list(intentos)
        self.llamadas = 0

    def __call__(self, payload):
        i = min(self.llamadas, len(self.intentos) - 1)
        self.llamadas += 1
        eventos = self.intentos[i]

        async def _gen():
            for ev in eventos:
                yield ev

        return _gen()


def _txt_delta(t):
    return {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}


def _thinking_delta(t=""):
    return {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": t}}


# ─── call_claude ────────────────────────────────────────────────────────────

async def test_call_claude_thinking_vacio_reintenta_y_lanza_error_especifico(monkeypatch):
    fake = _FakePost(RESP_THINKING_VACIO)  # siempre vacio
    monkeypatch.setattr(main, "_post_claude", fake)

    with pytest.raises(ClaudeRespuestaVaciaError) as exc:
        await call_claude([{"role": "user", "content": "hola"}], "sys", call_site="detectar_anomalias")

    assert fake.llamadas == 2, "debe reintentar exactamente una vez (2 llamadas)"
    assert exc.value.call_site == "detectar_anomalias"
    assert exc.value.stop_reason == "max_tokens"
    assert "thinking" in exc.value.tipos_bloque
    # NO es un HTTPException/502 generico
    assert not isinstance(exc.value, main.HTTPException)


async def test_call_claude_texto_solo_whitespace_cuenta_como_vacio(monkeypatch):
    fake = _FakePost(RESP_TEXT_VACIO)
    monkeypatch.setattr(main, "_post_claude", fake)

    with pytest.raises(ClaudeRespuestaVaciaError):
        await call_claude([{"role": "user", "content": "x"}], "sys", call_site="extraer_documento")
    assert fake.llamadas == 2


async def test_call_claude_reintento_exitoso_devuelve_texto(monkeypatch):
    fake = _FakePost(RESP_THINKING_VACIO, RESP_OK)  # 1er intento vacio, 2do OK
    monkeypatch.setattr(main, "_post_claude", fake)

    out = await call_claude([{"role": "user", "content": "hola"}], "sys", call_site="chat_fiscal")

    assert out == "HOLA MUNDO"
    assert fake.llamadas == 2


async def test_call_claude_primer_intento_ok_no_reintenta(monkeypatch):
    fake = _FakePost(RESP_OK)
    monkeypatch.setattr(main, "_post_claude", fake)

    out = await call_claude([{"role": "user", "content": "hola"}], "sys", call_site="chat_fiscal")

    assert out == "HOLA MUNDO"
    assert fake.llamadas == 1


# ─── stream_claude ─────────────────────────────────────────────────────────

async def test_stream_claude_sin_text_delta_reintenta_y_lanza(monkeypatch):
    # ambos intentos: solo thinking_delta, ningun text_delta
    fake = _FakeStream(
        [_thinking_delta(""), {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}}],
        [_thinking_delta("")],
    )
    monkeypatch.setattr(main, "_stream_eventos_claude", fake)

    with pytest.raises(ClaudeRespuestaVaciaError) as exc:
        async for _ in stream_claude([{"role": "user", "content": "x"}], "sys", call_site="chat_fiscal_stream"):
            pass

    assert fake.llamadas == 2, "debe reintentar el stream una vez"
    assert exc.value.call_site == "chat_fiscal_stream"
    assert exc.value.stop_reason == "stream_sin_text_delta"


async def test_stream_claude_reintento_exitoso_emite_tokens(monkeypatch):
    fake = _FakeStream(
        [_thinking_delta("")],                 # 1er intento: sin texto
        [_txt_delta("Ho"), _txt_delta("la")],  # 2do intento: texto real
    )
    monkeypatch.setattr(main, "_stream_eventos_claude", fake)

    chunks = [
        c
        async for c in stream_claude([{"role": "user", "content": "x"}], "sys", call_site="chat_fiscal_stream")
    ]

    assert chunks == ["Ho", "la"]
    assert fake.llamadas == 2


async def test_stream_claude_primer_intento_con_texto_no_reintenta(monkeypatch):
    fake = _FakeStream([_txt_delta("A"), _txt_delta("B")])
    monkeypatch.setattr(main, "_stream_eventos_claude", fake)

    chunks = [
        c
        async for c in stream_claude([{"role": "user", "content": "x"}], "sys", call_site="chat_fiscal_stream")
    ]

    assert chunks == ["A", "B"]
    assert fake.llamadas == 1


# ─── helper de extraccion ──────────────────────────────────────────────────

def test_extraer_texto_concatena_todos_los_bloques_text():
    data = {"content": [
        {"type": "thinking", "thinking": "razonando..."},
        {"type": "text", "text": "parte 1 "},
        {"type": "text", "text": "parte 2"},
    ]}
    assert main._extraer_texto(data) == "parte 1 parte 2"


def test_extraer_texto_sin_bloque_text_devuelve_vacio():
    assert main._extraer_texto({"content": [{"type": "thinking", "thinking": "x"}]}) == ""
    assert main._extraer_texto({"content": []}) == ""
