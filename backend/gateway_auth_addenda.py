# ─── gateway/main.py ──────────────────────────────────────────────────────────
# API Gateway centralizado
# Puerto: 8000
# Responsabilidades: Autenticación JWT, rate limiting, routing a microservicios
# ──────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import jwt
from datetime import datetime, timedelta

app = FastAPI(title="CFDI – API Gateway", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])

security = HTTPBearer()
JWT_SECRET = "CAMBIA_ESTO_EN_PRODUCCION"
JWT_ALGORITHM = "HS256"

SERVICES = {
    "facturas":       "http://facturacion:8001",
    "admin":          "http://administracion:8002",
    "addenda":        "http://addenda:8003",
    "reportes":       "http://reportes:8004",
    "auth":           "http://auth:8005",
}

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

@app.api_route("/{service}/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH"])
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
    return resp.json()

@app.get("/health")
async def health():
    return {"service": "gateway", "status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# ─── services/auth/main.py ────────────────────────────────────────────────────
# Microservicio de Autenticación y Usuarios – Puerto 8005
# ═══════════════════════════════════════════════════════════════════════════════
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import jwt, bcrypt

app = FastAPI(title="CFDI – Auth", version="2.0.0")
JWT_SECRET = "CAMBIA_ESTO_EN_PRODUCCION"

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600

@app.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    # En producción: buscar usuario en DB, verificar bcrypt hash
    # user = await db.fetch_one("SELECT * FROM usuarios WHERE email=:email", {"email": req.email})
    # if not user or not bcrypt.checkpw(req.password.encode(), user["password_hash"]):
    #     raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    payload = {
        "sub": req.email,
        "rfc_emisor": "DNS010101AAA",
        "roles": ["admin"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return TokenResponse(access_token=token, expires_in=3600)

@app.post("/auth/logout")
async def logout():
    # En producción: invalidar token en Redis blacklist
    return {"mensaje": "Sesión cerrada"}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# ─── services/addenda/main.py ─────────────────────────────────────────────────
# Microservicio de Addenda AES – Puerto 8003
# ═══════════════════════════════════════════════════════════════════════════════
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI(title="CFDI – Addenda AES", version="2.0.0")

SCHEMAS = {
    "walmart": ["NumProveedor","OrdenCompra","Departamento"],
    "femsa":   ["CentroLogistico","ClaveArticulo","NumPedido"],
    "liverpool":["CodigoProveedor","Sucursal","FolioRequisicion"],
    "soriana": ["NumProveedor","ClaveArticulo","Almacen"],
}

class AddendaRequest(BaseModel):
    cliente_key: str   # ej: "walmart"
    uuid_cfdi: str
    datos: Dict[str, Any]

@app.get("/addenda/schemas")
async def listar_schemas():
    return SCHEMAS

@app.get("/addenda/{cliente_key}/schema")
async def obtener_schema(cliente_key: str):
    if cliente_key not in SCHEMAS:
        raise HTTPException(status_code=404, detail="Schema no encontrado")
    return {"cliente": cliente_key, "campos": SCHEMAS[cliente_key]}

@app.post("/addenda/aplicar")
async def aplicar_addenda(req: AddendaRequest):
    # 1. Obtener XML desde almacenamiento
    # 2. Validar datos contra schema del cliente
    # 3. Inyectar nodo <Addenda> en el XML
    # 4. Guardar XML actualizado
    return {"uuid": req.uuid_cfdi, "addenda_aplicada": req.cliente_key, "estado": "OK"}
"""
