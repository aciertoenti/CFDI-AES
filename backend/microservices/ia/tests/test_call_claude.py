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


# ─── thinking_disabled (g7ilnY, 21 sep 2026) ───────────────────────────────
# Causa raiz real confirmada (llamada real a la API, ver evidencia del
# cierre de g7ilnY): omitir `thinking` NO lo deja desactivado por default en
# claude-sonnet-5+ (al reves de lo que asumia el comentario viejo de
# _payload_claude) - viene ACTIVADO, y con max_tokens chico se comia el
# presupuesto entero en razonamiento antes de emitir el JSON
# (detectar_anomalias con 36 facturas reales de EKU9003173C9, 502
# stop_reason=max_tokens, reproducido). thinking_disabled=True SI fue
# confirmado aceptado por la API (HTTP 200, thinking_tokens=0 real).

def test_payload_claude_sin_thinking_disabled_no_manda_la_clave():
    # default (thinking_disabled=False, sin cambios de comportamiento para
    # los demas call_site que no lo activaron - fuera de alcance de g7ilnY).
    payload = main._payload_claude([{"role": "user", "content": "hola"}], "sys", 800)
    assert "thinking" not in payload


def test_payload_claude_con_thinking_disabled_manda_type_disabled():
    payload = main._payload_claude([{"role": "user", "content": "hola"}], "sys", 4096, thinking_disabled=True)
    assert payload["thinking"] == {"type": "disabled"}


async def test_call_claude_propaga_thinking_disabled_al_payload(monkeypatch):
    payload_capturado = {}

    async def _fake_post(payload):
        payload_capturado.update(payload)
        return dict(RESP_OK)

    monkeypatch.setattr(main, "_post_claude", _fake_post)

    out = await main.call_claude(
        [{"role": "user", "content": "hola"}], "sys", max_tokens=4096,
        call_site="detectar_anomalias", thinking_disabled=True,
    )

    assert out == "HOLA MUNDO"
    assert payload_capturado["thinking"] == {"type": "disabled"}
    assert payload_capturado["max_tokens"] == 4096


async def test_call_claude_sin_thinking_disabled_no_manda_la_clave_por_default(monkeypatch):
    payload_capturado = {}

    async def _fake_post(payload):
        payload_capturado.update(payload)
        return dict(RESP_OK)

    monkeypatch.setattr(main, "_post_claude", _fake_post)

    await main.call_claude([{"role": "user", "content": "hola"}], "sys", call_site="chat_fiscal")

    assert "thinking" not in payload_capturado


# ─── filtrado de campos sin valor analitico en detectar_anomalias (g7ilnY) ─
# xml_url/pdf_url (URLs firmadas de MinIO) + noCertificadoSAT: ~68% del
# payload real con las 36 facturas de EKU9003173C9 que reprodujeron el bug,
# sin ningun valor para detectar anomalias fiscales.

def test_factura_para_prompt_ia_excluye_campos_sin_valor_analitico():
    factura = {
        "uuid": "abc-123", "folio": "A-0001", "total": 100.0,
        "xml_url": "https://minio/xml?firma=...", "pdf_url": "https://minio/pdf?firma=...",
        "noCertificadoSAT": "30001000000500003416",
    }
    limpia = main._factura_para_prompt_ia(factura)
    assert "xml_url" not in limpia
    assert "pdf_url" not in limpia
    assert "noCertificadoSAT" not in limpia
    assert limpia == {"uuid": "abc-123", "folio": "A-0001", "total": 100.0}


def test_factura_para_prompt_ia_no_rompe_si_faltan_los_campos():
    # Degradacion sin romper (mismo criterio de toda la sesion): una factura
    # que ya viniera sin estos campos (ej. otro caller futuro) no debe
    # lanzar KeyError.
    factura = {"uuid": "abc-123", "folio": "A-0001"}
    assert main._factura_para_prompt_ia(factura) == factura
