# ─── services/administracion/main.py ──────────────────────────────────────────
# Microservicio de Administración
# Puerto: 8002
# Responsabilidades: Emisores, Clientes, Series, Configuración
#
# Emisores y Clientes: persistencia real (SQLAlchemy + Postgres) - tarea #4.
# Series/folios consecutivos y Configuración: siguen mock, fuera de alcance
# de esta tarea (folios consecutivos es #12, tarea aparte).
# ──────────────────────────────────────────────────────────────────────────────
import base64
import binascii
import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional, List

import httpx
from cryptography.hazmat.primitives.serialization import load_der_private_key
from cryptography.x509 import load_der_x509_certificate
from fastapi import FastAPI, File, Header, HTTPException, Query, Depends, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Efirma, Emisor, Cliente, Negocio, Notificacion, SerieFolio, SolicitudDescarga, PaqueteDescarga, get_db, create_tables, stamp_head_si_es_ambiente_nuevo
from database import _fernet_efirma  # cifrado explicito de la e.firma (ver database.py)
from csd_rfc import extraer_rfc_de_certificado, extraer_vigencia_hasta_de_certificado
from logo_storage import subir_logo, validar_logo
from sat_descarga_client import (
    BloqueoPrevioError,
    construir_fiel,
    descargar_paquetes,
    solicitar_descarga,
    tick_verificar_solicitudes,
)
from shared.negocio_id import requerir_negocio_id
from shared.internal_key import INTERNAL_API_KEY, require_internal_key

# ─── Autenticacion interna servicio-a-servicio ─────────────────────────────────
# Mismo patron que whatsapp_bot/core/security.py (X-Internal-Key). Protege
# especificamente el endpoint que devuelve el CSD ya descifrado (#42) - el
# dato mas sensible del sistema. NUNCA loguear el resultado de este endpoint.
# require_internal_key() extraida a backend/shared/internal_key.py (14 ago
# 2026, refactor/shared-internal-key, ver import arriba) - antes vivia
# copiada aqui, identica a la de facturacion/ia.


# Invalidacion de cache (hallazgo #42-cache): facturacion cachea el CSD
# descifrado en memoria del proceso, sin TTL - al rotar un CSD aqui via PUT
# /admin/emisores/{rfc}, facturacion seguiria usando el CSD viejo hasta
# reiniciarse solo, salvo que se le avise explicitamente. Sin depends_on en
# docker-compose a proposito: esta llamada se tolera si facturacion esta
# caido (ver actualizar_emisor), nunca debe bloquear una rotacion de CSD
# valida solo porque facturacion no esta disponible en ese momento.
FACTURACION_URL = os.environ.get("FACTURACION_URL", "http://facturacion:8001")

PLAN_LIMITS = {
    "emprendedor": {"emisores": 1, "facturas_mes": 25},
    "basico": {"emisores": 1, "facturas_mes": 50},
    "contador": {"emisores": 5, "facturas_mes": 100},
    "despacho": {"emisores": 10, "facturas_mes": 500},
}


async def _invalidar_csd_cache_en_facturacion(rfc: str) -> bool:
    """
    True si facturacion confirmo la invalidacion, False ante cualquier
    falla (timeout, conexion rechazada, HTTP != 200) - nunca lanza, el CSD
    ya se guardo en BD y eso no se revierte por esto.
    """
    if not INTERNAL_API_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{FACTURACION_URL}/internal/csd-cache/invalidar/{rfc}",
                headers={"X-Internal-Key": INTERNAL_API_KEY},
            )
        return resp.status_code == 200
    except httpx.RequestError:
        return False


async def _obtener_resumen_facturas_mes(negocio_id: int, emisor_rfc: Optional[str] = None) -> Optional[dict]:
    """None si no se pudo obtener (sin INTERNAL_API_KEY, timeout, conexion
    rechazada, o status != 200) - a diferencia de _contar_facturas_del_emisor
    (que fail-cierra porque protege un DELETE), aqui la falla se degrada:
    el endpoint publico (obtener_resumen_negocio) devuelve los campos
    dependientes de facturacion como null + una advertencia, en vez de
    tumbar toda la respuesta con un 500 generico (zg6k9Pw, Dashboard 'Mi
    cuenta') - limite_plan sigue disponible porque vive en esta misma BD.

    emisor_rfc opcional (dashboard multi-emisor, GET
    /admin/negocios/{id}/emisores-resumen): filtra el resumen a un solo
    emisor en vez de todo el negocio - mismo endpoint de facturacion,
    mismo criterio de degradacion."""
    if not INTERNAL_API_KEY:
        return None
    params = {"emisor_rfc": emisor_rfc} if emisor_rfc else {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{FACTURACION_URL}/facturas/resumen-mes",
                params=params,
                headers={"X-Internal-Key": INTERNAL_API_KEY, "X-Negocio-Id": str(negocio_id)},
            )
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.RequestError:
        return None


async def _contar_tickets_pendientes_consolidacion(emisor_rfc: str, periodicidad: str) -> Optional[int]:
    """Recordatorio de consolidacion pendiente (g7imYM pieza 2). Pregunta a
    facturacion cuantos TicketVenta 'pendiente' tiene este emisor con
    fecha_hora ANTERIOR al inicio del periodo actual (ayer si es diario,
    mes pasado si es mensual) - facturacion resuelve ese limite con
    _resolver_periodo_actual, la MISMA funcion que ya usa
    consolidar_publico_general y el scheduler de cierre automatico, asi que
    el limite nunca se duplica ni se desincroniza entre los 3 lugares.

    None si no se pudo obtener (mismo criterio de degradacion que
    _obtener_resumen_facturas_mes) - listar_notificaciones simplemente no
    genera el recordatorio esta vez, sin romper el resto de la respuesta."""
    if not INTERNAL_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{FACTURACION_URL}/facturas/tickets/pendientes-antes-de-periodo",
                params={"emisor_rfc": emisor_rfc, "periodicidad": periodicidad},
                headers={"X-Internal-Key": INTERNAL_API_KEY},
            )
        if resp.status_code != 200:
            return None
        return resp.json().get("n_pendientes")
    except httpx.RequestError:
        return None


def _calcular_porcentaje_cancelacion(facturas_mes: int, canceladas_mes: int) -> float:
    """0.0 si no hubo facturas este mes - evita ZeroDivisionError. El
    frontend decide el empty state mirando facturas_mes == 0 (no este
    campo): 0.0 aqui significa "sin cancelaciones", no "sin datos"."""
    if facturas_mes <= 0:
        return 0.0
    return round((canceladas_mes / facturas_mes) * 100, 1)


async def _contar_facturas_del_emisor(rfc: str, negocio_id: int) -> Optional[int]:
    """None si no se pudo verificar (timeout/error) - en ese caso el
    DELETE debe FALLAR CERRADO (rechazar el borrado), no asumir 0 facturas
    por una falla de red. Distinto criterio a la invalidacion de cache
    (que sí puede degradar silenciosamente) porque aquí una falla mal
    manejada podría borrar un emisor con historial real."""
    if not INTERNAL_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{FACTURACION_URL}/facturas/count",
                params={"emisor_rfc": rfc},
                headers={"X-Internal-Key": INTERNAL_API_KEY, "X-Negocio-Id": str(negocio_id)},
            )
        if resp.status_code != 200:
            return None
        return resp.json().get("total_facturas")
    except httpx.RequestError:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await stamp_head_si_es_ambiente_nuevo()
    yield


# Mismo patron que facturacion (ver comentario ahi) - sin esto, uvicorn solo
# configura sus propios loggers y los mensajes INFO/WARNING se descartan en
# silencio. Necesario para _csd_es_copia_de_efirma() (ver abajo): una
# excepcion inesperada ahi debe quedar auditada, no desaparecer.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("administracion")

app = FastAPI(title="CFDI – Servicio de Administración", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])

# ─── Modelos ───────────────────────────────────────────────────────────────────

class EmisorCreate(BaseModel):
    razon_social: str
    rfc: str
    regimen_fiscal: str
    codigo_postal: str
    csd_cert_base64: str  # Certificado .cer en base64
    csd_key_base64: str   # Llave privada .key en base64
    csd_password: str

class EmisorUpdateParcial(BaseModel):
    # Todos opcionales a proposito: PATCH solo toca lo que venga, a
    # diferencia de PUT /admin/emisores/{rfc} (actualizar_emisor) que exige
    # el body completo de EmisorCreate, CSD incluido. Este endpoint es
    # deliberadamente ajeno al CSD - nunca lo recibe, nunca lo toca.
    razon_social: Optional[str] = None
    regimen_fiscal: Optional[str] = None
    codigo_postal: Optional[str] = None
    # "Inactivar" un emisor = PATCH estado="Inactivo". El conteo del plan
    # (crear_emisor) ya filtra por estado == "Activo", asi que inactivar
    # libera un cupo sin tocar esa logica. Reemplaza al DELETE cuando el
    # emisor tiene facturas timbradas y no se puede borrar.
    estado: Optional[str] = None
    # Consolidacion periodica de Publico en General (g5b-kc) - "diario" |
    # "mensual" para habilitar, None explicito en el body para deshabilitar
    # (volver al comportamiento individual). Omitir el campo del body no la
    # toca (exclude_unset=True abajo).
    periodicidad_consolidacion: Optional[str] = None
    # Color de marca del ticket impreso (g7VQns) - hex de 7 caracteres
    # (#RRGGBB), None explicito en el body para quitarlo (vuelve a caer al
    # color del negocio/default). Omitir el campo del body no lo toca
    # (exclude_unset=True abajo) - mismo criterio que periodicidad_consolidacion.
    color_primario: Optional[str] = None
    # Cierre automatico de consolidacion (g7imYM pieza 3) - string "HH:MM"
    # (24h), None explicito en el body para desactivarlo (vuelve a ser
    # 100% manual). Omitir el campo del body no lo toca (exclude_unset=True
    # abajo) - mismo criterio que periodicidad_consolidacion/color_primario.
    hora_cierre_automatico: Optional[str] = None

class EmisorResponse(BaseModel):
    rfc: str
    razon_social: str
    regimen_fiscal: str
    codigo_postal: str
    estado: str
    negocio_id: int
    created_at: datetime
    creado_por_rfc: Optional[str] = None
    modificado_por_rfc: Optional[str] = None
    # Consolidacion periodica de Publico en General (g5b-kc) - "diario" |
    # "mensual" | None (None = deshabilitada, default para todo emisor
    # existente/nuevo hasta que alguien la habilite explicitamente via PATCH).
    periodicidad_consolidacion: Optional[str] = None
    # Color de marca del ticket impreso (g7VQns, 18 sep 2026) - None para
    # todo emisor existente/nuevo hasta que alguien lo configure via PATCH.
    color_primario: Optional[str] = None
    # Cierre automatico de consolidacion (g7imYM pieza 3, 18 sep 2026) -
    # string "HH:MM" (convertido desde time en _emisor_to_response), None
    # para todo emisor existente/nuevo hasta que alguien lo configure.
    hora_cierre_automatico: Optional[str] = None
    # None en crear_emisor/listar (no aplica); True/False solo en
    # actualizar_emisor (PUT) - indica si facturacion confirmo haber
    # invalidado su cache del CSD viejo. False no es un error del PUT en si
    # (el CSD ya quedo guardado en BD), pero avisa explicitamente a quien
    # rota el CSD que facturacion podria seguir usando el CSD anterior
    # hasta que se reinicie o se reintente la invalidacion.
    cache_invalidado: Optional[bool] = None
    # Deliberado: nunca se regresan csd_cert_base64/csd_key_base64/csd_password
    # en ninguna respuesta de la API, ni siquiera al crear.

class EmisorCSDDescifrado(BaseModel):
    # Uso exclusivo servicio-a-servicio (#42) - protegido con
    # require_internal_key. Nunca exponer en una ruta que el frontend o el
    # gateway puedan alcanzar.
    rfc: str
    csd_cert_base64: str
    csd_key_base64: str
    csd_password: str

class EfirmaCreate(BaseModel):
    rfc_titular: str
    cert_base64: str   # .cer DER en base64 (certificado PUBLICO)
    key_base64: str    # .key DER en base64, SIN cifrar - se cifra en el endpoint
    password: str      # contrasena de la e.firma, SIN cifrar - se cifra en el endpoint
    # Consentimiento expreso ESPECIFICO para el tratamiento de la e.firma
    # (LFPDPPP, dato sensible). Obligatorio == True; si no, 422 antes de
    # tocar el archivo. Ver Efirma.consentimiento_at en database.py.
    acepto_tratamiento_efirma: bool

class EfirmaResponse(BaseModel):
    # Deliberado: NUNCA se exponen cert_base64/key_base64_cifrado/password_cifrado
    # en ninguna respuesta - el material sensible no sale del backend.
    id: int
    rfc_titular: str
    negocio_id: int
    vigencia_desde: date
    vigencia_hasta: date
    estado: str
    consentimiento_at: Optional[datetime] = None
    created_at: datetime

class EfirmaReemplazar(BaseModel):
    # Reemplazo/renovacion explicita de una e.firma ya custodiada (PUT
    # /admin/efirmas/{rfc_titular}). El rfc_titular viaja en la ruta, no en
    # el body - por eso este modelo NO lo repite. La e.firma nueva se valida
    # con exactamente el mismo criterio que el alta (misma tripleta
    # cert+key+password, mismo gate de consentimiento) y hereda un
    # consentimiento_at propio y fresco: renovar es un acto de tratamiento
    # nuevo sobre un dato sensible nuevo.
    cert_base64: str   # .cer DER en base64 (certificado PUBLICO) de la e.firma nueva
    key_base64: str    # .key DER en base64, SIN cifrar - se cifra en el endpoint
    password: str      # contrasena de la e.firma nueva, SIN cifrar - se cifra en el endpoint
    acepto_tratamiento_efirma: bool

class SolicitudDescargaCreate(BaseModel):
    # tipo: 'emitidas' | 'recibidas'. 'ambas' (dos solicitudes al SAT) queda
    # fuera de Fase 1 - se rechaza con 422 (ver crear_solicitud_descarga).
    tipo: str
    fecha_desde: date
    fecha_hasta: date

class SolicitudDescargaResponse(BaseModel):
    # Nunca expone material de la e.firma. Refleja la fila local; el token
    # del SAT no se persiste ni se devuelve.
    id: int
    efirma_id: int
    negocio_id: int
    tipo: str
    fecha_desde: date
    fecha_hasta: date
    id_solicitud_sat: Optional[str] = None
    # 1 Aceptada · 2 EnProceso · 3 Terminada · 4 Error · 5 Rechazada · 6 Vencida
    estado_solicitud: int
    cod_estatus: Optional[str] = None
    # CodigoEstadoSolicitud del SAT (distinto de cod_estatus). Ej.: "5004"
    # dentro de un estado_solicitud=5 = consulta vacia, NO un rechazo real.
    codigo_estado_solicitud: Optional[str] = None
    mensaje_sat: Optional[str] = None
    numero_cfdis: Optional[int] = None
    created_at: datetime

class NegocioCreate(BaseModel):
    nombre: str
    plan: str = "basico"

class NegocioResponse(BaseModel):
    id: int
    nombre: str
    plan: str
    fecha_alta: datetime
    estado: str
    # Derivados de PLAN_LIMITS[plan], no columnas de BD: se calculan en
    # _negocio_to_response. Los expone el GET para que el frontend (Mi perfil,
    # zg5z04A) los muestre sin duplicar la tabla PLAN_LIMITS. Consumidores
    # previos (facturacion.obtener_plan_negocio) solo leen .plan, campos
    # nuevos no los afectan.
    limite_emisores: int
    limite_facturas_mes: int

class NegocioResumenResponse(BaseModel):
    # Dashboard 'Mi cuenta' (zg6k9Pw). facturas_mes/porcentaje_cancelacion_mes
    # None cuando facturacion no respondio (ver advertencias) - limite_plan
    # NUNCA es None, sale de PLAN_LIMITS (esta misma BD, sin llamada externa).
    facturas_mes: Optional[int] = None
    limite_plan: int
    porcentaje_cancelacion_mes: Optional[float] = None
    # Sin infraestructura de wallet/timbres todavia (zg3mu7Q y relacionados,
    # confirmado por grep - no hay tabla ni columna de saldo en el repo).
    # Siempre null hasta que eso se construya; el campo ya esta en el
    # contrato para no romper el frontend cuando se implemente.
    timbres_disponibles: Optional[int] = None
    advertencias: List[str] = []


class EmisorResumenItem(BaseModel):
    # Dashboard multi-emisor (vigencia CSD + concentracion de facturas):
    # un item por emisor Activo del negocio. facturas_mes None si
    # facturacion no respondio (degradado, mismo criterio que
    # NegocioResumenResponse) - vigencia_csd_hasta/dias_restantes None si
    # el CSD nunca se pudo parsear (ej. GWT010101AA1, certificado corrupto
    # real conocido) o esta pendiente de backfill - nunca inventados.
    #
    # vigencia_efirma_hasta/dias_restantes_efirma (hallazgo real del 15-sep:
    # un usuario subio su e.firma en el formulario de CSD sin que nada en
    # pantalla lo hiciera evidente - CSD y e.firma son certificados
    # DISTINTOS por diseno del SAT, tabla Efirma separada de Emisor, ver
    # database.py) - se muestran como dos filas independientes en el
    # frontend precisamente para que esa confusion sea visible de inmediato
    # (ej. ambas vigencias identicas = señal de alerta). None si el RFC no
    # tiene ninguna e.firma con estado="Activo" registrada - nunca inventado.
    rfc: str
    razon_social: str
    facturas_mes: Optional[int] = None
    vigencia_csd_hasta: Optional[date] = None
    dias_restantes: Optional[int] = None
    vigencia_efirma_hasta: Optional[date] = None
    dias_restantes_efirma: Optional[int] = None
    # csd_es_efirma_duplicada (hallazgo del 15-sep, refuerzo del banner de
    # "misma fecha"): True cuando el CSD registrado es BYTE-POR-BYTE el
    # mismo archivo que la e.firma (comparado por SHA-256 sobre los bytes
    # ya descifrados de ambos certificados) - en ese caso vigencia_csd_hasta
    # se fuerza a None aqui mismo (el CSD "vigente" es en realidad el
    # archivo equivocado, no debe mostrarse como valido) para que el
    # frontend lo trate como "CSD no registrado", no como un CSD real con
    # coincidencia de fecha casual (ese otro caso sigue con el banner
    # existente, son mutuamente excluyentes por construccion: si esto es
    # True, vigencia_csd_hasta ya viene en None).
    csd_es_efirma_duplicada: bool = False
    estado: str


class NotificacionResponse(BaseModel):
    id: int
    negocio_id: int
    tipo: str
    mensaje: str
    periodo: str
    leida: bool
    created_at: datetime


def _notificacion_to_response(n: Notificacion) -> NotificacionResponse:
    return NotificacionResponse(
        id=n.id, negocio_id=n.negocio_id, tipo=n.tipo, mensaje=n.mensaje,
        periodo=n.periodo, leida=n.leida, created_at=n.created_at,
    )


UMBRAL_PLAN_CERCA_LIMITE = 0.80
TIPO_PLAN_CERCA_LIMITE = "plan_cerca_limite"
# Recordatorio de consolidacion pendiente (g7imYM pieza 2) - el "tipo" real
# guardado en BD lleva el RFC del emisor pegado como sufijo (ver
# listar_notificaciones), porque el UNIQUE(negocio_id, tipo, periodo) de la
# tabla no distingue emisor por si solo y un negocio puede tener varios
# emisores con periodicidad_consolidacion, cada uno con su propio backlog
# independiente - sin el sufijo, el ON CONFLICT DO NOTHING del segundo
# emisor pisaria (no crearia) el recordatorio del primero.
TIPO_CONSOLIDACION_PENDIENTE = "consolidacion_pendiente"


class ClienteCreate(BaseModel):
    emisor_rfc: str
    nombre: str
    rfc: str
    # email opcional: el guardado automatico de receptores desde
    # NuevaFactura.jsx (zg5Lf6Q) no captura correo. La columna se relajo
    # a nullable en la migracion c176eed5fc42.
    email: Optional[str] = None
    telefono: Optional[str] = None
    regimen_fiscal: str = "601"
    uso_cfdi_default: str = "G03"
    domicilio_fiscal: str
    credito_limite: float = 0.0

class ClienteResponse(BaseModel):
    id: int
    emisor_rfc: str
    nombre: str
    rfc: str
    email: Optional[str] = None
    telefono: Optional[str] = None
    regimen_fiscal: str
    uso_cfdi_default: str
    domicilio_fiscal: str
    credito_limite: float

class SerieCreate(BaseModel):
    serie: str  # Ej: "A", "B", "FAC"
    descripcion: str
    folio_inicial: int = 1
    emisor_rfc: str

class SerieResponse(BaseModel):
    emisor_rfc: str
    serie: str
    ultimo_folio: int

class ConfiguracionUpdate(BaseModel):
    # HALLAZGO (14 sep 2026, investigacion previa a zg2mOhE): los 6 campos
    # de este modelo se descartaban en silencio - PUT /admin/config
    # devolvia {"actualizado": True} sin persistir nada, endpoint sin
    # X-Internal-Key ni X-Negocio-Id. zg2mOhE arregla SOLO logo_url y
    # color_primario (white-label, por negocio). pac_url/pac_usuario/
    # pac_password/storage_bucket SIGUEN sin persistir a proposito -
    # fuera de alcance de esta tarjeta, documentado como hallazgo aparte,
    # no silenciado sin dejar rastro.
    pac_url: Optional[str] = None
    pac_usuario: Optional[str] = None
    pac_password: Optional[str] = None
    storage_bucket: Optional[str] = None
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None


class ConfiguracionResponse(BaseModel):
    pac_url: str
    storage_bucket: str
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None


def _emisor_to_response(e: Emisor, cache_invalidado: Optional[bool] = None) -> EmisorResponse:
    return EmisorResponse(
        rfc=e.rfc,
        razon_social=e.razon_social,
        regimen_fiscal=e.regimen_fiscal,
        codigo_postal=e.codigo_postal,
        estado=e.estado,
        negocio_id=e.negocio_id,
        created_at=e.created_at,
        creado_por_rfc=e.creado_por_rfc,
        modificado_por_rfc=e.modificado_por_rfc,
        periodicidad_consolidacion=e.periodicidad_consolidacion,
        color_primario=e.color_primario,
        hora_cierre_automatico=e.hora_cierre_automatico.strftime("%H:%M") if e.hora_cierre_automatico else None,
        cache_invalidado=cache_invalidado,
    )


def _negocio_to_response(n: Negocio) -> NegocioResponse:
    limites = PLAN_LIMITS.get(n.plan, PLAN_LIMITS["basico"])
    return NegocioResponse(
        id=n.id, nombre=n.nombre, plan=n.plan, fecha_alta=n.fecha_alta, estado=n.estado,
        limite_emisores=limites["emisores"], limite_facturas_mes=limites["facturas_mes"],
    )


def _cliente_to_response(c: Cliente) -> ClienteResponse:
    return ClienteResponse(
        id=c.id,
        emisor_rfc=c.emisor_rfc,
        nombre=c.nombre,
        rfc=c.rfc,
        email=c.email,
        telefono=c.telefono,
        regimen_fiscal=c.regimen_fiscal,
        uso_cfdi_default=c.uso_cfdi_default,
        domicilio_fiscal=c.domicilio_fiscal,
        credito_limite=float(c.credito_limite),
    )


# ─── Emisores ──────────────────────────────────────────────────────────────────

@app.post(
    "/admin/emisores",
    response_model=EmisorResponse,
    status_code=201,
    dependencies=[Depends(require_internal_key)],
)
async def crear_emisor(
    emisor: EmisorCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """Registra un nuevo emisor real. El CSD se guarda tal cual se recibe
    (base64) - cifrado con KMS queda pendiente, es una decision de
    seguridad aparte.

    negocio_id (#15) se toma de X-Negocio-Id (inyectado por el Gateway a
    partir del JWT ya verificado, ver #48) - nunca de un campo que el
    cliente pudiera enviar en el body, para que un usuario no pueda crear
    un emisor a nombre de un Negocio ajeno."""
    existente = await db.execute(select(Emisor).where(Emisor.rfc == emisor.rfc))
    if existente.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"El emisor {emisor.rfc} ya existe")

    negocio_id = requerir_negocio_id(x_negocio_id)

    negocio_result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = negocio_result.scalar_one_or_none()
    if negocio is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    limite_emisores = PLAN_LIMITS.get(negocio.plan, PLAN_LIMITS["basico"])["emisores"]
    emisores_activos = await db.scalar(
        select(func.count(Emisor.id)).where(
            Emisor.negocio_id == negocio_id,
            Emisor.estado == "Activo",
        )
    ) or 0
    if emisores_activos >= limite_emisores:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El plan {negocio.plan} permite hasta {limite_emisores} emisor(es). "
                "Actualiza tu plan para agregar otro emisor."
            ),
        )

    # Validacion CSD<->RFC (ver investigacion en csd_rfc.py): el RFC
    # declarado en el body debe coincidir con el RFC real embebido en el
    # certificado subido - sin esto, un usuario podia declarar cualquier
    # RFC y el backend nunca lo confirmaba contra el CSD real (a
    # diferencia de facturacion, que ya rechaza esto al timbrar). 422 (no
    # 500) tanto si no coincide como si el certificado no se puede leer.
    try:
        cert_bytes = base64.b64decode(emisor.csd_cert_base64)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"csd_cert_base64 invalido: {e}")
    try:
        rfc_del_certificado = extraer_rfc_de_certificado(cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if emisor.rfc.upper() != rfc_del_certificado:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El RFC declarado ({emisor.rfc}) no coincide con el RFC "
                f"del certificado CSD cargado ({rfc_del_certificado})"
            ),
        )

    # Vigencia del CSD (dashboard multi-emisor) - se puebla al vuelo, mismo
    # cert_bytes ya decodificado arriba. No bloquea el alta si falla: el
    # cert ya demostro ser parseable (extraer_rfc_de_certificado lo hizo
    # segundos antes, sobre el mismo objeto) asi que en la practica esto no
    # deberia fallar de forma independiente - pero se degrada a NULL en vez
    # de 422 por si acaso, la vigencia es informativa, no un gate de alta.
    try:
        vigencia_csd_hasta = extraer_vigencia_hasta_de_certificado(cert_bytes)
    except ValueError:
        vigencia_csd_hasta = None

    nuevo = Emisor(
        negocio_id=negocio_id,
        rfc=emisor.rfc,
        razon_social=emisor.razon_social,
        regimen_fiscal=emisor.regimen_fiscal,
        codigo_postal=emisor.codigo_postal,
        csd_cert_base64=emisor.csd_cert_base64,
        csd_key_base64=emisor.csd_key_base64,
        csd_password=emisor.csd_password,
        vigencia_csd_hasta=vigencia_csd_hasta,
        creado_por_rfc=x_usuario_rfc,
    )
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)
    return _emisor_to_response(nuevo)


# ─── Negocios (#15) ─────────────────────────────────────────────────────────────

@app.post(
    "/admin/negocios",
    response_model=NegocioResponse,
    status_code=201,
    dependencies=[Depends(require_internal_key)],
)
async def crear_negocio(negocio: NegocioCreate, db: AsyncSession = Depends(get_db)):
    """
    Usado por el flujo de registro real (POST /auth/registro en
    auth_usuarios, #15) - "crear cuenta" da de alta un Negocio nuevo antes
    de crear su primer usuario admin, en vez de un usuario suelto sin
    tenant.

    X-Internal-Key (20 ago 2026, tarjeta 2mUws - cierre del gap real de
    administracion): decision tomada. Este endpoint NO es publico como
    login/registro (el navegador nunca lo llama directo) - es una llamada
    servicio-a-servicio que hoy solo hace auth_usuarios.registro() desde su
    backend, sin pasar por el Gateway. Sin esta proteccion, cualquiera con
    acceso a la red interna de Docker podia crear Negocios arbitrarios
    llamando directo a administracion:8002/admin/negocios, sin ninguna
    autenticacion. Se agrego el header en auth_usuarios (mismo cambio, ver
    ese archivo) para no repetir la regresion ya documentada en esta misma
    tarjeta (cierre del 18 ago: obtener_datos_emisor en facturacion se
    protegio sin actualizar a su llamador).

    X-Negocio-Id NO aplica aqui: este es el endpoint que CREA un Negocio -
    no existe todavia un negocio_id previo contra el cual validar
    pertenencia (es el genesis del tenant, no una operacion dentro de uno
    ya existente). Sigue disponible para alta manual directa via curl con
    la clave interna, sin restriccion adicional de negocio.
    """
    nuevo = Negocio(nombre=negocio.nombre, plan=negocio.plan)
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)
    return _negocio_to_response(nuevo)


@app.get(
    "/admin/negocios/{negocio_id}",
    response_model=NegocioResponse,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_negocio(
    negocio_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """
    Un Negocio solo puede consultar su propia informacion (#15) - antes no
    exigia X-Negocio-Id, asi que cualquiera podia enumerar negocios ajenos
    (nombre, plan, estado) con solo iterar ids secuenciales. 404 (no 403)
    si el id pedido no es el propio, mismo criterio que el resto de lecturas.
    """
    caller_negocio_id = requerir_negocio_id(x_negocio_id)
    if negocio_id != caller_negocio_id:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = result.scalar_one_or_none()
    if negocio is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    return _negocio_to_response(negocio)


@app.get(
    "/admin/negocios/{negocio_id}/resumen",
    response_model=NegocioResumenResponse,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_resumen_negocio(
    negocio_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """Dashboard 'Mi cuenta' (zg6k9Pw). Mismo aislamiento self-only que
    GET /admin/negocios/{negocio_id} (404, no 403, si negocio_id no es el
    propio). Debe ir ANTES de cualquier ruta generica que capture un solo
    segmento bajo /admin/negocios/{negocio_id}/... - hoy no existe otra,
    pero mismo cuidado ya documentado en costos-resumen de facturacion.

    Agregador con degradacion parcial: si facturacion no responde,
    facturas_mes/porcentaje_cancelacion_mes salen null con una advertencia
    en vez de tumbar el endpoint completo (limite_plan siempre esta
    disponible, no depende de facturacion)."""
    caller_negocio_id = requerir_negocio_id(x_negocio_id)
    if negocio_id != caller_negocio_id:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = result.scalar_one_or_none()
    if negocio is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")

    limites = PLAN_LIMITS.get(negocio.plan, PLAN_LIMITS["basico"])
    resumen_facturas = await _obtener_resumen_facturas_mes(negocio_id)

    if resumen_facturas is None:
        return NegocioResumenResponse(
            limite_plan=limites["facturas_mes"],
            advertencias=["no se pudo obtener datos de facturación"],
        )

    facturas_mes = resumen_facturas.get("facturas_mes", 0)
    canceladas_mes = resumen_facturas.get("canceladas_mes", 0)
    return NegocioResumenResponse(
        facturas_mes=facturas_mes,
        limite_plan=limites["facturas_mes"],
        porcentaje_cancelacion_mes=_calcular_porcentaje_cancelacion(facturas_mes, canceladas_mes),
    )


def _csd_es_copia_de_efirma(emisor: Emisor, efirma: Efirma) -> bool:
    """
    True si el CSD registrado para este emisor es BYTE-POR-BYTE el mismo
    archivo que su e.firma (SHA-256 sobre los bytes YA DESCIFRADOS del
    certificado, no sobre el base64 crudo ni sobre el blob cifrado) -
    refuerzo del banner de "misma fecha" (dashboard multi-emisor): dos
    certificados legitimos pueden coincidir en fecha de vencimiento por
    casualidad (mismo tramite el mismo dia), pero nunca en el hash
    completo del archivo salvo que sea literalmente el mismo archivo
    subido dos veces (caso real: RAHP7112093H0, confirmado antes a mano).

    emisor.csd_cert_base64 ya llega descifrado de forma transparente por
    el TypeDecorator CifradoFernet (ver database.py) - efirma.cert_base64
    nunca se cifro en primer lugar (es el certificado PUBLICO, ver
    docstring de Efirma). Ninguno de los dos requiere una llamada de
    descifrado aparte de leer el atributo del ORM - se reutiliza tal cual.

    Nunca lanza - pero el except ahora es acotado, no un "except Exception"
    generico (verificado contra el caso real antes de escribir esto, no
    adivinado):
      - base64.b64decode(...) es la UNICA linea que puede fallar aqui
        (hashlib.sha256 nunca lanza sobre bytes, sea cual sea su
        contenido) - dispara binascii.Error si el string no es base64
        valido (padding/caracteres invalidos), o TypeError si el campo no
        es str/bytes (defensivo, csd_cert_base64/cert_base64 son NOT NULL
        en el schema, pero no cuesta cubrirlo).
      - Confirmado explicitamente contra GWT010101AA1 (el certificado
        corrupto real conocido): su csd_cert_base64 SI es base64 valido
        (decodifica a bytes reales, aunque cortos) - lo que esta corrupto
        es el DER resultante (falla al parsearlo como x509 en
        extraer_vigencia_hasta_de_certificado, una funcion DISTINTA que
        esta SI hace ese parseo). Esta funcion nunca parsea DER, solo
        hashea bytes crudos - GWT010101AA1 no dispara ninguna excepcion
        aqui, solo produce un hash que no coincide (False por comparacion
        normal, no por el except).
      - Cualquier excepcion FUERA de (binascii.Error, TypeError) es
        genuinamente inesperada - se registra con logger.warning(...)
        (RFC del emisor incluido) antes de degradar a False, para que no
        desaparezca en silencio si algun dia pasa algo que hoy no se
        preveo.
    """
    try:
        cert_csd = base64.b64decode(emisor.csd_cert_base64)
        cert_efirma = base64.b64decode(efirma.cert_base64)
        return hashlib.sha256(cert_csd).digest() == hashlib.sha256(cert_efirma).digest()
    except (binascii.Error, TypeError):
        return False
    except Exception:
        logger.warning(
            "Fallo inesperado comparando CSD vs e.firma por hash para el emisor %s",
            emisor.rfc, exc_info=True,
        )
        return False


@app.get(
    "/admin/negocios/{negocio_id}/emisores-resumen",
    response_model=List[EmisorResumenItem],
    dependencies=[Depends(require_internal_key)],
)
async def obtener_emisores_resumen(
    negocio_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """Dashboard multi-emisor (vigencia CSD + concentracion de facturas por
    emisor) - pensado para negocios con mas de 1 emisor Activo, aunque el
    endpoint no lo exige (el frontend decide si mostrar la seccion segun
    len(emisores) > 1, ver Perfil.jsx). Mismo self-only 404 que
    obtener_resumen_negocio/listar_notificaciones.

    Orden: mismo criterio "propio RFC primero" que listar_emisores() (ver
    _orden_emisores_propio_primero) - antes esta query no tenia ORDER BY
    en absoluto (orden incidental de Postgres, no deliberado), asi que el
    emisor del propio usuario podia no aparecer primero aqui aunque si lo
    hiciera en /admin/emisores.

    Un GET por emisor a facturacion (resumen-mes filtrado) - hoy son a lo
    sumo unos pocos emisores por negocio (limite_emisores del plan mas
    alto es 10), secuencial es suficiente, sin necesidad de paralelizar."""
    caller_negocio_id = requerir_negocio_id(x_negocio_id)
    if negocio_id != caller_negocio_id:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    negocio_result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    if negocio_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")

    emisores_activos = (
        await db.execute(
            select(Emisor)
            .where(Emisor.negocio_id == negocio_id, Emisor.estado == "Activo")
            .order_by(*_orden_emisores_propio_primero(x_usuario_rfc))
        )
    ).scalars().all()

    items = []
    for e in emisores_activos:
        resumen_facturas = await _obtener_resumen_facturas_mes(negocio_id, emisor_rfc=e.rfc)
        facturas_mes = resumen_facturas.get("facturas_mes") if resumen_facturas is not None else None
        dias_restantes = (e.vigencia_csd_hasta - date.today()).days if e.vigencia_csd_hasta else None

        # e.firma es una tabla APARTE (rfc_titular, referencia suave - ver
        # database.py) - se consulta por RFC, no por negocio_id, porque una
        # e.firma puede pertenecer a un negocio_id distinto al del Emisor
        # (caso real ya observado: RAHP7112093H0 tiene su Emisor en
        # negocio 11 pero su e.firma quedo con negocio_id=1). Solo la fila
        # Activa cuenta (misma semantica que "el CSD vigente hoy").
        efirma = (
            await db.execute(
                select(Efirma).where(Efirma.rfc_titular == e.rfc, Efirma.estado == "Activo")
            )
        ).scalars().first()
        vigencia_efirma_hasta = efirma.vigencia_hasta if efirma else None
        dias_restantes_efirma = (vigencia_efirma_hasta - date.today()).days if vigencia_efirma_hasta else None

        # Refuerzo por hash (ver _csd_es_copia_de_efirma) - solo tiene
        # sentido evaluarlo si hay e.firma registrada para este RFC.
        csd_es_efirma_duplicada = False
        if efirma is not None and _csd_es_copia_de_efirma(e, efirma):
            csd_es_efirma_duplicada = True
            vigencia_csd_hasta = None
            dias_restantes = None
        else:
            vigencia_csd_hasta = e.vigencia_csd_hasta

        items.append(EmisorResumenItem(
            rfc=e.rfc,
            razon_social=e.razon_social,
            facturas_mes=facturas_mes,
            vigencia_csd_hasta=vigencia_csd_hasta,
            dias_restantes=dias_restantes,
            vigencia_efirma_hasta=vigencia_efirma_hasta,
            dias_restantes_efirma=dias_restantes_efirma,
            csd_es_efirma_duplicada=csd_es_efirma_duplicada,
            estado=e.estado,
        ))
    return items


class NegocioBrandingResponse(BaseModel):
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None


@app.get(
    "/admin/negocios/{negocio_id}/branding",
    response_model=NegocioBrandingResponse,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_branding_negocio(negocio_id: int, db: AsyncSession = Depends(get_db)):
    """Portal de autofacturacion publica (zg2mOhE) - SIN self-only a
    proposito, a diferencia de GET /admin/negocios/{id}: lo llama
    facturacion servicio-a-servicio para enriquecer TicketPublicoResponse
    (pagina publica sin sesion, el visitante no tiene un negocio_id
    propio contra el cual validar). Expone SOLO logo_url/color_primario -
    nunca nombre/plan/estado ni nada mas, mismo criterio de "response
    reducido" que TicketPublicoResponse en facturacion.

    negocio_id inexistente -> campos null (no 404): el portal publico
    debe caer al fallback de marca CFDI-AES, nunca romperse por esto."""
    result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = result.scalar_one_or_none()
    if negocio is None:
        return NegocioBrandingResponse()
    return NegocioBrandingResponse(logo_url=negocio.logo_url, color_primario=negocio.color_primario)


@app.get(
    "/admin/negocios/{negocio_id}/notificaciones",
    response_model=List[NotificacionResponse],
    dependencies=[Depends(require_internal_key)],
)
async def listar_notificaciones(
    negocio_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """Alertas proactivas (zg6k9Ok, primera implementacion: plan cerca del
    limite; g7imYM pieza 2, segunda implementacion: consolidacion
    pendiente). Generacion LAZY - sin scheduler propio de administracion
    (esta consulta sigue siendo el unico disparador de AMBAS alertas; el
    scheduler que si existe desde g7imYM pieza 3 vive en facturacion y es
    para otra cosa - consolidar automaticamente, no para generar estas
    notificaciones). Reutiliza _obtener_resumen_facturas_mes / _contar_
    tickets_pendientes_consolidacion (mismo criterio: helpers dedicados en
    vez de duplicar logica de negocio dentro del endpoint).

    Si facturacion no responde, simplemente no se evalua ese umbral esta
    vez (no es un error - la proxima consulta lo vuelve a intentar, mismo
    criterio de degradacion en ambas alertas)."""
    caller_negocio_id = requerir_negocio_id(x_negocio_id)
    if negocio_id != caller_negocio_id:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = result.scalar_one_or_none()
    if negocio is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")

    resumen_facturas = await _obtener_resumen_facturas_mes(negocio_id)
    if resumen_facturas is not None:
        limite = PLAN_LIMITS.get(negocio.plan, PLAN_LIMITS["basico"])["facturas_mes"]
        facturas_mes = resumen_facturas.get("facturas_mes", 0)
        if limite > 0 and (facturas_mes / limite) >= UMBRAL_PLAN_CERCA_LIMITE:
            periodo = datetime.now().strftime("%Y-%m")
            porcentaje = round((facturas_mes / limite) * 100)
            mensaje = (
                f"Has usado el {porcentaje}% de tus facturas incluidas este mes "
                f"({facturas_mes} de {limite})."
            )
            # ON CONFLICT DO NOTHING (no SELECT-then-INSERT): el UNIQUE
            # (negocio_id, tipo, periodo) es lo que hace esto seguro ante 2
            # requests concurrentes al mismo endpoint - un SELECT previo
            # dejaria una ventana de carrera real entre el SELECT y el
            # INSERT (ver test que reproduce esto con 2 llamadas reales).
            stmt = pg_insert(Notificacion).values(
                negocio_id=negocio_id,
                tipo=TIPO_PLAN_CERCA_LIMITE,
                mensaje=mensaje,
                periodo=periodo,
                leida=False,
            ).on_conflict_do_nothing(
                index_elements=["negocio_id", "tipo", "periodo"],
            )
            await db.execute(stmt)
            await db.commit()

    # Recordatorio de consolidacion pendiente (g7imYM pieza 2) - mismo
    # patron LAZY de arriba, un emisor a la vez. Solo emisores Activos con
    # periodicidad_consolidacion configurada son candidatos (los demas ni
    # tienen consolidacion habilitada, nada que recordar).
    emisores_consolidacion = (
        await db.execute(
            select(Emisor).where(
                Emisor.negocio_id == negocio_id,
                Emisor.estado == "Activo",
                Emisor.periodicidad_consolidacion.isnot(None),
            )
        )
    ).scalars().all()
    for emisor in emisores_consolidacion:
        n_pendientes = await _contar_tickets_pendientes_consolidacion(
            emisor.rfc, emisor.periodicidad_consolidacion
        )
        if n_pendientes:  # None (facturacion no respondio) o 0 -> nada que avisar
            periodo = datetime.now().strftime("%Y-%m")
            plural = "s" if n_pendientes != 1 else ""
            mensaje = (
                f"Tienes {n_pendientes} ticket{plural} pendiente{plural} de consolidar "
                f"en {emisor.razon_social}."
            )
            # Mismo tipo por emisor (ver TIPO_CONSOLIDACION_PENDIENTE) - el
            # sufijo _{rfc} es lo que hace que el UNIQUE(negocio_id, tipo,
            # periodo) trate a cada emisor como un evento independiente.
            stmt = pg_insert(Notificacion).values(
                negocio_id=negocio_id,
                tipo=f"{TIPO_CONSOLIDACION_PENDIENTE}_{emisor.rfc}",
                mensaje=mensaje,
                periodo=periodo,
                leida=False,
            ).on_conflict_do_nothing(
                index_elements=["negocio_id", "tipo", "periodo"],
            )
            await db.execute(stmt)
            await db.commit()

    result = await db.execute(
        select(Notificacion)
        .where(Notificacion.negocio_id == negocio_id)
        .order_by(Notificacion.created_at.desc())
    )
    return [_notificacion_to_response(n) for n in result.scalars().all()]


@app.post(
    "/admin/negocios/{negocio_id}/notificaciones/{notif_id}/marcar-leida",
    response_model=NotificacionResponse,
    dependencies=[Depends(require_internal_key)],
)
async def marcar_notificacion_leida(
    negocio_id: int,
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    caller_negocio_id = requerir_negocio_id(x_negocio_id)
    if negocio_id != caller_negocio_id:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")

    result = await db.execute(
        select(Notificacion).where(
            Notificacion.id == notif_id,
            Notificacion.negocio_id == negocio_id,
        )
    )
    notificacion = result.scalar_one_or_none()
    if notificacion is None:
        raise HTTPException(status_code=404, detail=f"Notificación {notif_id} no encontrada")

    notificacion.leida = True
    await db.commit()
    await db.refresh(notificacion)
    return _notificacion_to_response(notificacion)


def _orden_emisores_propio_primero(x_usuario_rfc: Optional[str]):
    """Orden compuesto de 3 niveles, COMPARTIDO entre listar_emisores()
    (GET /admin/emisores) y obtener_emisores_resumen() (GET
    /admin/negocios/{id}/emisores-resumen) - extraido aqui para no
    duplicar la regla en dos endpoints (commits 299438131a81.../
    7974dd66945e...):
      1. El emisor cuyo RFC coincide con el del usuario logueado (persona
         fisica que es tambien su propio emisor, ej. Pedro/RAHP7112093H0
         en negocio 11) - siempre primero, sin importar estado.
      2. Activo antes que Inactivo.
      3. created_at desc como desempate final.

    x_usuario_rfc=None (o sin match) hace que el nivel 1 compile a
    "emisores.rfc IS NULL" - siempre falso (rfc es NOT NULL) - cae limpio
    a los niveles 2/3, mismo caso borde ya verificado en listar_emisores.
    """
    return (
        desc(Emisor.rfc == x_usuario_rfc),
        desc(Emisor.estado == "Activo"),
        Emisor.created_at.desc(),
    )


@app.get(
    "/admin/emisores",
    response_model=List[EmisorResponse],
    dependencies=[Depends(require_internal_key)],
)
async def listar_emisores(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """Orden compuesto de 3 niveles:
      1. El emisor cuyo RFC coincide con el del usuario logueado (persona
         fisica que es tambien su propio emisor, ej. Pedro/RAHP7112093H0
         en negocio 11) - siempre primero, sin importar estado.
      2. Activo antes que Inactivo (regla previa, sin cambio).
      3. created_at desc como desempate final (regla previa, sin cambio).

    x_usuario_rfc ya llegaba inyectado por el Gateway desde el JWT en
    cualquier request autenticado (igual que en crear_emisor) - este
    endpoint simplemente no lo leia todavia.

    Caso borde verificado por compilacion Y contra Postgres real antes de
    este cambio: si x_usuario_rfc es None (o no coincide con ningun
    emisor), "Emisor.rfc == None" compila a "emisores.rfc IS NULL" -
    siempre falso (rfc es NOT NULL), asi que el nivel 1 no afecta nada y
    cae limpio a las reglas 2/3 de siempre. No es un caso especial con
    manejo aparte, es la misma expresion evaluando a falso en todas las
    filas."""
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(
        select(Emisor)
        .where(Emisor.negocio_id == negocio_id)
        .order_by(*_orden_emisores_propio_primero(x_usuario_rfc))
    )
    return [_emisor_to_response(e) for e in result.scalars().all()]


@app.get(
    "/admin/emisores/consolidacion-automatica",
    response_model=List[EmisorResponse],
    dependencies=[Depends(require_internal_key)],
)
async def listar_emisores_consolidacion_automatica(db: AsyncSession = Depends(get_db)):
    """Listado GLOBAL (TODOS los negocios, sin X-Negocio-Id) de emisores con
    cierre automatico habilitado - g7imYM pieza 3. Consumido UNICAMENTE por
    el scheduler de facturacion (job cada 5 min, ver _job_cierre_automatico_
    consolidacion en ese servicio) - nunca por el frontend ni por ningun
    caller con sesion de usuario real. Por eso NO exige X-Negocio-Id: el
    scheduler no representa a un negocio en particular, evalua a todos de
    una sola pasada (evita N llamadas, una por negocio, desde facturacion).

    Solo Activo Y con AMBOS periodicidad_consolidacion Y
    hora_cierre_automatico configurados - un emisor con solo uno de los 2
    nunca aparece aqui, asi el scheduler no tiene que repetir ese chequeo:
    "aparece en esta lista" ya IMPLICA "es candidato a evaluar"."""
    result = await db.execute(
        select(Emisor).where(
            Emisor.estado == "Activo",
            Emisor.periodicidad_consolidacion.isnot(None),
            Emisor.hora_cierre_automatico.isnot(None),
        )
    )
    return [_emisor_to_response(e) for e in result.scalars().all()]

@app.get(
    "/admin/emisores/{rfc}",
    response_model=EmisorResponse,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_emisor(
    rfc: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    # 404 en vez de 403 (#15) - si el RFC existe pero es de otro Negocio, se
    # trata igual que si no existiera. Un 403 confirmaria que el recurso
    # existe en algun lado, aunque sea ajeno - fuga de informacion menor.
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc, Emisor.negocio_id == negocio_id))
    emisor = result.scalar_one_or_none()
    if emisor is None:
        raise HTTPException(status_code=404, detail=f"Emisor {rfc} no encontrado")
    return _emisor_to_response(emisor)

@app.get(
    "/admin/emisores/{rfc}/csd-descifrado",
    response_model=EmisorCSDDescifrado,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_csd_descifrado(rfc: str, db: AsyncSession = Depends(get_db)):
    """
    Uso exclusivo servicio-a-servicio (#42) - protegido con X-Internal-Key.
    Devuelve el CSD ya descifrado (CifradoFernet lo descifra de forma
    transparente al leer el modelo, ver database.py / #34).

    Alcance de #42: solo este endpoint. facturacion NO lo consume todavia -
    sigue firmando con los archivos estaticos de certs_test/, sin cambios.
    Conectar facturacion a este endpoint es un paso aparte, deliberadamente
    fuera de alcance hoy por el riesgo de romper el timbrado real que ya
    funciona.
    """
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc))
    emisor = result.scalar_one_or_none()
    if emisor is None:
        raise HTTPException(status_code=404, detail=f"Emisor {rfc} no encontrado")
    return EmisorCSDDescifrado(
        rfc=emisor.rfc,
        csd_cert_base64=emisor.csd_cert_base64,
        csd_key_base64=emisor.csd_key_base64,
        csd_password=emisor.csd_password,
    )

@app.put(
    "/admin/emisores/{rfc}",
    response_model=EmisorResponse,
    dependencies=[Depends(require_internal_key)],
)
async def actualizar_emisor(
    rfc: str,
    emisor: EmisorCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    # El mas grave de los IDOR (#15) - sin este check, cualquiera podia
    # editar el CSD de un emisor ajeno adivinando el RFC. 404 (no 403) si no
    # pertenece al Negocio del caller, mismo criterio que el resto.
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc, Emisor.negocio_id == negocio_id))
    existente = result.scalar_one_or_none()
    if existente is None:
        raise HTTPException(status_code=404, detail=f"Emisor {rfc} no encontrado")

    # Misma validacion CSD<->RFC que crear_emisor() (ver csd_rfc.py) -
    # hallazgo de ayer: el gap se cerro en el POST pero nunca se aplico
    # aqui, con lo que rotar el CSD via PUT seguia aceptando cualquier
    # certificado sin verificar que correspondiera al RFC de este emisor
    # (rfc = el del path, inmutable en este endpoint - el campo emisor.rfc
    # del body se ignora, igual que ya lo ignoraba el resto de esta
    # funcion antes de este cambio).
    try:
        cert_bytes = base64.b64decode(emisor.csd_cert_base64)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"csd_cert_base64 invalido: {e}")
    try:
        rfc_del_certificado = extraer_rfc_de_certificado(cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if rfc.upper() != rfc_del_certificado:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El RFC declarado ({rfc}) no coincide con el RFC "
                f"del certificado CSD cargado ({rfc_del_certificado})"
            ),
        )

    # Vigencia del CSD nuevo (dashboard multi-emisor) - mismo criterio de
    # degradacion a NULL que crear_emisor, ver comentario ahi.
    try:
        vigencia_csd_hasta = extraer_vigencia_hasta_de_certificado(cert_bytes)
    except ValueError:
        vigencia_csd_hasta = None

    existente.razon_social = emisor.razon_social
    existente.regimen_fiscal = emisor.regimen_fiscal
    existente.codigo_postal = emisor.codigo_postal
    existente.csd_cert_base64 = emisor.csd_cert_base64
    existente.csd_key_base64 = emisor.csd_key_base64
    existente.csd_password = emisor.csd_password
    existente.vigencia_csd_hasta = vigencia_csd_hasta
    existente.modificado_por_rfc = x_usuario_rfc
    await db.commit()
    await db.refresh(existente)

    # El CSD ya quedo guardado en BD (lo de arriba no se revierte por lo
    # que pase aqui abajo) - si facturacion no confirma la invalidacion,
    # cache_invalidado=False avisa explicitamente a quien roto el CSD que
    # facturacion podria seguir timbrando con el CSD anterior hasta que se
    # reinicie o se reintente. Nunca fallar en silencio.
    cache_invalidado = await _invalidar_csd_cache_en_facturacion(rfc)
    return _emisor_to_response(existente, cache_invalidado=cache_invalidado)


@app.patch(
    "/admin/emisores/{rfc}",
    response_model=EmisorResponse,
    dependencies=[Depends(require_internal_key)],
)
async def actualizar_emisor_parcial(
    rfc: str,
    emisor: EmisorUpdateParcial,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """Actualiza SOLO campos simples (razon_social/regimen_fiscal/
    codigo_postal) sin tocar el CSD en absoluto - para eso sigue existiendo
    el PUT de arriba (actualizar_emisor), que exige CSD completo a proposito
    (confirmacion explicita antes de rotar un secreto). Mismo IDOR check que
    el PUT: 404 (no 403) si el emisor no pertenece al Negocio del caller."""
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc, Emisor.negocio_id == negocio_id))
    existente = result.scalar_one_or_none()
    if existente is None:
        raise HTTPException(status_code=404, detail=f"Emisor {rfc} no encontrado")

    datos = emisor.model_dump(exclude_unset=True)
    if datos.get("estado") and datos["estado"] not in ("Activo", "Inactivo"):
        raise HTTPException(status_code=422, detail="estado debe ser 'Activo' o 'Inactivo'")
    if (
        "periodicidad_consolidacion" in datos
        and datos["periodicidad_consolidacion"] is not None
        and datos["periodicidad_consolidacion"] not in ("diario", "mensual")
    ):
        raise HTTPException(status_code=422, detail="periodicidad_consolidacion debe ser 'diario', 'mensual', o null")
    # Reusa _validar_color_primario (definida mas abajo en este archivo,
    # junto a /admin/config - Python resuelve la referencia al llamarse,
    # no al definirse, asi que el orden de aparicion en el modulo no
    # importa) - mismo regex/mensaje de error que ya usa el color del
    # negocio, para no tener 2 fuentes de verdad de "que es un hex valido"
    # en el mismo servicio.
    if "color_primario" in datos and datos["color_primario"] is not None:
        _validar_color_primario(datos["color_primario"])
    # Reusa _validar_hora_cierre_automatico (misma seccion que
    # _validar_color_primario, definida mas abajo) - valida el formato Y
    # devuelve el objeto time ya parseado, que se usa mas abajo al aplicar
    # el campo (la columna es Time, no String - un setattr con el string
    # crudo "23:30" rompiria en el proximo db.commit()).
    hora_cierre_parseada: Optional[time] = None
    if "hora_cierre_automatico" in datos and datos["hora_cierre_automatico"] is not None:
        hora_cierre_parseada = _validar_hora_cierre_automatico(datos["hora_cierre_automatico"])

    # Reactivar un emisor (Inactivo -> Activo) vuelve a consumir un cupo del
    # plan: aplica la MISMA validacion de limite que crear_emisor (mismo
    # PLAN_LIMITS, mismo 409). Sin esto el plan se podia exceder por la puerta
    # de atras: inactivar A -> alta de B -> reactivar A (bug zg5sS8g). Solo se
    # valida en la transicion REAL hacia "Activo": inactivar, un no-op
    # Activo->Activo, o tocar cualquier otro campo NO se bloquea. El COUNT va
    # ANTES del setattr (para leer el estado real en BD, sin el cambio
    # propuesto) y excluye explicitamente este mismo emisor.
    if datos.get("estado") == "Activo" and existente.estado != "Activo":
        negocio_result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
        negocio = negocio_result.scalar_one_or_none()
        if negocio is None:
            raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
        limite_emisores = PLAN_LIMITS.get(negocio.plan, PLAN_LIMITS["basico"])["emisores"]
        emisores_activos = await db.scalar(
            select(func.count(Emisor.id)).where(
                Emisor.negocio_id == negocio_id,
                Emisor.estado == "Activo",
                Emisor.rfc != rfc,
            )
        ) or 0
        if emisores_activos >= limite_emisores:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El plan {negocio.plan} permite hasta {limite_emisores} emisor(es). "
                    "Actualiza tu plan para continuar."
                ),
            )

    for campo, valor in datos.items():
        # Unico campo del PATCH cuyo tipo en BD (Time) no coincide con el
        # tipo que llega en el body (str "HH:MM") - se sustituye por el
        # objeto time ya validado/parseado arriba, en vez del string crudo.
        if campo == "hora_cierre_automatico":
            valor = hora_cierre_parseada
        setattr(existente, campo, valor)
    existente.modificado_por_rfc = x_usuario_rfc
    await db.commit()
    await db.refresh(existente)
    return _emisor_to_response(existente)


@app.delete("/admin/emisores/{rfc}", dependencies=[Depends(require_internal_key)])
async def eliminar_emisor(
    rfc: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """Mismo patron que eliminar_cliente (IDOR check + 404 + hard delete),
    con el chequeo adicional de facturas asociadas antes de borrar."""
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc, Emisor.negocio_id == negocio_id))
    existente = result.scalar_one_or_none()
    if existente is None:
        raise HTTPException(status_code=404, detail=f"Emisor {rfc} no encontrado")

    total_facturas = await _contar_facturas_del_emisor(rfc, negocio_id)
    if total_facturas is None:
        raise HTTPException(
            status_code=503,
            detail="No se pudo verificar si el emisor tiene facturas asociadas. Intenta de nuevo.",
        )
    if total_facturas > 0:
        raise HTTPException(
            status_code=409,
            detail=f"El emisor {rfc} tiene {total_facturas} factura(s) timbrada(s) - no se puede eliminar. Usa 'Inactivar' en su lugar.",
        )

    await db.delete(existente)
    await db.commit()
    return {"rfc": rfc, "eliminado": True}


# ─── e.firmas (FIEL) - custodia para descarga masiva SAT (zg55DWY) ─────────────

@dataclass
class _EfirmaValidada:
    """Resultado de validar la tripleta cert+key+password de una e.firma.

    Solo metadatos ya verificados - NO lleva material sensible (la key y la
    password las cifra cada endpoint a partir de su propio payload).
    """
    rfc_del_cert: str
    negocio_id: int
    vigencia_desde: date
    vigencia_hasta: date


def _validar_material_efirma(
    *,
    rfc_declarado: str,
    cert_base64: str,
    key_base64: str,
    password: str,
    acepto_tratamiento_efirma: bool,
    x_negocio_id: Optional[str],
) -> _EfirmaValidada:
    """Validacion compartida por el alta (POST) y el reemplazo (PUT) de e.firma.

    Cubre los pasos 1-8 del diseno acordado (zg55DWY), en orden de menor a
    mayor costo y con el gate legal primero. Toda la validacion de la
    tripleta cert+key+password es LOCAL, sin una sola llamada al SAT:

      1. consentimiento expreso (bool)  -> 422
      2. negocio_id del Gateway (fail-closed)
      3. base64 decode de cert y key    -> 422
      4. parse del cert + RFC embebido (csd_rfc, ya probado con esta FIEL) -> 422
      5. RFC declarado == RFC del cert   -> 422  (el 'declarado' es el body en
         el alta y el path param en el reemplazo)
      6. parse+descifrado de la key con la password (cryptography, NO
         cfdiclient.Fiel: Fiel no valida el par cert<->key ni distingue
         password-mala de key-ajena) + chequeo del par cert<->key -> 422
      7. vigencia extraida del cert (not_valid_before/after)
      8. rechazo si ya vencio            -> 422

    Devuelve _EfirmaValidada (rfc_del_cert, negocio_id, vigencia_desde,
    vigencia_hasta). La unicidad / el reemplazo transaccional y el cifrado
    son responsabilidad de cada endpoint (pasos 9-12), porque difieren.
    """
    # 1. Consentimiento - ANTES de tocar el archivo.
    if not acepto_tratamiento_efirma:
        raise HTTPException(
            status_code=422,
            detail="Se requiere aceptar expresamente el tratamiento de la e.firma para poder custodiarla.",
        )

    # 2. negocio_id (fail-closed, mismo patron que crear_emisor).
    negocio_id = requerir_negocio_id(x_negocio_id)

    # 3. base64 decode.
    try:
        cert_bytes = base64.b64decode(cert_base64)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"cert_base64 invalido: {e}")
    try:
        key_bytes = base64.b64decode(key_base64)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"key_base64 invalido: {e}")

    # 4. Parse del certificado + RFC embebido (reusa csd_rfc, ya probado
    #    contra la FIEL real de persona fisica en el Paso 1 del plan).
    try:
        rfc_del_cert = extraer_rfc_de_certificado(cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Certificado invalido: {e}")

    # 5. RFC declarado == RFC del certificado.
    if rfc_declarado.upper() != rfc_del_cert:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El RFC declarado ({rfc_declarado}) no coincide con el RFC "
                f"del certificado ({rfc_del_cert})."
            ),
        )

    # 6. Parse+descifrado de la llave con la password (LOCAL) + par cert<->key.
    #    cryptography distingue los casos que cfdiclient.Fiel no:
    #      - password ausente para key cifrada -> TypeError
    #      - password incorrecta / key corrupta -> ValueError
    #      - key valida que NO corresponde al cert -> se detecta comparando
    #        public_numbers() (Fiel construye sin error en ese caso).
    try:
        priv = load_der_private_key(key_bytes, password=password.encode())
    except TypeError:
        raise HTTPException(status_code=422, detail="La llave privada esta cifrada y requiere contrasena.")
    except ValueError:
        raise HTTPException(status_code=422, detail="Contrasena incorrecta o llave privada invalida.")

    cert = load_der_x509_certificate(cert_bytes)
    if cert.public_key().public_numbers() != priv.public_key().public_numbers():
        raise HTTPException(
            status_code=422,
            detail="La llave privada no corresponde al certificado (par cert/key distinto).",
        )

    # 7. Vigencia: se EXTRAE del certificado, no la captura el usuario.
    vigencia_desde = cert.not_valid_before_utc.date()
    vigencia_hasta = cert.not_valid_after_utc.date()

    # 8. Rechazo si ya vencio.
    if vigencia_hasta < date.today():
        raise HTTPException(
            status_code=422,
            detail=f"La e.firma vencio el {vigencia_hasta}; no puede custodiarse para descarga masiva.",
        )

    return _EfirmaValidada(
        rfc_del_cert=rfc_del_cert,
        negocio_id=negocio_id,
        vigencia_desde=vigencia_desde,
        vigencia_hasta=vigencia_hasta,
    )


def _efirma_to_response(e: Efirma) -> EfirmaResponse:
    return EfirmaResponse(
        id=e.id,
        rfc_titular=e.rfc_titular,
        negocio_id=e.negocio_id,
        vigencia_desde=e.vigencia_desde,
        vigencia_hasta=e.vigencia_hasta,
        estado=e.estado,
        consentimiento_at=e.consentimiento_at,
        created_at=e.created_at,
    )


@app.post(
    "/admin/efirmas",
    response_model=EfirmaResponse,
    status_code=201,
    dependencies=[Depends(require_internal_key)],
)
async def crear_efirma(
    payload: EfirmaCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """
    Sube y custodia la e.firma (FIEL) de un contribuyente para usarla en la
    descarga masiva de CFDI ante el SAT (zg55DWY). Validado con abogado:
    Responsable = el contribuyente (rfc_titular), Encargado = Acierto en TI.

    Orden de validacion (de menor a mayor costo, gate legal primero) - toda
    la validacion de la tripleta cert+key+password es LOCAL, sin una sola
    llamada al SAT:
      1-8. validacion compartida de la tripleta -> _validar_material_efirma
           (consentimiento, negocio_id, decode, RFC del cert, match,
            par cert<->key, vigencia, rechazo si vencio). Mismo bloque que
           usa el reemplazo (PUT /admin/efirmas/{rfc_titular}).
      9. unicidad: 1 sola e.firma 'Activo' por rfc_titular -> 409 (no se
         auto-renueva; para renovar existe PUT /admin/efirmas/{rfc_titular})
     10. cifrado explicito de key y password con _fernet_efirma
     11. INSERT + sello de consentimiento (at + por_rfc)
     12. respuesta sin material sensible
    """
    # 1-8. Validacion de la tripleta (compartida con el reemplazo). El RFC
    #      "declarado" en el alta es el del body.
    validada = _validar_material_efirma(
        rfc_declarado=payload.rfc_titular,
        cert_base64=payload.cert_base64,
        key_base64=payload.key_base64,
        password=payload.password,
        acepto_tratamiento_efirma=payload.acepto_tratamiento_efirma,
        x_negocio_id=x_negocio_id,
    )

    # 9. Unicidad: 1 sola e.firma 'Activo' por rfc_titular. Chequeo explicito
    #    para dar un 409 con mensaje claro; el indice unico parcial
    #    ix_efirmas_rfc_titular_activo_unico es el backstop ante una carrera.
    existente = await db.scalar(
        select(Efirma.id).where(
            Efirma.rfc_titular == validada.rfc_del_cert,
            Efirma.estado == "Activo",
        )
    )
    if existente is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya existe una e.firma activa para {validada.rfc_del_cert}. "
                "Para renovarla, usa PUT /admin/efirmas/{rfc_titular}."
            ),
        )

    # 10. Cifrado explicito (solo key y password; el cert es publico).
    key_cifrada = _fernet_efirma.encrypt(payload.key_base64.encode()).decode()
    pwd_cifrada = _fernet_efirma.encrypt(payload.password.encode()).decode()

    # 11. INSERT + sello del consentimiento (at en UTC, naive para la columna
    #     'timestamp without time zone', y el RFC personal de quien acepto).
    nueva = Efirma(
        rfc_titular=validada.rfc_del_cert,
        negocio_id=validada.negocio_id,
        cert_base64=payload.cert_base64,
        key_base64_cifrado=key_cifrada,
        password_cifrado=pwd_cifrada,
        vigencia_desde=validada.vigencia_desde,
        vigencia_hasta=validada.vigencia_hasta,
        estado="Activo",
        consentimiento_at=datetime.now(timezone.utc).replace(tzinfo=None),
        consentimiento_por_rfc=x_usuario_rfc,
        creado_por_rfc=x_usuario_rfc,
    )
    db.add(nueva)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una e.firma activa para {validada.rfc_del_cert}.",
        )
    await db.refresh(nueva)

    # 12. Respuesta sin material sensible.
    return _efirma_to_response(nueva)


@app.put(
    "/admin/efirmas/{rfc_titular}",
    response_model=EfirmaResponse,
    dependencies=[Depends(require_internal_key)],
)
async def reemplazar_efirma(
    rfc_titular: str,
    payload: EfirmaReemplazar,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """
    Reemplazo/renovacion EXPLICITA de la e.firma custodiada de un
    contribuyente (zg55DWY paso 5b). Distinto del alta: aqui YA existe una
    e.firma 'Activo' y se sustituye por una nueva (tipico: la anterior esta
    por vencer). Nunca es automatico - el alta (POST) da 409 a proposito.

      1-8. misma validacion de la tripleta que el alta -> _validar_material_efirma.
           El RFC "declarado" es el del path param {rfc_titular}: si el
           certificado nuevo es de otro RFC -> 422.
      9. debe existir EXACTAMENTE una e.firma 'Activo' para (rfc_titular,
         negocio_id). Si no hay ninguna -> 404 (usar el alta). El indice
         unico parcial garantiza que no puede haber mas de una.
     10. en UNA sola transaccion (rollback total si algo falla):
         a. la e.firma vieja pasa a estado 'Reemplazada'
         b. INSERT de la nueva 'Activo' con su propio consentimiento_at
         c. la vieja apunta a la nueva via reemplazada_por_id (historial)
         El orden de los flush importa: primero el UPDATE que libera el
         indice unico parcial, luego el INSERT de la nueva 'Activo'.
     11. respuesta = mismo shape que el alta, sin material sensible.
    """
    # 1-8. Validacion de la tripleta (compartida con el alta). El RFC
    #      "declarado" en el reemplazo es el del path param.
    validada = _validar_material_efirma(
        rfc_declarado=rfc_titular,
        cert_base64=payload.cert_base64,
        key_base64=payload.key_base64,
        password=payload.password,
        acepto_tratamiento_efirma=payload.acepto_tratamiento_efirma,
        x_negocio_id=x_negocio_id,
    )

    # 9. Tiene que haber una e.firma 'Activo' de este RFC en este negocio.
    existente = await db.scalar(
        select(Efirma).where(
            Efirma.rfc_titular == validada.rfc_del_cert,
            Efirma.negocio_id == validada.negocio_id,
            Efirma.estado == "Activo",
        )
    )
    if existente is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay una e.firma activa para {validada.rfc_del_cert} que renovar. "
                "Usa el alta (POST /admin/efirmas) en su lugar."
            ),
        )

    # 10. Reemplazo transaccional. Sin commit intermedio: todo vive en la
    #     misma transaccion que abre get_db, y cualquier excepcion hace
    #     rollback completo (no queda la vieja 'Reemplazada' sin sucesora).
    key_cifrada = _fernet_efirma.encrypt(payload.key_base64.encode()).decode()
    pwd_cifrada = _fernet_efirma.encrypt(payload.password.encode()).decode()

    try:
        # a. Libera el indice unico parcial ANTES de insertar la nueva 'Activo'.
        existente.estado = "Reemplazada"
        await db.flush()

        # b. INSERT de la nueva, con consentimiento_at propio y fresco
        #    (renovar es un tratamiento nuevo sobre un dato sensible nuevo).
        nueva = Efirma(
            rfc_titular=validada.rfc_del_cert,
            negocio_id=validada.negocio_id,
            cert_base64=payload.cert_base64,
            key_base64_cifrado=key_cifrada,
            password_cifrado=pwd_cifrada,
            vigencia_desde=validada.vigencia_desde,
            vigencia_hasta=validada.vigencia_hasta,
            estado="Activo",
            consentimiento_at=datetime.now(timezone.utc).replace(tzinfo=None),
            consentimiento_por_rfc=x_usuario_rfc,
            creado_por_rfc=x_usuario_rfc,
        )
        db.add(nueva)
        await db.flush()  # asigna nueva.id

        # c. Historial: la vieja apunta a su reemplazo.
        existente.reemplazada_por_id = nueva.id
        await db.flush()

        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"No se pudo reemplazar la e.firma de {validada.rfc_del_cert} (conflicto de concurrencia).",
        )
    except Exception:
        await db.rollback()
        raise

    await db.refresh(nueva)

    # 11. Respuesta sin material sensible (mismo shape que el alta).
    return _efirma_to_response(nueva)


# ─── Descarga masiva SAT: solicitudes + tick (zg55DWY) ────────────────────────

def _solicitud_a_response(s: SolicitudDescarga) -> SolicitudDescargaResponse:
    return SolicitudDescargaResponse(
        id=s.id,
        efirma_id=s.efirma_id,
        negocio_id=s.negocio_id,
        tipo=s.tipo,
        fecha_desde=s.fecha_desde,
        fecha_hasta=s.fecha_hasta,
        id_solicitud_sat=s.id_solicitud_sat,
        estado_solicitud=s.estado_solicitud,
        cod_estatus=s.cod_estatus,
        codigo_estado_solicitud=s.codigo_estado_solicitud,
        mensaje_sat=s.mensaje_sat,
        numero_cfdis=s.numero_cfdis,
        created_at=s.created_at,
    )


@app.post(
    "/admin/efirmas/{rfc_titular}/solicitudes-descarga",
    response_model=SolicitudDescargaResponse,
    status_code=201,
    dependencies=[Depends(require_internal_key)],
)
async def crear_solicitud_descarga(
    rfc_titular: str,
    payload: SolicitudDescargaCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
    x_usuario_rfc: Optional[str] = Header(None, alias="X-Usuario-Rfc"),
):
    """
    Dispara una solicitud de descarga masiva de CFDI ante el SAT para la
    e.firma Activa de `rfc_titular` (zg55DWY).

      - Requiere la e.firma en estado 'Activo' para ese RFC + negocio -> 404.
      - Descifra key/password SOLO en memoria para armar el Fiel; nada de eso
        se loguea ni sale en la respuesta.
      - Guarda de pre-vuelo: si ya hay una solicitud 5001/5002/5003 con los
        MISMOS (efirma_id, tipo, fecha_desde, fecha_hasta) -> 409 con el
        mensaje_sat verbatim y la fecha del intento previo, SIN llamar al SAT
        (no gasta un intento contra el limite "de por vida").
      - El estado real del ciclo (Verifica/Descarga) lo avanza el tick.
    """
    negocio_id = requerir_negocio_id(x_negocio_id)
    rfc_titular = rfc_titular.upper().strip()
    tipo = payload.tipo.lower().strip()

    if tipo == "ambas":
        raise HTTPException(
            status_code=422,
            detail="tipo 'ambas' aun no soportado; envia una solicitud 'emitidas' y otra 'recibidas'.",
        )
    if tipo not in ("emitidas", "recibidas"):
        raise HTTPException(
            status_code=422,
            detail="tipo invalido; usa 'emitidas' o 'recibidas'.",
        )
    if payload.fecha_desde > payload.fecha_hasta:
        raise HTTPException(
            status_code=422,
            detail="fecha_desde no puede ser posterior a fecha_hasta.",
        )

    efirma = await db.scalar(
        select(Efirma).where(
            Efirma.rfc_titular == rfc_titular,
            Efirma.negocio_id == negocio_id,
            Efirma.estado == "Activo",
        )
    )
    if efirma is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay una e.firma activa para {rfc_titular} en este negocio.",
        )

    fiel = construir_fiel(efirma)
    try:
        fila = await solicitar_descarga(
            fiel=fiel,
            negocio_id=negocio_id,
            efirma_id=efirma.id,
            rfc_titular=rfc_titular,
            tipo=tipo,
            fecha_desde=payload.fecha_desde,
            fecha_hasta=payload.fecha_hasta,
            solicitado_por_rfc=x_usuario_rfc or "",
            db=db,
        )
    except BloqueoPrevioError as e:
        prev = e.solicitud_previa
        raise HTTPException(
            status_code=409,
            detail=(
                f"El SAT ya bloqueo este periodo (cod_estatus {prev.cod_estatus}) "
                f"en un intento del {prev.created_at:%Y-%m-%d}. "
                f"Mensaje del SAT: {prev.mensaje_sat!r}. No se reintenta."
            ),
        )

    return _solicitud_a_response(fila)


@app.post(
    "/admin/solicitudes-descarga/tick",
    dependencies=[Depends(require_internal_key)],
)
async def tick_solicitudes_descarga(db: AsyncSession = Depends(get_db)):
    """
    Un "tick" del ciclo asincrono de descarga masiva: verifica en el SAT
    todas las solicitudes en vuelo (estado 1/2), avanza su maquina de
    estados y, para las que quedaron 3=Terminada en este tick, baja los
    paquetes y los sube a MinIO. Re-autentica desde cero en cada paso (el
    token del SAT vive 5 min).

    Pensado para un disparador EXTERNO periodico (no hay scheduler/Celery en
    el proyecto).

    TODO (seguridad - PENDIENTE DE DECISION, no resolver aqui): este endpoint
    hoy solo esta detras de require_internal_key (X-Internal-Key), igual que
    el resto de administracion. Pero es un endpoint de EFECTO (habla con el
    SAT, escribe en MinIO) que ademas se va a invocar en bucle. Falta
    definir el disparador y su superficie:
      - un cron DENTRO del propio docker-compose (contenedor sidecar que hace
        el POST con la internal key, sin exponer nada fuera de la red Docker)?
      - un job del host / GitHub Actions con la internal key en secreto?
      - rate-limit propio del endpoint (Redis, como facturacion) para que ni
        con la internal key se pueda martillar?
    Se decide antes de conectarlo a algo real.
    """
    terminadas = await tick_verificar_solicitudes(db)

    detalle = []
    for sol in terminadas:
        efirma = await db.get(Efirma, sol.efirma_id)
        if efirma is None:
            detalle.append({"solicitud_id": sol.id, "error": "e.firma inexistente"})
            continue
        fiel = construir_fiel(efirma)
        await descargar_paquetes(fiel, sol, db)
        await db.refresh(sol)
        pendientes = await db.scalar(
            select(func.count())
            .select_from(PaqueteDescarga)
            .where(
                PaqueteDescarga.solicitud_id == sol.id,
                PaqueteDescarga.descargado.is_(False),
            )
        )
        total = await db.scalar(
            select(func.count())
            .select_from(PaqueteDescarga)
            .where(PaqueteDescarga.solicitud_id == sol.id)
        )
        detalle.append(
            {
                "solicitud_id": sol.id,
                "id_solicitud_sat": sol.id_solicitud_sat,
                "numero_cfdis": sol.numero_cfdis,
                "paquetes_total": total,
                "paquetes_pendientes": pendientes,
            }
        )

    return {
        "terminadas_en_este_tick": len(terminadas),
        "detalle": detalle,
    }


# ─── Clientes ──────────────────────────────────────────────────────────────────

@app.post(
    "/admin/clientes",
    response_model=ClienteResponse,
    status_code=201,
    dependencies=[Depends(require_internal_key)],
)
async def crear_cliente(
    cliente: ClienteCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    # Hallazgo (14 ago 2026, tarjeta 2mUvo): este era el unico endpoint de
    # clientes sin validar el Negocio del caller - IDOR real, permitia crear
    # un cliente atado a un emisor_rfc ajeno. Mismo criterio que
    # obtener_cliente/actualizar_cliente: Cliente no tiene negocio_id propio,
    # se valida via el emisor_rfc contra los emisores de este Negocio. 404
    # (no 403) si el emisor no pertenece al caller - no revela que el RFC
    # existe en otro Negocio, mismo criterio anti-fuga que el resto (#15).
    #
    # X-Internal-Key (20 ago 2026, tarjeta 2mUws): agregado para cerrar el
    # ultimo hueco real de administracion. A diferencia de /admin/negocios,
    # este endpoint SI lo llama el navegador (frontend/src/App.jsx) - pero
    # siempre a traves del Gateway, cuyo proxy generico ya inyecta
    # X-Internal-Key en cada llamada autenticada (ver backend/api_gateway/
    # main.py:222), igual que ya hace para GET/PUT/DELETE /admin/clientes
    # (protegidos desde el 14 ago). No requiere ningun cambio en frontend ni
    # en el Gateway - el header ya viajaba, solo faltaba exigirlo aqui.
    negocio_id = requerir_negocio_id(x_negocio_id)
    rfcs_del_negocio = select(Emisor.rfc).where(Emisor.negocio_id == negocio_id)
    emisor_valido = await db.execute(
        select(Emisor.rfc).where(Emisor.rfc.in_(rfcs_del_negocio), Emisor.rfc == cliente.emisor_rfc)
    )
    if emisor_valido.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Emisor {cliente.emisor_rfc} no encontrado")

    nuevo = Cliente(
        emisor_rfc=cliente.emisor_rfc,
        rfc=cliente.rfc,
        nombre=cliente.nombre,
        email=cliente.email,
        telefono=cliente.telefono,
        regimen_fiscal=cliente.regimen_fiscal,
        uso_cfdi_default=cliente.uso_cfdi_default,
        domicilio_fiscal=cliente.domicilio_fiscal,
        credito_limite=cliente.credito_limite,
    )
    db.add(nuevo)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"El cliente {cliente.rfc} ya existe para el emisor {cliente.emisor_rfc}",
        )
    await db.refresh(nuevo)
    return _cliente_to_response(nuevo)

@app.get(
    "/admin/clientes",
    response_model=List[ClienteResponse],
    dependencies=[Depends(require_internal_key)],
)
async def listar_clientes(
    emisor_rfc: Optional[str] = None,
    busqueda: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    # Cliente no tiene negocio_id propio (solo emisor_rfc, referencia suave
    # sin FK) - se filtra por los RFCs de los emisores que pertenecen a este
    # Negocio, ya que Emisor y Cliente viven en la misma base de datos.
    rfcs_del_negocio = select(Emisor.rfc).where(Emisor.negocio_id == negocio_id)
    stmt = select(Cliente).where(Cliente.emisor_rfc.in_(rfcs_del_negocio))
    if emisor_rfc:
        stmt = stmt.where(Cliente.emisor_rfc == emisor_rfc)
    if busqueda:
        like = f"%{busqueda}%"
        stmt = stmt.where((Cliente.nombre.ilike(like)) | (Cliente.rfc.ilike(like)))
    stmt = stmt.order_by(Cliente.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(stmt)
    return [_cliente_to_response(c) for c in result.scalars().all()]

@app.get(
    "/admin/clientes/{rfc}",
    response_model=ClienteResponse,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_cliente(
    rfc: str,
    emisor_rfc: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    # Mismo criterio que listar_clientes: Cliente no tiene negocio_id propio,
    # se valida via el emisor_rfc contra los emisores de este Negocio. 404 en
    # vez de 403 (#15) - no revela que el RFC existe en otro Negocio.
    rfcs_del_negocio = select(Emisor.rfc).where(Emisor.negocio_id == negocio_id)
    stmt = select(Cliente).where(Cliente.rfc == rfc, Cliente.emisor_rfc.in_(rfcs_del_negocio))
    if emisor_rfc:
        stmt = stmt.where(Cliente.emisor_rfc == emisor_rfc)
    result = await db.execute(stmt)
    cliente = result.scalars().first()
    if cliente is None:
        raise HTTPException(status_code=404, detail=f"Cliente {rfc} no encontrado")
    return _cliente_to_response(cliente)

@app.put(
    "/admin/clientes/{rfc}",
    response_model=ClienteResponse,
    dependencies=[Depends(require_internal_key)],
)
async def actualizar_cliente(
    rfc: str,
    cliente: ClienteCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    # Mismo criterio que listar/obtener clientes: Cliente no tiene negocio_id
    # propio, se valida via el emisor_rfc contra los emisores de este Negocio.
    rfcs_del_negocio = select(Emisor.rfc).where(Emisor.negocio_id == negocio_id)
    result = await db.execute(
        select(Cliente).where(
            Cliente.rfc == rfc,
            Cliente.emisor_rfc == cliente.emisor_rfc,
            Cliente.emisor_rfc.in_(rfcs_del_negocio),
        )
    )
    existente = result.scalar_one_or_none()
    if existente is None:
        raise HTTPException(status_code=404, detail=f"Cliente {rfc} no encontrado")

    existente.nombre = cliente.nombre
    existente.email = cliente.email
    existente.telefono = cliente.telefono
    existente.regimen_fiscal = cliente.regimen_fiscal
    existente.uso_cfdi_default = cliente.uso_cfdi_default
    existente.domicilio_fiscal = cliente.domicilio_fiscal
    existente.credito_limite = cliente.credito_limite
    await db.commit()
    await db.refresh(existente)
    return _cliente_to_response(existente)

@app.delete(
    "/admin/clientes/{rfc}",
    dependencies=[Depends(require_internal_key)],
)
async def eliminar_cliente(
    rfc: str,
    emisor_rfc: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    rfcs_del_negocio = select(Emisor.rfc).where(Emisor.negocio_id == negocio_id)
    result = await db.execute(
        select(Cliente).where(
            Cliente.rfc == rfc,
            Cliente.emisor_rfc == emisor_rfc,
            Cliente.emisor_rfc.in_(rfcs_del_negocio),
        )
    )
    cliente = result.scalar_one_or_none()
    if cliente is None:
        raise HTTPException(status_code=404, detail=f"Cliente {rfc} no encontrado")
    await db.delete(cliente)
    await db.commit()
    return {"rfc": rfc, "eliminado": True}

# ─── Series ─────────────────────────────────────────────────────────────────────
# Alta manual sigue mock (gestion completa de series es fuera de alcance
# hoy - las series se siguen creando implicitamente al primer timbrado, ver
# siguiente_folio abajo). El listado si es real desde hoy - antes devolvia
# [] siempre sin importar los datos reales que ya existian en SerieFolio.

@app.post("/admin/series", status_code=201)
async def crear_serie(serie: SerieCreate):
    return {**serie.dict(), "folio_actual": serie.folio_inicial}

@app.get(
    "/admin/series",
    response_model=List[SerieResponse],
    dependencies=[Depends(require_internal_key)],
)
async def listar_series(
    emisor_rfc: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    # SerieFolio no tiene negocio_id propio (solo emisor_rfc) - mismo
    # criterio de filtrado via Emisor que ya usa clientes.
    rfcs_del_negocio = select(Emisor.rfc).where(Emisor.negocio_id == negocio_id)
    stmt = select(SerieFolio).where(SerieFolio.emisor_rfc.in_(rfcs_del_negocio))
    if emisor_rfc:
        stmt = stmt.where(SerieFolio.emisor_rfc == emisor_rfc)
    stmt = stmt.order_by(SerieFolio.emisor_rfc, SerieFolio.serie)
    result = await db.execute(stmt)
    return [
        SerieResponse(emisor_rfc=s.emisor_rfc, serie=s.serie, ultimo_folio=s.ultimo_folio)
        for s in result.scalars().all()
    ]

@app.get("/admin/series/{serie}/siguiente-folio")
async def siguiente_folio(
    serie: str,
    emisor_rfc: str,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """
    Folio consecutivo real por (emisor_rfc, serie) - #12.

    Llamado por facturacion durante el timbrado, nunca directo desde el
    navegador (#15) - pero SI necesita X-Negocio-Id: facturacion ya lo
    recibe del Gateway (el usuario se autentico para llegar a
    POST /facturas/timbrar) y lo reenvia aqui tal cual. No es un endpoint
    de servicio-a-servicio tipo csd-descifrado (X-Internal-Key) porque el
    contexto de tenant real SI existe en la cadena de la request - usarlo
    evita que un Negocio incremente/consulte el folio de otro adivinando su
    emisor_rfc. Se valida que el emisor pertenezca al Negocio del caller
    antes de tocar el contador.

    Atómico vía UPSERT (INSERT ... ON CONFLICT DO UPDATE ... RETURNING) en
    una sola sentencia: Postgres serializa las escrituras concurrentes sobre
    la misma fila a nivel de motor, así que dos timbrados casi simultáneos
    nunca pueden leer el mismo "último folio" y calcular el mismo siguiente -
    a diferencia de un "leer, sumar 1, guardar" hecho en dos pasos separados
    desde la aplicación, que sí tendría condición de carrera.
    """
    negocio_id = requerir_negocio_id(x_negocio_id)
    emisor_existente = await db.execute(
        select(Emisor).where(Emisor.rfc == emisor_rfc, Emisor.negocio_id == negocio_id)
    )
    if emisor_existente.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Emisor {emisor_rfc} no encontrado")

    stmt = pg_insert(SerieFolio).values(emisor_rfc=emisor_rfc, serie=serie, ultimo_folio=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=["emisor_rfc", "serie"],
        set_={"ultimo_folio": SerieFolio.ultimo_folio + 1},
    ).returning(SerieFolio.ultimo_folio)
    result = await db.execute(stmt)
    folio = result.scalar_one()
    await db.commit()
    return {"serie": serie, "folio": folio, "folio_formateado": f"{serie}-{folio:04d}"}

# ─── Configuración ──────────────────────────────────────────────────────────
# pac_url/storage_bucket: SIGUEN siendo mock global (hallazgo documentado en
# ConfiguracionUpdate, fuera de alcance de zg2mOhE). logo_url/color_primario:
# reales, por negocio, desde aqui (zg2mOhE, white-label del portal publico).

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validar_color_primario(valor: str) -> None:
    if not _HEX_COLOR_RE.match(valor):
        raise HTTPException(
            status_code=422,
            detail="color_primario debe ser un hex de 7 caracteres, ej. #00C896",
        )


# Cierre automatico de consolidacion (g7imYM pieza 3) - HH:MM 24h estricto,
# sin segundos (a diferencia de time.fromisoformat, que aceptaria "23:30:15"
# o incluso solo "23" en Python 3.11+) - el <input type="time"> del frontend
# manda exactamente este formato, y es lo que el scheduler de facturacion
# espera de vuelta en EmisorResponse.
_HORA_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validar_hora_cierre_automatico(valor: str) -> time:
    if not _HORA_HHMM_RE.match(valor):
        raise HTTPException(
            status_code=422,
            detail="hora_cierre_automatico debe tener formato HH:MM (24h), ej. 23:30",
        )
    return datetime.strptime(valor, "%H:%M").time()


@app.get(
    "/admin/config",
    response_model=ConfiguracionResponse,
    dependencies=[Depends(require_internal_key)],
)
async def obtener_config(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = result.scalar_one_or_none()
    if negocio is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")
    return ConfiguracionResponse(
        pac_url="https://ws.finkok.com/servicios/soap/stamp.wsdl",
        storage_bucket="cfdi-xmls",
        logo_url=negocio.logo_url,
        color_primario=negocio.color_primario,
    )


@app.put(
    "/admin/config",
    response_model=ConfiguracionResponse,
    dependencies=[Depends(require_internal_key)],
)
async def actualizar_config(
    config: ConfiguracionUpdate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(select(Negocio).where(Negocio.id == negocio_id))
    negocio = result.scalar_one_or_none()
    if negocio is None:
        raise HTTPException(status_code=404, detail=f"Negocio {negocio_id} no encontrado")

    if config.color_primario is not None:
        _validar_color_primario(config.color_primario)
        negocio.color_primario = config.color_primario
    if config.logo_url is not None:
        negocio.logo_url = config.logo_url

    await db.commit()
    await db.refresh(negocio)
    return ConfiguracionResponse(
        pac_url="https://ws.finkok.com/servicios/soap/stamp.wsdl",
        storage_bucket="cfdi-xmls",
        logo_url=negocio.logo_url,
        color_primario=negocio.color_primario,
    )


@app.post(
    "/admin/config/logo",
    dependencies=[Depends(require_internal_key)],
)
async def subir_logo_negocio(
    archivo: UploadFile = File(...),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """Sube el logo a MinIO (bucket publico, ver logo_storage.py) y
    devuelve la URL - el caller todavia debe mandarla en un PUT
    /admin/config para guardarla en negocios.logo_url. Separado en 2
    pasos a proposito (subir vs. confirmar) - permite preview en el
    frontend antes de guardar de verdad.

    Validacion REAL por magic bytes (validar_logo), no solo el
    Content-Type que declare el multipart - un cliente API directo puede
    saltarse cualquier validacion que solo confiara en el navegador."""
    negocio_id = requerir_negocio_id(x_negocio_id)
    contenido = await archivo.read()
    try:
        content_type = validar_logo(contenido)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    url = subir_logo(negocio_id, contenido, content_type)
    return {"logo_url": url}

# ─── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"service": "administracion", "status": "ok", "version": "2.0.0"}
