"""
Tests de _debe_disparar_cierre_automatico y _job_cierre_automatico_
consolidacion (facturacion/main.py) - g7imYM pieza 3, cierre automatico
de consolidacion de Publico en General.

_debe_disparar_cierre_automatico es funcion PURA (sin I/O, sin BD) - se
prueba directo con un "ahora" controlado, sin mocks (mismo criterio ya
usado para generar la evidencia en vivo de este cambio, ver
79_evidencia_g7imYM_6_casos.txt: los casos reales de "mensual + ultimo
dia del mes" se probaron asi porque el dia real de la corrida no lo era).

_job_cierre_automatico_consolidacion SI hace I/O (GET a administracion
via httpx.AsyncClient) - se mockea con el mismo patron _FakeResp/
_FakeClient de test_obtener_plan_negocio.py, para el unico caso facil
de aislar sin tocar Postgres: 0 emisores elegibles (el for nunca abre
una sesion de BD, ver el codigo real).
"""
from datetime import datetime

import main
from main import _debe_disparar_cierre_automatico, _job_cierre_automatico_consolidacion


# ─── _debe_disparar_cierre_automatico: bordes de la ventana horaria ────────

def test_exactamente_al_inicio_de_la_ventana_dispara():
    # hora_cierre=14:00, ahora=14:00:00 en punto - limite inferior INCLUSIVO.
    ahora = datetime(2026, 9, 18, 14, 0, 0)
    assert _debe_disparar_cierre_automatico("diario", "14:00", ahora) is True


def test_dentro_de_la_ventana_dispara():
    # hora_cierre=14:00, ahora=14:02 - dentro de [14:00, 14:05).
    ahora = datetime(2026, 9, 18, 14, 2)
    assert _debe_disparar_cierre_automatico("diario", "14:00", ahora) is True


def test_justo_fuera_de_la_ventana_no_dispara():
    # hora_cierre=14:00, ahora=14:05 en punto - limite superior EXCLUSIVO
    # (INTERVALO_SCHEDULER_MINUTOS=5): la ventana es [14:00, 14:05), 14:05
    # ya queda fuera.
    ahora = datetime(2026, 9, 18, 14, 5, 0)
    assert _debe_disparar_cierre_automatico("diario", "14:00", ahora) is False


def test_antes_de_la_hora_configurada_no_dispara():
    ahora = datetime(2026, 9, 18, 13, 59)
    assert _debe_disparar_cierre_automatico("diario", "14:00", ahora) is False


# ─── "diario": sin chequeo de dia del mes ──────────────────────────────────

def test_diario_dispara_cualquier_dia_del_mes():
    # Dia 1 y dia 31 del mes, misma hora, misma ventana - ambos disparan,
    # confirma que "diario" no aplica NINGUN chequeo de dia del mes (a
    # diferencia de "mensual").
    assert _debe_disparar_cierre_automatico("diario", "14:00", datetime(2026, 1, 1, 14, 1)) is True
    assert _debe_disparar_cierre_automatico("diario", "14:00", datetime(2026, 1, 31, 14, 1)) is True


# ─── "mensual": exige ADEMAS que hoy sea el ultimo dia del mes ─────────────

def test_mensual_hoy_no_es_ultimo_dia_del_mes_no_dispara():
    # Septiembre 2026 tiene 30 dias - el 29 esta DENTRO de la ventana
    # horaria pero NO es el ultimo dia, no debe disparar aunque la hora
    # coincida exactamente.
    ahora = datetime(2026, 9, 29, 14, 1)
    assert _debe_disparar_cierre_automatico("mensual", "14:00", ahora) is False


def test_mensual_hoy_si_es_ultimo_dia_del_mes_dispara():
    ahora = datetime(2026, 9, 30, 14, 1)
    assert _debe_disparar_cierre_automatico("mensual", "14:00", ahora) is True


def test_mensual_mes_de_28_dias_dispara_el_28_no_el_30():
    # Febrero 2026 - 2026 no es bisiesto (2026 % 4 != 0), 28 dias exactos.
    # Confirma que la logica usa calendar.monthrange REAL, no un "30 o 31"
    # hardcodeado que fallaria en febrero.
    assert _debe_disparar_cierre_automatico("mensual", "14:00", datetime(2026, 2, 28, 14, 1)) is True
    # El 25 esta DENTRO de la ventana horaria pero no es el ultimo dia.
    assert _debe_disparar_cierre_automatico("mensual", "14:00", datetime(2026, 2, 25, 14, 1)) is False


def test_mensual_mes_de_31_dias_dispara_el_31_no_antes():
    # Enero 2026 - 31 dias.
    assert _debe_disparar_cierre_automatico("mensual", "14:00", datetime(2026, 1, 31, 14, 1)) is True
    assert _debe_disparar_cierre_automatico("mensual", "14:00", datetime(2026, 1, 30, 14, 1)) is False


# ─── _job_cierre_automatico_consolidacion: integracion minima ─────────────
# Mismo patron _FakeResp/_FakeClient que test_obtener_plan_negocio.py -
# mockea main.httpx.AsyncClient, sin tocar Postgres real.

class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else []

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return self._resp


async def test_job_sin_emisores_elegibles_termina_limpio_sin_error(monkeypatch):
    # GET /admin/emisores/consolidacion-automatica devuelve [] (0
    # candidatos) - el tick debe terminar sin excepcion y SIN abrir
    # ninguna sesion de BD (AsyncSessionLocal solo se abre DENTRO del for,
    # que aqui nunca itera - por eso este caso es seguro de aislar sin
    # mockear Postgres).
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(_FakeResp(json_data=[])),
    )
    await _job_cierre_automatico_consolidacion()  # no debe lanzar
