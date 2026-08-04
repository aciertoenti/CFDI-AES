"""
Configuración de la base de datos async (SQLAlchemy 2.0 + asyncpg).
Base de datos dedicada para el bot: cfdi_bot (no comparte con otros microservicios).
"""
from typing import Any

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
    """Crear tablas en arranque (desarrollo). En producción usar Alembic."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
