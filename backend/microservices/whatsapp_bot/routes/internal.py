"""
Endpoints REST internos del microservicio (servicio-a-servicio).
Protegidos con X-Internal-Key — NO expuestos al internet público.

POST /bot/factura      → Timbrar vía datos ya validados (para integración con POS/ERP)
POST /bot/cancelar     → Solicitar cancelación de CFDI
GET  /bot/sesion/{id}  → Consultar estado de sesión (para debugging/soporte)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.security import require_internal_key
from models.schemas import RespuestaFacturaBot, SolicitudFacturaBot
from services.facturacion_client import DobleTimbradoError, FacturacionError, facturacion_client
from services.session_store import load_session

router = APIRouter(
    prefix="/bot",
    tags=["internal"],
    dependencies=[Depends(require_internal_key)],
)


@router.post(
    "/factura",
    response_model=RespuestaFacturaBot,
    status_code=status.HTTP_201_CREATED,
    summary="Timbrar CFDI vía API interna (sin flujo WhatsApp)",
)
async def timbrar_via_api(solicitud: SolicitudFacturaBot) -> RespuestaFacturaBot:
    """
    Endpoint interno para sistemas que ya tienen los datos fiscales validados
    (ej: POS, ERP) y quieren timbrar sin pasar por el flujo de conversación.

    La idempotencia se garantiza por ticket_id — enviar el mismo ticket_id
    siempre retorna el mismo CFDI, nunca genera duplicados.
    """
    try:
        return await facturacion_client.timbrar(solicitud)
    except DobleTimbradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except FacturacionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"mensaje": str(exc), "codigo": exc.code},
        )


@router.post(
    "/cancelar/{uuid_cfdi}",
    summary="Solicitar cancelación de CFDI",
)
async def cancelar_cfdi(
    uuid_cfdi: str,
    motivo: str = "02",
    uuid_sustitucion: str | None = None,
) -> dict:
    """
    Solicita la cancelación de un CFDI al microservicio de Facturación.
    El microservicio valida plazos SAT (72 horas para cancelación inmediata).

    motivo: 01=Comprobante emitido con errores con relación,
            02=Comprobante emitido con errores sin relación,
            03=No se llevó a cabo la operación,
            04=Operación nominativa relacionada en factura global
    """
    try:
        resultado = await facturacion_client.cancelar(
            uuid_cfdi=uuid_cfdi,
            motivo=motivo,
            uuid_sustitucion=uuid_sustitucion,
        )
        return resultado
    except FacturacionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.get(
    "/sesion/{wa_id}",
    summary="Consultar estado de sesión (soporte técnico)",
)
async def get_sesion(wa_id: str) -> dict:
    """
    Retorna el estado actual de la sesión de conversación.
    Útil para soporte técnico — no retorna datos sensibles completos.
    """
    ctx = await load_session(wa_id)
    return {
        "wa_id": wa_id,
        "estado": ctx.estado.value,
        "opt_in": ctx.opt_in,
        "campos_capturados": {
            "rfc": bool(ctx.datos.rfc),
            "razon_social": bool(ctx.datos.razon_social),
            "codigo_postal": bool(ctx.datos.codigo_postal),
            "regimen_fiscal": bool(ctx.datos.regimen_fiscal),
            "uso_cfdi": bool(ctx.datos.uso_cfdi),
            "email": bool(ctx.datos.email),
            "ticket_id": bool(ctx.datos.ticket_id),
        },
    }
