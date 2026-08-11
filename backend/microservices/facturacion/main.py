import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Depends, Query, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
import httpx

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
from database import Factura, get_db, create_tables, stamp_head_si_es_ambiente_nuevo

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
# Clave servicio-a-servicio (#42) - mismo mecanismo que whatsapp_bot ya usa
# contra facturacion (ver whatsapp_bot/core/security.py). Distinta de
# X-Negocio-Id: esta protege endpoints que ningun negocio deberia poder
# alcanzar directo (aqui, pedir el CSD descifrado de un emisor), no rutas
# con contexto de tenant.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")

# Hallazgo (#42-cache): facturacion ya usaba INTERNAL_API_KEY como CLIENTE
# saliente (arriba, headers hacia administracion), pero nunca validaba un
# X-Internal-Key entrante en ninguno de sus propios endpoints - ni siquiera
# en /facturas/timbrar, que whatsapp_bot ya llama con ese header (queda
# anotado como hallazgo aparte, no se resuelve aqui). Mismo patron que
# administracion (require_internal_key) para el endpoint interno nuevo de
# invalidacion de cache.
_internal_api_key_header = APIKeyHeader(name="X-Internal-Key", auto_error=False)


def require_internal_key(api_key: Optional[str] = Security(_internal_api_key_header)) -> str:
    if not INTERNAL_API_KEY or not api_key or api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clave interna inválida o ausente")
    return api_key


def requerir_negocio_id(x_negocio_id: Optional[str]) -> int:
    """
    Mismo patron fail-closed que requerir_negocio_id() en administracion:
    sin fallback a un Negocio por defecto. Una llamada sin X-Negocio-Id
    valido (bypass del Gateway, header ausente por error) se rechaza en
    vez de asumir un Negocio - usado tanto en lecturas como en escrituras
    propias de facturacion (a diferencia de obtener_datos_emisor/
    obtener_siguiente_folio, que solo reenvian el header a administracion).
    """
    if not x_negocio_id:
        raise HTTPException(
            status_code=400,
            detail="Falta X-Negocio-Id - esta operacion requiere pasar por el Gateway con un token valido",
        )
    try:
        return int(x_negocio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Negocio-Id invalido")


async def obtener_datos_emisor(rfc: str, x_negocio_id: Optional[str] = None) -> dict:
    """Consulta administracion por regimen fiscal y CP del emisor. Si el
    emisor no esta registrado ahi, es un error real (no hay a que hacer
    fallback) - no se puede timbrar a nombre de un emisor sin dar de alta.

    x_negocio_id (#15) se reenvia tal cual llego a este servicio - viene del
    Gateway (derivado del JWT ya verificado del usuario que llamo a este
    endpoint) y administracion lo exige para no dejar que un Negocio consulte
    (o firme a nombre de) el emisor de otro adivinando el RFC."""
    headers = {"X-Negocio-Id": x_negocio_id} if x_negocio_id else {}
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

    receptor = Receptor(
        rfc=factura.receptor.rfc,
        nombre=factura.receptor.nombre,
        domicilio_fiscal_receptor=domicilio_fiscal_receptor,
        regimen_fiscal_receptor=factura.receptor.regimen_fiscal,
        uso_cfdi=factura.receptor.uso_cfdi,
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


@app.post("/facturas/timbrar", response_model=FacturaResponse, status_code=201)
async def timbrar_factura(
    factura: FacturaCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
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

@app.get("/facturas", response_model=List[FacturaResponse])
async def listar_facturas(
    tipo: str = Query("generadas", enum=["generadas", "recibidas"]),
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    rfc_receptor: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    stmt = select(Factura).where(Factura.negocio_id == negocio_id)
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

@app.get("/facturas/costos-resumen", response_model=List[CostoResumenItem])
async def costos_resumen(emisor_rfc: Optional[str] = None, db: AsyncSession = Depends(get_db)):
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
    """
    periodo = func.to_char(Factura.fecha_timbrado, "YYYY-MM")
    stmt = (
        select(
            periodo.label("periodo"),
            Factura.emisor_rfc,
            func.count(Factura.id).label("num_timbres"),
            func.sum(Factura.costo_timbre).label("costo_total"),
        )
        .where(Factura.costo_timbre.is_not(None))
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

@app.get("/facturas/contador-virtual/isr-resico", response_model=ContadorVirtualISRResicoResponse)
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


@app.get("/facturas/{uuid}")
async def obtener_factura(
    uuid: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    factura = await obtener_factura_propia(uuid, negocio_id, db)
    return _factura_to_response(factura)

@app.get("/facturas/{uuid}/xml")
async def descargar_xml(
    uuid: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    await obtener_factura_propia(uuid, negocio_id, db)
    return {"url": storage_client.url_xml(uuid)}

@app.get("/facturas/{uuid}/pdf")
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


@app.post("/facturas/{uuid}/cancelar")
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

@app.get("/facturas/reporte/mensual")
async def reporte_mensual(anio: int = 2025, mes: int = Query(ge=1, le=12)):
    return {
        "anio": anio,
        "mes": mes,
        "total_emitido": 302450.00,
        "total_cancelado": 9800.00,
        "count_vigentes": 4,
        "count_canceladas": 1,
    }

@app.get("/health")
async def health():
    return {"service": "facturacion", "status": "ok", "version": "2.0.0"}
