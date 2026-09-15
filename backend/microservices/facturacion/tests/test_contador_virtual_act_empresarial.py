"""
Tests del Contador Virtual Fase 2 (zg1cYDU) - ISR Art. 106 (Actividad
Empresarial y Profesional, regimen 612), acumulado desde enero + IVA
simple del mes. NO reutiliza Fase 1 (RESICO) - mecanica distinta.

Mockea main.obtener_datos_emisor (llamada real a administracion) - no
depende de administracion real, mismo patron que ya usa
test_obtener_plan_negocio.py. Usa Postgres REAL (mismo patron ya
establecido en administracion/tests/test_listar_emisores_orden.py) para
las Facturas: la acumulacion multi-mes y el escalamiento de la tarifa por
Art. 106 es justamente lo que hay que probar contra datos reales, un mock
no lo cubriria.

Los 2 casos manuales (test_caso_manual_*) fueron verificados ademas con
una segunda cuenta INDEPENDIENTE (Python nuevo, sin importar main.py) y
contra el endpoint real corriendo en Docker antes de escribir estos
tests - ver evidencia entregada en el chat.
"""
from datetime import datetime
from decimal import Decimal

import main
import pytest
import pytest_asyncio
from database import AsyncSessionLocal, Factura, engine

RFC_TEST = "TEST010101AA1"
NEGOCIO_ID_TEST = 999001  # aislado de negocios reales, solo referencia local


@pytest_asyncio.fixture(autouse=True)
async def _pool_por_test():
    # Mismo bug/fix ya documentado en administracion/tests/test_listar_emisores_orden.py.
    await engine.dispose()
    yield


def _mockear_emisor(monkeypatch, regimen_fiscal="612"):
    async def _fake_obtener_datos_emisor(rfc, x_negocio_id=None):
        return {"regimen_fiscal": regimen_fiscal, "codigo_postal": "01000"}
    monkeypatch.setattr(main, "obtener_datos_emisor", _fake_obtener_datos_emisor)


@pytest.fixture
async def facturas_temporales():
    """Limpia cualquier Factura de RFC_TEST antes y despues del test -
    aislado por RFC unico de prueba, no toca datos reales."""
    async with AsyncSessionLocal() as session:
        await session.execute(Factura.__table__.delete().where(Factura.emisor_rfc == RFC_TEST))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(Factura.__table__.delete().where(Factura.emisor_rfc == RFC_TEST))
        await session.commit()


async def _crear_factura(session, *, mes, anio, monto: Decimal, estado="Vigente"):
    import uuid
    f = Factura(
        uuid=str(uuid.uuid4()),
        negocio_id=NEGOCIO_ID_TEST,
        folio=f"TEST-{anio}{mes:02d}-{uuid.uuid4().hex[:6]}",
        fecha_timbrado=datetime(anio, mes, 15, 12, 0, 0),
        emisor_rfc=RFC_TEST,
        receptor_rfc="TES020202BB2",
        subtotal=(monto / Decimal("1.16")).quantize(Decimal("0.01")),
        total_iva=(monto - monto / Decimal("1.16")).quantize(Decimal("0.01")),
        total=monto,
        estado=estado,
        xml="<xml>dummy-test</xml>",
        metodo_pago="PUE",
    )
    session.add(f)


# ─── Caso manual 1: mes 1, sin meses previos (mismo ejemplo de la fuente de la tarifa) ──

async def test_caso_manual_mes_1_sin_meses_previos(monkeypatch, facturas_temporales):
    """$15,000 en enero -> bracket 5 (14644.65-17533.64), sin escalar
    (meses=1). ISR esperado 1402.82 - verificado independientemente
    (cuenta aparte, sin importar main.py) y contra el endpoint real antes
    de escribir este test."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=1, anio=2026, monto=Decimal("15000.00"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=1, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )

    assert out.aplica is True
    assert out.ingresos_mes == 15000.0
    assert out.base_gravable_acumulada == 15000.0
    assert out.isr_acumulado == 1402.82
    assert out.isr_pagado_meses_anteriores == 0.0  # caso borde pedido: mes 1, nada que restar
    assert out.isr_a_pagar_mes == 1402.82
    assert out.iva_a_pagar_mes == 2400.0  # 15000 * 0.16
    assert out.gastos_mes == 0.0
    assert "CFDI recibidos" in out.advertencia


# ─── Caso manual 2: mes 6, acumulado multi-mes, tramo DISTINTO al caso 1 ────

async def test_caso_manual_mes_6_acumulado_tramo_distinto(monkeypatch, facturas_temporales):
    """Enero $15,000 + Feb-Jun $21,000 c/u = acumulado $120,000 a junio.
    Bracket 6 (17533.65-35362.83) ESCALADO x6 - tramo distinto al caso 1
    (bracket 5). Valores esperados verificados con una segunda cuenta
    independiente (Python aparte) Y contra el endpoint real corriendo:
      isr_acumulado(mes 6, base 120000, x6)  = 14301.91
      isr_acumulado(mes 5, base 99000, x5)   = 11704.66 (= isr_pagado_meses_anteriores)
      isr_a_pagar_mes = 14301.91 - 11704.66  = 2597.25
    """
    _mockear_emisor(monkeypatch)
    montos = {1: Decimal("15000.00"), 2: Decimal("21000.00"), 3: Decimal("21000.00"),
              4: Decimal("21000.00"), 5: Decimal("21000.00"), 6: Decimal("21000.00")}
    async with AsyncSessionLocal() as session:
        for mes, monto in montos.items():
            await _crear_factura(session, mes=mes, anio=2026, monto=monto)
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=6, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )

    assert out.ingresos_mes == 21000.0  # solo el de junio, no el acumulado
    assert out.base_gravable_acumulada == 120000.0
    assert out.isr_acumulado == 14301.91
    assert out.isr_pagado_meses_anteriores == 11704.66
    assert out.isr_a_pagar_mes == 2597.25
    assert out.iva_a_pagar_mes == 3360.0  # 21000 * 0.16


# ─── Caso borde: mes 1 del ano (ya cubierto arriba, se reafirma explicito) ──

async def test_mes_1_no_intenta_restar_mes_0(monkeypatch, facturas_temporales):
    """Caso borde pedido explicitamente: mes=1 no debe intentar calcular
    un 'mes 0' (indefinido/division rara) - isr_pagado_meses_anteriores
    debe ser 0.0 SIEMPRE en mes 1, sin importar el monto."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=1, anio=2026, monto=Decimal("500000.00"))  # ultimo tramo
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=1, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.isr_pagado_meses_anteriores == 0.0


# ─── Caso borde: ingresos en $0 ─────────────────────────────────────────────

async def test_ingresos_en_cero_no_truena(monkeypatch, facturas_temporales):
    """Sin ninguna Factura para el RFC/periodo - no debe dividir entre
    cero ni lanzar excepcion, todo en 0."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=3, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.aplica is True
    assert out.ingresos_mes == 0.0
    assert out.base_gravable_acumulada == 0.0
    assert out.isr_acumulado == 0.0
    assert out.isr_a_pagar_mes == 0.0
    assert out.iva_a_pagar_mes == 0.0


async def test_ingresos_negativos_o_isr_a_pagar_nunca_negativo(monkeypatch, facturas_temporales):
    """Caso real confirmado en la verificacion manual: escalar la tarifa a
    mas meses con la MISMA base acumulada puede dar un isr_acumulado menor
    que el ya 'pagado' en el mes anterior (la tarifa escalada es mas
    ancha). isr_a_pagar_mes debe caer a 0.0, nunca negativo."""
    _mockear_emisor(monkeypatch)
    montos = {1: Decimal("15000.00"), 2: Decimal("21000.00"), 3: Decimal("21000.00"),
              4: Decimal("21000.00"), 5: Decimal("21000.00"), 6: Decimal("21000.00")}
    async with AsyncSessionLocal() as session:
        for mes, monto in montos.items():
            await _crear_factura(session, mes=mes, anio=2026, monto=monto)
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=12, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.base_gravable_acumulada == 120000.0  # sin facturas nuevas jul-dic
    assert out.isr_a_pagar_mes == 0.0
    assert out.isr_a_pagar_mes >= 0.0


# ─── Regimen distinto: no aplica, sin tronar ────────────────────────────────

async def test_regimen_distinto_no_aplica(monkeypatch, facturas_temporales):
    _mockear_emisor(monkeypatch, regimen_fiscal="601")
    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=1, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.aplica is False
    assert "612" in out.motivo_no_aplica


async def test_persona_moral_con_codigo_612_no_aplica(monkeypatch, facturas_temporales):
    """612 tambien puede corresponder a Persona Moral por longitud de RFC
    (12 caracteres) - mismo criterio ya usado en Fase 1 (RESICO) para
    distinguir PF/PM por longitud de RFC, no solo por el codigo de regimen."""
    _mockear_emisor(monkeypatch, regimen_fiscal="612")
    rfc_moral = "TES020202BB2"  # 12 caracteres
    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=rfc_moral, anio=2026, mes=1, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.aplica is False


# ─── Facturas canceladas y PPD no cuentan como ingreso acumulado ───────────

async def test_facturas_canceladas_no_cuentan(monkeypatch, facturas_temporales):
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=2, anio=2026, monto=Decimal("15000.00"))
        await _crear_factura(session, mes=2, anio=2026, monto=Decimal("9999.00"), estado="Cancelada")
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_actividad_empresarial(
            emisor_rfc=RFC_TEST, anio=2026, mes=2, db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.ingresos_mes == 15000.0
    assert out.base_gravable_acumulada == 15000.0
