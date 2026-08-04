"""
Configuración de la base de datos async (SQLAlchemy 2.0 + asyncpg).
Base de datos dedicada para el bot: cfdi_bot (no comparte con otros microservicios).
"""
import asyncio
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

db_kwargs: dict[str, Any] = {
    "echo": settings.environment == "development",
}

if not settings.database_url.startswith("sqlite"):
    db_kwargs.update({"pool_size": 10, "max_overflow": 20})

engine = create_async_engine(settings.database_url, **db_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """Dependencia FastAPI para inyectar sesión de base de datos."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """Crea tablas que no existan todavia (bootstrap de un ambiente nuevo).
    No reemplaza a Alembic: create_all nunca modifica una tabla ya
    existente - cualquier cambio a una tabla que ya existe debe ir por
    una migracion de Alembic, no aqui."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _stamp_head_sync() -> None:
    # alembic.ini vive en /app, un nivel arriba de models/ (donde esta
    # este archivo) - a diferencia de facturacion/administracion/auth_usuarios,
    # donde database.py y alembic.ini estan en el mismo directorio.
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    command.stamp(Config(str(alembic_ini)), "head")


async def stamp_head_si_es_ambiente_nuevo() -> None:
    """
    Bootstrap automatico de Alembic para un ambiente nuevo (#38).

    Si alembic_version no existe todavia, esta BD nunca ha sido tocada por
    Alembic - create_tables() ya construyo el esquema completo con el
    modelo actual, asi que aqui solo se marca como sincronizada con head,
    sin ejecutar ninguna migracion real. Si alembic_version ya existe
    (ambiente con historia), no se hace nada a proposito: cualquier
    migracion pendiente sigue requiriendo `alembic upgrade head` manual.
    """
    async with engine.connect() as conn:
        ya_tiene_historia = await conn.run_sync(lambda c: inspect(c).has_table("alembic_version"))

    if ya_tiene_historia:
        return

    await asyncio.to_thread(_stamp_head_sync)
