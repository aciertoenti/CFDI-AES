from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

from shared.internal_key import require_internal_key

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

@app.get("/addenda/schemas", dependencies=[Depends(require_internal_key)])
async def listar_schemas():
    """
    Sin X-Negocio-Id: el catalogo de schemas (SCHEMAS) es estatico y global,
    no hay ningun dato por-negocio que aislar todavia - addenda_aes no toca
    ninguna base de datos (ver tarjeta 229036865, dimensionamiento 20 ago
    2026). X-Internal-Key si aplica (bloquea bypass directo del Gateway).
    """
    return SCHEMAS

def _validar_cliente_key(cliente_key: str) -> list:
    if cliente_key not in SCHEMAS:
        raise HTTPException(status_code=404, detail="Schema no encontrado")
    return SCHEMAS[cliente_key]

@app.get("/addenda/{cliente_key}/schema", dependencies=[Depends(require_internal_key)])
async def obtener_schema(cliente_key: str):
    """Sin X-Negocio-Id: mismo motivo que GET /addenda/schemas arriba."""
    campos = _validar_cliente_key(cliente_key)
    return {"cliente": cliente_key, "campos": campos}

@app.post("/addenda/aplicar", dependencies=[Depends(require_internal_key)])
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
    #
    # Sin X-Negocio-Id: mismo motivo que los 2 endpoints GET de arriba - no
    # hay ningun dato por-negocio que este endpoint lea o escriba todavia
    # (ni siquiera persiste nada real, ver placeholder arriba).
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
