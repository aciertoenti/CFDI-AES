"""
Tests de orden de GET /admin/emisores. Orden compuesto de 3 niveles:
  1. RFC del usuario logueado (X-Usuario-Rfc) coincide con el emisor - va
     primero, sin importar estado.
  2. Activo antes que Inactivo.
  3. created_at desc como desempate final.

A diferencia de test_resumen_negocio.py (que mockea la DB porque la logica
interesante ahi es el manejo de fallos de facturacion), aqui lo unico
interesante ES el ORDER BY - un fake que simule scalar_one_or_none() no
probaria nada real sobre el orden que devuelve Postgres. Por eso estos tests
usan la BD real (AsyncSessionLocal, mismo engine que la app) con filas
temporales que se insertan y se borran en cada test - no tocan datos de
negocio reales (EKU9003173C9 y compania).
"""
from datetime import datetime, timedelta

import main
import pytest
import pytest_asyncio
from database import AsyncSessionLocal, Emisor, Negocio, engine


@pytest_asyncio.fixture(autouse=True)
async def _pool_por_test():
    # engine es un singleton de modulo (mismo patron/bug ya visto con
    # redis_client._redis en auth_usuarios): su pool de conexiones queda
    # atado al event loop del primer test que lo usa. pytest-asyncio crea
    # un loop nuevo por test (modo auto), asi que sin este dispose() el
    # 2o test en adelante truena con "another operation is in progress"
    # (asyncpg reutilizando una conexion de un loop ya cerrado).
    await engine.dispose()
    yield


def _csd_dummy():
    # Cualquier texto sirve - CifradoFernet solo cifra/descifra de forma
    # transparente, no valida que sea un CSD real a nivel de columna.
    return "dummy-no-es-un-csd-real"


@pytest.fixture
async def negocio_temporal():
    """Negocio real y aislado (no uno de los de negocio real del sistema),
    borrado junto con sus emisores al final del test."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST orden emisores", plan="basico")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(
            Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id)
        )
        await session.execute(
            Negocio.__table__.delete().where(Negocio.id == negocio_id)
        )
        await session.commit()


async def _crear_emisor(session, *, negocio_id, rfc, estado, created_at):
    e = Emisor(
        negocio_id=negocio_id,
        rfc=rfc,
        razon_social=f"TEST {rfc}",
        regimen_fiscal="601",
        codigo_postal="00000",
        csd_cert_base64=_csd_dummy(),
        csd_key_base64=_csd_dummy(),
        csd_password=_csd_dummy(),
        estado=estado,
        created_at=created_at,
    )
    session.add(e)
    return e


async def test_activo_mas_antiguo_va_antes_que_inactivo_mas_reciente(negocio_temporal):
    ahora = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST010101AA1",
            estado="Activo", created_at=ahora - timedelta(days=30),  # mas antiguo
        )
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST020202BB2",
            estado="Inactivo", created_at=ahora,  # mas reciente
        )
        await session.commit()

        out = await main.listar_emisores(db=session, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None)

    rfcs = [e.rfc for e in out]
    assert rfcs == ["TEST010101AA1", "TEST020202BB2"], (
        "el Activo (mas antiguo) debe ir primero, no el Inactivo (mas reciente)"
    )


async def test_entre_activos_se_mantiene_orden_por_fecha_desc(negocio_temporal):
    ahora = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST030303CC3",
            estado="Activo", created_at=ahora - timedelta(days=10),
        )
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST040404DD4",
            estado="Activo", created_at=ahora,
        )
        await session.commit()

        out = await main.listar_emisores(db=session, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None)

    rfcs = [e.rfc for e in out]
    assert rfcs == ["TEST040404DD4", "TEST030303CC3"], (
        "sin importar el orden compuesto, entre 2 Activos sigue ganando el mas reciente"
    )


# ─── caso borde: sin ningun emisor Activo ──────────────────────────────────

async def test_sin_ningun_emisor_activo_cae_a_orden_por_fecha_sin_error(negocio_temporal):
    ahora = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST050505EE5",
            estado="Inactivo", created_at=ahora - timedelta(days=5),
        )
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST060606FF6",
            estado="Inactivo", created_at=ahora,
        )
        await session.commit()

        # No debe lanzar - el ORDER BY compuesto degrada limpio a "solo
        # fecha" cuando ningun emisor cumple estado == "Activo".
        out = await main.listar_emisores(db=session, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None)

    rfcs = [e.rfc for e in out]
    assert rfcs == ["TEST060606FF6", "TEST050505EE5"]


async def test_un_solo_emisor_no_rompe_el_order_by(negocio_temporal):
    async with AsyncSessionLocal() as session:
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST070707GG7",
            estado="Activo", created_at=datetime.utcnow(),
        )
        await session.commit()

        out = await main.listar_emisores(db=session, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None)

    assert [e.rfc for e in out] == ["TEST070707GG7"]


# ─── nivel 1: RFC del usuario logueado (Pedro/RAHP7112093H0, negocio 11) ───

async def test_rfc_usuario_coincide_va_primero_aunque_sea_inactivo_y_mas_antiguo(negocio_temporal):
    """El caso mas exigente: el emisor del usuario es Inactivo Y mas
    antiguo que el otro (Activo, mas reciente) - bajo la regla vieja
    perderia en los 2 desempates. Con el nivel 1 nuevo, gana igual."""
    ahora = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST080808HH8",
            estado="Inactivo", created_at=ahora - timedelta(days=30),  # el del usuario
        )
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST090909II9",
            estado="Activo", created_at=ahora,
        )
        await session.commit()

        out = await main.listar_emisores(
            db=session, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TEST080808HH8",
        )

    assert [e.rfc for e in out] == ["TEST080808HH8", "TEST090909II9"]


async def test_usuario_sin_emisor_propio_cae_a_regla_de_activo_y_fecha(negocio_temporal):
    """x_usuario_rfc no coincide con ningun emisor del negocio (ej. admin
    de despacho sin RFC propio como emisor) - el nivel 1 no debe afectar
    nada, cae limpio a las reglas 2/3 de siempre."""
    ahora = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST101010JJ0",
            estado="Activo", created_at=ahora - timedelta(days=30),
        )
        await _crear_emisor(
            session, negocio_id=negocio_temporal, rfc="TEST111111KK1",
            estado="Inactivo", created_at=ahora,
        )
        await session.commit()

        out = await main.listar_emisores(
            db=session, x_negocio_id=str(negocio_temporal), x_usuario_rfc="RFC_QUE_NO_EXISTE_AQUI",
        )

    assert [e.rfc for e in out] == ["TEST101010JJ0", "TEST111111KK1"]
