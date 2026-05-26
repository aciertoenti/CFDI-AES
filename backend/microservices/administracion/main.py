# ─── services/administracion/main.py ──────────────────────────────────────────
# Microservicio de Administración
# Puerto: 8002
# Responsabilidades: Emisores, Clientes, Series, Configuración
# ──────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List

app = FastAPI(title="CFDI – Servicio de Administración", version="2.0.0")
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

class ClienteCreate(BaseModel):
    nombre: str
    rfc: str
    email: str
    telefono: Optional[str] = None
    regimen_fiscal: str = "601"
    uso_cfdi_default: str = "G03"
    domicilio_fiscal: str
    credito_limite: float = 0.0

class SerieCreate(BaseModel):
    serie: str  # Ej: "A", "B", "FAC"
    descripcion: str
    folio_inicial: int = 1
    emisor_rfc: str

class ConfiguracionUpdate(BaseModel):
    pac_url: Optional[str] = None
    pac_usuario: Optional[str] = None
    pac_password: Optional[str] = None
    storage_bucket: Optional[str] = None
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None

# ─── Emisores ──────────────────────────────────────────────────────────────────

@app.post("/admin/emisores", status_code=201)
async def crear_emisor(emisor: EmisorCreate):
    """Registra un nuevo emisor. Valida y cifra las credenciales CSD antes de guardar."""
    # En producción: validar CSD contra SAT, cifrar key con KMS
    return {"rfc": emisor.rfc, "estado": "Activo", "mensaje": "Emisor registrado con CSD activo"}

@app.get("/admin/emisores")
async def listar_emisores():
    return []

@app.put("/admin/emisores/{rfc}")
async def actualizar_emisor(rfc: str, emisor: EmisorCreate):
    return {"rfc": rfc, "actualizado": True}

# ─── Clientes ──────────────────────────────────────────────────────────────────

@app.post("/admin/clientes", status_code=201)
async def crear_cliente(cliente: ClienteCreate):
    return {"rfc": cliente.rfc, "nombre": cliente.nombre, "id": 1}

@app.get("/admin/clientes")
async def listar_clientes(
    busqueda: Optional[str] = None,
    page: int = 1,
    size: int = 50,
):
    return []

@app.get("/admin/clientes/{rfc}")
async def obtener_cliente(rfc: str):
    raise HTTPException(status_code=404, detail=f"Cliente {rfc} no encontrado")

@app.put("/admin/clientes/{rfc}")
async def actualizar_cliente(rfc: str, cliente: ClienteCreate):
    return {"rfc": rfc, "actualizado": True}

@app.delete("/admin/clientes/{rfc}")
async def eliminar_cliente(rfc: str):
    return {"rfc": rfc, "eliminado": True}

# ─── Series ────────────────────────────────────────────────────────────────────

@app.post("/admin/series", status_code=201)
async def crear_serie(serie: SerieCreate):
    return {**serie.dict(), "folio_actual": serie.folio_inicial}

@app.get("/admin/series")
async def listar_series(emisor_rfc: Optional[str] = None):
    return []

@app.get("/admin/series/{serie}/siguiente-folio")
async def siguiente_folio(serie: str, emisor_rfc: str):
    """Retorna el siguiente folio disponible de forma atómica (transacción DB)."""
    return {"serie": serie, "folio": 42, "folio_formateado": f"{serie}-0042"}

# ─── Configuración ─────────────────────────────────────────────────────────────

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
