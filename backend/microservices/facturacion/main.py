import asyncio
import base64
import io
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import date, datetime
import httpx
import jinja2
import qrcode
import weasyprint

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cryptography.hazmat.primitives.serialization import Encoding
from satcfdi.models import Signer
from satcfdi.cfdi import CFDI
from satcfdi.render import pdf_bytes as generar_pdf_bytes
from satcfdi.create.cfd.cfdi40 import (
    Comprobante,
    Emisor,
    Receptor,
    Concepto as ConceptoCFDI,
    Impuestos,
    Traslado,
    InformacionGlobal,
)

import finkok_client
import storage_client
from database import BorradorFactura, BorradorFacturaEliminado, Factura, TicketVenta, get_db, create_tables, stamp_head_si_es_ambiente_nuevo
from shared.negocio_id import requerir_negocio_id
from shared.internal_key import INTERNAL_API_KEY, require_internal_key

# basicConfig es necesario para que los logger.info/error de este archivo Y
# de finkok_client lleguen a algun lado - sin esto (confirmado hoy en vivo,
# incluso con un timbrado/cancelacion real exitoso contra Finkok) los
# loggers "facturacion"/"finkok_client" no tienen ningun handler efectivo
# (uvicorn solo configura sus propios loggers "uvicorn"/"uvicorn.access") y
# los mensajes INFO se descartan en silencio. Necesario de aqui en adelante
# para poder auditar cuando se pide/cachea un CSD real (#42).
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("facturacion")

RFC_PUBLICO_EN_GENERAL = "XAXX010101000"
TASA_IVA_DECIMALES = Decimal("0.000000")

# Costo real por timbre exitoso, cotizado con Finkok (#6). Cambia el
# precio de Finkok, cambia esta linea - nada mas.
COSTO_TIMBRE_FINKOK = Decimal("0.30")
IVA_TASA_COSTO_TIMBRE = Decimal("0.16")
COSTO_TIMBRE_CON_IVA = (COSTO_TIMBRE_FINKOK * (1 + IVA_TASA_COSTO_TIMBRE)).quantize(Decimal("0.0001"))

# Contador virtual (#40, Fase 1) - estimador de ISR provisional mensual
# para RESICO Personas Fisicas. Tasa fija sobre el TOTAL del mes (no es
# calculo marginal como las tarifas de sueldos) - Art. 113-E LISR.
REGIMEN_RESICO = "626"  # verificado contra el catalogo oficial C756_c_RegimenFiscal (satcfdi), no asumido
REGIMEN_SIN_OBLIGACIONES = "616"  # verificado contra C756_c_RegimenFiscal (satcfdi), no asumido
# Valores fijos que el SAT exige para el receptor "Publico en General"
# (RFC XAXX010101000) - ver construir_comprobante y zg5UciU (03 sep 2026).
NOMBRE_PUBLICO_EN_GENERAL = "PUBLICO EN GENERAL"  # EXACTO en mayusculas; otra capitalizacion -> CFDI40130
USO_CFDI_SIN_EFECTOS = "S01"  # unico UsoCFDI valido con regimen 616 (c_UsoCFDI); otro -> CFDI40161
RFC_LEN_PERSONA_FISICA = 13  # 12 = Persona Moral - el codigo 626 aplica a ambas, hay que distinguir por RFC
TABLA_ISR_RESICO_PF = [
    (Decimal("25000.00"), Decimal("0.0100")),
    (Decimal("50000.00"), Decimal("0.0110")),
    (Decimal("83333.33"), Decimal("0.0150")),
    (Decimal("208333.33"), Decimal("0.0200")),
    (Decimal("291666.67"), Decimal("0.0250")),
]

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await stamp_head_si_es_ambiente_nuevo()
    yield


app = FastAPI(title="CFDI – Servicio de Facturación", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Concepto(BaseModel):
    descripcion: str
    cantidad: float = Field(gt=0)
    precio_unitario: float = Field(gt=0)
    clave_prod_serv: str = "01010101"
    clave_unidad: str = "H87"
    iva_tasa: float = 0.16

class ReceptorCFDI(BaseModel):
    nombre: str
    rfc: str
    uso_cfdi: str = "G03"
    regimen_fiscal: str = "601"
    domicilio_fiscal: str

class FacturaCreate(BaseModel):
    emisor_rfc: str
    receptor: ReceptorCFDI
    conceptos: List[Concepto]
    serie: str = "A"
    moneda: str = "MXN"
    tipo_comprobante: str = "I"
    metodo_pago: str = "PUE"
    forma_pago: str = "03"
    # Solo se usan si receptor.rfc es Público en General (XAXX010101000),
    # donde el SAT exige el nodo InformacionGlobal. Defaults de prueba.
    informacion_global_periodicidad: str = "01"
    informacion_global_meses: str = "01"
    informacion_global_ano: Optional[int] = None

class FacturaResponse(BaseModel):
    uuid: str
    folio: str
    serie: str
    fecha_timbrado: datetime
    receptor_rfc: str
    subtotal: float
    total_iva: float
    total: float
    estado: str
    xml_url: str
    pdf_url: str
    noCertificadoSAT: Optional[str] = None
    creado_por_rfc: Optional[str] = None
    cancelado_por_rfc: Optional[str] = None

class CancelacionRequest(BaseModel):
    uuid: str
    motivo: str
    uuid_sustitucion: Optional[str] = None

class CostoResumenItem(BaseModel):
    periodo: str  # "YYYY-MM"
    emisor_rfc: str
    num_timbres: int
    costo_total: float
    costo_promedio: float

class FacturaResumenLigero(BaseModel):
    folio: str
    uuid: str
    receptor_rfc: str
    total: float

class ContadorVirtualISRResicoResponse(BaseModel):
    aplica: bool
    motivo_no_aplica: Optional[str] = None
    emisor_rfc: str
    periodo: str  # "YYYY-MM"
    ingreso_pue_incluido: float = 0.0
    tasa_aplicada: Optional[float] = None
    isr_estimado: float = 0.0
    excede_tope_mensual: bool = False
    facturas_pue_incluidas: List[FacturaResumenLigero] = []
    facturas_ppd_excluidas: List[FacturaResumenLigero] = []
    disclaimer: str = (
        "Estimación informativa basada en tus CFDI emitidos. "
        "No sustituye a tu contador ni constituye asesoría fiscal."
    )

# ─── Datos del emisor: consulta real a administracion (#14) ───────────────────
# El regimen fiscal y el CP de expedicion ya NO son constantes de prueba -
# se consultan a administracion, que persiste emisores reales desde #4.
ADMINISTRACION_URL = os.environ.get("ADMINISTRACION_URL", "http://administracion:8002")

# Base publica para el QR del ticket de venta (POS ligero, zg5b-ZE, 04 sep
# 2026) - codifica f"{PUBLIC_APP_URL}/facturas/tickets/{qr_token}". Config,
# no secreto: default de desarrollo (localhost, inutil fuera de esta red).
# Cuando exista un dominio real de produccion, solo cambia esta variable de
# entorno - el codigo no se toca (ver docker-compose.yml y .env).
PUBLIC_APP_URL = os.environ.get("PUBLIC_APP_URL", "http://localhost:8000")

# Entorno Jinja2 para el PDF del ticket (templates/ticket_pdf.html) -
# FileSystemLoader relativo a este archivo, no al cwd del proceso, para que
# funcione sin importar desde donde se lance uvicorn.
_jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(__file__).resolve().parent / "templates"))
# Clave servicio-a-servicio (#42), extraida a backend/shared/internal_key.py
# (14 ago 2026, refactor/shared-internal-key, ver import arriba) - antes
# vivia copiada aqui, identica a la de administracion/ia. La misma
# INTERNAL_API_KEY compartida se reusa como cliente saliente en las llamadas
# a administracion de este archivo (obtener_datos_emisor y
# obtener_csd_descifrado, mas abajo), en vez de leer la variable una segunda
# vez por separado.


async def obtener_datos_emisor(rfc: str, x_negocio_id: Optional[str] = None) -> dict:
    """Consulta administracion por regimen fiscal y CP del emisor. Si el
    emisor no esta registrado ahi, es un error real (no hay a que hacer
    fallback) - no se puede timbrar a nombre de un emisor sin dar de alta.

    x_negocio_id (#15) se reenvia tal cual llego a este servicio - viene del
    Gateway (derivado del JWT ya verificado del usuario que llamo a este
    endpoint) y administracion lo exige para no dejar que un Negocio consulte
    (o firme a nombre de) el emisor de otro adivinando el RFC."""
    # Hallazgo 18 ago 2026: esta llamada nunca mando X-Internal-Key desde que
    # GET /admin/emisores/{rfc} empezo a exigirla (tarjeta 229004043, commit
    # 3b47ef3) - causaba 403 en administracion y por lo tanto 502 aqui en
    # cada timbrado. Agregado ahora, mismo patron que obtener_csd_descifrado.
    headers = {"X-Negocio-Id": x_negocio_id} if x_negocio_id else {}
    headers["X-Internal-Key"] = INTERNAL_API_KEY
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{ADMINISTRACION_URL}/admin/emisores/{rfc}", headers=headers)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"No se pudo conectar con administracion: {e}")

    if resp.status_code == 404:
        raise HTTPException(
            status_code=400,
            detail=f"Emisor {rfc} no esta registrado en administracion. Debe darse de alta antes de timbrar.",
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"administracion respondio {resp.status_code}: {resp.text}")

    return resp.json()


async def obtener_plan_negocio(negocio_id: int) -> str:
    """Consulta el plan vigente del negocio antes de aplicar su cuota mensual."""
    headers = {"X-Negocio-Id": str(negocio_id), "X-Internal-Key": INTERNAL_API_KEY}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{ADMINISTRACION_URL}/admin/negocios/{negocio_id}", headers=headers)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"No se pudo consultar el plan del negocio: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"administracion respondio {resp.status_code} al consultar el plan")
    return resp.json().get("plan", "basico").lower()


async def obtener_siguiente_folio(rfc: str, serie: str, x_negocio_id: Optional[str] = None) -> str:
    """Pide a administracion el siguiente folio consecutivo real para este
    emisor+serie (#12) - el conteo atomico vive alla, no aqui. Reemplaza el
    identificador pseudoaleatorio que se usaba antes.

    x_negocio_id (#15) se reenvia igual que en obtener_datos_emisor - evita
    que un Negocio incremente el folio de otro adivinando su emisor_rfc."""
    headers = {"X-Negocio-Id": x_negocio_id} if x_negocio_id else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{ADMINISTRACION_URL}/admin/series/{serie}/siguiente-folio",
                params={"emisor_rfc": rfc},
                headers=headers,
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"No se pudo conectar con administracion: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"administracion respondio {resp.status_code}: {resp.text}")

    return resp.json()["folio_formateado"]


@dataclass
class _CSDCacheado:
    signer: Signer
    cert_bytes: bytes
    key_bytes: bytes
    password: str


# Cache por rfc (#42) - reemplaza el @lru_cache global de antes, que solo
# podia sostener un CSD para todo el proceso sin importar el emisor (por
# eso hoy solo existe un archivo estatico de prueba). Un lock de asyncio
# por rfc evita que dos requests simultaneas al mismo emisor (ej. dos
# timbrados casi a la vez) disparen dos llamadas duplicadas a
# administracion - "double-checked locking": se revisa el cache, si no
# esta se adquiere el lock de ESE rfc, y se revisa el cache otra vez ya
# adentro (por si otra corrutina ya lo lleno mientras se esperaba el lock).
_csd_cache: dict[str, _CSDCacheado] = {}
_csd_locks: dict[str, asyncio.Lock] = {}


def _lock_para_rfc(rfc: str) -> asyncio.Lock:
    # Sin await en todo el cuerpo de esta funcion - en asyncio (un solo
    # hilo, cooperativo) eso basta para que el check-then-create de abajo
    # sea atomico frente a otras corrutinas, sin necesitar un lock aparte
    # para proteger el propio diccionario de locks.
    lock = _csd_locks.get(rfc)
    if lock is None:
        lock = asyncio.Lock()
        _csd_locks[rfc] = lock
    return lock


async def obtener_csd_descifrado(rfc: str) -> dict:
    """
    Pide el CSD descifrado a administracion via el endpoint interno (#42),
    protegido con X-Internal-Key (servicio-a-servicio, NO X-Negocio-Id) -
    NO valida pertenencia al negocio del caller. Quien llama
    (_obtener_csd_cacheado) es responsable de haber confirmado eso antes
    con obtener_datos_emisor(). Nunca loguear el resultado de esta funcion.
    """
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=500, detail="INTERNAL_API_KEY no esta configurado")
    headers = {"X-Internal-Key": INTERNAL_API_KEY}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{ADMINISTRACION_URL}/admin/emisores/{rfc}/csd-descifrado", headers=headers
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"No se pudo conectar con administracion: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=502, detail=f"Emisor {rfc} no tiene CSD registrado en administracion")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"administracion respondio {resp.status_code}: {resp.text}")

    return resp.json()


async def _obtener_csd_cacheado(rfc: str, negocio_id: int) -> _CSDCacheado:
    # Verificacion de pertenencia SIEMPRE, en cada llamada, ANTES de
    # cualquier lookup de cache - reutiliza obtener_datos_emisor (ya da
    # 404/400 si rfc no pertenece a negocio_id, #58). Esto NUNCA debe
    # saltarse por un cache hit: rfc es unique en administracion (un rfc
    # pertenece a un solo negocio), asi que lo unico que se cachea por rfc
    # es el propio Signer/CSD ya descifrado - la confirmacion de pertenencia
    # se repite en cada llamada, si no un negocio ajeno heredaria via cache
    # el acceso que gano el primer negocio en pedir ese mismo rfc. Sin este
    # orden, se reabre el hueco de cancelacion cross-tenant cerrado en
    # 294fc52, ahora tambien en timbrado: con CSD reales por emisor, ya no
    # existe la proteccion accidental de "solo hay un CSD para todo el
    # proceso".
    await obtener_datos_emisor(rfc, str(negocio_id))

    cacheado = _csd_cache.get(rfc)
    if cacheado is not None:
        return cacheado

    async with _lock_para_rfc(rfc):
        cacheado = _csd_cache.get(rfc)
        if cacheado is not None:
            return cacheado

        datos_csd = await obtener_csd_descifrado(rfc)
        try:
            cert_bytes = base64.b64decode(datos_csd["csd_cert_base64"])
            key_bytes = base64.b64decode(datos_csd["csd_key_base64"])
            password = datos_csd["csd_password"]
            signer = Signer.load(certificate=cert_bytes, key=key_bytes, password=password)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"No se pudo cargar el CSD de {rfc}: {e}")

        cacheado = _CSDCacheado(signer=signer, cert_bytes=cert_bytes, key_bytes=key_bytes, password=password)
        _csd_cache[rfc] = cacheado
        logger.info("CSD de %s cargado desde administracion y cacheado (negocio_id=%s)", rfc, negocio_id)
        return cacheado


async def get_signer_para_negocio(rfc: str, negocio_id: int) -> Signer:
    """
    Punto unico para obtener el Signer real de un emisor (#42). Verifica
    propiedad ANTES de tocar su CSD real (ver _obtener_csd_cacheado) -
    reutiliza obtener_datos_emisor(), no inventa una validacion nueva.
    """
    cacheado = await _obtener_csd_cacheado(rfc, negocio_id)
    return cacheado.signer


async def obtener_csd_bytes_para_negocio(rfc: str, negocio_id: int) -> tuple[bytes, bytes, str]:
    """
    Igual que get_signer_para_negocio pero regresa los bytes crudos
    (cert, key, password) en vez del Signer ya cargado - los necesita
    finkok_client.registrar_emisor(), que no acepta un Signer. Comparte el
    mismo cache/lock por rfc: si get_signer_para_negocio ya se llamo antes
    para este rfc en la misma request, esto no dispara una segunda
    llamada a administracion.
    """
    cacheado = await _obtener_csd_cacheado(rfc, negocio_id)
    return cacheado.cert_bytes, cacheado.key_bytes, cacheado.password


@app.post("/internal/csd-cache/invalidar/{rfc}", dependencies=[Depends(require_internal_key)])
async def invalidar_csd_cache(rfc: str):
    """
    Uso exclusivo servicio-a-servicio (administracion, al rotar un CSD via
    PUT /admin/emisores/{rfc}) - protegido con X-Internal-Key. _csd_cache no
    tiene TTL (dict en memoria del proceso, ver _obtener_csd_cacheado): sin
    esto, un CSD rotado en administracion se seguiria usando aqui hasta que
    el proceso de facturacion se reiniciara solo. Limpia tambien el lock
    (_csd_locks), no solo la entrada cacheada - dejar un Lock huerfano no
    rompe nada (se recrea en _lock_para_rfc si hace falta), pero no hay
    razon para no limpiarlo junto con su CSD.
    """
    estaba_cacheado = _csd_cache.pop(rfc, None) is not None
    _csd_locks.pop(rfc, None)
    logger.info("csd_cache.invalidado rfc=%s estaba_cacheado=%s", rfc, estaba_cacheado)
    return {"rfc": rfc, "estaba_cacheado": estaba_cacheado}


async def construir_comprobante(factura: FacturaCreate, signer: Signer, x_negocio_id: Optional[str] = None) -> Comprobante:
    if factura.emisor_rfc != str(signer.rfc):
        raise HTTPException(
            status_code=400,
            detail=f"emisor_rfc ({factura.emisor_rfc}) no coincide con el RFC del CSD cargado ({signer.rfc})",
        )

    datos_emisor = await obtener_datos_emisor(factura.emisor_rfc, x_negocio_id)

    # Un emisor Inactivo NO puede emitir CFDI nuevos (RFC dado de baja, CSD
    # que ya no debe usarse, etc.). La autorizacion vive aqui, no solo en que
    # el frontend oculte el boton - una llamada directa a POST /facturas/timbrar
    # con un emisor_rfc inactivo tiene que fallar antes de siquiera llamar a
    # Finkok. Se valida SOLO en el path de emision: obtener_datos_emisor lo
    # comparten rutas de lectura (GET /facturas, /costos-resumen,
    # /contador-virtual) y la cancelacion, que deben seguir funcionando para
    # emisores inactivos (el historico no desaparece al inactivar).
    if datos_emisor.get("estado") != "Activo":
        raise HTTPException(
            status_code=409,
            detail=(
                f"El emisor {factura.emisor_rfc} esta Inactivo — no puede "
                f"timbrar. Reactivalo en Administracion antes de continuar."
            ),
        )

    emisor = Emisor(
        rfc=str(signer.rfc),
        nombre=signer.legal_name,
        regimen_fiscal=datos_emisor["regimen_fiscal"],
    )
    # Regla real del SAT (CFDI40149, encontrada probando #14): si el receptor
    # es Publico en General, DomicilioFiscalReceptor debe ser igual al
    # LugarExpedicion del comprobante. Se fuerza aqui - quien llama a la API
    # no tiene que saberlo ni mandarlo bien a mano.
    domicilio_fiscal_receptor = factura.receptor.domicilio_fiscal
    if factura.receptor.rfc == RFC_PUBLICO_EN_GENERAL:
        domicilio_fiscal_receptor = datos_emisor["codigo_postal"]

    # Mismo criterio que DomicilioFiscalReceptor: si el receptor es Publico
    # en General, el SAT exige valores fijos que el caller no siempre manda
    # bien (el front puede dejar el nombre en minusculas, un regimen 601 por
    # default, o un UsoCFDI que no aplica a regimen 616). Se fuerzan aqui, no
    # se confia en el caller:
    #   - RegimenFiscalReceptor = 616 (Sin obligaciones fiscales).
    #   - Nombre = "PUBLICO EN GENERAL" EXACTO en mayusculas: con otra
    #     capitalizacion el PAC rechaza con CFDI40130 ("falta InformacionGlobal")
    #     aunque el nodo si exista - confirmado contra el sandbox de Finkok
    #     (zg5UciU, 03 sep 2026).
    #   - UsoCFDI = S01, el unico valido con regimen 616; cualquier otro da CFDI40161.
    regimen_fiscal_receptor = factura.receptor.regimen_fiscal
    nombre_receptor = factura.receptor.nombre
    uso_cfdi_receptor = factura.receptor.uso_cfdi
    if factura.receptor.rfc == RFC_PUBLICO_EN_GENERAL:
        regimen_fiscal_receptor = REGIMEN_SIN_OBLIGACIONES
        nombre_receptor = NOMBRE_PUBLICO_EN_GENERAL
        uso_cfdi_receptor = USO_CFDI_SIN_EFECTOS

    receptor = Receptor(
        rfc=factura.receptor.rfc,
        nombre=nombre_receptor,
        domicilio_fiscal_receptor=domicilio_fiscal_receptor,
        regimen_fiscal_receptor=regimen_fiscal_receptor,
        uso_cfdi=uso_cfdi_receptor,
    )
    conceptos = [
        ConceptoCFDI(
            clave_prod_serv=c.clave_prod_serv,
            cantidad=Decimal(str(c.cantidad)),
            clave_unidad=c.clave_unidad,
            descripcion=c.descripcion,
            valor_unitario=Decimal(str(c.precio_unitario)),
            impuestos=Impuestos(
                traslados=Traslado(
                    impuesto="002",
                    tipo_factor="Tasa",
                    # c_TasaOcuota exige exactamente 6 decimales (0.160000).
                    # Se fuerza con quantize, no se depende de como Python
                    # represente el float por default.
                    tasa_o_cuota=Decimal(str(c.iva_tasa)).quantize(TASA_IVA_DECIMALES),
                )
            ) if c.iva_tasa else None,
        )
        for c in factura.conceptos
    ]

    informacion_global = None
    if factura.receptor.rfc == RFC_PUBLICO_EN_GENERAL:
        informacion_global = InformacionGlobal(
            periodicidad=factura.informacion_global_periodicidad,
            meses=factura.informacion_global_meses,
            ano=factura.informacion_global_ano or datetime.now().year,
        )

    comprobante = Comprobante(
        emisor=emisor,
        lugar_expedicion=datos_emisor["codigo_postal"],
        receptor=receptor,
        conceptos=conceptos,
        moneda=factura.moneda,
        tipo_de_comprobante=factura.tipo_comprobante,
        serie=factura.serie,
        metodo_pago=factura.metodo_pago,
        forma_pago=factura.forma_pago,
        informacion_global=informacion_global,
    )
    comprobante.sign(signer)
    return comprobante


def _factura_to_response(f: Factura) -> FacturaResponse:
    # Las URLs son firmadas (expiran) y no se guardan en BD - se regeneran
    # frescas en cada lectura contra el objeto ya subido en MinIO.
    return FacturaResponse(
        uuid=f.uuid,
        folio=f.folio,
        serie=f.folio.split("-")[0] if "-" in f.folio else "A",
        fecha_timbrado=f.fecha_timbrado,
        receptor_rfc=f.receptor_rfc,
        subtotal=float(f.subtotal),
        total_iva=float(f.total_iva),
        total=float(f.total),
        estado=f.estado,
        xml_url=storage_client.url_xml(f.uuid),
        pdf_url=storage_client.url_pdf(f.uuid),
        noCertificadoSAT=f.no_certificado_sat,
        creado_por_rfc=f.creado_por_rfc,
        cancelado_por_rfc=f.cancelado_por_rfc,
    )


@app.post("/facturas/timbrar", response_model=FacturaResponse, status_code=201, dependencies=[Depends(require_internal_key)])
async def timbrar_factura(
    factura: FacturaCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)

    if x_idempotency_key:
        existente = await db.execute(
            select(Factura).where(Factura.idempotency_key == x_idempotency_key)
        )
        factura_existente = existente.scalar_one_or_none()
        if factura_existente:
            logger.info("facturacion.idempotencia.hit idempotency_key=%s", x_idempotency_key)
            return JSONResponse(
                status_code=200,
                content=_factura_to_response(factura_existente).model_dump(mode="json"),
            )

    plan = await obtener_plan_negocio(negocio_id)
    limites_facturas = {"emprendedor": 25, "basico": 50, "contador": 100, "despacho": 500}
    limite_mensual = limites_facturas.get(plan, limites_facturas["basico"])
    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    facturas_mes = await db.scalar(
        select(func.count(Factura.id)).where(
            Factura.negocio_id == negocio_id,
            Factura.fecha_timbrado >= inicio_mes,
        )
    ) or 0
    if facturas_mes >= limite_mensual:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El plan {plan} permite hasta {limite_mensual} factura(s) por mes. "
                "Actualiza tu plan para continuar."
            ),
        )

    signer = await get_signer_para_negocio(factura.emisor_rfc, negocio_id)
    comprobante = await construir_comprobante(factura, signer, x_negocio_id)

    cert_bytes, key_bytes, csd_password = await obtener_csd_bytes_para_negocio(factura.emisor_rfc, negocio_id)
    try:
        finkok_client.registrar_emisor(factura.emisor_rfc, cert_bytes, key_bytes, csd_password)
        resultado = finkok_client.timbrar_factura(comprobante.xml_bytes())
    except finkok_client.FinkokError as e:
        raise HTTPException(status_code=502, detail=f"[{e.codigo}] {e.mensaje}")

    impuestos = comprobante.get("Impuestos") or {}
    # Folio consecutivo real por emisor+serie, contado atomicamente en
    # administracion (#12). Se pide DESPUES de que Finkok ya confirmo el
    # timbrado, para no quemar folios en intentos que fallan en el PAC.
    folio = await obtener_siguiente_folio(factura.emisor_rfc, factura.serie, x_negocio_id)
    subtotal = Decimal(str(comprobante["SubTotal"]))
    total_iva = Decimal(str(impuestos.get("TotalImpuestosTrasladados") or 0))
    total = Decimal(str(comprobante["Total"]))
    fecha_timbrado = resultado["fecha_timbrado"]
    if isinstance(fecha_timbrado, str):
        fecha_timbrado = datetime.fromisoformat(fecha_timbrado)

    # La factura YA esta timbrada en Finkok en este punto (dato fiscal real,
    # irreversible). Un fallo al guardarla en BD no debe tirar la respuesta
    # ni perder el timbrado — se loggea con todos los datos para poder
    # recuperarlo/reinsertarlo manualmente despues.
    try:
        db.add(Factura(
            uuid=resultado["uuid"],
            negocio_id=negocio_id,
            folio=folio,
            fecha_timbrado=fecha_timbrado,
            emisor_rfc=factura.emisor_rfc,
            receptor_rfc=factura.receptor.rfc,
            subtotal=subtotal,
            total_iva=total_iva,
            total=total,
            estado="Vigente",
            no_certificado_sat=resultado["no_certificado_sat"],
            xml=resultado["xml_timbrado"],
            costo_timbre=COSTO_TIMBRE_CON_IVA,
            metodo_pago=factura.metodo_pago,
            creado_por_rfc=x_usuario_rfc,
            idempotency_key=x_idempotency_key,
        ))
        await db.commit()
    except Exception:
        await db.rollback()
        logger.error(
            "FACTURA TIMBRADA EN FINKOK PERO NO SE PUDO GUARDAR EN BD - "
            "recuperar manualmente: uuid=%s folio=%s emisor_rfc=%s receptor_rfc=%s "
            "total=%s fecha_timbrado=%s no_certificado_sat=%s",
            resultado["uuid"], folio, factura.emisor_rfc, factura.receptor.rfc,
            total, fecha_timbrado, resultado["no_certificado_sat"],
            exc_info=True,
        )

    # El XML timbrado que regresa Finkok viene como texto con declaracion de
    # encoding (<?xml ... encoding="utf-8"?>) - hay que codificarlo a bytes
    # antes de re-parsearlo, porque lxml rechaza declaraciones de encoding
    # en strings de Python.
    xml_timbrado_bytes = resultado["xml_timbrado"].encode("utf-8")
    cfdi_timbrado = CFDI.from_string(xml_timbrado_bytes)
    pdf_generado = generar_pdf_bytes(cfdi_timbrado)

    xml_url = storage_client.subir_xml(resultado["uuid"], xml_timbrado_bytes)
    pdf_url = storage_client.subir_pdf(resultado["uuid"], pdf_generado)

    return FacturaResponse(
        uuid=resultado["uuid"],
        folio=folio,
        serie=factura.serie,
        fecha_timbrado=fecha_timbrado,
        receptor_rfc=factura.receptor.rfc,
        subtotal=float(subtotal),
        total_iva=float(total_iva),
        total=float(total),
        estado="Vigente",
        xml_url=xml_url,
        pdf_url=pdf_url,
        noCertificadoSAT=resultado["no_certificado_sat"],
        creado_por_rfc=x_usuario_rfc,
    )

@app.get("/facturas/count", dependencies=[Depends(require_internal_key)])
async def contar_facturas_por_emisor(
    emisor_rfc: str = Query(...),
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """Cuenta facturas timbradas de un emisor, para verificar antes de
    permitir eliminarlo desde administracion - endpoint barato (solo
    COUNT, no trae las filas), mismo aislamiento por negocio_id que el
    resto del servicio."""
    negocio_id = requerir_negocio_id(x_negocio_id)
    total = await db.scalar(
        select(func.count(Factura.id)).where(
            Factura.negocio_id == negocio_id,
            Factura.emisor_rfc == emisor_rfc,
        )
    ) or 0
    return {"emisor_rfc": emisor_rfc, "total_facturas": total}


# ─── Borradores de factura ────────────────────────────────────────────────────
# Un borrador es el form de NuevaFactura.jsx guardado tal cual (datos_json),
# NO un documento fiscal. Mismo aislamiento por negocio_id que Factura.
# IMPORTANTE: estas rutas van declaradas ANTES de /facturas/{uuid} para que
# "borradores" no lo capture esa ruta generica (mismo cuidado que /facturas/count).

class BorradorCreate(BaseModel):
    emisor_rfc: Optional[str] = None
    datos_json: str

class BorradorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    negocio_id: int
    emisor_rfc: Optional[str] = None
    datos_json: str
    created_at: datetime
    updated_at: datetime

class BorradorEliminadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    negocio_id: int
    borrador_id_original: int
    emisor_rfc: Optional[str] = None
    datos_json: str
    creado_por_rfc: Optional[str] = None
    eliminado_por_rfc: Optional[str] = None
    motivo: str
    creado_en_original: datetime
    eliminado_at: datetime

@app.post("/facturas/borradores", response_model=BorradorResponse, status_code=201, dependencies=[Depends(require_internal_key)])
async def crear_borrador(
    borrador: BorradorCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    nuevo = BorradorFactura(negocio_id=negocio_id, emisor_rfc=borrador.emisor_rfc, datos_json=borrador.datos_json, creado_por_rfc=x_usuario_rfc)
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)
    return nuevo

@app.get("/facturas/borradores", response_model=List[BorradorResponse], dependencies=[Depends(require_internal_key)])
async def listar_borradores(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(BorradorFactura).where(BorradorFactura.negocio_id == negocio_id).order_by(BorradorFactura.updated_at.desc()))
    return result.scalars().all()

# IMPORTANTE: declarada ANTES de /facturas/borradores/{borrador_id}. Si va
# despues, Starlette casa "eliminados" contra {borrador_id} (int), FastAPI
# falla la coercion y responde 422 sin llegar aqui - mismo cuidado que el
# bloque de arriba con /facturas/{uuid}.
@app.get("/facturas/borradores/eliminados", response_model=List[BorradorEliminadoResponse], dependencies=[Depends(require_internal_key)])
async def listar_borradores_eliminados(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(
        select(BorradorFacturaEliminado)
        .where(BorradorFacturaEliminado.negocio_id == negocio_id)
        .order_by(BorradorFacturaEliminado.eliminado_at.desc())
    )
    return result.scalars().all()

@app.get("/facturas/borradores/{borrador_id}", response_model=BorradorResponse, dependencies=[Depends(require_internal_key)])
async def obtener_borrador(
    borrador_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(BorradorFactura).where(BorradorFactura.id == borrador_id, BorradorFactura.negocio_id == negocio_id))
    b = result.scalar_one_or_none()
    if b is None:
        raise HTTPException(status_code=404, detail=f"Borrador {borrador_id} no encontrado")
    return b

# Motivos validos de borrado, se persisten en BorradorFacturaEliminado.motivo
# (String(20)). Cualquier otro valor que llegue por query se normaliza a
# "manual" - la auditoria de un borrado nunca debe tronar el borrado en si.
MOTIVOS_BORRADO_BORRADOR = {"manual", "post_timbrado"}


@app.delete("/facturas/borradores/{borrador_id}", dependencies=[Depends(require_internal_key)])
async def eliminar_borrador(
    borrador_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
    motivo: str = "manual",
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    motivo_normalizado = motivo if motivo in MOTIVOS_BORRADO_BORRADOR else "manual"
    result = await db.execute(select(BorradorFactura).where(BorradorFactura.id == borrador_id, BorradorFactura.negocio_id == negocio_id))
    b = result.scalar_one_or_none()
    if b is None:
        raise HTTPException(status_code=404, detail=f"Borrador {borrador_id} no encontrado")

    auditoria = BorradorFacturaEliminado(
        negocio_id=b.negocio_id,
        borrador_id_original=b.id,
        emisor_rfc=b.emisor_rfc,
        datos_json=b.datos_json,
        creado_por_rfc=b.creado_por_rfc,
        eliminado_por_rfc=x_usuario_rfc,
        motivo=motivo_normalizado,
        creado_en_original=b.created_at,
    )
    db.add(auditoria)
    await db.delete(b)
    await db.commit()
    return {"id": borrador_id, "eliminado": True}


# ─── Tickets de venta (POS ligero, zg5b-ZE) ─────────────────────────────────
# Existen ANTES de facturar - mismo espiritu que BorradorFactura, pero con
# validacion real de emisor (a diferencia de un borrador) porque el ticket
# si consume un folio real (SerieFolio serie="TICKET") y es lo que el
# cliente ve/escanea.

class TicketCreate(BaseModel):
    emisor_rfc: str
    conceptos: List[Concepto]

class TicketResponse(BaseModel):
    id: int
    negocio_id: int
    emisor_rfc: str
    folio: str
    fecha_hora: datetime
    conceptos: List[Concepto]
    total: float
    rfc_receptor: Optional[str] = None
    estado: str
    qr_token: str
    creado_por_rfc: Optional[str] = None
    created_at: datetime
    updated_at: datetime

@app.post("/facturas/tickets", response_model=TicketResponse, status_code=201, dependencies=[Depends(require_internal_key)])
async def crear_ticket(
    ticket: TicketCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)

    # Mismo guard que timbrar_factura: obtener_datos_emisor ya valida que
    # el emisor exista Y pertenezca a este negocio (400 si no, resuelto en
    # administracion). Extra: exige Activo (409 si no) - mismo criterio que
    # bloquea timbrado y todas las vistas del frontend, aplicado tambien a
    # la creacion de tickets del POS.
    datos_emisor = await obtener_datos_emisor(ticket.emisor_rfc, x_negocio_id)
    if datos_emisor.get("estado") != "Activo":
        raise HTTPException(
            status_code=409,
            detail=f"El emisor {ticket.emisor_rfc} esta Inactivo - no puede generar tickets.",
        )

    # Total SIEMPRE calculado en el servidor desde los conceptos, nunca
    # aceptado del cliente - mismo principio que Factura (satcfdi recalcula
    # el Total real desde los conceptos via construir_comprobante, no usa
    # nada que mande el frontend). TicketCreate no tiene campo total.
    total = sum(
        (Decimal(str(c.cantidad)) * Decimal(str(c.precio_unitario)) for c in ticket.conceptos),
        start=Decimal("0"),
    )

    # Folio propio, secuencia separada de Factura.folio via serie="TICKET"
    # (misma fila SerieFolio en administracion, UniqueConstraint(emisor_rfc,
    # serie) las separa sin tabla ni codigo nuevo) - wrapper ya existente,
    # mismo patron que usa timbrar_factura.
    folio = await obtener_siguiente_folio(ticket.emisor_rfc, "TICKET", x_negocio_id)

    # uuid4: aleatoriedad criptografica (122 bits), no secuencial - no debe
    # ser adivinable desde la URL publica del portal de autofacturacion
    # individual (a diferencia del folio, que si es predecible/secuencial).
    qr_token = uuid.uuid4().hex

    nuevo = TicketVenta(
        negocio_id=negocio_id,
        emisor_rfc=ticket.emisor_rfc,
        folio=folio,
        conceptos=json.dumps([c.dict() for c in ticket.conceptos]),
        total=total,
        estado="pendiente",
        qr_token=qr_token,
        creado_por_rfc=x_usuario_rfc,
    )
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)

    # Generacion de PDF con QR - best-effort (POS ligero, zg5b-ZE, punto 3).
    # Mismo principio que timbrar_factura con el guardado en BD tras un
    # timbrado real exitoso: el ticket YA existe (dato real, folio ya
    # consumido) - un fallo aqui (weasyprint, qrcode, o la subida a MinIO)
    # NO debe tumbar la respuesta ni el ticket ya creado. pdf_generado_at
    # queda en None si algo falla, para que un futuro GET .../pdf sepa
    # distinguir eso de "si se genero" antes de regenerar una URL firmada
    # hacia un objeto que podria no existir en MinIO.
    try:
        qr_url = f"{PUBLIC_APP_URL}/facturas/tickets/{nuevo.qr_token}"
        qr_buffer = io.BytesIO()
        qrcode.make(qr_url).save(qr_buffer, format="PNG")
        qr_data_uri = "data:image/png;base64," + base64.b64encode(qr_buffer.getvalue()).decode("ascii")

        template = _jinja_env.get_template("ticket_pdf.html")
        html_renderizado = template.render(
            razon_social=datos_emisor.get("razon_social", ticket.emisor_rfc),
            emisor_rfc=nuevo.emisor_rfc,
            folio=nuevo.folio,
            fecha_hora=nuevo.fecha_hora,
            conceptos=ticket.conceptos,
            total=float(nuevo.total),
            qr_data_uri=qr_data_uri,
        )
        pdf_bytes = weasyprint.HTML(string=html_renderizado).write_pdf()
        storage_client.subir_pdf(nuevo.qr_token, pdf_bytes)

        nuevo.pdf_generado_at = datetime.now()
        await db.commit()
        await db.refresh(nuevo)
    except Exception as e:
        logger.error("crear_ticket.pdf_fallo qr_token=%s error=%s", nuevo.qr_token, e)
        # Deja la sesion limpia: el ticket (commit anterior) ya es durable:
        # esto solo revierte el intento sin terminar de pdf_generado_at, para
        # que el commit ambiental de get_db() al final de la request no
        # tropiece con una transaccion a medias.
        await db.rollback()

    # Eco de ticket.conceptos (lo que mando el cliente), no un re-parseo del
    # JSON recien guardado en DB - evita un round-trip innecesario, mismo
    # contenido de todas formas.
    return TicketResponse(
        id=nuevo.id,
        negocio_id=nuevo.negocio_id,
        emisor_rfc=nuevo.emisor_rfc,
        folio=nuevo.folio,
        fecha_hora=nuevo.fecha_hora,
        conceptos=ticket.conceptos,
        total=float(nuevo.total),
        rfc_receptor=nuevo.rfc_receptor,
        estado=nuevo.estado,
        qr_token=nuevo.qr_token,
        creado_por_rfc=nuevo.creado_por_rfc,
        created_at=nuevo.created_at,
        updated_at=nuevo.updated_at,
    )


class TicketPublicoResponse(BaseModel):
    emisor_rfc: str
    folio: str
    fecha_hora: datetime
    conceptos: List[Concepto]
    total: float
    rfc_receptor: Optional[str] = None
    estado: str

# Publico de cara al usuario final: sin JWT de sesion (ver la ruta dedicada
# en api_gateway/main.py, que se registra antes de la ruta generica para no
# chocar con verify_token) - pero SI exige require_internal_key. Defensa en
# profundidad: la autorizacion real de negocio es el qr_token en si (uuid4,
# 122 bits de aleatoriedad), require_internal_key evita ademas que alguien
# le pegue directo al puerto interno de facturacion sin pasar por el Gateway.
# Response reducido a proposito (TicketPublicoResponse, no TicketResponse):
# SIN id/negocio_id/creado_por_rfc/qr_token/created_at/updated_at - datos
# internos que no le importan (o no debe ver) a quien escaneo el QR.
@app.get("/facturas/tickets/{qr_token}", response_model=TicketPublicoResponse, dependencies=[Depends(require_internal_key)])
async def obtener_ticket_publico(qr_token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TicketVenta).where(TicketVenta.qr_token == qr_token))
    ticket = result.scalar_one_or_none()
    # 404 generico sin importar si qr_token esta mal formado o simplemente
    # no existe - no hay validacion de formato por separado del lookup, para
    # no filtrar esa distincion a quien esta adivinando tokens.
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return TicketPublicoResponse(
        emisor_rfc=ticket.emisor_rfc,
        folio=ticket.folio,
        fecha_hora=ticket.fecha_hora,
        conceptos=[Concepto(**c) for c in json.loads(ticket.conceptos)],
        total=float(ticket.total),
        rfc_receptor=ticket.rfc_receptor,
        estado=ticket.estado,
    )


@app.get("/facturas", response_model=List[FacturaResponse], dependencies=[Depends(require_internal_key)])
async def listar_facturas(
    tipo: str = Query("generadas", enum=["generadas", "recibidas"]),
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    rfc_receptor: Optional[str] = None,
    emisor_rfc: Optional[str] = Query(None),
    page: int = 1,
    size: int = 50,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    # emisor_rfc opcional (#soporte multi-emisor, aun sin UI): si viene, se
    # valida ANTES de tocar la lista que ese emisor pertenezca al negocio
    # del caller - mismo mecanismo que ya usa timbrar_factura/cancelar
    # (obtener_datos_emisor -> 400 si el emisor es de otro negocio o no
    # existe, fail-closed). Sin esto, un negocio podria enumerar RFCs de
    # otro negocio y ver si le devuelve facturas. Si NO viene, comportamiento
    # identico al de siempre (todas las facturas del negocio) - compatible
    # con llamadores que no conocen este concepto todavia (ej. el bot).
    if emisor_rfc:
        await obtener_datos_emisor(emisor_rfc, x_negocio_id)
    stmt = select(Factura).where(Factura.negocio_id == negocio_id)
    if emisor_rfc:
        stmt = stmt.where(Factura.emisor_rfc == emisor_rfc)
    if estado:
        stmt = stmt.where(Factura.estado == estado)
    if fecha_desde:
        stmt = stmt.where(Factura.fecha_timbrado >= fecha_desde)
    if fecha_hasta:
        stmt = stmt.where(Factura.fecha_timbrado <= fecha_hasta)
    if rfc_receptor:
        stmt = stmt.where(Factura.receptor_rfc == rfc_receptor)
    stmt = stmt.order_by(Factura.fecha_timbrado.desc()).offset((page - 1) * size).limit(size)

    result = await db.execute(stmt)
    return [_factura_to_response(f) for f in result.scalars().all()]

@app.get("/facturas/costos-resumen", response_model=List[CostoResumenItem], dependencies=[Depends(require_internal_key)])
async def costos_resumen(
    emisor_rfc: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """
    Agrega el costo real de Finkok por timbre (#6), por mes y por emisor -
    parte "costos" de #11 (margen y costo de WhatsApp quedan fuera, sin
    implementar todavia). Debe ir ANTES de /facturas/{uuid} en las rutas:
    con un solo segmento de path ("costos-resumen"), {uuid} lo capturaria
    primero si esta ruta se registrara despues (FastAPI empata por orden
    de declaracion, no por especificidad).

    Incluye facturas canceladas: el costo ya se pago a Finkok al timbrar,
    cancelar despues no lo devuelve (ver comentario en Factura.costo_timbre).
    Excluye timbrados sin costo_timbre (nunca deberia pasar en timbrados
    exitosos, pero por si existe algun dato viejo de antes de #6).

    Fix critico (12 ago 2026): este endpoint nunca filtraba por negocio_id -
    agregaba el costo de TODOS los negocios de la BD sin distincion, y
    devolvia eso a cualquier caller autenticado, sin importar a que negocio
    perteneciera. Confirmado en vivo: una cuenta sin ningun emisor propio
    veia el costo real de EKU9003173C9 (negocio ajeno). Mismo patron
    fail-closed que el resto del archivo (requerir_negocio_id) y mismo
    mecanismo de validacion de emisor_rfc que ya usa
    contador_virtual_isr_resico (obtener_datos_emisor).
    """
    negocio_id = requerir_negocio_id(x_negocio_id)
    if emisor_rfc:
        await obtener_datos_emisor(emisor_rfc, x_negocio_id)

    periodo = func.to_char(Factura.fecha_timbrado, "YYYY-MM")
    stmt = (
        select(
            periodo.label("periodo"),
            Factura.emisor_rfc,
            func.count(Factura.id).label("num_timbres"),
            func.sum(Factura.costo_timbre).label("costo_total"),
        )
        .where(Factura.costo_timbre.is_not(None))
        .where(Factura.negocio_id == negocio_id)
        .group_by(periodo, Factura.emisor_rfc)
        .order_by(periodo.desc(), Factura.emisor_rfc)
    )
    if emisor_rfc:
        stmt = stmt.where(Factura.emisor_rfc == emisor_rfc)

    result = await db.execute(stmt)
    return [
        CostoResumenItem(
            periodo=r.periodo,
            emisor_rfc=r.emisor_rfc,
            num_timbres=r.num_timbres,
            costo_total=float(r.costo_total),
            costo_promedio=float(r.costo_total) / r.num_timbres,
        )
        for r in result.all()
    ]

@app.get("/facturas/contador-virtual/isr-resico", response_model=ContadorVirtualISRResicoResponse, dependencies=[Depends(require_internal_key)])
async def contador_virtual_isr_resico(
    emisor_rfc: str,
    anio: int,
    mes: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """
    Contador virtual (#40, Fase 1): estimador de ISR provisional mensual
    para RESICO Personas Fisicas, usando solo ingresos ya facturados.

    Alcance deliberado - NO calcula:
    - IVA ni retenciones de personas morales (fuera de alcance de esta fase).
    - Actividad Empresarial/Regimen General (necesitan CFDI recibidos que
      el sistema no tiene - ver tarjeta de seguimiento de Fase 2/3).

    Solo cuenta CFDI con metodo_pago="PUE" (se presume cobrado al timbrar).
    Los PPD se excluyen del calculo y se listan aparte - no hay complemento
    de pago en el sistema para saber cuando se cobraron de verdad.
    """
    datos_emisor = await obtener_datos_emisor(emisor_rfc, x_negocio_id)
    periodo = f"{anio:04d}-{mes:02d}"

    es_resico_pf = (
        datos_emisor["regimen_fiscal"] == REGIMEN_RESICO
        and len(emisor_rfc) == RFC_LEN_PERSONA_FISICA
    )
    if not es_resico_pf:
        if datos_emisor["regimen_fiscal"] != REGIMEN_RESICO:
            motivo = (
                f"Tu régimen fiscal ({datos_emisor['regimen_fiscal']}) no es RESICO Personas Físicas "
                f"({REGIMEN_RESICO}) - el contador virtual Fase 1 solo aplica a ese régimen."
            )
        else:
            motivo = (
                "El código 626 (RESICO) de tu RFC corresponde a un patrón de Persona Moral, "
                "no de Persona Física - este estimador solo aplica a RESICO Personas Físicas."
            )
        return ContadorVirtualISRResicoResponse(
            aplica=False, motivo_no_aplica=motivo, emisor_rfc=emisor_rfc, periodo=periodo,
        )

    mes_siguiente = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    stmt = (
        select(Factura)
        .where(
            Factura.emisor_rfc == emisor_rfc,
            Factura.estado == "Vigente",
            Factura.fecha_timbrado >= date(anio, mes, 1),
            Factura.fecha_timbrado < mes_siguiente,
        )
        .order_by(Factura.fecha_timbrado)
    )
    facturas = (await db.execute(stmt)).scalars().all()

    pue = [f for f in facturas if f.metodo_pago == "PUE"]
    ppd = [f for f in facturas if f.metodo_pago == "PPD"]

    ingreso_pue = sum((f.total for f in pue), Decimal("0"))

    tasa_aplicada = None
    excede_tope = False
    for limite, tasa in TABLA_ISR_RESICO_PF:
        if ingreso_pue <= limite:
            tasa_aplicada = tasa
            break
    if tasa_aplicada is None:
        # Excede el ultimo tramo ($291,666.67/mes, equivalente al tope
        # anual de RESICO de $3.5M) - se aplica la tasa mas alta como
        # referencia, mostrando la advertencia explicita.
        tasa_aplicada = TABLA_ISR_RESICO_PF[-1][1]
        excede_tope = True

    isr_estimado = (ingreso_pue * tasa_aplicada).quantize(Decimal("0.01"))

    return ContadorVirtualISRResicoResponse(
        aplica=True,
        emisor_rfc=emisor_rfc,
        periodo=periodo,
        ingreso_pue_incluido=float(ingreso_pue),
        tasa_aplicada=float(tasa_aplicada),
        isr_estimado=float(isr_estimado),
        excede_tope_mensual=excede_tope,
        facturas_pue_incluidas=[
            FacturaResumenLigero(folio=f.folio, uuid=f.uuid, receptor_rfc=f.receptor_rfc, total=float(f.total))
            for f in pue
        ],
        facturas_ppd_excluidas=[
            FacturaResumenLigero(folio=f.folio, uuid=f.uuid, receptor_rfc=f.receptor_rfc, total=float(f.total))
            for f in ppd
        ],
    )

async def obtener_factura_propia(uuid: str, negocio_id: int, db: AsyncSession) -> Factura:
    """
    Busca la Factura por uuid y valida pertenencia al negocio del caller
    en la misma consulta - 404 (no 403) tanto si no existe como si es de
    otro negocio, mismo patron que administracion, para no confirmarle a
    un caller no autorizado que el uuid si existe.
    """
    result = await db.execute(
        select(Factura).where(Factura.uuid == uuid, Factura.negocio_id == negocio_id)
    )
    factura = result.scalar_one_or_none()
    if factura is None:
        raise HTTPException(status_code=404, detail=f"Factura {uuid} no encontrada")
    return factura


@app.get("/facturas/{uuid}", dependencies=[Depends(require_internal_key)])
async def obtener_factura(
    uuid: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    factura = await obtener_factura_propia(uuid, negocio_id, db)
    return _factura_to_response(factura)

@app.get("/facturas/{uuid}/xml", dependencies=[Depends(require_internal_key)])
async def descargar_xml(
    uuid: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    await obtener_factura_propia(uuid, negocio_id, db)
    return {"url": storage_client.url_xml(uuid)}

@app.get("/facturas/{uuid}/pdf", dependencies=[Depends(require_internal_key)])
async def descargar_pdf(
    uuid: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    await obtener_factura_propia(uuid, negocio_id, db)
    return {"url": storage_client.url_pdf(uuid)}

# Catalogo real del SAT c_MotivoCancelacion (#5). "01" exige folio de
# sustitucion - el SAT rechaza la cancelacion sin el.
MOTIVOS_CANCELACION_VALIDOS = {"01", "02", "03", "04"}


@app.post("/facturas/{uuid}/cancelar", dependencies=[Depends(require_internal_key)])
async def cancelar_factura(
    uuid: str,
    req: CancelacionRequest,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    if req.motivo not in MOTIVOS_CANCELACION_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Motivo de cancelacion invalido: {req.motivo!r}. Debe ser uno de {sorted(MOTIVOS_CANCELACION_VALIDOS)}.",
        )
    if req.motivo == "01" and not req.uuid_sustitucion:
        raise HTTPException(
            status_code=400,
            detail="El motivo 01 (comprobante con errores con relacion) exige uuid_sustitucion - "
                   "el SAT rechaza la cancelacion sin el folio del CFDI que reemplaza al cancelado.",
        )

    # Verificacion de pertenencia ANTES de cualquier llamada real a Finkok
    # (cancel.wsdl) - fix critico (PASO 9, commit 294fc52): 404 si el uuid
    # no existe O es de otro negocio, para no confirmarle a un caller no
    # autorizado que existe.
    negocio_id = requerir_negocio_id(x_negocio_id)
    factura = await obtener_factura_propia(uuid, negocio_id, db)

    # get_signer_para_negocio (#42) ya verifica pertenencia del rfc al
    # negocio_id ANTES de tocar el CSD real (via obtener_datos_emisor,
    # dentro de _obtener_csd_cacheado) - con CSD reales por emisor ya no
    # existe la proteccion accidental que daba el CSD global unico de
    # antes (un solo emisor de prueba cargado siempre). El chequeo de
    # abajo queda como verificacion de sanidad, no como el control real.
    signer = await get_signer_para_negocio(factura.emisor_rfc, negocio_id)
    if factura.emisor_rfc != str(signer.rfc):
        raise HTTPException(
            status_code=400,
            detail=f"emisor_rfc de la factura ({factura.emisor_rfc}) no coincide con el RFC del CSD cargado ({signer.rfc})",
        )

    try:
        resultado = finkok_client.cancelar_factura(
            uuid=uuid,
            rfc_emisor=factura.emisor_rfc,
            # cancel.wsdl exige PEM, a diferencia de stamp/registration -
            # con DER falla con "wrong signature length" (probado hoy).
            cer_bytes=signer.certificate_bytes(encoding=Encoding.PEM),
            key_bytes_sin_cifrar=signer.key_bytes(encoding=Encoding.PEM),
            motivo=req.motivo,
            folio_sustitucion=req.uuid_sustitucion or "",
        )
    except finkok_client.FinkokError as e:
        raise HTTPException(status_code=502, detail=f"[{e.codigo}] {e.mensaje}")

    # El texto libre del PAC (estatus_cancelacion) varia entre llamadas -
    # confirmado hoy: dos cancelaciones reales con motivo "02" regresaron
    # mensajes distintos ("Cancelado sin aceptación" vs "Petición de
    # cancelación realizada exitosamente") para el MISMO estatus_uuid
    # ("201"). Guardarlo tal cual en Factura.estado rompe el filtro del
    # frontend (App.jsx compara con igualdad exacta contra "Cancelada").
    # Se guarda aparte, en detalle_pac, para auditoria/transparencia.
    # Factura.estado se normaliza a partir de estatus_uuid, que es el
    # campo estable - "201" es el unico codigo de exito confirmado en
    # pruebas reales; cualquier otro codigo no se traduce a ciegas.
    factura.detalle_pac = resultado["estatus_cancelacion"]
    factura.cancelado_por_rfc = x_usuario_rfc
    if resultado["estatus_uuid"] == "201":
        factura.estado = "Cancelada"
    else:
        logger.warning(
            "Cancelacion de %s: estatus_uuid=%s no reconocido (solo '201' esta "
            "confirmado en pruebas reales) - no se cambia el estado categorico "
            "automaticamente, revisar manualmente. Mensaje del PAC: %s",
            uuid, resultado["estatus_uuid"], resultado["estatus_cancelacion"],
        )
    await db.commit()

    return {
        "uuid": uuid,
        "estatus_uuid": resultado["estatus_uuid"],
        "estado_cancelacion": resultado["estatus_cancelacion"],
        "acuse": resultado["acuse"],
        "fecha": resultado["fecha"],
        "cod_estatus": resultado["cod_estatus"],
    }

@app.get("/health")
async def health():
    return {"service": "facturacion", "status": "ok", "version": "2.0.0"}
