import os
from decimal import Decimal
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from uuid import uuid4
import httpx

from satcfdi.models import Signer
from satcfdi.create.cfd.cfdi40 import Comprobante, Emisor, Receptor, Concepto as ConceptoCFDI, Impuestos, Traslado

load_dotenv()

app = FastAPI(title="CFDI – Servicio de Facturación", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Concepto(BaseModel):
    descripcion: str
    cantidad: float = Field(gt=0)
    precio_unitario: float = Field(gt=0)
    clave_prod_serv: str = "01010101"
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
    tipo_comprobante: str = "I"
    metodo_pago: str = "PUE"
    forma_pago: str = "03"

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
    motivo: str
    uuid_sustitucion: Optional[str] = None

# ─── CSD y generación de XML CFDI 4.0 (paso 2 — NO conectado a Finkok todavía) ─
# Datos del emisor de PRUEBA, atados al CSD EKU9003173C9 configurado en
# CSD_CERT_PATH/CSD_KEY_PATH/CSD_PASSWORD. "administracion" todavia no
# persiste emisores reales, por eso el regimen y el CP de expedicion no
# vienen en el contrato de FacturaCreate y se fijan aqui como default de
# prueba. Ambos deben revisarse antes de timbrar con Finkok real.
EMISOR_REGIMEN_FISCAL_TEST = "601"
LUGAR_EXPEDICION_TEST = "42501"


@lru_cache
def get_signer() -> Signer:
    cert_path = os.environ.get("CSD_CERT_PATH")
    key_path = os.environ.get("CSD_KEY_PATH")
    password = os.environ.get("CSD_PASSWORD")
    if not (cert_path and key_path and password):
        raise HTTPException(
            status_code=500,
            detail="CSD_CERT_PATH, CSD_KEY_PATH y CSD_PASSWORD deben estar configurados (ver .env)",
        )
    try:
        with open(cert_path, "rb") as f:
            cert_bytes = f.read()
        with open(key_path, "rb") as f:
            key_bytes = f.read()
        return Signer.load(certificate=cert_bytes, key=key_bytes, password=password)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"No se encontro el archivo del CSD: {e.filename}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo cargar el CSD: {e}")


def construir_comprobante(factura: FacturaCreate, signer: Signer) -> Comprobante:
    if factura.emisor_rfc != str(signer.rfc):
        raise HTTPException(
            status_code=400,
            detail=f"emisor_rfc ({factura.emisor_rfc}) no coincide con el RFC del CSD cargado ({signer.rfc})",
        )

    emisor = Emisor(
        rfc=str(signer.rfc),
        nombre=signer.legal_name,
        regimen_fiscal=EMISOR_REGIMEN_FISCAL_TEST,
    )
    receptor = Receptor(
        rfc=factura.receptor.rfc,
        nombre=factura.receptor.nombre,
        domicilio_fiscal_receptor=factura.receptor.domicilio_fiscal,
        regimen_fiscal_receptor=factura.receptor.regimen_fiscal,
        uso_cfdi=factura.receptor.uso_cfdi,
    )
    conceptos = [
        ConceptoCFDI(
            clave_prod_serv=c.clave_prod_serv,
            cantidad=Decimal(str(c.cantidad)),
            clave_unidad=c.clave_unidad,
            descripcion=c.descripcion,
            valor_unitario=Decimal(str(c.precio_unitario)),
            impuestos=Impuestos(
                traslados=Traslado(
                    impuesto="002",
                    tipo_factor="Tasa",
                    tasa_o_cuota=Decimal(str(c.iva_tasa)),
                )
            ) if c.iva_tasa else None,
        )
        for c in factura.conceptos
    ]

    comprobante = Comprobante(
        emisor=emisor,
        lugar_expedicion=LUGAR_EXPEDICION_TEST,
        receptor=receptor,
        conceptos=conceptos,
        moneda=factura.moneda,
        tipo_de_comprobante=factura.tipo_comprobante,
        serie=factura.serie,
        metodo_pago=factura.metodo_pago,
        forma_pago=factura.forma_pago,
    )
    comprobante.sign(signer)
    return comprobante


@app.post("/facturas/generar-xml", response_class=PlainTextResponse)
async def generar_xml_firmado(factura: FacturaCreate):
    """
    ENDPOINT TEMPORAL DE PRUEBA — genera y firma el XML CFDI 4.0 (cadena
    original + sello) con el CSD de prueba configurado, pero NO lo envia
    a Finkok ni lo persiste. Es solo para inspeccionar el XML resultante
    antes de conectar el PAC (paso 3).
    """
    signer = get_signer()
    comprobante = construir_comprobante(factura, signer)
    xml_bytes = comprobante.xml_bytes(pretty_print=True)
    return PlainTextResponse(content=xml_bytes.decode("utf-8"), media_type="application/xml")


@app.post("/facturas/timbrar", response_model=FacturaResponse, status_code=201)
async def timbrar_factura(factura: FacturaCreate):
    subtotal = sum(c.cantidad * c.precio_unitario for c in factura.conceptos)
    total_iva = sum(c.cantidad * c.precio_unitario * c.iva_tasa for c in factura.conceptos)
    total = subtotal + total_iva
    folio = f"A-{str(uuid4().int)[:4].zfill(4)}"
    uuid_cfdi = str(uuid4()).upper()

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
    return []

@app.get("/facturas/{uuid}")
async def obtener_factura(uuid: str):
    raise HTTPException(status_code=404, detail=f"Factura {uuid} no encontrada")

@app.get("/facturas/{uuid}/xml")
async def descargar_xml(uuid: str):
    return {"url": f"https://storage.tudominio.mx/cfdi/{uuid}.xml"}

@app.get("/facturas/{uuid}/pdf")
async def descargar_pdf(uuid: str):
    return {"url": f"https://storage.tudominio.mx/cfdi/{uuid}.pdf"}

@app.post("/facturas/{uuid}/cancelar")
async def cancelar_factura(uuid: str, req: CancelacionRequest):
    return {"uuid": uuid, "estado_cancelacion": "Pendiente aceptación receptor", "acuse": None}

@app.get("/facturas/reporte/mensual")
async def reporte_mensual(anio: int = 2025, mes: int = Query(ge=1, le=12)):
    return {
        "anio": anio,
        "mes": mes,
        "total_emitido": 302450.00,
        "total_cancelado": 9800.00,
        "count_vigentes": 4,
        "count_canceladas": 1,
    }

@app.get("/health")
async def health():
    return {"service": "facturacion", "status": "ok", "version": "2.0.0"}
