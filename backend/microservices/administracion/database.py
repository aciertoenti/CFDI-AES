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
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, TypeDecorator, UniqueConstraint, func, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cfdi:secret_admin@postgres_admin/cfdi_admin",
)

# Cifrado del CSD en reposo (#34) - ver docs/cifrado-csd.md.
CSD_MASTER_KEY = os.environ["CSD_MASTER_KEY"]
_fernet = Fernet(CSD_MASTER_KEY.encode())


class CifradoFernet(TypeDecorator):
    """Cifra/descifra de forma transparente al escribir/leer de Postgres.
    El resto del codigo (main.py) sigue tratando estas columnas como
    strings normales en texto plano - nunca ve el valor cifrado."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _fernet.decrypt(value.encode()).decode()

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Negocio(Base):
    """
    El cliente de pago (#15) - un Negocio puede administrar varios
    RFCs/emisores (caso principal: contadores/despachos con varios
    negocios). Vive en administracion porque este servicio ya es el dueno
    de los datos maestros de negocio (Emisor, Cliente, Series).

    Usuario (en auth_usuarios, base de datos separada: cfdi_auth) referencia
    este mismo negocio_id como referencia suave - mismo patron ya usado en
    todo el proyecto para relaciones entre servicios (ej. Cliente.emisor_rfc
    aqui mismo, Factura.emisor_rfc en facturacion) - no puede ser un FK real
    de Postgres porque son bases de datos fisicamente distintas.
    """
    __tablename__ = "negocios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    plan: Mapped[str] = mapped_column(String(30), nullable=False, default="basico")
    fecha_alta: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="Activo")


class Emisor(Base):
    __tablename__ = "emisores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # FK real - Negocio vive en esta misma base de datos (cfdi_admin).
    # Backfill de datos existentes ya aplicado (scripts/backfill_negocio.py,
    # #15) - ahora endurecido a NOT NULL.
    negocio_id: Mapped[int] = mapped_column(ForeignKey("negocios.id"), nullable=False, index=True)
    rfc: Mapped[str] = mapped_column(String(13), unique=True, nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(300), nullable=False)
    regimen_fiscal: Mapped[str] = mapped_column(String(10), nullable=False)
    codigo_postal: Mapped[str] = mapped_column(String(5), nullable=False)
    # Cifrados en reposo con Fernet desde #34 - ver docs/cifrado-csd.md.
    # CifradoFernet cifra/descifra de forma transparente: este codigo (y el
    # resto del servicio) sigue leyendo/escribiendo texto plano.
    csd_cert_base64: Mapped[str] = mapped_column(CifradoFernet, nullable=False)
    csd_key_base64: Mapped[str] = mapped_column(CifradoFernet, nullable=False)
    # Text (no String(255)): el texto cifrado con Fernet es mas largo que la
    # contrasena original.
    csd_password: Mapped[str] = mapped_column(CifradoFernet, nullable=False)
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
    """Crea tablas que no existan todavia (bootstrap de un ambiente nuevo).
    No reemplaza a Alembic: create_all nunca modifica una tabla ya
    existente - cualquier cambio a una tabla que ya existe debe ir por
    una migracion de Alembic, no aqui."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _stamp_head_sync() -> None:
    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
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
