"""
Endpoints del webhook de WhatsApp Business Cloud API.

GET  /webhook  → verificación de webhook (challenge de Meta)
POST /webhook  → recepción de mensajes entrantes

Diseño para cumplir <3s de respuesta:
  El webhook responde HTTP 200 inmediatamente y encola el procesamiento
  pesado en Redis (o lo procesa en background task).
  Meta reintenta si no recibe 200 en ~20s.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from core.config import settings
from core.logging import get_logger
from models.schemas import EstadoConversacion
from services.facturacion_client import (
    DobleTimbradoError,
    FacturacionError,
    facturacion_client,
)
from services.ia_client import identificar_proveedor as ia_identificar_proveedor
from services.ocr_service import procesar_csf
from services.session_store import load_session, save_session
from services.state_machine import (
    ConversationStateMachine,
    DatosCapturados,
    MSG_TIMBRADO_OK,
    MSG_ERROR_PAC,
    SessionContext,
)
from services.whatsapp_client import whatsapp_client

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])
_state_machine = ConversationStateMachine()


# ─── Verificación de webhook (handshake inicial de Meta) ─────────────────────

@router.get("", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> str:
    """
    Meta llama este endpoint al registrar el webhook.
    Verifica el token y retorna el challenge para confirmar la suscripción.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("webhook.verified")
        return hub_challenge
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token inválido")


# ─── Recepción de mensajes ────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Punto de entrada de todos los eventos de WhatsApp.
    Responde 200 inmediatamente y procesa en background para cumplir <3s.
    """
    try:
        body = await request.json()
    except Exception:
        # Meta puede enviar requests vacíos en pruebas — siempre retornar 200
        return {"status": "ok"}

    background_tasks.add_task(_process_webhook_body, body)
    return {"status": "ok"}


# ─── Procesamiento en background ─────────────────────────────────────────────

async def _process_webhook_body(body: dict) -> None:
    """Procesa el cuerpo del webhook. No puede lanzar excepciones (background)."""
    try:
        if body.get("object") != "whatsapp_business_account":
            return

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                await _process_change(value)
    except Exception as exc:
        logger.error("webhook.process_error", error=str(exc))


async def _process_change(value: dict) -> None:
    """Procesa un evento individual del webhook."""
    messages = value.get("messages", [])
    for msg in messages:
        wa_id: str = msg.get("from", "")
        message_id: str = msg.get("id", "")
        msg_type: str = msg.get("type", "")

        if not wa_id:
            continue

        # Marcar como leído (no crítico)
        asyncio.create_task(whatsapp_client.mark_as_read(message_id))

        ctx = await load_session(wa_id)

        if msg_type == "text":
            texto = msg.get("text", {}).get("body", "").strip()
            await _handle_text_message(ctx, texto, wa_id)

        elif msg_type in ("image", "document"):
            media_id = msg.get(msg_type, {}).get("id", "")
            await _handle_media_message(ctx, media_id, wa_id)

        else:
            await whatsapp_client.send_text(
                wa_id,
                "Solo puedo procesar mensajes de texto, imágenes o PDF. "
                "Escribe *FACTURAR* para comenzar.",
            )


async def _handle_text_message(ctx: SessionContext, texto: str, wa_id: str) -> None:
    """Procesa un mensaje de texto y avanza la máquina de estados."""
    transition = _state_machine.process(
        ctx=ctx,
        mensaje=texto,
        nombre_empresa=settings.service_name,
        privacy_url=settings.privacy_notice_url,
    )

    ctx.estado = transition.nuevo_estado
    ctx.datos = transition.datos_actualizados

    await whatsapp_client.send_text(wa_id, transition.respuesta)
    await save_session(ctx)

    if transition.listo_para_timbrar:
        await _ejecutar_timbrado(ctx, wa_id)


async def _handle_media_message(
    ctx: SessionContext, media_id: str, wa_id: str
) -> None:
    """Procesa imagen/PDF: identificacion de proveedor (modo IDENTIFICAR) o
    Constancia de Situacion Fiscal (OCR, flujo normal de facturacion)."""
    if ctx.estado == EstadoConversacion.IDENTIFICANDO_TICKETS:
        await _handle_media_identificar(ctx, media_id, wa_id)
        return

    await whatsapp_client.send_text(
        wa_id, "📎 Procesando tu documento... Un momento."
    )

    try:
        contenido, mime_type = await whatsapp_client.download_media(media_id)
    except Exception as exc:
        logger.error("webhook.media_download_error", error=str(exc))
        await whatsapp_client.send_text(
            wa_id, "⚠️ No pude descargar el documento. Intenta de nuevo."
        )
        return

    rfc_actual = ctx.datos.rfc if ctx.datos else None
    csf_result = await procesar_csf(contenido, mime_type, rfc_actual)

    if csf_result.error:
        await whatsapp_client.send_text(wa_id, f"⚠️ {csf_result.error}")
        return

    if csf_result.confianza < 0.5:
        await whatsapp_client.send_text(
            wa_id,
            "⚠️ No pude leer el documento con suficiente claridad. "
            "Por favor envía una imagen más nítida o ingresa los datos manualmente.",
        )
        return

    # Rellenar los datos capturados con los del OCR
    datos = ctx.datos
    if csf_result.rfc and not datos.rfc:
        datos.rfc = csf_result.rfc
    if csf_result.razon_social and not datos.razon_social:
        datos.razon_social = csf_result.razon_social
    if csf_result.codigo_postal and not datos.codigo_postal:
        datos.codigo_postal = csf_result.codigo_postal
    if csf_result.regimen_fiscal and not datos.regimen_fiscal:
        datos.regimen_fiscal = csf_result.regimen_fiscal

    datos.csf_procesada = True
    ctx.datos = datos

    # Avanzar al siguiente campo que falte
    siguiente_estado = _siguiente_estado_post_csf(ctx)
    ctx.estado = siguiente_estado

    resumen = (
        f"✅ *Datos extraídos de tu constancia:*\n\n"
        f"• RFC: `{csf_result.rfc or 'No detectado'}`\n"
        f"• Razón Social: {csf_result.razon_social or 'No detectado'}\n"
        f"• CP: {csf_result.codigo_postal or 'No detectado'}\n"
        f"• Régimen: {csf_result.regimen_fiscal or 'No detectado'}\n"
        f"• Confianza: {int(csf_result.confianza * 100)}%\n\n"
    )

    from services.state_machine import MENSAJES
    if siguiente_estado in MENSAJES:
        resumen += MENSAJES[siguiente_estado]
    else:
        resumen += "Continuemos. ¿Cuál es tu correo electrónico?"

    await whatsapp_client.send_text(wa_id, resumen)
    await save_session(ctx)


async def _handle_media_identificar(
    ctx: SessionContext, media_id: str, wa_id: str
) -> None:
    """Procesa una foto de ticket en modo IDENTIFICAR: identifica al
    proveedor via ia_client, sin tocar el flujo normal de captura fiscal."""
    await whatsapp_client.send_text(
        wa_id, "📎 Identificando ticket... Un momento."
    )

    try:
        contenido, mime_type = await whatsapp_client.download_media(media_id)
    except Exception as exc:
        logger.error("webhook.media_download_error", error=str(exc))
        await whatsapp_client.send_text(
            wa_id, "⚠️ No pude descargar la foto. Intenta de nuevo."
        )
        return

    try:
        resultado = await ia_identificar_proveedor(contenido, mime_type)
    except Exception as exc:
        logger.error("webhook.identificar_proveedor_error", error=str(exc))
        await whatsapp_client.send_text(
            wa_id, "⚠️ No pude identificar el ticket. Intenta con otra foto."
        )
        return

    ctx.datos.tickets_identificados += 1
    n = ctx.datos.tickets_identificados

    lineas = [f"✅ Ticket {n}/10 identificado:"]
    if resultado.get("proveedor_nombre"):
        lineas.append(f"🏪 {resultado['proveedor_nombre']}")
    if resultado.get("proveedor_rfc"):
        lineas.append(f"📄 RFC: {resultado['proveedor_rfc']}")
    if resultado.get("proveedor_sitio_web"):
        lineas.append(f"🌐 Factura en: {resultado['proveedor_sitio_web']}")

    detalle = []
    if resultado.get("ticket_folio"):
        detalle.append(f"🧾 Folio: {resultado['ticket_folio']}")
    if resultado.get("ticket_monto") is not None:
        detalle.append(f"💰 ${resultado['ticket_monto']}")
    if resultado.get("ticket_fecha"):
        detalle.append(f"📅 {resultado['ticket_fecha']}")
    if detalle:
        lineas.append(" | ".join(detalle))

    await whatsapp_client.send_text(wa_id, "\n".join(lineas))
    await save_session(ctx)

    if n >= 10:
        ctx.estado = EstadoConversacion.INICIO
        ctx.datos = DatosCapturados()
        await whatsapp_client.send_text(
            wa_id,
            "🔟 Llegaste al límite de 10 tickets por sesión. "
            "Escribe *FACTURAR* o *IDENTIFICAR* de nuevo cuando quieras.",
        )
        await save_session(ctx)


def _siguiente_estado_post_csf(ctx: SessionContext) -> EstadoConversacion:
    """Determina el siguiente campo a capturar tras procesar la CSF."""
    d = ctx.datos
    if not d.rfc:
        return EstadoConversacion.CAPTURA_RFC
    if not d.razon_social:
        return EstadoConversacion.CAPTURA_RAZON_SOCIAL
    if not d.codigo_postal:
        return EstadoConversacion.CAPTURA_CP
    if not d.regimen_fiscal:
        return EstadoConversacion.CAPTURA_REGIMEN
    if not d.uso_cfdi:
        return EstadoConversacion.CAPTURA_USO_CFDI
    if not d.email:
        return EstadoConversacion.CAPTURA_EMAIL
    return EstadoConversacion.CAPTURA_TICKET


# ─── Timbrado ────────────────────────────────────────────────────────────────

async def _ejecutar_timbrado(ctx: SessionContext, wa_id: str) -> None:
    """Llama al microservicio de Facturación y entrega el resultado."""
    from models.schemas import SolicitudFacturaBot

    datos = ctx.datos
    solicitud = SolicitudFacturaBot(
        rfc=datos.rfc or "",
        razon_social=datos.razon_social or "",
        codigo_postal=datos.codigo_postal or "",
        regimen_fiscal=datos.regimen_fiscal or "",
        uso_cfdi=datos.uso_cfdi or "",
        email=datos.email or "",
        ticket_id=datos.ticket_id or "",
        concepto="Producto/Servicio",
        # subtotal derivado en el estado CAPTURA_MONTO (monto con IVA / 1.16),
        # guardado como str en DatosCapturados. Pydantic (SolicitudFacturaBot)
        # lo valida con gt=0.
        subtotal=float(datos.subtotal or 0),
    )

    try:
        resultado = await facturacion_client.timbrar(solicitud)
        ctx.estado = EstadoConversacion.ENTREGA
        await save_session(ctx)

        # Enviar confirmación textual
        msg_ok = MSG_TIMBRADO_OK.format(
            uuid=resultado.uuid_cfdi,
            folio=resultado.folio,
            total=resultado.total,
            email=datos.email,
        )
        await whatsapp_client.send_text(wa_id, msg_ok)

        # Enviar PDF si la URL está disponible
        if resultado.pdf_url:
            await whatsapp_client.send_document(
                wa_id=wa_id,
                url=resultado.pdf_url,
                filename=f"factura_{resultado.folio}.pdf",
                caption="📄 Tu factura en PDF",
            )

        # Enviar XML si la URL está disponible
        if resultado.xml_url:
            await whatsapp_client.send_document(
                wa_id=wa_id,
                url=resultado.xml_url,
                filename=f"factura_{resultado.uuid_cfdi}.xml",
                caption="📎 XML CFDI 4.0",
            )

    except DobleTimbradoError as exc:
        logger.warning("timbrado.doble_intento", error=str(exc))
        await whatsapp_client.send_text(
            wa_id,
            f"ℹ️ Este ticket ya fue facturado previamente. {exc}",
        )

    except FacturacionError as exc:
        ctx.estado = EstadoConversacion.ERROR
        await save_session(ctx)
        msg_error = MSG_ERROR_PAC.format(
            codigo=exc.code or "N/A",
            detalle=str(exc),
        )
        await whatsapp_client.send_text(wa_id, msg_error)
        logger.error("timbrado.error", error=str(exc), code=exc.code, wa_id=wa_id)

    except Exception as exc:
        ctx.estado = EstadoConversacion.ERROR
        await save_session(ctx)
        await whatsapp_client.send_text(
            wa_id,
            "⚠️ Error inesperado al generar tu factura. Contacta a soporte.",
        )
        logger.error("timbrado.error_inesperado", error=str(exc), wa_id=wa_id)
