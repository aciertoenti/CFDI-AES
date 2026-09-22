"""
Tests del fallback explicito de generar_resumen (zg8CkcU, 22 sep 2026):
cuando la IA responde algo que no parsea como JSON (fragilidad
probabilistica del LLM al formatear JSON en texto libre - independiente
del bug de thinking ya corregido en zg4pAxA, ver
168_investigacion_zg8CkcU_texto_raw.txt), el endpoint debe:
  1. Seguir devolviendo 200 con {"texto_raw": ...} (decision explicita,
     status code sin cambios).
  2. Agregar "degradado": true, para que cualquier caller lo detecte sin
     inferirlo por la ausencia de campos esperados.
  3. Loguear con WARNING el call_site y el motivo especifico del fallo de
     parseo (antes de este cambio, ninguna de las 6 ramas
     "except json.JSONDecodeError" de este archivo logueaba nada).

NO se llama a la API real: se mockea main.call_claude (mismo nivel que
test_call_claude.py mockea main._post_claude, pero aqui un nivel mas
arriba - lo que generar_resumen() consume directamente).
"""
import logging

import main
import pytest
from main import SummaryRequest, generar_resumen


def _req():
    return SummaryRequest(
        periodo_inicio="2026-01-01",
        periodo_fin="2026-03-31",
        datos_facturacion={"total_acumulado": 1000.0, "num_facturas": 5, "promedio": 200.0, "por_mes": {}},
    )


async def test_json_no_parseable_agrega_campo_degradado(monkeypatch):
    # Mismo tipo de respuesta rota que hubiera devuelto el bug de thinking
    # ya corregido (JSON cortado a medio texto_ejecutivo) - pero aqui
    # simulado directo, sin depender de que el bug de thinking se
    # reproduzca, para probar el fallback en aislamiento.
    async def _fake_call_claude(*a, **k):
        return '{"titulo": "Reporte", "texto_ejecutivo": "empieza bien pero se corta a la mit'

    monkeypatch.setattr(main, "call_claude", _fake_call_claude)

    out = await generar_resumen(req=_req(), _="dummy")

    assert out["degradado"] is True
    assert "texto_raw" in out
    assert out["texto_raw"].startswith('{"titulo"')


async def test_json_valido_no_agrega_campo_degradado(monkeypatch):
    async def _fake_call_claude(*a, **k):
        return '{"titulo": "Reporte OK", "kpis_principales": [], "hallazgos": [], "riesgos": [], "recomendaciones": [], "texto_ejecutivo": "todo bien"}'

    monkeypatch.setattr(main, "call_claude", _fake_call_claude)

    out = await generar_resumen(req=_req(), _="dummy")

    assert "degradado" not in out
    assert "texto_raw" not in out
    assert out["titulo"] == "Reporte OK"


async def test_json_no_parseable_loguea_warning_con_call_site_y_motivo(monkeypatch, caplog):
    async def _fake_call_claude(*a, **k):
        return "esto no es JSON en absoluto"

    monkeypatch.setattr(main, "call_claude", _fake_call_claude)

    with caplog.at_level(logging.WARNING):
        out = await generar_resumen(req=_req(), _="dummy")

    assert out["degradado"] is True
    # Debe haber exactamente 1 WARNING (no silencioso, no duplicado).
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "generar_resumen" in msg  # call_site
    assert "fallback_texto_raw" in msg
    # El motivo especifico del fallo de parseo debe estar presente (no un
    # mensaje generico tipo "error de parseo") - mismo criterio de
    # diagnosticabilidad que _validar_certificado_es_csd (zg7DuHM): loguear
    # CUAL fue la causa exacta, no solo que algo fallo.
    assert "Expecting value" in msg or "line" in msg  # texto real de JSONDecodeError
