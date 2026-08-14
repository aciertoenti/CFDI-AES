from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI(title="CFDI – Addenda AES", version="2.0.0")

SCHEMAS = {
    "walmart": ["NumProveedor", "OrdenCompra", "Departamento"],
    "femsa": ["CentroLogistico", "ClaveArticulo", "NumPedido"],
    "liverpool": ["CodigoProveedor", "Sucursal", "FolioRequisicion"],
    "soriana": ["NumProveedor", "ClaveArticulo", "Almacen"],
}

class AddendaRequest(BaseModel):
    cliente_key: str
    uuid_cfdi: str
    datos: Dict[str, Any]

@app.get("/addenda/schemas")
async def listar_schemas():
    return SCHEMAS

def _validar_cliente_key(cliente_key: str) -> list:
    if cliente_key not in SCHEMAS:
        raise HTTPException(status_code=404, detail="Schema no encontrado")
    return SCHEMAS[cliente_key]

@app.get("/addenda/{cliente_key}/schema")
async def obtener_schema(cliente_key: str):
    campos = _validar_cliente_key(cliente_key)
    return {"cliente": cliente_key, "campos": campos}

@app.post("/addenda/aplicar")
async def aplicar_addenda(req: AddendaRequest):
    # Placeholder honesto (tarjeta 224211735, alcance acotado via tarjeta
    # madre de MVP 229037180) - antes este endpoint respondia "estado":"OK"
    # sin validar, sin persistir ni tocar el XML del CFDI, sin importar el
    # input. Ahora falla explicito: 404 si el cliente_key ni siquiera existe
    # en el catalogo, 501 si existe pero la insercion real en el XML todavia
    # no esta implementada (ningun cliente_key la tiene implementada hoy).
    # Si un cliente confirma necesitar una addenda especifica antes de que
    # esto se implemente de verdad, ver plan de contingencia en 229036181
    # (comprar addenda de un proveedor como Facturama en vez de bloquear).
    _validar_cliente_key(req.cliente_key)
    raise HTTPException(
        status_code=501,
        detail=(
            f"La addenda para '{req.cliente_key}' aun no esta implementada. "
            f"Consulta el catalogo de addendas disponibles en "
            f"GET /addenda/{req.cliente_key}/schema."
        ),
    )

@app.get("/health")
async def health():
    return {"service": "addenda", "status": "ok"}
