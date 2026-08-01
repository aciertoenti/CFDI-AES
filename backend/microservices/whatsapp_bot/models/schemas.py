"""
Modelos SQLAlchemy ORM y Pydantic v2 para el microservicio WhatsApp Bot.
Tablas: sesiones_conversacion, clientes_fiscal, tickets_factura, log_whatsapp.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class EstadoConversacion(str, enum.Enum):
    """Máquina de estados de la conversación WhatsApp."""
    INICIO = "INICIO"
    ESPERANDO_OPTIN = "ESPERANDO_OPTIN"
    CAPTURA_RFC = "CAPTURA_RFC"
    CAPTURA_RAZON_SOCIAL = "CAPTURA_RAZON_SOCIAL"
    CAPTURA_CP = "CAPTURA_CP"
    CAPTURA_REGIMEN = "CAPTURA_REGIMEN"
    CAPTURA_USO_CFDI = "CAPTURA_USO_CFDI"
    CAPTURA_EMAIL = "CAPTURA_EMAIL"
    CAPTURA_TICKET = "CAPTURA_TICKET"
    ESPERANDO_CSF = "ESPERANDO_CSF"
    CONFIRMACION = "CONFIRMACION"
    TIMBRADO = "TIMBRADO"
    ENTREGA = "ENTREGA"
    CANCELACION_SOLICITADA = "CANCELACION_SOLICITADA"
    CERRADA = "CERRADA"
    ERROR = "ERROR"


class EstadoTicket(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    TIMBRADO = "TIMBRADO"
    CANCELADO = "CANCELADO"
    ERROR = "ERROR"


# ─── ORM Models ───────────────────────────────────────────────────────────────

class SesionConversacion(Base):
    """Estado de la conversación por número de WhatsApp."""
    __tablename__ = "sesiones_conversacion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    estado: Mapped[str] = mapped_column(
        Enum(EstadoConversacion), default=EstadoConversacion.INICIO, nullable=False
    )
    datos_capturados: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    opt_in_dado: Mapped[bool] = mapped_column(Boolean, default=False)
    intentos_rfc: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    tickets: Mapped[list[TicketFactura]] = relationship(
        "TicketFactura", back_populates="sesion"
    )


class ClienteFiscal(Base):
    """Datos fiscales validados de un cliente (cache para reuso futuro)."""
    __tablename__ = "clientes_fiscal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rfc: Mapped[str] = mapped_column(String(13), nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(300), nullable=False)
    codigo_postal: Mapped[str] = mapped_column(String(5), nullable=False)
    regimen_fiscal: Mapped[str] = mapped_column(String(10), nullable=False)
    uso_cfdi: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    csf_procesada: Mapped[bool] = mapped_column(Boolean, default=False)
    csf_storage_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TicketFactura(Base):
    """Registro de cada solicitud de timbrado (idempotencia + auditoría)."""
    __tablename__ = "tickets_factura"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    sesion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sesiones_conversacion.id"), nullable=False
    )
    ticket_id_cliente: Mapped[str] = mapped_column(String(100), nullable=False)
    rfc_receptor: Mapped[str] = mapped_column(String(13), nullable=False)
    payload_request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    estado: Mapped[str] = mapped_column(
        Enum(EstadoTicket), default=EstadoTicket.PENDIENTE, nullable=False
    )
    uuid_cfdi: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    xml_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_detalle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    sesion: Mapped[SesionConversacion] = relationship(
        "SesionConversacion", back_populates="tickets"
    )


class LogWhatsapp(Base):
    """Bitácora de todos los mensajes enviados/recibidos (auditoría LFPDPPP)."""
    __tablename__ = "log_whatsapp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direccion: Mapped[str] = mapped_column(String(10), nullable=False)  # "INBOUND"|"OUTBOUND"
    tipo_mensaje: Mapped[str] = mapped_column(String(50), nullable=False)
    # Nota: no guardamos el contenido completo del mensaje por LFPDPPP
    resumen: Mapped[str] = mapped_column(String(500), nullable=True)
    wa_message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── Pydantic Schemas (request/response de la API interna) ───────────────────

class SolicitudFacturaBot(BaseModel):
    """
    Schema de entrada del endpoint interno POST /bot/factura.
    Recibe todos los datos ya capturados y validados por la conversación.
    """
    rfc: str = Field(examples=["XAXX010101000"])
    razon_social: str = Field(min_length=1, max_length=300)
    codigo_postal: str = Field(pattern=r"^\d{5}$")
    regimen_fiscal: str = Field(examples=["601"])
    uso_cfdi: str = Field(examples=["G03"])
    email: EmailStr
    ticket_id: str = Field(description="ID del ticket/folio del negocio")
    concepto: str = Field(default="Producto/Servicio", max_length=1000)
    subtotal: float = Field(gt=0)
    iva_tasa: float = Field(default=0.16, ge=0, le=1)
    emisor_rfc: Optional[str] = None  # Si no se pasa, usa el default del settings


class RespuestaFacturaBot(BaseModel):
    """Respuesta del endpoint interno POST /bot/factura."""
    uuid_cfdi: str
    folio: str
    xml_url: str
    pdf_url: str
    total: float
    fecha_timbrado: datetime
    idempotency_key: str


class WebhookEntry(BaseModel):
    """Payload simplificado del webhook de WhatsApp Cloud API."""
    object: str
    entry: list[dict]
