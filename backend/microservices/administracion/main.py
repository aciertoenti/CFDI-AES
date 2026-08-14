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
from datetime import datetime
from typing import Optional, List

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Emisor, Cliente, Negocio, SerieFolio, get_db, create_tables, stamp_head_si_es_ambiente_nuevo
from csd_rfc import extraer_rfc_de_certificado
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

class EmisorResponse(BaseModel):
    rfc: str
    razon_social: str
    regimen_fiscal: str
    codigo_postal: str
    estado: str
    negocio_id: int
    created_at: datetime
    creado_por_rfc: Optional[str] = None
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

class NegocioCreate(BaseModel):
    nombre: str
    plan: str = "basico"

class NegocioResponse(BaseModel):
    id: int
    nombre: str
    plan: str
    fecha_alta: datetime
    estado: str

class ClienteCreate(BaseModel):
    emisor_rfc: str
    nombre: str
    rfc: str
    email: str
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
    email: str
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
        cache_invalidado=cache_invalidado,
    )


def _negocio_to_response(n: Negocio) -> NegocioResponse:
    return NegocioResponse(id=n.id, nombre=n.nombre, plan=n.plan, fecha_alta=n.fecha_alta, estado=n.estado)


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

@app.post("/admin/emisores", response_model=EmisorResponse, status_code=201)
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

@app.post("/admin/negocios", response_model=NegocioResponse, status_code=201)
async def crear_negocio(negocio: NegocioCreate, db: AsyncSession = Depends(get_db)):
    """
    Usado por el flujo de registro real (POST /auth/registro en
    auth_usuarios, #15) - "crear cuenta" da de alta un Negocio nuevo antes
    de crear su primer usuario admin, en vez de un usuario suelto sin
    tenant. Tambien disponible para alta manual directa.
    """
    nuevo = Negocio(nombre=negocio.nombre, plan=negocio.plan)
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)
    return _negocio_to_response(nuevo)


@app.get("/admin/negocios/{negocio_id}", response_model=NegocioResponse)
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

@app.get("/admin/emisores", response_model=List[EmisorResponse])
async def listar_emisores(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(
        select(Emisor).where(Emisor.negocio_id == negocio_id).order_by(Emisor.created_at.desc())
    )
    return [_emisor_to_response(e) for e in result.scalars().all()]

@app.get("/admin/emisores/{rfc}", response_model=EmisorResponse)
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

@app.put("/admin/emisores/{rfc}", response_model=EmisorResponse)
async def actualizar_emisor(
    rfc: str,
    emisor: EmisorCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
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
    await db.commit()
    await db.refresh(existente)

    # El CSD ya quedo guardado en BD (lo de arriba no se revierte por lo
    # que pase aqui abajo) - si facturacion no confirma la invalidacion,
    # cache_invalidado=False avisa explicitamente a quien roto el CSD que
    # facturacion podria seguir timbrando con el CSD anterior hasta que se
    # reinicie o se reintente. Nunca fallar en silencio.
    cache_invalidado = await _invalidar_csd_cache_en_facturacion(rfc)
    return _emisor_to_response(existente, cache_invalidado=cache_invalidado)

# ─── Clientes ──────────────────────────────────────────────────────────────────

@app.post("/admin/clientes", response_model=ClienteResponse, status_code=201)
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

@app.get("/admin/clientes", response_model=List[ClienteResponse])
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

@app.get("/admin/clientes/{rfc}", response_model=ClienteResponse)
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

@app.put("/admin/clientes/{rfc}", response_model=ClienteResponse)
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

@app.delete("/admin/clientes/{rfc}")
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

@app.get("/admin/series", response_model=List[SerieResponse])
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
