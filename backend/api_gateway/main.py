import os

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
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
    "addenda": "http://addenda:8003",
    "reportes": "http://reportes:8004",
    "auth": "http://auth:8005",
    "bot": "http://whatsapp_bot:8006",   # WhatsApp bot (webhook público + API interna)
}


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(service: str, path: str, request: Request, token=Depends(verify_token)):
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Servicio '{service}' no encontrado")

    target = f"{SERVICES[service]}/{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method=request.method,
            url=target,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            content=await request.body(),
            params=dict(request.query_params),
        )

    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio downstream")


@app.get("/health")
async def health():
    return {"service": "gateway", "status": "ok"}
