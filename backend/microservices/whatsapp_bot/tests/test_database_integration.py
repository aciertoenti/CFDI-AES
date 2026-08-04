"""
Prueba de integracion real (#37) - a diferencia del resto de la suite
(unitaria, con mocks), esta escribe y lee de verdad contra Postgres.

En CI corre contra el service de postgres de whatsapp-bot.yml, ya con el
bootstrap real (create_tables + stamp_head_si_es_ambiente_nuevo, #38)
aplicado antes de pytest - el mismo camino que seguiria un ambiente nuevo
real, no un atajo aparte.

Localmente, si no hay un Postgres real alcanzable en DATABASE_URL con las
tablas ya creadas, se omite en vez de fallar - no se quiere obligar a
nadie a levantar Postgres solo para correr la suite de unit tests con mocks.
"""
import pytest
from sqlalchemy import select

from models.database import AsyncSessionLocal
from models.schemas import EstadoConversacion, SesionConversacion


async def _postgres_real_disponible() -> bool:
    # Catch amplio a proposito: esto es solo una sonda de disponibilidad -
    # una conexion rechazada puede llegar como OperationalError de
    # SQLAlchemy, o como ConnectionRefusedError/OSError sin envolver
    # (visto en Windows con el event loop por defecto), o como
    # ProgrammingError si la BD existe pero le faltan las tablas. Cualquier
    # falla aqui significa "no se puede correr esta prueba", no un bug.
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(select(SesionConversacion).limit(1))
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_crear_y_leer_sesion_conversacion_contra_postgres_real():
    if not await _postgres_real_disponible():
        pytest.skip("Postgres real no disponible en DATABASE_URL - prueba de integracion omitida")

    wa_id = "5215500000099"

    async with AsyncSessionLocal() as session:
        existente = (
            await session.execute(select(SesionConversacion).where(SesionConversacion.wa_id == wa_id))
        ).scalar_one_or_none()
        if existente:
            await session.delete(existente)
            await session.commit()

        nueva = SesionConversacion(wa_id=wa_id, opt_in_dado=True)
        session.add(nueva)
        await session.commit()
        sesion_id = nueva.id

    # Sesion de BD nueva (no la misma que escribio) - confirma que
    # realmente persistio en Postgres, no que solo vive en cache local.
    async with AsyncSessionLocal() as session:
        leida = (
            await session.execute(select(SesionConversacion).where(SesionConversacion.id == sesion_id))
        ).scalar_one()

        assert leida.wa_id == wa_id
        assert leida.estado == EstadoConversacion.INICIO
        assert leida.opt_in_dado is True

        await session.delete(leida)
        await session.commit()
