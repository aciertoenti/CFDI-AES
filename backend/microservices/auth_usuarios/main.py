import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import bcrypt
import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Usuario, create_tables, get_db, stamp_head_si_es_ambiente_nuevo

# Mismo patron que facturacion -> administracion (consulta de datos de
# emisor): llamada directa al microservicio, sin pasar por el Gateway
# (este propio endpoint SI se llama desde el Gateway, pero la llamada
# saliente hacia administracion es interna, servicio-a-servicio).
ADMINISTRACION_URL = os.environ.get("ADMINISTRACION_URL", "http://administracion:8002")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await stamp_head_si_es_ambiente_nuevo()
    yield


app = FastAPI(title="CFDI – Auth", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET no está definido. Configúralo como variable de entorno.")
JWT_ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class UsuarioCreate(BaseModel):
    email: str
    password: str
    nombre: Optional[str] = None
    rfc_emisor: Optional[str] = None
    # A partir de #15 este endpoint ya no es el registro "de entrada"
    # (eso es POST /auth/registro, que crea el Negocio) - este queda para
    # agregar un usuario adicional a un Negocio que ya existe, asi que
    # negocio_id es obligatorio: Usuario.negocio_id es NOT NULL en BD.
    negocio_id: int
    # Sin campo "rol" aqui a proposito: este endpoint es publico (sin JWT
    # previo) y no puede permitir que quien se registra se autoasigne un
    # rol. Todo usuario nuevo nace con ROL_DEFAULT_REGISTRO_PUBLICO, sin
    # excepcion. Como promover a alguien a "admin" (quien puede hacerlo,
    # por que via) es un problema de diseno aparte, todavia sin resolver.


class UsuarioResponse(BaseModel):
    id: int
    email: str
    nombre: Optional[str]
    rfc_emisor: Optional[str]
    negocio_id: int
    rol: str


class UsuarioListItem(BaseModel):
    # Deliberado: nunca incluye password_hash. Solo lectura por ahora -
    # gestion de roles (promover a admin) queda fuera a proposito, sigue
    # siendo una decision de diseno sin resolver (ver nota en #10).
    id: int
    email: str
    nombre: Optional[str]
    rfc_emisor: Optional[str]
    negocio_id: int
    rol: str
    created_at: datetime


class RegistroRequest(BaseModel):
    """Registro real (#15) - "crear cuenta" crea un Negocio nuevo + su
    primer usuario admin, nunca un usuario suelto sin tenant."""
    nombre_negocio: str
    plan: str = "basico"
    email: str
    password: str
    nombre: Optional[str] = None


class RegistroResponse(BaseModel):
    negocio_id: int
    negocio_nombre: str
    usuario: UsuarioResponse


# Mensaje deliberadamente genérico: no revela si falló el email o la
# contraseña (evita que un atacante use el login para enumerar cuentas).
CREDENCIALES_INVALIDAS = "Email o contraseña incorrectos"

# Rol fijo para todo registro via el endpoint publico. No confundir con
# capacidad de administrar: promover a un usuario a "admin" requiere un
# mecanismo aparte (todavia sin disenar) que no dependa de que el propio
# usuario lo pida.
ROL_DEFAULT_REGISTRO_PUBLICO = "usuario"

# Rol del primer usuario de un Negocio nuevo (#15). El diseno acordado
# reinterpreta el rol existente ("usuario"/"admin") como "admin de su
# propio Negocio", no admin de plataforma - quien registra un Negocio es,
# por definicion, su primer admin.
ROL_ADMIN_NEGOCIO = "admin"


@app.post("/auth/usuarios", response_model=UsuarioResponse, status_code=201)
async def crear_usuario(req: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    usuario = Usuario(
        email=req.email,
        password_hash=password_hash,
        nombre=req.nombre,
        rfc_emisor=req.rfc_emisor,
        negocio_id=req.negocio_id,
        rol=ROL_DEFAULT_REGISTRO_PUBLICO,
    )
    db.add(usuario)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {req.email}")
    return UsuarioResponse(
        id=usuario.id, email=usuario.email, nombre=usuario.nombre,
        rfc_emisor=usuario.rfc_emisor, negocio_id=usuario.negocio_id, rol=usuario.rol,
    )


@app.post("/auth/registro", response_model=RegistroResponse, status_code=201)
async def registro(req: RegistroRequest, db: AsyncSession = Depends(get_db)):
    """
    Registro real (#15) - "crear cuenta" da de alta un Negocio nuevo antes
    de crear su primer usuario, que nace admin de ese Negocio
    (ROL_ADMIN_NEGOCIO). Orquesta una llamada de servicio a servicio hacia
    administracion, que es quien es dueno de la tabla negocios.

    Publico a proposito (#48/#15): igual que login, este es un paso previo
    a tener un token, asi que el Gateway debe exponerlo sin exigir JWT.
    """
    existente = await db.execute(select(Usuario).where(Usuario.email == req.email))
    if existente.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {req.email}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{ADMINISTRACION_URL}/admin/negocios",
                json={"nombre": req.nombre_negocio, "plan": req.plan},
            )
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="No se pudo contactar al servicio de administracion")

    if resp.status_code != 201:
        raise HTTPException(status_code=502, detail="No se pudo crear el Negocio")

    negocio = resp.json()

    password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    usuario = Usuario(
        email=req.email,
        password_hash=password_hash,
        nombre=req.nombre,
        negocio_id=negocio["id"],
        rol=ROL_ADMIN_NEGOCIO,
    )
    db.add(usuario)
    try:
        await db.flush()
    except IntegrityError:
        # Ventana de carrera muy angosta con el check de arriba: el Negocio
        # ya se creo en administracion y quedaria huerfano. Aceptado por
        # ahora - mismo nivel de garantia que el resto del proyecto en esta
        # etapa (ver nota de JWT sin verificar en microservicios).
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {req.email}")

    return RegistroResponse(
        negocio_id=negocio["id"],
        negocio_nombre=negocio["nombre"],
        usuario=UsuarioResponse(
            id=usuario.id, email=usuario.email, nombre=usuario.nombre,
            rfc_emisor=usuario.rfc_emisor, negocio_id=usuario.negocio_id, rol=usuario.rol,
        ),
    )


@app.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Usuario).where(Usuario.email == req.email))
    usuario = result.scalar_one_or_none()

    if usuario is None or not bcrypt.checkpw(req.password.encode("utf-8"), usuario.password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail=CREDENCIALES_INVALIDAS)

    payload = {
        "sub": usuario.email,
        "rfc_emisor": usuario.rfc_emisor,
        "negocio_id": usuario.negocio_id,
        "roles": [usuario.rol],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenResponse(access_token=token, expires_in=3600)


@app.post("/auth/logout")
async def logout():
    return {"mensaje": "Sesión cerrada"}


@app.get("/auth/usuarios", response_model=List[UsuarioListItem])
async def listar_usuarios(db: AsyncSession = Depends(get_db)):
    """Solo lectura. Gestion de roles, edicion y eliminacion quedan fuera
    a proposito - promover a un usuario a "admin" sigue siendo una
    decision de diseno sin resolver (ver #10)."""
    result = await db.execute(select(Usuario).order_by(Usuario.created_at.desc()))
    return [
        UsuarioListItem(
            id=u.id, email=u.email, nombre=u.nombre,
            rfc_emisor=u.rfc_emisor, negocio_id=u.negocio_id, rol=u.rol, created_at=u.created_at,
        )
        for u in result.scalars().all()
    ]


@app.get("/health")
async def health():
    return {"service": "auth", "status": "ok"}
