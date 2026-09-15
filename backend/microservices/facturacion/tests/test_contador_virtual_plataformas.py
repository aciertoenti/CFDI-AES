"""
Tests del Contador Virtual Fase 3 (zg1cYDU/zg645h8) - retencion de ISR
(Art. 113-A LISR) e IVA para Actividades Empresariales via Plataformas
Tecnologicas (regimen 625). NO acumulado (a diferencia de Fase 2/Art. 106) -
cada mes se calcula aislado, mismo criterio que RESICO (Fase 1).

Mockea main.obtener_datos_emisor, Postgres REAL para las Facturas - mismo
patron que test_contador_virtual_act_empresarial.py.

Los 3 casos manuales (uno por actividad) fueron verificados a mano
(ingreso x tasa) y ademas contra el endpoint real corriendo en Docker,
usando la cuenta real de Pedro (RAHP7112093H0, regimen 625) con una
factura temporal insertada y eliminada despues de la prueba - ver
evidencia entregada en el chat.
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
    await engine.dispose()
    yield


def _mockear_emisor(monkeypatch, regimen_fiscal="625"):
    async def _fake_obtener_datos_emisor(rfc, x_negocio_id=None):
        return {"regimen_fiscal": regimen_fiscal, "codigo_postal": "01000"}
    monkeypatch.setattr(main, "obtener_datos_emisor", _fake_obtener_datos_emisor)


@pytest.fixture
async def facturas_temporales():
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


# ─── Caso manual 1: transporte, 2.1% ────────────────────────────────────────

async def test_caso_manual_transporte(monkeypatch, facturas_temporales):
    """$10,000 en septiembre, actividad transporte -> ISR = 10000*0.021 =
    210.00, IVA = 10000*0.08 = 800.00. Verificado a mano y contra el
    endpoint real con la cuenta de Pedro (RAHP7112093H0)."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=9, anio=2026, monto=Decimal("10000.00"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=9, actividad="transporte",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )

    assert out.aplica is True
    assert out.actividad == "transporte"
    assert out.ingresos_mes == 10000.0
    assert out.tasa_isr_aplicada == 0.021
    assert out.isr_retenido_mes == 210.0
    assert out.iva_retenido_mes == 800.0
    assert "300,000" in out.advertencia_umbral


# ─── Caso manual 2: hospedaje, 4% ───────────────────────────────────────────

async def test_caso_manual_hospedaje(monkeypatch, facturas_temporales):
    """$10,000 -> ISR = 10000*0.04 = 400.00, IVA = 800.00."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=9, anio=2026, monto=Decimal("10000.00"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=9, actividad="hospedaje",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )

    assert out.tasa_isr_aplicada == 0.04
    assert out.isr_retenido_mes == 400.0
    assert out.iva_retenido_mes == 800.0


# ─── Caso manual 3: contenido_digital, 1% ───────────────────────────────────

async def test_caso_manual_contenido_digital(monkeypatch, facturas_temporales):
    """$10,000 -> ISR = 10000*0.01 = 100.00, IVA = 800.00."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=9, anio=2026, monto=Decimal("10000.00"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=9, actividad="contenido_digital",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )

    assert out.tasa_isr_aplicada == 0.01
    assert out.isr_retenido_mes == 100.0
    assert out.iva_retenido_mes == 800.0


# ─── No acumulado: un mes con ingreso previo no afecta al mes siguiente ────

async def test_no_es_acumulado_entre_meses(monkeypatch, facturas_temporales):
    """A diferencia de Fase 2 (Art. 106), cada mes se calcula aislado - un
    ingreso grande en agosto NO debe sumarse al calculo de septiembre."""
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=8, anio=2026, monto=Decimal("50000.00"))
        await _crear_factura(session, mes=9, anio=2026, monto=Decimal("10000.00"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=9, actividad="transporte",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.ingresos_mes == 10000.0  # NO 60000.0
    assert out.isr_retenido_mes == 210.0


# ─── Caso borde: ingresos en $0 ─────────────────────────────────────────────

async def test_ingresos_en_cero_no_truena(monkeypatch, facturas_temporales):
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=3, actividad="transporte",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.aplica is True
    assert out.ingresos_mes == 0.0
    assert out.isr_retenido_mes == 0.0
    assert out.iva_retenido_mes == 0.0


# ─── Regimen distinto: no aplica, sin tronar ────────────────────────────────

async def test_regimen_distinto_no_aplica(monkeypatch, facturas_temporales):
    _mockear_emisor(monkeypatch, regimen_fiscal="601")
    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=1, actividad="transporte",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.aplica is False
    assert "625" in out.motivo_no_aplica


async def test_persona_moral_con_codigo_625_no_aplica(monkeypatch, facturas_temporales):
    _mockear_emisor(monkeypatch, regimen_fiscal="625")
    rfc_moral = "TES020202BB2"  # 12 caracteres
    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=rfc_moral, anio=2026, mes=1, actividad="transporte",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.aplica is False


# ─── Facturas canceladas no cuentan ─────────────────────────────────────────

async def test_facturas_canceladas_no_cuentan(monkeypatch, facturas_temporales):
    _mockear_emisor(monkeypatch)
    async with AsyncSessionLocal() as session:
        await _crear_factura(session, mes=2, anio=2026, monto=Decimal("10000.00"))
        await _crear_factura(session, mes=2, anio=2026, monto=Decimal("9999.00"), estado="Cancelada")
        await session.commit()

    async with AsyncSessionLocal() as session:
        out = await main.contador_virtual_isr_plataformas(
            emisor_rfc=RFC_TEST, anio=2026, mes=2, actividad="transporte",
            db=session, x_negocio_id=str(NEGOCIO_ID_TEST),
        )
    assert out.ingresos_mes == 10000.0
