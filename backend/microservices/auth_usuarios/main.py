import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import bcrypt
import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Usuario, create_tables, get_db, stamp_head_si_es_ambiente_nuevo
from rfc_validation import es_rfc_persona_fisica_valido
from usuario_validation import es_usuario_valido

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
    # Acepta RFC personal O usuario (ver Usuario.usuario) en el mismo campo -
    # login() busca WHERE rfc_personal = :valor OR usuario = :valor. Sin
    # ambiguedad posible: un RFC valido siempre mide 13 caracteres, un
    # usuario siempre mide 6-10 (es_usuario_valido), los rangos nunca se
    # solapan. email se queda como dato de contacto y para recuperacion de
    # contrasena (todavia sin implementar, ver tarjeta de #48), pero ya no
    # autentica.
    identificador: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class UsuarioCreate(BaseModel):
    email: str
    password: str
    # RFC personal (persona fisica) de quien inicia sesion - reemplaza al
    # email como credencial de login. Obligatorio: Usuario.rfc_personal es
    # NOT NULL en BD. Validado (formato + digito verificador) antes de
    # guardar, no solo aceptado tal cual.
    rfc_personal: str
    # nombre y usuario obligatorios a partir de HOY (10 ago 2026) para
    # cuentas NUEVAS - no retroactivo, Usuario.nombre/usuario siguen
    # nullable en BD porque las cuentas existentes (todas de prueba a esta
    # fecha) no se migran ni se validan. usuario es credencial de login
    # alterna al RFC (ver validar_usuario), formato validado con
    # es_usuario_valido() y normalizado a MAYUSCULAS antes de guardar.
    nombre: str
    usuario: str
    rfc_emisor: Optional[str] = None
    # IGNORADO deliberadamente (fix de seguridad, ver crear_usuario): un
    # caller podia mandar aqui el negocio_id de OTRO negocio y el usuario
    # nuevo terminaba creado ahi, sin validacion alguna. El negocio_id real
    # se toma siempre de X-Negocio-Id (header inyectado por el Gateway
    # desde el JWT ya verificado del caller), nunca de este campo. Se deja
    # en el schema solo por compatibilidad con clientes existentes que
    # todavia lo mandan - no tiene efecto.
    negocio_id: int
    # Sin campo "rol" aqui a proposito: este endpoint es publico (sin JWT
    # previo) y no puede permitir que quien se registra se autoasigne un
    # rol. Todo usuario nuevo nace con ROL_DEFAULT_REGISTRO_PUBLICO, sin
    # excepcion. Como promover a alguien a "admin" (quien puede hacerlo,
    # por que via) es un problema de diseno aparte, todavia sin resolver.


class UsuarioResponse(BaseModel):
    id: int
    email: str
    rfc_personal: str
    nombre: Optional[str]
    usuario: Optional[str]
    rfc_emisor: Optional[str]
    negocio_id: int
    rol: str


class UsuarioListItem(BaseModel):
    # Deliberado: nunca incluye password_hash. Solo lectura por ahora -
    # gestion de roles (promover a admin) queda fuera a proposito, sigue
    # siendo una decision de diseno sin resolver (ver nota en #10).
    id: int
    email: str
    rfc_personal: str
    nombre: Optional[str]
    usuario: Optional[str]
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
    # RFC personal (persona fisica) de quien registra la cuenta - se
    # vuelve la credencial de login. email se queda como dato de contacto
    # y para recuperacion de contrasena, no para autenticar.
    rfc_personal: str
    password: str
    # nombre y usuario obligatorios a partir de HOY (10 ago 2026, ver
    # UsuarioCreate) - no retroactivo.
    nombre: str
    usuario: str


class RegistroResponse(BaseModel):
    negocio_id: int
    negocio_nombre: str
    usuario: UsuarioResponse


# Mensaje deliberadamente genérico: no revela si falló el identificador
# (RFC o usuario) o la contraseña (evita que un atacante use el login para
# enumerar cuentas).
CREDENCIALES_INVALIDAS = "RFC, usuario o contraseña incorrectos"


def validar_rfc_personal(rfc_personal: str) -> str:
    """
    Formato + digito verificador real (rfc_validation.py, algoritmo de
    satcfdi) - no solo longitud. 422 (no 400) porque es un error de
    validacion del cuerpo de la peticion, mismo criterio que usaria
    Pydantic para un campo mal formado.
    """
    rfc_personal = rfc_personal.upper()
    if not es_rfc_persona_fisica_valido(rfc_personal):
        raise HTTPException(
            status_code=422,
            detail=f"RFC personal invalido: {rfc_personal} (formato o digito verificador incorrecto)",
        )
    return rfc_personal


def validar_usuario(usuario: str) -> str:
    """
    Formato de es_usuario_valido() (usuario_validation.py) - 422 con
    mensaje claro si no cumple, mismo criterio que validar_rfc_personal.
    Normaliza a MAYUSCULAS antes de validar/guardar (mismo patron que RFC).
    """
    usuario = usuario.upper()
    if not es_usuario_valido(usuario):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Usuario invalido: {usuario} (debe medir 6-10 caracteres, "
                "empezar con una letra, y contener solo letras, numeros o guion bajo)"
            ),
        )
    return usuario


def requerir_negocio_id(x_negocio_id: Optional[str]) -> int:
    """
    Mismo criterio que administracion (#15): las LECTURAS multi-tenant no
    tienen fallback permisivo. Un fallback a un Negocio por defecto aqui
    significaria que una llamada sin X-Negocio-Id (bypass del Gateway,
    header ausente por error) podria mostrar usuarios de un Negocio ajeno.
    """
    if not x_negocio_id:
        raise HTTPException(
            status_code=400,
            detail="Falta X-Negocio-Id - esta lectura requiere pasar por el Gateway con un token valido",
        )
    try:
        return int(x_negocio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Negocio-Id invalido")

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
async def crear_usuario(
    req: UsuarioCreate,
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    # Fix de seguridad: negocio_id SIEMPRE del caller autenticado
    # (X-Negocio-Id, ver requerir_negocio_id), nunca de req.negocio_id -
    # antes cualquier llamante autenticado podia crear un usuario en
    # CUALQUIER negocio con solo mandar su id en el body (confirmado con
    # una prueba real cross-tenant). req.negocio_id se ignora a proposito.
    negocio_id = requerir_negocio_id(x_negocio_id)
    rfc_personal = validar_rfc_personal(req.rfc_personal)
    usuario_login = validar_usuario(req.usuario)
    password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    usuario = Usuario(
        email=req.email,
        rfc_personal=rfc_personal,
        usuario=usuario_login,
        password_hash=password_hash,
        nombre=req.nombre,
        rfc_emisor=req.rfc_emisor,
        negocio_id=negocio_id,
        rol=ROL_DEFAULT_REGISTRO_PUBLICO,
    )
    db.add(usuario)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un usuario con email {req.email}, RFC {rfc_personal} o usuario {usuario_login}",
        )
    return UsuarioResponse(
        id=usuario.id, email=usuario.email, rfc_personal=usuario.rfc_personal, nombre=usuario.nombre,
        usuario=usuario.usuario, rfc_emisor=usuario.rfc_emisor, negocio_id=usuario.negocio_id, rol=usuario.rol,
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
    rfc_personal = validar_rfc_personal(req.rfc_personal)
    usuario_login = validar_usuario(req.usuario)

    # Se valida ANTES de llamar a administracion (que crea el Negocio) para
    # no dejar un Negocio huerfano si el registro va a fallar de todos
    # modos por un RFC, email o usuario ya usados.
    existente = await db.execute(
        select(Usuario).where(
            (Usuario.email == req.email)
            | (Usuario.rfc_personal == rfc_personal)
            | (Usuario.usuario == usuario_login)
        )
    )
    if existente.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un usuario con email {req.email}, RFC {rfc_personal} o usuario {usuario_login}",
        )

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
        rfc_personal=rfc_personal,
        usuario=usuario_login,
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
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un usuario con email {req.email}, RFC {rfc_personal} o usuario {usuario_login}",
        )

    return RegistroResponse(
        negocio_id=negocio["id"],
        negocio_nombre=negocio["nombre"],
        usuario=UsuarioResponse(
            id=usuario.id, email=usuario.email, rfc_personal=usuario.rfc_personal, nombre=usuario.nombre,
            usuario=usuario.usuario, rfc_emisor=usuario.rfc_emisor, negocio_id=usuario.negocio_id, rol=usuario.rol,
        ),
    )


@app.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    identificador = req.identificador.upper()
    # Acepta RFC personal O usuario en el mismo campo, sin ambiguedad: un
    # RFC valido siempre mide 13 caracteres, un usuario siempre mide 6-10
    # (es_usuario_valido) - los rangos de longitud nunca se solapan, asi
    # que como maximo una de las dos condiciones puede matchear una fila.
    result = await db.execute(
        select(Usuario).where(
            (Usuario.rfc_personal == identificador) | (Usuario.usuario == identificador)
        )
    )
    usuario = result.scalar_one_or_none()

    if usuario is None or not bcrypt.checkpw(req.password.encode("utf-8"), usuario.password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail=CREDENCIALES_INVALIDAS)

    # sub SIEMPRE es rfc_personal, sin importar si el login fue por RFC o
    # por usuario - "usuario" es solo una credencial alterna de entrada,
    # nunca reemplaza al RFC como identidad real del principal autenticado.
    # Esto es lo que mantiene intacta toda la auditoria de hoy
    # (creado_por_rfc, cancelado_por_rfc, X-Usuario-Rfc) sin ningun cambio
    # en facturacion/administracion/whatsapp_bot/api_gateway.
    payload = {
        "sub": usuario.rfc_personal,
        "email": usuario.email,
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
async def listar_usuarios(
    db: AsyncSession = Depends(get_db),
    x_negocio_id: Optional[str] = Header(None, alias="X-Negocio-Id"),
):
    """Solo lectura. Gestion de roles, edicion y eliminacion quedan fuera
    a proposito - promover a un usuario a "admin" sigue siendo una
    decision de diseno sin resolver (ver #10). Filtrado por Negocio (#15) -
    cada usuario ve solo los usuarios de su propio Negocio."""
    negocio_id = requerir_negocio_id(x_negocio_id)
    result = await db.execute(
        select(Usuario).where(Usuario.negocio_id == negocio_id).order_by(Usuario.created_at.desc())
    )
    return [
        UsuarioListItem(
            id=u.id, email=u.email, rfc_personal=u.rfc_personal, nombre=u.nombre,
            usuario=u.usuario, rfc_emisor=u.rfc_emisor, negocio_id=u.negocio_id, rol=u.rol,
            created_at=u.created_at,
        )
        for u in result.scalars().all()
    ]


@app.get("/health")
async def health():
    return {"service": "auth", "status": "ok"}
