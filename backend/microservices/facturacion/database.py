"""
Base de datos async (SQLAlchemy 2.0 + asyncpg). Mismo patron que ya usa
whatsapp_bot (ver backend/microservices/whatsapp_bot/models/database.py).
Base de datos dedicada para facturacion: cfdi_facturas.

Alcance de esta sesion: sin Alembic (create_all), sin folios consecutivos.
"""
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import DateTime, Numeric, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cfdi:secret_facturas@postgres_facturas/cfdi_facturas",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    folio: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha_timbrado: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    emisor_rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    receptor_rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_iva: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="Vigente")
    no_certificado_sat: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    xml: Mapped[str] = mapped_column(Text, nullable=False)
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
