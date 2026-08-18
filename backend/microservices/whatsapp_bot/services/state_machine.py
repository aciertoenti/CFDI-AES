"""
Máquina de estados de la conversación WhatsApp.

Estados:
  INICIO → ESPERANDO_OPTIN → CAPTURA_RFC → CAPTURA_RAZON_SOCIAL
        → CAPTURA_CP → CAPTURA_REGIMEN → CAPTURA_USO_CFDI
        → CAPTURA_EMAIL → CAPTURA_TICKET → CONFIRMACION
        → TIMBRADO → ENTREGA → CERRADA

Flujo de cancelación:
  CERRADA/ENTREGA → CANCELACION_SOLICITADA → CERRADA (si aplica)

Timeouts: sesión expira a los 30 min sin actividad (manejado en Redis TTL).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.logging import get_logger
from models.schemas import EstadoConversacion
from services.fiscal_validator import (
    CATALOGO_REGIMEN_FISCAL,
    CATALOGO_USO_CFDI,
    validate_codigo_postal,
    validate_rfc,
    validate_regimen_fiscal,
    validate_uso_cfdi,
)

logger = get_logger(__name__)


# ─── Mensajes de la conversación ─────────────────────────────────────────────
# Separados del código de lógica para facilitar i18n y edición sin tocar lógica.

AVISO_PRIVACIDAD = (
    "👋 Hola, soy el asistente de facturación de *{nombre_empresa}*.\n\n"
    "Antes de continuar, te pido tu consentimiento para procesar tus datos fiscales "
    "conforme a nuestra Política de Privacidad: {url}\n\n"
    "Tus datos se usarán *únicamente* para generar tu factura CFDI 4.0 y se conservarán "
    "5 años conforme a obligaciones del SAT.\n\n"
    "¿Aceptas? Responde *SÍ* para continuar."
)

MENSAJES: dict[EstadoConversacion, str] = {
    EstadoConversacion.CAPTURA_RFC: (
        "✅ ¡Gracias por aceptar! Empecemos con tu factura.\n\n"
        "¿Cuál es tu *RFC*?\n_(Ej: XAXX010101000 para público en general)_"
    ),
    EstadoConversacion.CAPTURA_RAZON_SOCIAL: (
        "¿Cuál es tu *Razón Social o Nombre* tal como aparece en tu constancia fiscal?\n"
        "_(Sin S.A., S. de R.L., etc. — escríbelo exactamente como en el SAT)_"
    ),
    EstadoConversacion.CAPTURA_CP: (
        "¿Cuál es tu *Código Postal* del domicilio fiscal?\n_(5 dígitos, ej: 06600)_"
    ),
    EstadoConversacion.CAPTURA_REGIMEN: (
        "¿Cuál es tu *Régimen Fiscal*?\n\n"
        "Los más comunes:\n"
        "• *601* – General de Ley Personas Morales\n"
        "• *612* – Personas Físicas con Actividad Empresarial\n"
        "• *626* – Régimen Simplificado de Confianza\n"
        "• *616* – Sin Obligaciones Fiscales\n\n"
        "Escribe el *número* de tu régimen o envía tu *Constancia de Situación Fiscal* "
        "como imagen/PDF para que lo detecte automáticamente. 📄"
    ),
    EstadoConversacion.CAPTURA_USO_CFDI: (
        "¿Cuál es el *Uso CFDI*?\n\n"
        "Los más comunes:\n"
        "• *G03* – Gastos en general\n"
        "• *G01* – Adquisición de mercancías\n"
        "• *P01* – Por definir\n\n"
        "Escribe el código (ej: *G03*)."
    ),
    EstadoConversacion.CAPTURA_EMAIL: (
        "¿A qué *correo electrónico* te enviamos la factura?"
    ),
    EstadoConversacion.CAPTURA_TICKET: (
        "¿Cuál es el *número de ticket o folio* de tu compra?\n"
        "_(Lo encontrarás en tu comprobante de venta)_"
    ),
    EstadoConversacion.ESPERANDO_CSF: (
        "📎 Puedes enviarme tu *Constancia de Situación Fiscal* como imagen (JPG/PNG) o PDF "
        "para llenar los datos automáticamente, o escribe el régimen manualmente."
    ),
}

MSG_CONFIRMACION = (
    "✅ *Resumen de tu factura:*\n\n"
    "• RFC: `{rfc}`\n"
    "• Razón Social: {razon_social}\n"
    "• CP: {codigo_postal}\n"
    "• Régimen: {regimen_fiscal} – {desc_regimen}\n"
    "• Uso CFDI: {uso_cfdi} – {desc_uso}\n"
    "• Email: {email}\n"
    "• Ticket: {ticket_id}\n\n"
    "⚠️ _Este es un ambiente de PRUEBA. Esta factura no tiene validez fiscal "
    "ante el SAT._\n\n"
    "¿Los datos son correctos?\n"
    "Responde *SÍ* para timbrar o *NO* para corregir."
)

MSG_TIMBRADO_OK = (
    "🎉 *¡Tu factura fue timbrada exitosamente!*\n\n"
    "• UUID: `{uuid}`\n"
    "• Folio: {folio}\n"
    "• Total: ${total:.2f} MXN\n\n"
    "📎 Recibirás XML y PDF en tu correo *{email}* en unos minutos.\n\n"
    "¿Necesitas algo más?"
)

MSG_ERROR_PAC = (
    "⚠️ Ocurrió un error al timbrar tu factura.\n"
    "Código: {codigo}\n"
    "Detalle: {detalle}\n\n"
    "Por favor contacta a soporte o intenta de nuevo en unos minutos."
)

MSG_TIMEOUT = (
    "⏰ Tu sesión expiró por inactividad. "
    "Escribe *FACTURAR* cuando quieras retomar."
)

MSG_OPTIN_RECHAZADO = (
    "Entendido. Sin tu consentimiento no podemos procesar la factura. "
    "Si cambias de opinión escribe *FACTURAR*."
)

MSG_IDENTIFICAR_INICIO = (
    "📋 Modo identificación de tickets. Mándame hasta 10 fotos de tickets "
    "(uno por uno) y te digo quién los emitió y cómo facturarlos.\n"
    "Escribe *LISTO* cuando termines."
)


# ─── Datos de sesión en memoria (Redis los persiste) ─────────────────────────

@dataclass
class DatosCapturados:
    rfc: Optional[str] = None
    razon_social: Optional[str] = None
    codigo_postal: Optional[str] = None
    regimen_fiscal: Optional[str] = None
    uso_cfdi: Optional[str] = None
    email: Optional[str] = None
    ticket_id: Optional[str] = None
    csf_procesada: bool = False
    tickets_identificados: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "DatosCapturados":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionContext:
    wa_id: str
    estado: EstadoConversacion = EstadoConversacion.INICIO
    datos: DatosCapturados = field(default_factory=DatosCapturados)
    opt_in: bool = False
    intentos_rfc: int = 0
    campo_a_corregir: Optional[str] = None


# ─── Transición ──────────────────────────────────────────────────────────────

@dataclass
class TransitionResult:
    nuevo_estado: EstadoConversacion
    respuesta: str
    datos_actualizados: DatosCapturados
    listo_para_timbrar: bool = False


MAX_INTENTOS_RFC = 3


class ConversationStateMachine:
    """
    Procesa un mensaje de texto y retorna la transición de estado y la respuesta.
    No tiene estado propio — recibe y retorna contexto inmutable (SessionContext).
    """

    def process(
        self,
        ctx: SessionContext,
        mensaje: str,
        nombre_empresa: str = "CFDI-AES",
        privacy_url: str = "https://tudominio.mx/aviso-privacidad",
    ) -> TransitionResult:
        """
        Procesa el mensaje según el estado actual y retorna la transición.
        """
        texto = mensaje.strip()
        estado = ctx.estado
        datos = ctx.datos

        logger.info(
            "state_machine.process",
            wa_id=ctx.wa_id,
            estado=estado,
            mensaje_len=len(texto),
        )

        # ── INICIO ────────────────────────────────────────────────────────────
        if estado == EstadoConversacion.INICIO:
            if "IDENTIFICAR" in texto.upper():
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.IDENTIFICANDO_TICKETS,
                    respuesta=MSG_IDENTIFICAR_INICIO,
                    datos_actualizados=datos,
                )
            if any(kw in texto.upper() for kw in ("FACTURA", "HOLA", "INICIO", "START")):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.ESPERANDO_OPTIN,
                    respuesta=AVISO_PRIVACIDAD.format(
                        nombre_empresa=nombre_empresa, url=privacy_url
                    ),
                    datos_actualizados=datos,
                )
            return TransitionResult(
                nuevo_estado=EstadoConversacion.INICIO,
                respuesta=(
                    "👋 Escribe *FACTURAR* para solicitar tu factura electrónica CFDI 4.0."
                ),
                datos_actualizados=datos,
            )

        # ── IDENTIFICANDO_TICKETS ────────────────────────────────────────────
        # Las fotos de ticket se procesan en webhook.py (fuera de esta maquina
        # de texto) - aqui solo se maneja la palabra clave LISTO para salir,
        # y cualquier otro texto mientras el usuario sigue en este modo.
        if estado == EstadoConversacion.IDENTIFICANDO_TICKETS:
            if texto.upper() == "LISTO":
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.INICIO,
                    respuesta="Listo. Escribe *FACTURAR* o *IDENTIFICAR* de nuevo cuando quieras.",
                    datos_actualizados=DatosCapturados(),
                )
            return TransitionResult(
                nuevo_estado=EstadoConversacion.IDENTIFICANDO_TICKETS,
                respuesta="📎 Mándame la foto del ticket, o escribe *LISTO* cuando termines.",
                datos_actualizados=datos,
            )

        # ── OPTIN ─────────────────────────────────────────────────────────────
        if estado == EstadoConversacion.ESPERANDO_OPTIN:
            if texto.upper() in ("SI", "SÍ", "YES", "ACEPTO", "OK", "1"):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_RFC,
                    respuesta=MENSAJES[EstadoConversacion.CAPTURA_RFC],
                    datos_actualizados=datos,
                )
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CERRADA,
                respuesta=MSG_OPTIN_RECHAZADO,
                datos_actualizados=datos,
            )

        # ── RFC ───────────────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_RFC:
            result = validate_rfc(texto)
            if not result.valid:
                ctx.intentos_rfc += 1
                if ctx.intentos_rfc >= MAX_INTENTOS_RFC:
                    return TransitionResult(
                        nuevo_estado=EstadoConversacion.ERROR,
                        respuesta=(
                            "⚠️ Demasiados intentos. Por favor contacta a soporte."
                        ),
                        datos_actualizados=datos,
                    )
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_RFC,
                    respuesta=f"❌ {result.error}\n\nIntento {ctx.intentos_rfc}/{MAX_INTENTOS_RFC}. Intenta de nuevo:",
                    datos_actualizados=datos,
                )
            datos.rfc = result.normalized
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CAPTURA_RAZON_SOCIAL,
                respuesta=MENSAJES[EstadoConversacion.CAPTURA_RAZON_SOCIAL],
                datos_actualizados=datos,
            )

        # ── RAZÓN SOCIAL ──────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_RAZON_SOCIAL:
            if len(texto) < 2:
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_RAZON_SOCIAL,
                    respuesta="❌ Por favor escribe tu razón social completa.",
                    datos_actualizados=datos,
                )
            datos.razon_social = texto[:300]
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CAPTURA_CP,
                respuesta=MENSAJES[EstadoConversacion.CAPTURA_CP],
                datos_actualizados=datos,
            )

        # ── CÓDIGO POSTAL ─────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_CP:
            result = validate_codigo_postal(texto)
            if not result.valid:
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_CP,
                    respuesta=f"❌ {result.error}",
                    datos_actualizados=datos,
                )
            datos.codigo_postal = result.normalized
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CAPTURA_REGIMEN,
                respuesta=MENSAJES[EstadoConversacion.CAPTURA_REGIMEN],
                datos_actualizados=datos,
            )

        # ── RÉGIMEN FISCAL ────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_REGIMEN:
            result = validate_regimen_fiscal(texto)
            if not result.valid:
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_REGIMEN,
                    respuesta=f"❌ {result.error}\n\nIngresa el código (ej: *601*) o envía tu Constancia como imagen.",
                    datos_actualizados=datos,
                )
            datos.regimen_fiscal = result.normalized
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CAPTURA_USO_CFDI,
                respuesta=MENSAJES[EstadoConversacion.CAPTURA_USO_CFDI],
                datos_actualizados=datos,
            )

        # ── USO CFDI ──────────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_USO_CFDI:
            result = validate_uso_cfdi(texto, datos.regimen_fiscal)
            if not result.valid:
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_USO_CFDI,
                    respuesta=f"❌ {result.error}",
                    datos_actualizados=datos,
                )
            datos.uso_cfdi = result.normalized
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CAPTURA_EMAIL,
                respuesta=MENSAJES[EstadoConversacion.CAPTURA_EMAIL],
                datos_actualizados=datos,
            )

        # ── EMAIL ─────────────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_EMAIL:
            import re
            email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
            if not email_pattern.match(texto):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_EMAIL,
                    respuesta="❌ El correo no parece válido. Ej: nombre@dominio.com",
                    datos_actualizados=datos,
                )
            datos.email = texto.lower().strip()
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CAPTURA_TICKET,
                respuesta=MENSAJES[EstadoConversacion.CAPTURA_TICKET],
                datos_actualizados=datos,
            )

        # ── TICKET ────────────────────────────────────────────────────────────
        if estado == EstadoConversacion.CAPTURA_TICKET:
            if len(texto.strip()) < 1:
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_TICKET,
                    respuesta="❌ Por favor ingresa el número de ticket.",
                    datos_actualizados=datos,
                )
            datos.ticket_id = texto.strip()[:100]
            desc_regimen = CATALOGO_REGIMEN_FISCAL.get(datos.regimen_fiscal or "", "")
            desc_uso = CATALOGO_USO_CFDI.get(datos.uso_cfdi or "", {}).get("desc", "")
            confirmacion = MSG_CONFIRMACION.format(
                rfc=datos.rfc,
                razon_social=datos.razon_social,
                codigo_postal=datos.codigo_postal,
                regimen_fiscal=datos.regimen_fiscal,
                desc_regimen=desc_regimen,
                uso_cfdi=datos.uso_cfdi,
                desc_uso=desc_uso,
                email=datos.email,
                ticket_id=datos.ticket_id,
            )
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CONFIRMACION,
                respuesta=confirmacion,
                datos_actualizados=datos,
            )

        # ── CONFIRMACIÓN ──────────────────────────────────────────────────────
        if estado == EstadoConversacion.CONFIRMACION:
            if texto.upper() in ("SI", "SÍ", "YES", "OK", "CORRECTO", "1"):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.TIMBRADO,
                    respuesta="⏳ Procesando tu factura... Un momento.",
                    datos_actualizados=datos,
                    listo_para_timbrar=True,
                )
            if texto.upper() in ("NO", "CORREGIR", "CAMBIAR", "2"):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CAPTURA_RFC,
                    respuesta=(
                        "Bien, volvemos a empezar. ¿Cuál es tu *RFC*?"
                    ),
                    datos_actualizados=datos,
                )
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CONFIRMACION,
                respuesta="Responde *SÍ* para timbrar o *NO* para corregir.",
                datos_actualizados=datos,
            )

        # ── CANCELACIÓN ───────────────────────────────────────────────────────
        if estado == EstadoConversacion.CANCELACION_SOLICITADA:
            if texto.upper() in ("SI", "SÍ", "YES", "CONFIRMAR"):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.CERRADA,
                    respuesta=(
                        "✅ Solicitud de cancelación enviada. El proceso puede tardar "
                        "hasta 72 horas hábiles conforme a los plazos del SAT."
                    ),
                    datos_actualizados=datos,
                )
            return TransitionResult(
                nuevo_estado=EstadoConversacion.CERRADA,
                respuesta="Cancelación no solicitada. ¿Necesitas algo más?",
                datos_actualizados=datos,
            )

        # ── ESTADOS TERMINALES ────────────────────────────────────────────────
        if estado in (
            EstadoConversacion.CERRADA,
            EstadoConversacion.ENTREGA,
            EstadoConversacion.ERROR,
        ):
            if any(kw in texto.upper() for kw in ("FACTURA", "CANCELAR", "NUEVA")):
                return TransitionResult(
                    nuevo_estado=EstadoConversacion.INICIO,
                    respuesta="Iniciando una nueva solicitud. Escribe *FACTURAR* para comenzar.",
                    datos_actualizados=DatosCapturados(),
                )
            return TransitionResult(
                nuevo_estado=estado,
                respuesta="Escribe *FACTURAR* para solicitar una nueva factura.",
                datos_actualizados=datos,
            )

        # ── Fallback ──────────────────────────────────────────────────────────
        logger.warning("state_machine.unhandled_state", estado=estado, wa_id=ctx.wa_id)
        return TransitionResult(
            nuevo_estado=EstadoConversacion.ERROR,
            respuesta="Estado inesperado. Escribe *FACTURAR* para reiniciar.",
            datos_actualizados=datos,
        )
