"""
Base de datos async (SQLAlchemy 2.0 + asyncpg). Mismo patron que ya usan
facturacion y administracion. Base de datos dedicada para auth: cfdi_auth
(ya existia en docker-compose, DATABASE_URL nunca se habia usado hasta hoy).

Alcance de esta tarea (#10): validacion real de credenciales contra BD.
No hay modelo de roles/permisos (RBAC) todavia - Usuario.rol es un string
simple con default "admin", suficiente para el alcance actual.
"""
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import DateTime, String, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cfdi:secret_auth@postgres_auth/cfdi_auth",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # Referencia suave, mismo patron que Cliente.emisor_rfc en administracion -
    # no hay modelo de tenants todavia (#15 en Backlog).
    rfc_emisor: Mapped[Optional[str]] = mapped_column(String(13), nullable=True)
    rol: Mapped[str] = mapped_column(String(20), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """Dependencia FastAPI para inyectar sesion de base de datos."""
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
    """Crear tablas en arranque. En produccion usar Alembic (tarea aparte)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
