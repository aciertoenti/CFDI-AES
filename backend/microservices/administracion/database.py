"""
Base de datos async (SQLAlchemy 2.0 + asyncpg). Mismo patron que ya usa
facturacion (ver backend/microservices/facturacion/database.py).
Base de datos dedicada para administracion: cfdi_admin.

Alcance de esta tarea (#4): persistencia real de Emisores y Clientes.
Todavia no existe modelo de tenants (#15 en Backlog) - Cliente.emisor_rfc
es una referencia suave (mismo patron que Factura.emisor_rfc en
facturacion, sin FK dura), no un tenant_id real.

SerieFolio (agregado en #12): contador real de folios consecutivos por
emisor+serie. El conteo es por combinacion (emisor_rfc, serie) y no solo
por emisor, porque el CFDI ya modela Serie/Folio como conceptos separados
(ej. serie "A" para facturas normales) y el frontend ya tiene el concepto
de "Series" en la UI (todavia mock, tarea aparte).
"""
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import DateTime, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cfdi:secret_admin@postgres_admin/cfdi_admin",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Emisor(Base):
    __tablename__ = "emisores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rfc: Mapped[str] = mapped_column(String(13), unique=True, nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(300), nullable=False)
    regimen_fiscal: Mapped[str] = mapped_column(String(10), nullable=False)
    codigo_postal: Mapped[str] = mapped_column(String(5), nullable=False)
    # Sin cifrar por ahora: cifrar con KMS es una decision de seguridad
    # aparte, fuera del alcance de "solo persistencia" de esta tarea.
    csd_cert_base64: Mapped[str] = mapped_column(Text, nullable=False)
    csd_key_base64: Mapped[str] = mapped_column(Text, nullable=False)
    csd_password: Mapped[str] = mapped_column(String(255), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="Activo")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    # Referencia suave al emisor - mismo patron que Factura.emisor_rfc en
    # facturacion (string, no FK dura), porque no existe modelo de tenants aun.
    emisor_rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    telefono: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    regimen_fiscal: Mapped[str] = mapped_column(String(10), nullable=False, default="601")
    uso_cfdi_default: Mapped[str] = mapped_column(String(10), nullable=False, default="G03")
    domicilio_fiscal: Mapped[str] = mapped_column(String(5), nullable=False)
    credito_limite: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Mismo RFC puede repetirse para distintos emisores (multi-tenant a
        # futuro), pero no dos veces para el mismo emisor.
        UniqueConstraint("rfc", "emisor_rfc", name="uq_cliente_rfc_emisor"),
    )


class SerieFolio(Base):
    __tablename__ = "series_folios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    emisor_rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    serie: Mapped[str] = mapped_column(String(10), nullable=False)
    ultimo_folio: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("emisor_rfc", "serie", name="uq_serie_folio_emisor_serie"),
    )


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
