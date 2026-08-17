"""
Cliente para WhatsApp Business Cloud API (Meta).
Supuesto: se usa la API directa de Meta (no Twilio ni 360dialog).
Referencia: https://developers.facebook.com/docs/whatsapp/cloud-api

Responsabilidades:
  - Enviar mensajes de texto
  - Enviar documentos (XML/PDF de la factura)
  - Descargar media (imágenes/PDFs enviados por el usuario para OCR)
  - Marcar mensajes como leídos (mejora UX)
"""
from __future__ import annotations

from typing import Optional

import httpx

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


class WhatsAppClient:
    """
    Cliente async para la Cloud API de WhatsApp (Meta).
    Las credenciales se leen de settings — NUNCA se pasan como parámetros.
    """

    def __init__(self) -> None:
        self._api_url = settings.whatsapp_api_url
        self._headers = {
            "Authorization": f"Bearer {settings.whatsapp_token}",
            "Content-Type": "application/json",
        }
        self._media_url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        )

    async def send_text(self, wa_id: str, text: str) -> dict:
        """Envía un mensaje de texto al número wa_id (formato: 521XXXXXXXXXX)."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return await self._post(payload)

    async def send_document(
        self,
        wa_id: str,
        url: str,
        filename: str,
        caption: Optional[str] = None,
    ) -> dict:
        """
        Envía un documento (XML o PDF) por URL pública (MinIO/S3).
        La URL debe ser accesible por los servidores de Meta.
        """
        doc: dict = {"link": url, "filename": filename}
        if caption:
            doc["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "document",
            "document": doc,
        }
        return await self._post(payload)

    async def mark_as_read(self, message_id: str) -> None:
        """Marca el mensaje del usuario como leído (doble paloma azul)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            await self._post(payload)
        except Exception as exc:
            # No crítico — el flujo continúa aunque falle el "leído"
            logger.warning("whatsapp.mark_read_failed", error=str(exc))

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """
        Descarga media (imagen/PDF) enviada por el usuario.
        Retorna (contenido_bytes, tipo_mime).
        """
        # Paso 1: obtener URL de descarga
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._media_url}/{settings.whatsapp_api_version}/{media_id}",
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            )
            resp.raise_for_status()
            media_info = resp.json()
            download_url: str = media_info["url"]
            mime_type: str = media_info.get("mime_type", "application/octet-stream")

        # Paso 2: descargar el contenido
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            )
            resp.raise_for_status()
            return resp.content, mime_type

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self._api_url,
                json=payload,
                headers=self._headers,
            )
            if not resp.is_success:
                logger.error(
                    "whatsapp.api_error",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                resp.raise_for_status()
            logger.info(
                "whatsapp.send_success",
                wa_id=payload.get("to"),
                status=resp.status_code,
            )
            return resp.json()


# Singleton
whatsapp_client = WhatsAppClient()
