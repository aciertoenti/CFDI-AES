import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Usuario, create_tables, get_db, stamp_head_si_es_ambiente_nuevo


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
    rol: str


# Mensaje deliberadamente genérico: no revela si falló el email o la
# contraseña (evita que un atacante use el login para enumerar cuentas).
CREDENCIALES_INVALIDAS = "Email o contraseña incorrectos"

# Rol fijo para todo registro via el endpoint publico. No confundir con
# capacidad de administrar: promover a un usuario a "admin" requiere un
# mecanismo aparte (todavia sin disenar) que no dependa de que el propio
# usuario lo pida.
ROL_DEFAULT_REGISTRO_PUBLICO = "usuario"


@app.post("/auth/usuarios", response_model=UsuarioResponse, status_code=201)
async def crear_usuario(req: UsuarioCreate, db: AsyncSession = Depends(get_db)):
    password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    usuario = Usuario(
        email=req.email,
        password_hash=password_hash,
        nombre=req.nombre,
        rfc_emisor=req.rfc_emisor,
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
        rfc_emisor=usuario.rfc_emisor, rol=usuario.rol,
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
        "roles": [usuario.rol],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return TokenResponse(access_token=token, expires_in=3600)


@app.post("/auth/logout")
async def logout():
    return {"mensaje": "Sesión cerrada"}


@app.get("/health")
async def health():
    return {"service": "auth", "status": "ok"}
