"""
Base de datos async (SQLAlchemy 2.0 + asyncpg). Mismo patron que ya usa
whatsapp_bot (ver backend/microservices/whatsapp_bot/models/database.py).
Base de datos dedicada para facturacion: cfdi_facturas.

Migraciones con Alembic (#38) - ver alembic/env.py, que reutiliza Base y
DATABASE_URL de este mismo archivo. Cambios de esquema van por
`alembic revision --autogenerate` + `alembic upgrade head`, no ALTER TABLE
manual (ver README.md de este servicio).
"""
import asyncio
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import DateTime, Integer, Numeric, String, Text, func, inspect
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
    # Denormalizado a proposito (fix de fuga de datos entre negocios,
    # PASO 3): Negocio vive en administracion, otra base de datos
    # (cfdi_admin vs cfdi_facturas de este servicio), asi que no puede ser
    # un FK real de Postgres ni resolverse via join/subquery como en
    # administracion (Emisor/Cliente si comparten BD ahi). Se captura del
    # X-Negocio-Id del caller al timbrar (ya viene verificado desde el
    # gateway) y se usa para filtrar todas las lecturas/escrituras propias
    # de facturacion sin depender de una llamada cruzada a administracion.
    # Backfill de filas previas ya aplicado (las 23 filas existentes eran
    # todas de EKU9003173C9 / Negocio 1, confirmado antes de endurecer).
    negocio_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    folio: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha_timbrado: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    emisor_rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    receptor_rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_iva: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # Categorico y estable a proposito ("Vigente"/"Cancelada"/etc.) - el
    # frontend filtra con igualdad exacta contra este campo (App.jsx,
    # filtro Vigente/Vencida/Cancelada). El texto libre que reporta el PAC
    # al cancelar (que puede variar entre llamadas, ej. "Cancelado sin
    # aceptacion" vs "Peticion de cancelacion realizada exitosamente" para
    # el mismo motivo) NO se guarda aqui - va en detalle_pac (#5).
    estado: Mapped[str] = mapped_column(String(255), nullable=False, default="Vigente")
    # Texto crudo de la ultima respuesta del PAC (ej. al cancelar), para
    # auditoria/transparencia - nunca se usa para logica de negocio.
    detalle_pac: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    no_certificado_sat: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    xml: Mapped[str] = mapped_column(Text, nullable=False)
    # Costo real cobrado por Finkok por este timbre (#6) - Numeric(10,4)
    # para no perder centavos en acumulados (ej. reportes mensuales sumando
    # miles de timbres). Solo se llena en timbrados exitosos; una
    # cancelacion no genera ni quita este costo, ya se pago al timbrar.
    costo_timbre: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    # PUE (pago en una sola exhibicion) / PPD (pago en parcialidades) - #40.
    # Nullable: las facturas timbradas antes de agregar esta columna se
    # rellenan con un backfill aparte (parseando el XML ya guardado), no
    # con create_all/Alembic (eso es transformacion de datos, no de esquema).
    metodo_pago: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    # Auditoria (no control de seguridad) - RFC personal (X-Usuario-Rfc, ver
    # api_gateway) de quien timbro/cancelo. Nullable a proposito: dato de
    # auditoria, no se rechaza la operacion si falta (a diferencia de
    # X-Negocio-Id), y las facturas previas a este cambio no lo tienen -
    # no se inventa retroactivamente. Pueden ser dos personas distintas del
    # mismo negocio (o el bot, ver X-Usuario-Rfc="BOT-WHATSAPP").
    creado_por_rfc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cancelado_por_rfc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
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
    """Crea tablas que no existan todavia (bootstrap de un ambiente nuevo,
    ej. primer `docker compose up` con una BD vacia). No reemplaza a
    Alembic: create_all nunca modifica una tabla ya existente, asi que
    convive bien con migraciones - pero cualquier cambio a una tabla que
    ya existe debe ir por una migracion de Alembic, no aqui."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _stamp_head_sync() -> None:
    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
    command.stamp(Config(str(alembic_ini)), "head")


async def stamp_head_si_es_ambiente_nuevo() -> None:
    """
    Bootstrap automatico de Alembic para un ambiente nuevo (#38).

    Si la tabla alembic_version NO existe todavia, esta BD nunca ha sido
    tocada por Alembic - create_tables() de arriba ya construyo el esquema
    completo con el modelo actual, asi que aqui solo se marca como
    sincronizada con head (alembic stamp head), sin ejecutar ninguna
    migracion real. Sin esto, la primera vez que alguien corriera
    `alembic upgrade head` en un ambiente asi, Alembic intentaria aplicar
    TODAS las migraciones desde cero y tronaria en la primera que agregue
    una columna que create_tables() ya puso ahi (DuplicateColumnError -
    probado en un ambiente desechable antes de implementar esto).

    Si alembic_version YA existe (ambiente con historia real), no se hace
    nada a proposito: cualquier migracion pendiente sigue requiriendo
    `alembic upgrade head` manual y deliberado. Aplicarlas solas en cada
    arranque silenciaria migraciones reales sin que nadie las revise.

    command.stamp() es sincrono y su env.py (async) hace su propio
    asyncio.run() internamente - no se puede llamar directo desde el
    lifespan de FastAPI (ya hay un event loop corriendo), por eso corre en
    un thread aparte via asyncio.to_thread().
    """
    async with engine.connect() as conn:
        ya_tiene_historia = await conn.run_sync(lambda c: inspect(c).has_table("alembic_version"))

    if ya_tiene_historia:
        return

    await asyncio.to_thread(_stamp_head_sync)
