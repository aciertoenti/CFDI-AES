import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import bcrypt
import httpx
import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import Usuario, create_tables, get_db, stamp_head_si_es_ambiente_nuevo
from rfc_validation import es_rfc_persona_fisica_valido
from usuario_validation import es_usuario_valido
from shared.negocio_id import requerir_negocio_id
from shared.internal_key import require_internal_key
from email_sender import enviar_correo_reset
from redis_client import (
    MAX_INTENTOS_LOGIN,
    consumir_token_reset,
    crear_token_reset,
    permitir_solicitud_reset,
    registrar_intento_fallido,
    resetear_intentos,
    segundos_bloqueado,
)

# Sin esto, logger.info() no aparece en ningun lado - el root logger de
# Python arranca sin handlers y en nivel WARNING por default, asi que los
# logs de auditoria de password-reset (nunca antes existian en este
# servicio) se descartaban en silencio. Confirmado el bug corriendo la
# prueba real antes de este fix - los INFO simplemente no salian.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("auth_usuarios")

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


class PasswordResetRequestRequest(BaseModel):
    # Solo correo a proposito (#48-reset) - nunca RFC/usuario, para que este
    # endpoint no sirva como oraculo de "que identificadores de login
    # existen" (ya evitado en /auth/login con CREDENCIALES_INVALIDAS
    # generico; aqui el mismo principio, pero antes de llegar siquiera a
    # ese endpoint).
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    nueva_password: str


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


# Hallazgo (13 ago 2026, al construir password-reset/confirm): no existia
# NINGUNA validacion de complejidad de contrasena en el backend - ni en
# crear_usuario ni en registro, password: str se acepta y se hashea tal
# cual. Lo unico parecido en todo el proyecto es minLength={8} en el
# formulario de registro del frontend (App.jsx, campo reg-password) - nunca
# aplicado del lado servidor. Se replica ese mismo minimo aqui (8
# caracteres), el unico precedente real que existe, en vez de inventar un
# criterio de complejidad nuevo sin pedirlo.
MIN_PASSWORD_LENGTH = 8


def validar_password_nueva(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"La contraseña debe medir al menos {MIN_PASSWORD_LENGTH} caracteres",
        )
    return password


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


@app.post("/auth/usuarios", response_model=UsuarioResponse, status_code=201, dependencies=[Depends(require_internal_key)])
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

    # Rate limiting (13 ago 2026, #48-ratelimit) - por identificador de
    # login (RFC/usuario), NO por IP: la IP real del cliente no llega
    # confiable a este servicio hoy (login_proxy en el Gateway reenvia
    # headers tal cual, sin inyectar X-Forwarded-For), y ademas contar por
    # identificador es lo que realmente protege UNA cuenta contra fuerza
    # bruta sin importar desde cuantas IPs distintas ataquen. Se revisa
    # ANTES de tocar la BD/bcrypt - un identificador bloqueado no debe
    # gastar ni un ciclo de verificacion.
    bloqueo = await segundos_bloqueado(identificador)
    if bloqueo is not None:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Demasiados intentos fallidos. Intenta de nuevo en "
                f"{bloqueo // 60 + 1} minutos."
            ),
            headers={"Retry-After": str(bloqueo)},
        )

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
        # MAX_INTENTOS_LOGIN intentos consecutivos -> bloqueo de 15 min
        # (ver redis_client.registrar_intento_fallido). Este intento (el
        # que sea que dispare el bloqueo, incluido el 5to) sigue
        # respondiendo 401 normal - es el SIGUIENTE el que encuentra el
        # bloqueo ya activo arriba y recibe 429.
        await registrar_intento_fallido(identificador)
        raise HTTPException(status_code=401, detail=CREDENCIALES_INVALIDAS)

    # Login exitoso - limpia cualquier contador/bloqueo previo de este
    # identificador (ver resetear_intentos).
    await resetear_intentos(identificador)

    # sub SIEMPRE es rfc_personal, sin importar si el login fue por RFC o
    # por usuario - "usuario" es solo una credencial alterna de entrada,
    # nunca reemplaza al RFC como identidad real del principal autenticado.
    # Esto es lo que mantiene intacta toda la auditoria de hoy
    # (creado_por_rfc, cancelado_por_rfc, X-Usuario-Rfc) sin ningun cambio
    # en facturacion/administracion/whatsapp_bot/api_gateway.
    payload = {
        "sub": usuario.rfc_personal,
        "nombre": usuario.nombre,
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


# Mensaje IDENTICO exista o no la cuenta - literal compartido para que no
# haya forma de que un caller distinga las 2 ramas por el texto exacto.
RESET_MENSAJE_GENERICO = "Si el correo está registrado, se envió un enlace de recuperación."


@app.post("/auth/password-reset/request", status_code=202)
async def password_reset_request(
    req: PasswordResetRequestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_forwarded_for: Optional[str] = Header(None, alias="X-Forwarded-For"),
):
    """
    Publico a proposito (#48-reset), mismo motivo que /auth/login: quien
    llama todavia no tiene sesion. NO exige X-Internal-Key ni X-Negocio-Id -
    consistente con como esta montado hoy este servicio (auth_usuarios no
    valida X-Internal-Key en NINGUN endpoint, ni siquiera los que ya
    existian - ver hallazgo aparte, fuera de alcance aqui). El Gateway
    necesita una ruta dedicada para esto (proxy() generico exige JWT via
    verify_token, que rompe endpoints publicos).

    Respuesta IDENTICA exista o no la cuenta (mismo status, mismo body) -
    el envio real del correo (si la cuenta existe) se dispara con
    BackgroundTasks, DESPUES de que la respuesta ya salio. Esto no es solo
    prolijidad: es lo que evita que la llamada real y bloqueante a la API
    de SendGrid (100-500ms tipico) se vuelva un timing attack obvio que
    revele si el correo existe (la rama "no existe" respondia casi
    instantaneo, la rama "existe" tardaria notoriamente mas si se esperara
    el envio antes de responder).
    """
    ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else "desconocida"
    if not await permitir_solicitud_reset(ip):
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes de recuperación. Intenta más tarde.",
        )

    result = await db.execute(select(Usuario).where(Usuario.email == req.email))
    usuario = result.scalar_one_or_none()

    # Log interno para auditoria (nunca expuesto en la respuesta HTTP) -
    # incluye si se encontro cuenta, nunca el token (que ni siquiera existe
    # todavia en este punto para la rama "no encontrado").
    logger.info(
        "password_reset.solicitud email=%s ip=%s cuenta_encontrada=%s",
        req.email, ip, usuario is not None,
    )

    if usuario is not None:
        token = await crear_token_reset(usuario.rfc_personal)
        background_tasks.add_task(enviar_correo_reset, usuario.email, token)

    return {"mensaje": RESET_MENSAJE_GENERICO}


@app.post("/auth/password-reset/confirm")
async def password_reset_confirm(req: PasswordResetConfirmRequest, db: AsyncSession = Depends(get_db)):
    """Publico, mismo motivo que password_reset_request de arriba."""
    # Complejidad de la contrasena ANTES de tocar el token - si el usuario
    # escribe una contrasena demasiado corta, el token debe seguir sirviendo
    # para un segundo intento real, no perderse por un error de formulario.
    nueva_password = validar_password_nueva(req.nueva_password)

    # consumir_token_reset borra el token atomicamente (GETDEL) al leerlo -
    # a partir de aqui, sea cual sea el resultado, ese token ya no sirve
    # para nada mas, incluso si el resto de esta funcion falla despues.
    rfc_personal = await consumir_token_reset(req.token)

    MENSAJE_TOKEN_INVALIDO = "El enlace de recuperación no es válido, ya expiró o ya fue utilizado."

    if rfc_personal is None:
        # Sin distinguir "no existe" / "expiro" / "ya se uso" - las 3 son
        # el mismo caso desde la perspectiva del caller (requisito
        # explicito: no filtrar detalles sensibles sobre el motivo).
        raise HTTPException(status_code=400, detail=MENSAJE_TOKEN_INVALIDO)

    result = await db.execute(select(Usuario).where(Usuario.rfc_personal == rfc_personal))
    usuario = result.scalar_one_or_none()
    if usuario is None:
        # Caso raro (cuenta borrada entre la solicitud y la confirmacion) -
        # mismo mensaje generico que un token invalido, no uno distinto.
        raise HTTPException(status_code=400, detail=MENSAJE_TOKEN_INVALIDO)

    usuario.password_hash = bcrypt.hashpw(nueva_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await db.flush()

    # Invalidacion de sesiones activas previas: NO implementada (marcada
    # como opcional en el requisito). Los JWT de este servicio son
    # stateless (el Gateway solo verifica firma/expiracion, nunca consulta
    # Redis/BD por cada request) - invalidar tokens ya emitidos de verdad
    # requeriria agregar un chequeo de revocacion en verify_token() del
    # Gateway (una llamada extra, a Redis o similar, en CADA request
    # proxiada, no solo en las de este servicio), un cambio de arquitectura
    # mas amplio que este requisito no pidio explicitamente. Mitigante ya
    # existente: los JWT expiran solos a la 1h (ver JWT_ALGORITHM arriba),
    # asi que la ventana de exposicion tras un reset tiene un techo corto.
    logger.info("password_reset.confirmado rfc=%s", rfc_personal)

    return {"mensaje": "Contraseña actualizada correctamente."}


@app.get("/auth/usuarios", response_model=List[UsuarioListItem], dependencies=[Depends(require_internal_key)])
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
