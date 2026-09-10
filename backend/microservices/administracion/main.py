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
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, List

import httpx
from cryptography.hazmat.primitives.serialization import load_der_private_key
from cryptography.x509 import load_der_x509_certificate
from fastapi import FastAPI, Header, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Efirma, Emisor, Cliente, Negocio, SerieFolio, SolicitudDescarga, PaqueteDescarga, get_db, create_tables, stamp_head_si_es_ambiente_nuevo
from database import _fernet_efirma  # cifrado explicito de la e.firma (ver database.py)
from csd_rfc import extraer_rfc_de_certificado
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
    pac_url: Optional[str] = None
    pac_usuario: Optional[str] = None
    pac_password: Optional[str] = None
    storage_bucket: Optional[str] = None
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

    nuevo = Emisor(
        negocio_id=negocio_id,
        rfc=emisor.rfc,
        razon_social=emisor.razon_social,
        regimen_fiscal=emisor.regimen_fiscal,
        codigo_postal=emisor.codigo_postal,
        csd_cert_base64=emisor.csd_cert_base64,
        csd_key_base64=emisor.csd_key_base64,
        csd_password=emisor.csd_password,
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
    "/admin/emisores",
    response_model=List[EmisorResponse],
    dependencies=[Depends(require_internal_key)],
)
async def listar_emisores(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(
        select(Emisor).where(Emisor.negocio_id == negocio_id).order_by(Emisor.created_at.desc())
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

    existente.razon_social = emisor.razon_social
    existente.regimen_fiscal = emisor.regimen_fiscal
    existente.codigo_postal = emisor.codigo_postal
    existente.csd_cert_base64 = emisor.csd_cert_base64
    existente.csd_key_base64 = emisor.csd_key_base64
    existente.csd_password = emisor.csd_password
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

# ─── Configuración (mock, fuera de alcance de esta tarea) ──────────────────────

@app.get("/admin/config")
async def obtener_config():
    return {"pac_url": "https://ws.finkok.com/servicios/soap/stamp.wsdl", "storage_bucket": "cfdi-xmls"}

@app.put("/admin/config")
async def actualizar_config(config: ConfiguracionUpdate):
    return {"actualizado": True}

# ─── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"service": "administracion", "status": "ok", "version": "2.0.0"}
