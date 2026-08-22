"""
Modelo espejo de SOLO LECTURA de Factura. Fuente de verdad real del esquema:
backend/microservices/facturacion/database.py:Factura - esta es una copia
deliberada y acotada de esa tabla, no un descuido ni una segunda fuente de
verdad. Decision tomada el 20 ago 2026 (tarjeta PVTI_lAHOBYC0Os4BfCxZzg2m00E,
mismo criterio que PVTI_lAHOBYC0Os4BfCxZzg2eMt4): reportes NO importa el
modelo completo de facturacion via shared/ - evita arrastrar Alembic/
python-dotenv a un servicio que solo necesita leer 4 columnas para un
reporte agregado.

reportes nunca crea, migra ni escribe esta tabla - la posee facturacion
(incluidas sus migraciones de Alembic). Por eso este archivo no tiene
create_tables() ni alembic/: si la tabla no existiera, el problema esta en
facturacion, no aqui.
"""
import os
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cfdi:secret_facturas@postgres_facturas/cfdi_facturas",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Factura(Base):
    """
    Espejo de SOLO LECTURA de facturacion/database.py:Factura - mismo
    __tablename__ ("facturas"), mismas 4 columnas que este servicio
    necesita para el reporte mensual (negocio_id, fecha_timbrado, total,
    estado). SQLAlchemy no exige que un modelo cubra el 100% de las
    columnas reales de una tabla - el resto (uuid, xml, csd, etc.) no se
    declara aqui a proposito, nunca se lee ni se necesita.

    NUNCA usar este modelo para escribir/actualizar - reportes no es dueno
    de esta tabla.
    """
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    negocio_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_timbrado: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(255), nullable=False)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """Dependencia FastAPI para inyectar sesion de base de datos. Solo
    lectura en la practica, pero se mantiene el mismo patron commit/
    rollback que el resto de servicios por consistencia - un SELECT no
    tiene nada que comitear, pero no hace dano."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
