# ─── services/administracion/main.py ──────────────────────────────────────────
# Microservicio de Administración
# Puerto: 8002
# Responsabilidades: Emisores, Clientes, Series, Configuración
#
# Emisores y Clientes: persistencia real (SQLAlchemy + Postgres) - tarea #4.
# Series/folios consecutivos y Configuración: siguen mock, fuera de alcance
# de esta tarea (folios consecutivos es #12, tarea aparte).
# ──────────────────────────────────────────────────────────────────────────────
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query, Depends, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Emisor, Cliente, SerieFolio, get_db, create_tables, stamp_head_si_es_ambiente_nuevo

# ─── Autenticacion interna servicio-a-servicio ─────────────────────────────────
# Mismo patron que whatsapp_bot/core/security.py (X-Internal-Key). Protege
# especificamente el endpoint que devuelve el CSD ya descifrado (#42) - el
# dato mas sensible del sistema. NUNCA loguear el resultado de este endpoint.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
_internal_api_key_header = APIKeyHeader(name="X-Internal-Key", auto_error=False)


def require_internal_key(api_key: Optional[str] = Security(_internal_api_key_header)) -> str:
    if not INTERNAL_API_KEY or not api_key or api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clave interna inválida o ausente")
    return api_key


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
    created_at: datetime
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


def _emisor_to_response(e: Emisor) -> EmisorResponse:
    return EmisorResponse(
        rfc=e.rfc,
        razon_social=e.razon_social,
        regimen_fiscal=e.regimen_fiscal,
        codigo_postal=e.codigo_postal,
        estado=e.estado,
        created_at=e.created_at,
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

@app.post("/admin/emisores", response_model=EmisorResponse, status_code=201)
async def crear_emisor(emisor: EmisorCreate, db: AsyncSession = Depends(get_db)):
    """Registra un nuevo emisor real. El CSD se guarda tal cual se recibe
    (base64) - cifrado con KMS queda pendiente, es una decision de
    seguridad aparte."""
    existente = await db.execute(select(Emisor).where(Emisor.rfc == emisor.rfc))
    if existente.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"El emisor {emisor.rfc} ya existe")

    nuevo = Emisor(
        rfc=emisor.rfc,
        razon_social=emisor.razon_social,
        regimen_fiscal=emisor.regimen_fiscal,
        codigo_postal=emisor.codigo_postal,
        csd_cert_base64=emisor.csd_cert_base64,
        csd_key_base64=emisor.csd_key_base64,
        csd_password=emisor.csd_password,
    )
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)
    return _emisor_to_response(nuevo)

@app.get("/admin/emisores", response_model=List[EmisorResponse])
async def listar_emisores(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Emisor).order_by(Emisor.created_at.desc()))
    return [_emisor_to_response(e) for e in result.scalars().all()]

@app.get("/admin/emisores/{rfc}", response_model=EmisorResponse)
async def obtener_emisor(rfc: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc))
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
async def actualizar_emisor(rfc: str, emisor: EmisorCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Emisor).where(Emisor.rfc == rfc))
    existente = result.scalar_one_or_none()
    if existente is None:
        raise HTTPException(status_code=404, detail=f"Emisor {rfc} no encontrado")

    existente.razon_social = emisor.razon_social
    existente.regimen_fiscal = emisor.regimen_fiscal
    existente.codigo_postal = emisor.codigo_postal
    existente.csd_cert_base64 = emisor.csd_cert_base64
    existente.csd_key_base64 = emisor.csd_key_base64
    existente.csd_password = emisor.csd_password
    await db.commit()
    await db.refresh(existente)
    return _emisor_to_response(existente)

# ─── Clientes ──────────────────────────────────────────────────────────────────

@app.post("/admin/clientes", response_model=ClienteResponse, status_code=201)
async def crear_cliente(cliente: ClienteCreate, db: AsyncSession = Depends(get_db)):
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
):
    stmt = select(Cliente)
    if emisor_rfc:
        stmt = stmt.where(Cliente.emisor_rfc == emisor_rfc)
    if busqueda:
        like = f"%{busqueda}%"
        stmt = stmt.where((Cliente.nombre.ilike(like)) | (Cliente.rfc.ilike(like)))
    stmt = stmt.order_by(Cliente.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(stmt)
    return [_cliente_to_response(c) for c in result.scalars().all()]

@app.get("/admin/clientes/{rfc}", response_model=ClienteResponse)
async def obtener_cliente(rfc: str, emisor_rfc: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Cliente).where(Cliente.rfc == rfc)
    if emisor_rfc:
        stmt = stmt.where(Cliente.emisor_rfc == emisor_rfc)
    result = await db.execute(stmt)
    cliente = result.scalars().first()
    if cliente is None:
        raise HTTPException(status_code=404, detail=f"Cliente {rfc} no encontrado")
    return _cliente_to_response(cliente)

@app.put("/admin/clientes/{rfc}", response_model=ClienteResponse)
async def actualizar_cliente(rfc: str, cliente: ClienteCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Cliente).where(Cliente.rfc == rfc, Cliente.emisor_rfc == cliente.emisor_rfc)
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
async def eliminar_cliente(rfc: str, emisor_rfc: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Cliente).where(Cliente.rfc == rfc, Cliente.emisor_rfc == emisor_rfc)
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
async def listar_series(emisor_rfc: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(SerieFolio)
    if emisor_rfc:
        stmt = stmt.where(SerieFolio.emisor_rfc == emisor_rfc)
    stmt = stmt.order_by(SerieFolio.emisor_rfc, SerieFolio.serie)
    result = await db.execute(stmt)
    return [
        SerieResponse(emisor_rfc=s.emisor_rfc, serie=s.serie, ultimo_folio=s.ultimo_folio)
        for s in result.scalars().all()
    ]

@app.get("/admin/series/{serie}/siguiente-folio")
async def siguiente_folio(serie: str, emisor_rfc: str, db: AsyncSession = Depends(get_db)):
    """
    Folio consecutivo real por (emisor_rfc, serie) - #12.

    Atómico vía UPSERT (INSERT ... ON CONFLICT DO UPDATE ... RETURNING) en
    una sola sentencia: Postgres serializa las escrituras concurrentes sobre
    la misma fila a nivel de motor, así que dos timbrados casi simultáneos
    nunca pueden leer el mismo "último folio" y calcular el mismo siguiente -
    a diferencia de un "leer, sumar 1, guardar" hecho en dos pasos separados
    desde la aplicación, que sí tendría condición de carrera.
    """
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
