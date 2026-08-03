"""
Tests de integración para el cliente de Facturación.
Usa mocks de httpx para simular respuestas del microservicio sin levantar el stack.
Cubre: timbrado exitoso, idempotencia, doble timbrado, errores del PAC, reintentos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from models.schemas import SolicitudFacturaBot
from services.facturacion_client import (
    DobleTimbradoError,
    FacturacionError,
    FacturacionClient,
    _idempotency_key,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def solicitud() -> SolicitudFacturaBot:
    return SolicitudFacturaBot(
        rfc="DNS010101AAA",
        razon_social="Distribuidora Nacional SA de CV",
        codigo_postal="06600",
        regimen_fiscal="601",
        uso_cfdi="G03",
        email="test@empresa.mx",
        ticket_id="TKT-2025-001",
        concepto="Servicio de prueba",
        subtotal=1000.0,
        emisor_rfc="DNS010101AAA",
    )


@pytest.fixture
def respuesta_ok() -> dict:
    return {
        "uuid": "A1B2C3D4-E5F6-7890-ABCD-EF1234567890",
        "folio": "W-0001",
        "serie": "W",
        "fecha_timbrado": datetime.now(timezone.utc).isoformat(),
        "subtotal": 1000.0,
        "total_iva": 160.0,
        "total": 1160.0,
        "estado": "Vigente",
        "xml_url": "https://storage.test/cfdi/test.xml",
        "pdf_url": "https://storage.test/cfdi/test.pdf",
    }


def _mock_response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", "http://facturacion:8001/facturas/timbrar"),
    )


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestIdempotencyKey:
    def test_mismos_inputs_misma_llave(self):
        k1 = _idempotency_key("TKT-001", "DNS010101AAA", "EMS010101AAA")
        k2 = _idempotency_key("TKT-001", "DNS010101AAA", "EMS010101AAA")
        assert k1 == k2

    def test_diferentes_ticket_diferentes_llaves(self):
        k1 = _idempotency_key("TKT-001", "DNS010101AAA", "EMS010101AAA")
        k2 = _idempotency_key("TKT-002", "DNS010101AAA", "EMS010101AAA")
        assert k1 != k2

    def test_longitud_32_chars(self):
        k = _idempotency_key("TKT-001", "DNS010101AAA", "EMS010101AAA")
        assert len(k) == 32

    def test_case_insensitive(self):
        k1 = _idempotency_key("TKT-001", "DNS010101AAA", "EMS010101AAA")
        k2 = _idempotency_key("TKT-001", "dns010101aaa", "ems010101aaa")
        assert k1 == k2


class TestTimbradoExitoso:
    @pytest.mark.asyncio
    async def test_timbrado_201(self, solicitud, respuesta_ok):
        client = FacturacionClient()
        mock_response = _mock_response(201, respuesta_ok)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            resultado = await client.timbrar(solicitud)

        assert resultado.uuid_cfdi == respuesta_ok["uuid"]
        assert resultado.folio == "W-0001"
        assert resultado.total == 1160.0
        assert resultado.xml_url == respuesta_ok["xml_url"]
        assert len(resultado.idempotency_key) == 32

    @pytest.mark.asyncio
    async def test_timbrado_200_idempotente(self, solicitud, respuesta_ok):
        """Un 200 significa que ya existía (idempotencia del microservicio)."""
        client = FacturacionClient()
        mock_response = _mock_response(200, respuesta_ok)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            resultado = await client.timbrar(solicitud)

        assert resultado.uuid_cfdi == respuesta_ok["uuid"]


class TestDoubleTimbrado:
    @pytest.mark.asyncio
    async def test_409_lanza_doble_timbrado(self, solicitud):
        client = FacturacionClient()
        mock_response = _mock_response(409, {
            "detail": "Ya existe un CFDI para este ticket",
            "uuid": "EXISTING-UUID",
        })

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(DobleTimbradoError) as exc_info:
                await client.timbrar(solicitud)

        assert exc_info.value.retryable is False


class TestErroresPAC:
    @pytest.mark.asyncio
    async def test_error_702_no_reintentable(self, solicitud):
        client = FacturacionClient()
        mock_response = _mock_response(400, {"code": "302", "detail": "RFC inválido SAT"})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(FacturacionError) as exc_info:
                await client.timbrar(solicitud)

        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_error_sat_caido_reintentable(self, solicitud, respuesta_ok):
        """Error 709 (SAT caído) es reintentable — el 3er intento exitoso."""
        client = FacturacionClient()
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _mock_response(503, {"code": "709", "detail": "SAT timeout"})
            return _mock_response(201, respuesta_ok)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
            resultado = await client.timbrar(solicitud)

        assert resultado.uuid_cfdi == respuesta_ok["uuid"]
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_error_500_reintentable_agota_intentos(self, solicitud):
        """Después de 3 intentos fallidos lanza la excepción."""
        client = FacturacionClient()
        mock_response = _mock_response(500, {"detail": "Internal Server Error"})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(FacturacionError):
                await client.timbrar(solicitud)


class TestCancelacion:
    @pytest.mark.asyncio
    async def test_cancelar_exitoso(self):
        client = FacturacionClient()
        uuid = "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        mock_response = _mock_response(200, {
            "uuid": uuid,
            "estado_cancelacion": "Pendiente aceptación receptor",
            "acuse": None,
        })

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            resultado = await client.cancelar(uuid, motivo="02")

        assert resultado["uuid"] == uuid

    @pytest.mark.asyncio
    async def test_cancelar_error_lanza_excepcion(self):
        client = FacturacionClient()
        mock_response = _mock_response(400, {"detail": "CFDI ya cancelado"})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(FacturacionError):
                await client.cancelar("UUID-FAKE", motivo="02")
