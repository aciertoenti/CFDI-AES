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
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, TypeDecorator, UniqueConstraint, func, inspect, text
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

# Cifrado de la e.firma en reposo (zg55DWY). LLAVE SEPARADA de CSD_MASTER_KEY
# a proposito: la e.firma tiene validez legal equivalente a firma autografa
# para CUALQUIER tramite ante el SAT (no solo timbrado), su blast radius es
# mayor que el del CSD - una fuga de una llave no debe exponer la otra.
# Mismo mecanismo (Fernet, 32 bytes base64 url-safe) y mismo fail-fast que
# CSD_MASTER_KEY (KeyError al importar si falta). A diferencia del CSD, NO se
# usa via TypeDecorator: las columnas de `efirmas` son Text plano y el
# cifrado/descifrado de key_base64_cifrado y password_cifrado se hace
# EXPLICITAMENTE en los endpoints con _fernet_efirma. cert_base64 es el
# certificado publico, no se cifra.
EFIRMA_MASTER_KEY = os.environ["EFIRMA_MASTER_KEY"]
_fernet_efirma = Fernet(EFIRMA_MASTER_KEY.encode())


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
    # Auditoria (no control de seguridad) - RFC personal (X-Usuario-Rfc, ver
    # api_gateway) de quien dio de alta el emisor. Nullable a proposito: dato
    # de auditoria, no se rechaza el alta si falta, y los emisores previos a
    # este cambio (ej. EKU9003173C9) no lo tienen - no se inventa retroactivamente.
    creado_por_rfc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Mismo criterio que creado_por_rfc: auditoria, no control de seguridad,
    # nullable (un emisor nunca editado no lo tiene). Se llena tanto en el
    # PATCH de campos simples como en el PUT de reemplazo de CSD.
    modificado_por_rfc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
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
    # nullable: el guardado automatico de receptores desde NuevaFactura.jsx
    # (zg5Lf6Q) no captura correo. Migracion c176eed5fc42.
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
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


class Efirma(Base):
    """
    e.firma (FIEL) de un contribuyente, custodiada para la descarga masiva
    de CFDI ante el SAT (zg55DWY). Validado con abogado (08 sep 2026):
    Responsable = el contribuyente titular (rfc_titular); Encargado =
    Acierto en TI. Distinta del CSD (tabla `emisores`): el CSD solo sella
    facturas, la e.firma autentica como el contribuyente ante todo el SAT.

    A diferencia del reemplazo de CSD (PUT /admin/emisores/{rfc}, que
    SOBRESCRIBE la fila), aqui SI se lleva historial: renovar una e.firma
    inserta una fila nueva y marca la anterior con
    reemplazada_por_id + estado (para poder auditar con que e.firma se hizo
    una descarga masiva de hace meses, y por retencion legal).

    rfc_titular es referencia suave (no FK a emisores.rfc): la e.firma
    pertenece al contribuyente aunque su RFC aun no este dado de alta como
    Emisor en la plataforma. negocio_id sigue el patron de Usuario.negocio_id
    (Integer + index, sin FK: Negocio vive en esta misma BD pero se mantiene
    el mismo estilo de referencia suave que el resto de columnas *_id
    cross-concepto del proyecto).

    consentimiento_at / consentimiento_por_rfc (Paso 3 del plan zg55DWY):
    evidencia AUDITABLE del consentimiento expreso ESPECIFICO para el
    tratamiento de este dato personal sensible, que la LFPDPPP exige recabar
    en el momento de recibir el dato. NO se confunde con el aviso general de
    la app (ModalPrivacidadPruebas en login/registro, commit d188098) - ese
    es un aviso global, no consentimiento puntual para la e.firma. El
    endpoint de subida exigira un flag explicito en el request y, al
    aceptarlo, sella aqui el timestamp y el RFC personal (X-Usuario-Rfc) de
    quien lo otorgo. Nullables porque las filas previas a esta feature (hoy
    ninguna) no lo tendrian.
    """
    __tablename__ = "efirmas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rfc_titular: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    negocio_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # cert_base64: certificado PUBLICO (.cer DER en base64), NO se cifra.
    cert_base64: Mapped[str] = mapped_column(Text, nullable=False)
    # key + password: dato sensible. Text plano en BD; el valor se guarda YA
    # cifrado con _fernet_efirma (cifrado explicito en el endpoint, ver
    # comentario de EFIRMA_MASTER_KEY arriba). El sufijo _cifrado lo hace
    # explicito para quien lee el modelo.
    key_base64_cifrado: Mapped[str] = mapped_column(Text, nullable=False)
    password_cifrado: Mapped[str] = mapped_column(Text, nullable=False)
    vigencia_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="Activo")
    # Historial de renovacion: apunta a la e.firma que reemplazo a esta.
    # Self-FK, nullable (una e.firma vigente no tiene reemplazo).
    reemplazada_por_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("efirmas.id"), nullable=True
    )
    # Marca de tiempo del borrado criptografico (procedimiento de destruccion,
    # Parte 2 del aviso de privacidad). Nullable: una e.firma viva no lo tiene.
    destruida_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Consentimiento expreso especifico para el tratamiento de la e.firma
    # (LFPDPPP, dato sensible) - ver docstring de la clase. Se sella al aceptar
    # el flag del request en el endpoint de subida.
    consentimiento_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    consentimiento_por_rfc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Auditoria (mismo criterio que creado_por_rfc en emisores): RFC personal
    # de quien la subio. Nullable, no es control de seguridad.
    creado_por_rfc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # UNICA e.firma en estado 'Activo' por rfc_titular (Paso 2 del plan
        # zg55DWY). Indice unico PARCIAL: solo aplica a las filas 'Activo',
        # asi el historial ('Reemplazada', 'Vencida', 'Destruida') puede
        # tener varias filas del mismo RFC sin chocar. El flujo de renovacion
        # debe marcar la anterior como 'Reemplazada' (y llenar
        # reemplazada_por_id) ANTES de insertar la nueva 'Activo'.
        # No confundir con ix_efirmas_rfc_titular (el index=True de la
        # columna): ese es el lookup general, no-unico; este es la garantia
        # de "una sola vigente".
        Index(
            "ix_efirmas_rfc_titular_activo_unico",
            "rfc_titular",
            unique=True,
            postgresql_where=text("estado = 'Activo'"),
        ),
    )


class SolicitudDescarga(Base):
    """
    Una solicitud de descarga masiva enviada al SAT (SolicitaDescargaEmitidos
    / Recibidos, cfdiclient). El SAT no entrega los CFDI al momento: devuelve
    un id_solicitud_sat (UUID) que hay que consultar despues con
    VerificaSolicitudDescarga hasta que estado_solicitud == 3 (Terminada) y
    entonces bajar los paquetes (tabla paquetes_descarga).

    id_solicitud_sat: nullable + unique. Se llena DESPUES de que el SAT acepta
    (cod_estatus == "5000"); mientras tanto la fila ya existe localmente con
    estado_solicitud=1. unique para no registrar dos veces la misma solicitud
    del SAT.
    """
    __tablename__ = "solicitudes_descarga"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    negocio_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    efirma_id: Mapped[int] = mapped_column(
        ForeignKey("efirmas.id"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # emitidas|recibidas|ambas
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    # UUID que devuelve el SAT (formato 8-4-4-4-12). String(40) con holgura
    # sobre los 36 chars reales. Nullable hasta que el SAT acepta la solicitud.
    id_solicitud_sat: Mapped[Optional[str]] = mapped_column(
        String(40), unique=True, index=True, nullable=True
    )
    # 1 Aceptada · 2 EnProceso · 3 Terminada · 4 Error · 5 Rechazada ·
    # 6 Vencida (0 = token invalido). Arranca en 1 al crear la fila local.
    estado_solicitud: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    cod_estatus: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    numero_cfdis: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # RFC personal de quien la disparo (auditoria, obligatorio aqui: una
    # solicitud siempre la inicia un usuario autenticado).
    solicitado_por_rfc: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PaqueteDescarga(Base):
    """
    Un paquete .zip generado por el SAT para una SolicitudDescarga terminada.
    Una solicitud puede producir varios paquetes (el SAT parte cuando el
    volumen es grande). id_paquete_sat = UUID + sufijo "_NN" (~39 chars).
    """
    __tablename__ = "paquetes_descarga"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    solicitud_id: Mapped[int] = mapped_column(
        ForeignKey("solicitudes_descarga.id"), nullable=False, index=True
    )
    id_paquete_sat: Mapped[str] = mapped_column(String(45), nullable=False)
    descargado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Donde quedo el .zip descargado (ej. clave de objeto en MinIO). Nullable
    # hasta que se descarga.
    ruta_almacenamiento: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
