"""
Envio de correo transaccional via SendGrid. Llamada directa a su API REST v3
con httpx (ya es dependencia real de este servicio, para la llamada a
administracion en /auth/registro) en vez de agregar el paquete `sendgrid` -
mismo criterio que rfc_validation.py/csd_rfc.py: no meter una dependencia
nueva solo para una funcion chica y autocontenida.
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("auth_usuarios.email")

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


async def enviar_correo_reset(destinatario_email: str, token: str) -> bool:
    """
    True si SendGrid acepto el envio (202), False ante cualquier falla -
    nunca lanza. Deliberado: el endpoint que llama a esto ya le respondio
    al caller ANTES de invocar esta funcion (ver BackgroundTasks en
    password_reset_request, mitigacion de timing attack) - una excepcion
    aqui no tiene a quien devolverle un error, solo se loggea.

    NUNCA loggear el token ni el valor de SENDGRID_API_KEY (requisito de
    seguridad explicito) - el log de exito/fallo abajo referencia el
    destinatario (dato ya conocido por quien tiene acceso a los logs
    internos, util para auditoria) pero jamas el token ni la clave.
    """
    if not SENDGRID_API_KEY or not SENDGRID_FROM_EMAIL:
        logger.error("email_reset.no_configurado destinatario=%s", destinatario_email)
        return False

    link = f"{FRONTEND_URL}/reset-password?token={token}"
    payload = {
        "personalizations": [{"to": [{"email": destinatario_email}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": "CFDI-AES"},
        "subject": "Recuperación de contraseña — CFDI-AES",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    "Recibimos una solicitud para restablecer tu contraseña en CFDI-AES.\n\n"
                    f"Para continuar, abre este enlace (valido por 30 minutos):\n{link}\n\n"
                    "Si tu no solicitaste esto, puedes ignorar este correo - tu contraseña "
                    "actual sigue siendo valida."
                ),
            },
            {
                "type": "text/html",
                "value": (
                    "<p>Recibimos una solicitud para restablecer tu contraseña en CFDI-AES.</p>"
                    f'<p><a href="{link}">Haz clic aquí para continuar</a> (válido por 30 minutos).</p>'
                    "<p>Si tú no solicitaste esto, puedes ignorar este correo — tu contraseña "
                    "actual sigue siendo válida.</p>"
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(SENDGRID_API_URL, json=payload, headers=headers)
        if resp.status_code == 202:
            logger.info("email_reset.enviado destinatario=%s", destinatario_email)
            return True
        # Cuerpo de error de SendGrid SI se loggea (ayuda a diagnosticar
        # remitente no verificado, etc.) - no contiene el token ni la
        # API key, solo la respuesta de SendGrid sobre el envio.
        logger.error(
            "email_reset.fallo destinatario=%s status=%s body=%s",
            destinatario_email, resp.status_code, resp.text[:500],
        )
        return False
    except httpx.RequestError as e:
        logger.error("email_reset.error_red destinatario=%s error=%s", destinatario_email, str(e))
        return False
