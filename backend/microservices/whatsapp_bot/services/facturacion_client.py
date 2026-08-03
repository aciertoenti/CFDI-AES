"""
Cliente REST hacia el microservicio de Facturación (CFDI-AES).
Contrato real del endpoint: POST /facturas/timbrar
Response: FacturaResponse (uuid, folio, xml_url, pdf_url, total, fecha_timbrado)

Implementa:
  - Idempotency key basada en ticket_id (previene doble timbrado)
  - Reintentos con exponential backoff (tenacity)
  - Manejo de errores del PAC/SAT con mensajes claros al usuario
  - El CSD/llave privada NUNCA pasa por aquí — vive en facturacion-service
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config import settings
from core.logging import get_logger
from models.schemas import RespuestaFacturaBot, SolicitudFacturaBot

logger = get_logger(__name__)


# ─── Errores del PAC / SAT ────────────────────────────────────────────────────

class FacturacionError(Exception):
    """Error del microservicio de facturación o del PAC."""

    def __init__(self, message: str, code: Optional[str] = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DobleTimbradoError(FacturacionError):
    """El ticket ya fue timbrado (idempotencia detectada)."""
    pass


# ─── Mapeo de errores Finkok → mensaje amigable ──────────────────────────────
# Supuesto: PAC es Finkok. Estos son los códigos de error más frecuentes.
# Referencia: https://wiki.finkok.com/doku.php?id=stamp_v4#errores

FINKOK_ERRORES: dict[str, tuple[str, bool]] = {
    # (mensaje_usuario, es_reintentable)
    "301": ("RFC del emisor no registrado en el PAC.", False),
    "302": ("RFC del receptor no válido en el SAT.", False),
    "307": ("Folio y serie ya utilizados. Se generará un nuevo folio.", True),
    "309": ("El SAT está saturado. Reintentando automáticamente...", True),
    "401": ("CSD del emisor expirado o cancelado. Contacta a soporte.", False),
    "708": ("El servicio del SAT no está disponible. Reintentando...", True),
    "709": ("Timeout del SAT. Reintentando...", True),
}


def _idempotency_key(ticket_id: str, rfc_receptor: str, emisor_rfc: str) -> str:
    """
    Genera una clave de idempotencia determinista basada en los datos del timbrado.
    Misma llave = mismo timbrado → el microservicio retorna el UUID ya generado.
    """
    raw = f"{ticket_id}:{rfc_receptor}:{emisor_rfc}".lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _build_request_payload(solicitud: SolicitudFacturaBot) -> dict:
    """
    Construye el payload para POST /facturas/timbrar
    Contrato según backend/microservices/facturacion/main.py:FacturaCreate
    """
    emisor_rfc = solicitud.emisor_rfc or settings.emisor_rfc_default
    subtotal = solicitud.subtotal
    iva_tasa = solicitud.iva_tasa

    return {
        "emisor_rfc": emisor_rfc,
        "receptor": {
            "nombre": solicitud.razon_social,
            "rfc": solicitud.rfc,
            "uso_cfdi": solicitud.uso_cfdi,
            "regimen_fiscal": solicitud.regimen_fiscal,
            "domicilio_fiscal": solicitud.codigo_postal,
        },
        "conceptos": [
            {
                "descripcion": solicitud.concepto,
                "cantidad": 1.0,
                "precio_unitario": subtotal,
                "clave_prod_serv": "01010101",
                "clave_unidad": "H87",
                "iva_tasa": iva_tasa,
            }
        ],
        "serie": "W",  # Serie específica para facturas vía WhatsApp
        "moneda": "MXN",
        "tipo_comprobante": "I",
        "metodo_pago": "PUE",
        "forma_pago": "03",
    }


class FacturacionClient:
    """
    Cliente async para el microservicio de Facturación.
    Instanciar una vez y reutilizar (mantiene pool de conexiones).
    """

    def __init__(self) -> None:
        self._base_url = settings.facturacion_url
        self._headers = {
            "X-Internal-Key": settings.internal_api_key,
            "Content-Type": "application/json",
        }

    async def timbrar(
        self, solicitud: SolicitudFacturaBot
    ) -> RespuestaFacturaBot:
        """
        Envía la solicitud de timbrado al microservicio de Facturación.
        - Implementa idempotencia (mismo ticket_id = mismo resultado)
        - Reintenta automáticamente errores transitorios del PAC/SAT
        """
        emisor_rfc = solicitud.emisor_rfc or settings.emisor_rfc_default
        idem_key = _idempotency_key(solicitud.ticket_id, solicitud.rfc, emisor_rfc)
        payload = _build_request_payload(solicitud)

        logger.info(
            "facturacion.timbrar.inicio",
            idempotency_key=idem_key,
            ticket_id=solicitud.ticket_id,
            rfc_receptor=solicitud.rfc,
        )

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(FacturacionError),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                reraise=True,
            ):
                with attempt:
                    resultado = await self._post_timbrar(payload, idem_key)

        except FacturacionError:
            raise
        except Exception as exc:
            logger.error("facturacion.timbrar.error_inesperado", error=str(exc))
            raise FacturacionError(
                f"Error de comunicación con el servicio de facturación: {exc}",
                retryable=True,
            ) from exc

        from datetime import timezone
        return RespuestaFacturaBot(
            uuid_cfdi=resultado["uuid"],
            folio=resultado["folio"],
            xml_url=resultado["xml_url"],
            pdf_url=resultado["pdf_url"],
            total=resultado["total"],
            fecha_timbrado=datetime.fromisoformat(
                str(resultado.get("fecha_timbrado", datetime.now(timezone.utc).isoformat()))
            ),
            idempotency_key=idem_key,
        )

    async def _post_timbrar(self, payload: dict, idem_key: str) -> dict:
        """Realiza el POST real al microservicio."""
        headers = {
            **self._headers,
            "X-Idempotency-Key": idem_key,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/facturas/timbrar",
                json=payload,
                headers=headers,
            )

        # 201 = creado, 200 = ya existía (idempotencia)
        if response.status_code in (200, 201):
            return response.json()

        # 409 Conflict = ya timbrado con esta llave
        if response.status_code == 409:
            data = response.json()
            raise DobleTimbradoError(
                f"Este ticket ya fue timbrado. UUID: {data.get('uuid', 'desconocido')}",
                retryable=False,
            )

        # Errores del PAC/SAT
        try:
            err_body = response.json()
            pac_code = str(err_body.get("code", err_body.get("codigo", "")))
            mensaje, reintentable = FINKOK_ERRORES.get(
                pac_code, (err_body.get("detail", "Error desconocido del PAC"), False)
            )
        except Exception:
            pac_code = str(response.status_code)
            mensaje = f"Error HTTP {response.status_code} del servicio de facturación"
            reintentable = response.status_code >= 500

        logger.warning(
            "facturacion.timbrar.error_pac",
            http_status=response.status_code,
            pac_code=pac_code,
            reintentable=reintentable,
        )

        raise FacturacionError(
            mensaje,
            code=pac_code,
            retryable=reintentable,
        )

    async def cancelar(
        self,
        uuid_cfdi: str,
        motivo: str,
        uuid_sustitucion: Optional[str] = None,
    ) -> dict:
        """
        Solicita cancelación de CFDI al microservicio de Facturación.
        POST /facturas/{uuid}/cancelar
        El microservicio valida plazos SAT antes de proceder.
        """
        payload: dict = {"uuid": uuid_cfdi, "motivo": motivo}
        if uuid_sustitucion:
            payload["uuid_sustitucion"] = uuid_sustitucion

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/facturas/{uuid_cfdi}/cancelar",
                json=payload,
                headers=self._headers,
            )

        if response.status_code == 200:
            return response.json()

        err = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        raise FacturacionError(
            err.get("detail", f"Error al cancelar: HTTP {response.status_code}"),
            retryable=False,
        )


# Instancia singleton para reusar pool de conexiones
facturacion_client = FacturacionClient()
