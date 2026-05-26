# ─── services/facturacion/main.py ─────────────────────────────────────────────
# Microservicio de Facturación CFDI 4.0
# Puerto: 8001
# Responsabilidades: Nueva factura, timbrado PAC, generadas, recibidas, cancelación
# ──────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from uuid import uuid4
import httpx

app = FastAPI(title="CFDI – Servicio de Facturación", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Modelos ───────────────────────────────────────────────────────────────────

class Concepto(BaseModel):
    descripcion: str
    cantidad: float = Field(gt=0)
    precio_unitario: float = Field(gt=0)
    clave_prod_serv: str = "01010101"  # SAT key
    clave_unidad: str = "H87"
    iva_tasa: float = 0.16

class ReceptorCFDI(BaseModel):
    nombre: str
    rfc: str
    uso_cfdi: str = "G03"
    regimen_fiscal: str = "601"
    domicilio_fiscal: str

class FacturaCreate(BaseModel):
    emisor_rfc: str
    receptor: ReceptorCFDI
    conceptos: List[Concepto]
    serie: str = "A"
    moneda: str = "MXN"
    tipo_comprobante: str = "I"  # I=Ingreso, E=Egreso, T=Traslado
    metodo_pago: str = "PUE"
    forma_pago: str = "03"  # Transferencia

class FacturaResponse(BaseModel):
    uuid: str
    folio: str
    serie: str
    fecha_timbrado: datetime
    subtotal: float
    total_iva: float
    total: float
    estado: str
    xml_url: str
    pdf_url: str
    noCertificadoSAT: Optional[str] = None

class CancelacionRequest(BaseModel):
    uuid: str
    motivo: str  # 01=Comprobante emitido con errores con relación, 02=sin relación, etc.
    uuid_sustitucion: Optional[str] = None

# ─── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/facturas/timbrar", response_model=FacturaResponse, status_code=201)
async def timbrar_factura(factura: FacturaCreate):
    """
    Genera el XML CFDI 4.0, lo firma con el CSD del emisor
    y lo envía al PAC para timbrado ante el SAT.
    """
    # 1. Calcular totales
    subtotal = sum(c.cantidad * c.precio_unitario for c in factura.conceptos)
    total_iva = sum(c.cantidad * c.precio_unitario * c.iva_tasa for c in factura.conceptos)
    total = subtotal + total_iva

    # 2. Generar folio (en producción: consultar BD de series)
    folio = f"A-{str(uuid4().int)[:4].zfill(4)}"
    uuid_cfdi = str(uuid4()).upper()

    # 3. Construir XML CFDI 4.0 (aquí iría el builder real con lxml)
    # xml_string = build_cfdi_xml(factura, subtotal, total_iva, total)

    # 4. Firmar con CSD
    # xml_sellado = sign_xml(xml_string, csd_cert, csd_key)

    # 5. Enviar al PAC para timbrado (ej: Finkok, Diverza, FiscoClic)
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(PAC_URL, content=xml_sellado)

    # 6. Guardar en BD y almacenar XML/PDF en S3
    return FacturaResponse(
        uuid=uuid_cfdi,
        folio=folio,
        serie=factura.serie,
        fecha_timbrado=datetime.utcnow(),
        subtotal=subtotal,
        total_iva=total_iva,
        total=total,
        estado="Vigente",
        xml_url=f"https://storage.tudominio.mx/cfdi/{uuid_cfdi}.xml",
        pdf_url=f"https://storage.tudominio.mx/cfdi/{uuid_cfdi}.pdf",
    )


@app.get("/facturas", response_model=List[FacturaResponse])
async def listar_facturas(
    tipo: str = Query("generadas", enum=["generadas", "recibidas"]),
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    rfc_receptor: Optional[str] = None,
    page: int = 1,
    size: int = 50,
):
    """Lista facturas generadas o recibidas con filtros opcionales."""
    # En producción: query a la BD con los filtros
    return []


@app.get("/facturas/{uuid}")
async def obtener_factura(uuid: str):
    """Retorna el detalle completo de una factura por su UUID fiscal."""
    raise HTTPException(status_code=404, detail=f"Factura {uuid} no encontrada")


@app.get("/facturas/{uuid}/xml")
async def descargar_xml(uuid: str):
    """Descarga el XML timbrado desde almacenamiento S3."""
    # En producción: obtener URL firmada de S3/MinIO
    return {"url": f"https://storage.tudominio.mx/cfdi/{uuid}.xml"}


@app.get("/facturas/{uuid}/pdf")
async def descargar_pdf(uuid: str):
    """Descarga la representación impresa (PDF) del CFDI."""
    return {"url": f"https://storage.tudominio.mx/cfdi/{uuid}.pdf"}


@app.post("/facturas/{uuid}/cancelar")
async def cancelar_factura(uuid: str, req: CancelacionRequest):
    """
    Solicita la cancelación del CFDI ante el SAT.
    El SAT retorna aceptación inmediata o pending si requiere aceptación del receptor.
    """
    # En producción: llamar PAC cancellation endpoint
    return {"uuid": uuid, "estado_cancelacion": "Pendiente aceptación receptor", "acuse": None}


@app.get("/facturas/reporte/mensual")
async def reporte_mensual(anio: int = 2025, mes: int = Query(ge=1, le=12)):
    """Agrega totales y conteos de facturas por mes."""
    return {
        "anio": anio,
        "mes": mes,
        "total_emitido": 302450.00,
        "total_cancelado": 9800.00,
        "count_vigentes": 4,
        "count_canceladas": 1,
    }


# ─── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"service": "facturacion", "status": "ok", "version": "2.0.0"}
