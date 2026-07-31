import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import jwt

app = FastAPI(title="CFDI – Auth", version="2.0.0")

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

@app.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    payload = {
        "sub": req.email,
        "rfc_emisor": "DNS010101AAA",
        "roles": ["admin"],
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
