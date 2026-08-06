import os

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
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

    forward_headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    # Inyectado tras verificar el JWT (#15) - el downstream nunca decodifica
    # el token el mismo, confia en este header. negocio_id solo existe en
    # tokens emitidos despues de #15; los anteriores no lo tienen, y el
    # downstream cae a su Negocio por defecto (resolver_negocio_id en
    # administracion).
    if "negocio_id" in token and token["negocio_id"] is not None:
        forward_headers["X-Negocio-Id"] = str(token["negocio_id"])
    if "sub" in token and token["sub"] is not None:
        forward_headers["X-Usuario-Email"] = str(token["sub"])

    async with httpx.AsyncClient(timeout=30.0) as client:
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
