"""
Correo de recuperacion de contrasena. La mecanica de envio (SendGrid v3 via
httpx, manejo de errores, timeout) vive en backend/shared/email_sender.py
desde el 08 sep 2026 (zg3DyDM) - aqui queda SOLO el armado del mensaje
especifico de reset: asunto, cuerpo (texto + HTML) y el link con FRONTEND_URL.

Comportamiento observable sin cambios respecto a la version previa: mismo
asunto, mismo cuerpo, mismo formato de link, devuelve bool, nunca lanza.
"""
import os

from shared.email_sender import enviar_correo

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


async def enviar_correo_reset(destinatario_email: str, token: str) -> bool:
    """
    True si SendGrid acepto el envio (202), False ante cualquier falla -
    nunca lanza. Deliberado: el endpoint que llama a esto ya le respondio
    al caller ANTES de invocar esta funcion (ver BackgroundTasks en
    password_reset_request, mitigacion de timing attack) - una excepcion
    aqui no tiene a quien devolverle un error.

    NUNCA se loggea el token ni la API key - shared.email_sender ya cumple
    ese requisito de seguridad; aqui solo se arma el texto del mensaje.
    """
    link = f"{FRONTEND_URL}/reset-password?token={token}"
    cuerpo_texto = (
        "Recibimos una solicitud para restablecer tu contraseña en CFDI-AES.\n\n"
        f"Para continuar, abre este enlace (valido por 30 minutos):\n{link}\n\n"
        "Si tu no solicitaste esto, puedes ignorar este correo - tu contraseña "
        "actual sigue siendo valida."
    )
    cuerpo_html = (
        "<p>Recibimos una solicitud para restablecer tu contraseña en CFDI-AES.</p>"
        f'<p><a href="{link}">Haz clic aquí para continuar</a> (válido por 30 minutos).</p>'
        "<p>Si tú no solicitaste esto, puedes ignorar este correo — tu contraseña "
        "actual sigue siendo válida.</p>"
    )
    return await enviar_correo(
        destinatario=destinatario_email,
        asunto="Recuperación de contraseña — CFDI-AES",
        cuerpo_html=cuerpo_html,
        cuerpo_texto=cuerpo_texto,
    )
