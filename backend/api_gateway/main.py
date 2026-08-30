import os

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import jwt

app = FastAPI(title="CFDI – API Gateway", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])

security = HTTPBearer()

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET no está definido. Configúralo como variable de entorno.")
JWT_ALGORITHM = "HS256"

# Rewiring de IA al Gateway (13 ago 2026) - ia:8007 ahora exige X-Internal-Key
# en sus 6 endpoints (antes completamente abierto, sin JWT ni ningun otro
# mecanismo - cualquiera que alcanzara el puerto podia gastar credito real de
# Anthropic). El Gateway es el unico llamante legitimo: ya exige el JWT del
# usuario (verify_token) antes de agregar este header, asi que una clave
# interna robada sin JWT valido no basta para llegar hasta aqui.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
if not INTERNAL_API_KEY:
    raise RuntimeError("INTERNAL_API_KEY no está definido. Configúralo como variable de entorno.")

# Confianza en el X-Forwarded-For entrante (30 ago 2026). La topologia
# actual NO tiene reverse proxy real delante del Gateway (docker-compose:
# gateway expone 8000:8000 directo, el unico nginx sirve el SPA y no hace
# proxy) - confirmado. Sin proxy de confianza, cualquier X-Forwarded-For
# que llegue es 100% spoof del cliente. Por defecto (env ausente) el
# Gateway lo DESCARTA y usa solo la IP TCP real (request.client.host).
# Solo cuando se ponga un proxy/balanceador real en produccion se pone
# TRUST_PROXY_XFF=true y se vuelve a encadenar el salto previo.
TRUST_PROXY_XFF = os.environ.get("TRUST_PROXY_XFF", "").lower() in ("1", "true", "yes")

SERVICES = {
    "facturas": "http://facturacion:8001",
    "admin": "http://administracion:8002",
    "addenda": "http://addenda_aes:8003",  # corregido (#48) - el servicio real en docker-compose es "addenda_aes", no "addenda"
    "reportes": "http://reportes:8004",
    "auth": "http://auth:8005",
    "bot": "http://whatsapp_bot:8006",   # WhatsApp bot (webhook público + API interna)
    "ia": "http://ia:8007",  # agregado (#48) - faltaba por completo; rewiring del frontend queda en tarjeta aparte
}


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


@app.post("/auth/login")
async def login_proxy(request: Request):
    """
    Publica a proposito (#48): no puede exigir verify_token, porque login
    es precisamente el paso que TODAVIA no tiene token. Debe registrarse
    antes que la ruta generica /{service}/{path:path} - Starlette empata
    por orden de registro, no por especificidad, y verify_token es una
    dependencia de esa ruta generica que rechazaria esta llamada primero.
    """
    target = f"{SERVICES['auth']}/auth/login"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method="POST",
            url=target,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=await request.body(),
        )
    # Rate limiting de login (13 ago 2026, #48-ratelimit): un 429 de
    # auth_usuarios trae Retry-After - sin este forward explicito se
    # perderia (JSONResponse de abajo solo lleva status_code, nunca copia
    # headers del downstream).
    headers_extra = {}
    if "Retry-After" in resp.headers:
        headers_extra["Retry-After"] = resp.headers["Retry-After"]
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code, headers=headers_extra)
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.post("/auth/registro")
async def registro_proxy(request: Request):
    """
    Publica a proposito (#15), mismo motivo que /auth/login: "crear cuenta"
    es, como login, un paso previo a tener un token.
    """
    target = f"{SERVICES['auth']}/auth/registro"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method="POST",
            url=target,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=await request.body(),
        )
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.post("/auth/password-reset/request")
async def password_reset_request_proxy(request: Request):
    """
    Publica a proposito (#48-reset), mismo motivo que /auth/login: quien
    pide un reset todavia no tiene sesion. Inyecta X-Forwarded-For con la
    IP real del cliente que llego al Gateway (request.client.host) - el
    rate limit de auth_usuarios (10 solicitudes/hora) es por IP, y sin este
    header ese servicio solo veria la IP del propio Gateway en el header
    Host recibido (la conexion httpx sale del contenedor gateway), lo que
    contaria a TODOS los usuarios reales como una sola IP compartida.
    """
    target = f"{SERVICES['auth']}/auth/password-reset/request"
    forward_headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    client_ip = request.client.host if request.client else "desconocida"
    # Fix de seguridad (26 ago 2026): se usa pop() en vez de get() para
    # ELIMINAR el X-Forwarded-For entrante (cualquier casing) al leerlo, no
    # solo copiar su valor - asi no quedan dos llaves coexistiendo.
    #
    # Fix de seguridad (30 ago 2026): antes se reencadenaba SIEMPRE como
    # "{xff_previo}, {client_ip}". Como auth_usuarios hace rate-limit sobre
    # xff.split(",")[0] (el PRIMER salto), y no hay reverse proxy real
    # delante del Gateway (topologia confirmada), un atacante que mande
    # X-Forwarded-For: <valor rotado> se salta el limite de 10/hora de
    # password-reset por completo. Por defecto ahora se DESCARTA el XFF
    # entrante y se manda solo la IP TCP real. El reencadenado del salto
    # previo solo ocurre con TRUST_PROXY_XFF=true (proxy real en prod).
    xff_previo = forward_headers.pop("x-forwarded-for", None) or forward_headers.pop("X-Forwarded-For", None)
    if TRUST_PROXY_XFF and xff_previo:
        forward_headers["X-Forwarded-For"] = f"{xff_previo}, {client_ip}"
    else:
        forward_headers["X-Forwarded-For"] = client_ip

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method="POST",
            url=target,
            headers=forward_headers,
            content=await request.body(),
        )
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.post("/auth/password-reset/confirm")
async def password_reset_confirm_proxy(request: Request):
    """Publica, mismo motivo que password_reset_request_proxy - no aplica
    rate limit por IP aqui (el token de un solo uso ya es la proteccion
    real: cada uno solo sirve una vez, sin importar cuantas veces se
    intente)."""
    target = f"{SERVICES['auth']}/auth/password-reset/confirm"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method="POST",
            url=target,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=await request.body(),
        )
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.post("/auth/password/change")
async def password_change_proxy(request: Request, token=Depends(verify_token)):
    """Actualiza la contraseña solo para usuarios autenticados."""
    target = f"{SERVICES['auth']}/auth/password/change"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method="POST",
            url=target,
            headers=headers,
            content=await request.body(),
        )
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.post("/ia/chat/stream")
async def ia_chat_stream_proxy(request: Request, token=Depends(verify_token)):
    """
    Ruta dedicada (13 ago 2026, rewiring de IA) - el proxy() generico de
    abajo espera la respuesta completa del downstream (resp.json()) antes de
    devolver nada, lo que no sirve para Server-Sent Events: el navegador
    necesita los tokens de Chat Fiscal a medida que Claude los genera, no
    todos de golpe al final. Debe registrarse ANTES de proxy() - Starlette
    empata por orden de registro (mismo motivo que /auth/login y
    /auth/registro van antes que la ruta generica).
    """
    target = f"{SERVICES['ia']}/ia/chat/stream"
    body = await request.body()

    forward_headers = {"Content-Type": "application/json", "X-Internal-Key": INTERNAL_API_KEY}
    if "negocio_id" in token and token["negocio_id"] is not None:
        forward_headers["X-Negocio-Id"] = str(token["negocio_id"])
    if "email" in token and token["email"] is not None:
        forward_headers["X-Usuario-Email"] = str(token["email"])
    if "sub" in token and token["sub"] is not None:
        forward_headers["X-Usuario-Rfc"] = str(token["sub"])

    async def event_generator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", target, content=body, headers=forward_headers) as resp:
                async for chunk in resp.aiter_raw():
                    yield chunk

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.api_route("/{service}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(service: str, request: Request, path: str = "", token=Depends(verify_token)):
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Servicio '{service}' no encontrado")

    # Corregido (#48): las rutas reales de cada microservicio YA incluyen su
    # propio prefijo (/admin/..., /auth/..., /facturas/...) - "service" aqui
    # es solo la clave de enrutamiento del gateway, no un segmento a
    # descartar. Antes se perdia ese prefijo al reenviar, y el downstream
    # nunca encontraba la ruta real (probado en vivo: gateway:8000/admin/emisores
    # reenviaba a administracion:8002/emisores, que no existe).
    full_path = f"{service}/{path}" if path else service
    target = f"{SERVICES[service]}/{full_path}"

    # Fix de seguridad (26 ago 2026): antes solo se excluia "host", dejando que
    # el cliente inyectara sus propios X-Negocio-Id/X-Usuario-Email/X-Usuario-Rfc/
    # X-Internal-Key con distinto casing (ej. "x-negocio-id" en minusculas) que
    # coexistian como llaves DISTINTAS junto a las que este mismo proxy agrega
    # abajo con mayusculas - el downstream terminaba leyendo el valor del
    # atacante, no el del servidor (confirmado explotable: fuga cross-tenant
    # real via X-Negocio-Id). Se excluyen aqui TODOS los headers de confianza
    # que este proxy fija mas abajo, sin importar el casing con que llegaron
    # del cliente, para que no puedan colisionar.
    HEADERS_DE_CONFIANZA = {"host", "x-negocio-id", "x-usuario-email", "x-usuario-rfc", "x-internal-key"}
    forward_headers = {k: v for k, v in request.headers.items() if k.lower() not in HEADERS_DE_CONFIANZA}
    # Inyectado tras verificar el JWT (#15) - el downstream nunca decodifica
    # el token el mismo, confia en este header. negocio_id solo existe en
    # tokens emitidos despues de #15; los anteriores no lo tienen, y el
    # downstream cae a su Negocio por defecto (resolver_negocio_id en
    # administracion).
    if "negocio_id" in token and token["negocio_id"] is not None:
        forward_headers["X-Negocio-Id"] = str(token["negocio_id"])
    # "sub" dejo de ser el email (ahora es rfc_personal, ver auth_usuarios
    # #15-login) - X-Usuario-Email debe leer el claim "email" explicito,
    # no "sub", para que el header siga siendo fiel a su nombre.
    if "email" in token and token["email"] is not None:
        forward_headers["X-Usuario-Email"] = str(token["email"])
    # sub ya es rfc_personal desde el cambio de login (#15-login) - no hace
    # falta descifrar nada nuevo, solo reenviarlo. Usado para auditoria
    # (quien timbro/cancelo/dio de alta), no como control de seguridad.
    if "sub" in token and token["sub"] is not None:
        forward_headers["X-Usuario-Rfc"] = str(token["sub"])
    # Rewiring de IA (13 ago 2026): agregado aqui, en el proxy generico, para
    # que cubra tambien /ia/* sin necesitar una rama especial por servicio -
    # los demas microservicios simplemente no lo validan todavia (ver #58,
    # hallazgo aparte, fuera de alcance aqui).
    forward_headers["X-Internal-Key"] = INTERNAL_API_KEY

    # Timeout subido de 30s a 60s (27 ago 2026) - un timbrado real contra
    # Finkok tardo 34.6s en pruebas, mas que el timeout anterior. El gateway
    # cortaba la conexion ANTES de que el PAC respondiera, devolviendo
    # 500/error al usuario mientras facturacion seguia procesando en segundo
    # plano y completaba el timbrado con exito - riesgo real de que el
    # usuario, viendo el error, reintente y genere una SEGUNDA factura real
    # timbrada para la misma operacion (un CFDI ya timbrado no se puede
    # borrar, solo cancelar formalmente ante el SAT). 60s da margen razonable
    # sobre los 34.6s observados. Nota: esto reduce la ventana de riesgo, no
    # la elimina del todo - una solucion mas robusta (ej. idempotencia real
    # en el timbrado, o polling de estado en vez de esperar la respuesta
    # sincrona completa) queda como mejora de fondo pendiente, documentada
    # en tarjeta de backlog aparte.
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(
            method=request.method,
            url=target,
            headers=forward_headers,
            content=await request.body(),
            params=dict(request.query_params),
        )

    # Corregido (#48): antes se devolvia resp.json() directo, lo que FastAPI
    # siempre serializa con 200 - un 401/404/500 real del downstream le
    # llegaba al frontend disfrazado de 200. JSONResponse preserva el status
    # code real.
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.get("/health")
async def health():
    return {"service": "gateway", "status": "ok"}
