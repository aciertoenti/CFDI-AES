"""
Envio de correo transaccional via SendGrid (API REST v3, llamada directa con
httpx - NO el paquete `sendgrid`). Modulo compartido: httpx ya es dependencia
de los 5 microservicios, mismo criterio que shared/fiscal_validator.py.

Lo consumen:
  - auth_usuarios (correo de recuperacion de contrasena, via el wrapper
    delgado auth_usuarios/email_sender.py:enviar_correo_reset)
  - facturacion (envio del CFDI timbrado -XML + PDF adjuntos- al receptor,
    zg3DyDM)

Historial: hasta el 08 sep 2026 esto vivia como enviar_correo_reset() en
backend/microservices/auth_usuarios/email_sender.py. Generalizado y movido
aqui (zg3DyDM): misma mecanica de envio y el mismo manejo de errores ya
probado (nunca lanza, timeout 10s, maneja httpx.RequestError, log de error
sin filtrar secretos), ahora con un primitivo enviar_correo() y soporte de
adjuntos.
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL")

_TIMEOUT_S = 10.0


async def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo_html: str,
    cuerpo_texto: str,
    adjuntos: Optional[list] = None,
) -> bool:
    """
    Envia un correo via SendGrid. True si SendGrid acepto el envio (202),
    False ante CUALQUIER falla - NUNCA lanza. Los callers lo usan
    best-effort: auth_usuarios ya le respondio al usuario (BackgroundTasks,
    mitigacion de timing attack), facturacion ya timbro en Finkok
    (irreversible) - una excepcion aqui no tiene a quien devolverle un
    error, solo se loggea.

    adjuntos: lista opcional de dicts, cada uno:
        {"filename": str, "content_base64": str, "content_type": str}
      content_base64 = el archivo YA codificado en base64 (sin prefijo
      data:), tal como lo pide el campo "content" de SendGrid v3.

    NUNCA loggear el valor de SENDGRID_API_KEY ni el contenido de los
    adjuntos - los logs referencian solo destinatario/asunto/status (dato
    ya conocido por quien tiene acceso a los logs internos, util para
    auditoria).
    """
    if not SENDGRID_API_KEY or not SENDGRID_FROM_EMAIL:
        logger.error("correo.no_configurado destinatario=%s asunto=%s", destinatario, asunto)
        return False

    payload = {
        "personalizations": [{"to": [{"email": destinatario}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": "CFDI-AES"},
        "subject": asunto,
        # SendGrid v3 exige las partes de "content" en orden de preferencia
        # ascendente: primero text/plain, luego text/html.
        "content": [
            {"type": "text/plain", "value": cuerpo_texto},
            {"type": "text/html", "value": cuerpo_html},
        ],
    }
    if adjuntos:
        payload["attachments"] = [
            {
                "content": a["content_base64"],
                "filename": a["filename"],
                "type": a.get("content_type", "application/octet-stream"),
                "disposition": "attachment",
            }
            for a in adjuntos
        ]

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(SENDGRID_API_URL, json=payload, headers=headers)
        if resp.status_code == 202:
            logger.info("correo.enviado destinatario=%s asunto=%s", destinatario, asunto)
            return True
        # El cuerpo de error de SendGrid SI se loggea (ayuda a diagnosticar
        # remitente no verificado, etc.) - no contiene la API key, solo la
        # respuesta de SendGrid sobre el envio.
        logger.error(
            "correo.fallo destinatario=%s asunto=%s status=%s body=%s",
            destinatario, asunto, resp.status_code, resp.text[:500],
        )
        return False
    except httpx.RequestError as e:
        logger.error(
            "correo.error_red destinatario=%s asunto=%s error=%s",
            destinatario, asunto, str(e),
        )
        return False
