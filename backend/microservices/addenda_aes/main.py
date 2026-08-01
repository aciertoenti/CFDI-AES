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

@app.get("/addenda/{cliente_key}/schema")
async def obtener_schema(cliente_key: str):
    if cliente_key not in SCHEMAS:
        raise HTTPException(status_code=404, detail="Schema no encontrado")
    return {"cliente": cliente_key, "campos": SCHEMAS[cliente_key]}

@app.post("/addenda/aplicar")
async def aplicar_addenda(req: AddendaRequest):
    return {"uuid": req.uuid_cfdi, "addenda_aplicada": req.cliente_key, "estado": "OK"}

@app.get("/health")
async def health():
    return {"service": "addenda", "status": "ok"}
