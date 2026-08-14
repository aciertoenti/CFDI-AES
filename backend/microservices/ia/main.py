# ─── Rescatado de backend/api_gateway/main.py (commit bdb9550) ───────────────
# Este código vivía por error dentro del API Gateway. El gateway fue
# reescrito para ser un proxy JWT hacia los microservicios (ver
# backend/api_gateway/main.py actual), y este módulo de IA quedó fuera de
# esa reescritura. Se movió aquí, a su microservicio propio (Fase 3 del
# roadmap — ver docs/CFDI-AES_Roadmap.md).
#
# Activado en #18 (05 ago 2026): Lector de Documentos, Chat Fiscal y
# Anomalías IA (los 3 modulos que el frontend ya consumia con fetch real).
# Conciliacion y Resumen Ejecutivo quedan fuera de alcance a proposito -
# el backend ya existe pero el frontend nunca se construyo para ellos
# (siguen siendo un Placeholder y un boton que solo simula un toast).
#
# Pendiente para activar esos dos endpoints de verdad: construir el
# frontend correspondiente (tarea aparte).
# ──────────────────────────────────────────────────────────────────────────────
# ─── services/ia/main.py ──────────────────────────────────────────────────────
# Microservicio de IA – CFDI-AES
# Puerto: 8007 (8006 ya es de whatsapp_bot)
# Módulos:
#   1. Lector de PDFs / imágenes → extracción de datos fiscales
#   2. Chat fiscal conversacional con contexto de la cuenta
#   3. Detección de anomalías en facturas y pagos
#   4. Conciliación bancaria automática (backend listo, sin frontend - #18)
# Modelo: Claude claude-sonnet-5 vía Anthropic API
# ──────────────────────────────────────────────────────────────────────────────

import os
import base64
import json
import httpx
from datetime import datetime, date
from typing import Optional, List, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from shared.internal_key import require_internal_key

load_dotenv()

app = FastAPI(title="CFDI-AES – Microservicio IA", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Autenticacion interna servicio-a-servicio (rewiring al Gateway) ───────────
# Hallazgo (13 ago 2026): ia:8007 no validaba absolutamente nada - los 6
# endpoints de este archivo estaban completamente abiertos a cualquiera que
# alcanzara el puerto, sin JWT ni ningun otro mecanismo. No es una fuga
# cross-tenant en el sentido de #58 (ia nunca toca la BD, es enteramente
# stateless - solo reenvia a Claude lo que el caller mande en el body), pero
# si permitia gasto no autorizado del credito real de Anthropic. Mismo
# patron exacto que ya usan administracion/facturacion - el Gateway es el
# unico llamante legitimo: exige el JWT del usuario primero, y solo entonces
# agrega este header antes de reenviar.
#
# require_internal_key() extraida a backend/shared/internal_key.py (14 ago
# 2026, refactor/shared-internal-key, ver import arriba) - antes vivia
# copiada aqui, identica a la de facturacion/administracion.


@app.exception_handler(httpx.HTTPStatusError)
async def anthropic_error_handler(request: Request, exc: httpx.HTTPStatusError):
    """
    Sin esto, un error real de Anthropic (ej. 401 por falta de API key)
    queda como excepcion no manejada -> Starlette responde 500 desde
    ServerErrorMiddleware, que vive POR FUERA de CORSMiddleware, asi que
    la respuesta nunca lleva Access-Control-Allow-Origin. Desde curl se ve
    como un 500 normal; desde el navegador el fetch falla como ERR_FAILED,
    indistinguible de un error de conexion real. Los exception_handler de
    FastAPI si corren dentro del stack de CORSMiddleware, asi que esta
    respuesta si lleva los headers correctos.
    """
    return JSONResponse(
        status_code=502,
        content={"detail": f"Error de Anthropic: {exc.response.status_code} {exc.response.reason_phrase}"},
    )

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-5"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def anthropic_headers() -> dict:
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

async def call_claude(messages: list, system: str, max_tokens: int = 1024) -> str:
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=anthropic_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]

async def stream_claude(messages: list, system: str, max_tokens: int = 1024) -> AsyncGenerator[str, None]:
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", ANTHROPIC_API_URL, headers=anthropic_headers(), json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        event = json.loads(chunk)
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                    except json.JSONDecodeError:
                        continue


# ═══════════════════════════════════════════════════════════════════════════════
# MÓDULO 1 – LECTOR DE DOCUMENTOS (PDF / imagen)
# ═══════════════════════════════════════════════════════════════════════════════

PDF_EXTRACTION_SYSTEM = """
Eres un experto en fiscalidad mexicana especializado en CFDI 4.0.
Tu tarea es analizar documentos (órdenes de compra, cotizaciones, notas de entrega)
y extraer los datos necesarios para generar una factura CFDI.

Responde ÚNICAMENTE con un objeto JSON válido con esta estructura exacta,
sin texto adicional, sin markdown, sin backticks:

{
  "receptor_nombre": "...",
  "receptor_rfc": "...",
  "receptor_uso_cfdi": "G03",
  "receptor_regimen_fiscal": "601",
  "receptor_domicilio_fiscal": "...",
  "conceptos": [
    {
      "descripcion": "...",
      "cantidad": 0.0,
      "precio_unitario": 0.0,
      "clave_prod_serv": "01010101",
      "clave_unidad": "H87",
      "iva_tasa": 0.16
    }
  ],
  "moneda": "MXN",
  "tipo_cambio": 1.0,
  "metodo_pago": "PUE",
  "forma_pago": "03",
  "numero_orden": "...",
  "notas_adicionales": "...",
  "confianza": {
    "general": 0.95,
    "campos_inciertos": ["precio_unitario"]
  },
  "addenda_detectada": null
}

Si no puedes extraer un campo, usa null. El campo "confianza.general" va de 0 a 1.
En "campos_inciertos" lista los campos que no puedes confirmar con certeza.
Si detectas que el receptor es Walmart, FEMSA, Liverpool, Soriana o Chedraui,
indica el nombre en "addenda_detectada".
"""

class ExtractionResult(BaseModel):
    receptor_nombre: Optional[str]
    receptor_rfc: Optional[str]
    receptor_uso_cfdi: Optional[str]
    receptor_regimen_fiscal: Optional[str]
    receptor_domicilio_fiscal: Optional[str]
    conceptos: list
    moneda: str
    metodo_pago: Optional[str]
    forma_pago: Optional[str]
    numero_orden: Optional[str]
    notas_adicionales: Optional[str]
    confianza: dict
    addenda_detectada: Optional[str]
    procesado_en_ms: int

@app.post("/ia/extraer-documento", response_model=ExtractionResult)
async def extraer_documento(file: UploadFile = File(...), _: str = Depends(require_internal_key)):
    """
    Recibe un PDF o imagen de una orden de compra / cotización.
    Devuelve los campos fiscales listos para generar el CFDI.
    """
    start = datetime.utcnow()
    content = await file.read()
    b64 = base64.standard_b64encode(content).decode("utf-8")

    # Determinar media_type
    fname = (file.filename or "").lower()
    if fname.endswith(".pdf"):
        media_type = "application/pdf"
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    else:
        # Imagen (jpg, png, webp)
        ext_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        media_type = ext_map.get("." + fname.rsplit(".", 1)[-1], "image/jpeg")
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }

    messages = [
        {
            "role": "user",
            "content": [
                content_block,
                {"type": "text", "text": "Extrae los datos fiscales de este documento para generar un CFDI 4.0."},
            ],
        }
    ]

    raw = await call_claude(messages, PDF_EXTRACTION_SYSTEM, max_tokens=2000)

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail=f"La IA no devolvió JSON válido: {raw[:200]}")

    elapsed = int((datetime.utcnow() - start).total_seconds() * 1000)
    data["procesado_en_ms"] = elapsed
    return ExtractionResult(**data)


# ═══════════════════════════════════════════════════════════════════════════════
# MÓDULO 2 – CHAT FISCAL CONVERSACIONAL
# ═══════════════════════════════════════════════════════════════════════════════

CHAT_FISCAL_SYSTEM = """
Eres el asistente fiscal de CFDI-AES, integrado directamente a la cuenta del usuario.
Tienes acceso en tiempo real a sus facturas, clientes, obligaciones ante el SAT
y movimientos bancarios. Respondes en español, de forma clara y directa.

Cuando el usuario pregunte por cifras, usa los datos del contexto proporcionado.
Cuando puedas ejecutar una acción (generar reporte, enviar recordatorio, etc.),
ofrécela claramente al final de tu respuesta.

No inventes datos que no estén en el contexto. Si no tienes la información,
dilo honestamente y sugiere dónde obtenerla.

Formato de respuesta: texto plano con saltos de línea naturales. Máximo 3 párrafos.
"""

class ChatMessage(BaseModel):
    role: str  # "user" o "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    contexto_cuenta: Optional[dict] = None  # Datos en tiempo real de la cuenta

class ChatResponse(BaseModel):
    respuesta: str
    acciones_sugeridas: List[str]

@app.post("/ia/chat", response_model=ChatResponse)
async def chat_fiscal(req: ChatRequest, _: str = Depends(require_internal_key)):
    """Chat fiscal no-streaming. Para UI simple o integraciones."""
    ctx = req.contexto_cuenta or {}
    context_str = json.dumps(ctx, ensure_ascii=False, indent=2) if ctx else "No disponible"
    system = CHAT_FISCAL_SYSTEM + f"\n\nCONTEXTO DE LA CUENTA EN TIEMPO REAL:\n{context_str}"

    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    respuesta = await call_claude(messages, system, max_tokens=800)

    # Extraer acciones sugeridas (líneas que empiezan con "→" o "•")
    acciones = [
        line.lstrip("→•- ").strip()
        for line in respuesta.split("\n")
        if line.strip().startswith(("→", "•", "-")) and len(line.strip()) > 3
    ]

    return ChatResponse(respuesta=respuesta, acciones_sugeridas=acciones[:4])


@app.post("/ia/chat/stream")
async def chat_fiscal_stream(req: ChatRequest, _: str = Depends(require_internal_key)):
    """
    Chat fiscal con streaming Server-Sent Events.
    El frontend recibe tokens en tiempo real.
    """
    ctx = req.contexto_cuenta or {}
    context_str = json.dumps(ctx, ensure_ascii=False, indent=2) if ctx else "No disponible"
    system = CHAT_FISCAL_SYSTEM + f"\n\nCONTEXTO DE LA CUENTA EN TIEMPO REAL:\n{context_str}"
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_generator():
        try:
            async for token in stream_claude(messages, system, max_tokens=800):
                yield f"data: {json.dumps({'token': token})}\n\n"
        except httpx.HTTPStatusError as e:
            # A diferencia de los endpoints no-streaming, aqui NO se puede
            # dejar que la excepcion suba hasta el exception_handler global
            # (anthropic_error_handler): StreamingResponse ya envio los
            # headers HTTP en cuanto empezo a iterar este generador, y
            # FastAPI no puede sustituir una respuesta que ya inicio -
            # intentarlo produce "RuntimeError: Caught handled exception,
            # but response already started" y corta la conexion de forma
            # abrupta (ERR_INCOMPLETE_CHUNKED_ENCODING en el navegador).
            # Se maneja aqui mismo, como un evento mas del stream, y se
            # cierra limpio.
            mensaje_error = f"⚠ Error de Anthropic: {e.response.status_code} {e.response.reason_phrase}"
            yield f"data: {json.dumps({'token': mensaje_error})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
# MÓDULO 3 – DETECCIÓN DE ANOMALÍAS
# ═══════════════════════════════════════════════════════════════════════════════

ANOMALY_SYSTEM = """
Eres un motor de detección de anomalías fiscales para empresas mexicanas.
Recibes un JSON con el historial de facturas y pagos de una cuenta.
Debes devolver ÚNICAMENTE un array JSON de anomalías detectadas, sin texto adicional.

Cada anomalía tiene esta estructura:
{
  "tipo": "pago_retrasado" | "rfc_riesgo" | "discrepancia_pago" | "patron_inusual" | "obligacion_fiscal",
  "severidad": "alta" | "media" | "baja",
  "titulo": "Título breve (máx 60 chars)",
  "descripcion": "Descripción detallada con el dato concreto",
  "entidad_afectada": "Nombre del cliente o proceso",
  "monto_en_riesgo": 0.0,
  "accion_recomendada": "Qué debe hacer el usuario",
  "fecha_deteccion": "ISO 8601"
}

Detecta al menos: pagos retrasados >30 días vs historial del cliente,
discrepancias entre facturas y depósitos bancarios,
RFCs con patrones de RFC inválido o en lista negra,
concentración de riesgo en un solo cliente (>40% de cartera),
facturas sin pago próximas a vencer en 7 días.
"""

class AnomalyRequest(BaseModel):
    facturas: list
    pagos_bancarios: Optional[list] = []
    clientes: Optional[list] = []

class Anomaly(BaseModel):
    tipo: str
    severidad: str
    titulo: str
    descripcion: str
    entidad_afectada: str
    monto_en_riesgo: float
    accion_recomendada: str
    fecha_deteccion: str

@app.post("/ia/anomalias", response_model=List[Anomaly])
async def detectar_anomalias(req: AnomalyRequest, _: str = Depends(require_internal_key)):
    """
    Analiza el conjunto de facturas y pagos en busca de anomalías.
    Se ejecuta en background cada hora vía tarea Celery.
    """
    data_str = json.dumps(req.dict(), ensure_ascii=False, indent=2)
    messages = [
        {"role": "user", "content": f"Analiza estas facturas y pagos y detecta anomalías:\n\n{data_str}"}
    ]
    raw = await call_claude(messages, ANOMALY_SYSTEM, max_tokens=2000)

    try:
        # Limpiar posibles backticks de markdown
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        anomalias = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Error parseando anomalías")

    return [Anomaly(**a) for a in anomalias]


# ═══════════════════════════════════════════════════════════════════════════════
# MÓDULO 4 – CONCILIACIÓN BANCARIA AUTOMÁTICA
# ═══════════════════════════════════════════════════════════════════════════════

CONCILIATION_SYSTEM = """
Eres un experto en conciliación bancaria para empresas mexicanas con CFDI.
Recibes dos listas: facturas emitidas y movimientos bancarios (depósitos).
Tu tarea es cruzarlos y devolver ÚNICAMENTE un JSON con este formato:

{
  "conciliados": [
    {
      "factura_folio": "A-0001",
      "factura_uuid": "...",
      "deposito_referencia": "...",
      "monto_factura": 0.0,
      "monto_deposito": 0.0,
      "discrepancia": 0.0,
      "confianza": 0.98,
      "fecha_pago": "2025-05-10"
    }
  ],
  "sin_conciliar_facturas": ["A-0005", "A-0007"],
  "sin_conciliar_depositos": ["DEP-2291", "DEP-2298"],
  "total_conciliado": 0.0,
  "total_discrepancias": 0.0,
  "resumen": "Texto breve del resultado"
}

Para cruzar: usa monto ±5% de tolerancia, fecha ±10 días, o referencia/RFC en concepto del depósito.
Ordena "conciliados" de mayor a menor confianza.
"""

class ConciliationRequest(BaseModel):
    facturas: list        # Lista de facturas con folio, uuid, total, fecha, receptor_rfc
    depositos: list       # Movimientos bancarios con referencia, monto, fecha, concepto
    tolerancia_porcentaje: float = 5.0

@app.post("/ia/conciliar")
async def conciliar_banco(req: ConciliationRequest, _: str = Depends(require_internal_key)):
    """
    Cruza facturas emitidas con depósitos bancarios.
    Devuelve pares conciliados, discrepancias y pendientes.
    """
    data_str = json.dumps(req.dict(), ensure_ascii=False, indent=2)
    messages = [
        {"role": "user", "content": f"Concilia estas facturas con los depósitos bancarios:\n\n{data_str}"}
    ]
    raw = await call_claude(messages, CONCILIATION_SYSTEM, max_tokens=3000)

    try:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Error en conciliación")


# ═══════════════════════════════════════════════════════════════════════════════
# MÓDULO 5 – GENERADOR DE RESUMEN EJECUTIVO
# ═══════════════════════════════════════════════════════════════════════════════

SUMMARY_SYSTEM = """
Eres un analista financiero especializado en PyMEs mexicanas.
Recibes los datos de facturación de un período y generas un resumen ejecutivo
en español, claro, orientado a la toma de decisiones del dueño del negocio.

Estructura tu respuesta en 4 secciones con este formato JSON:
{
  "titulo": "Reporte ejecutivo · Mayo 2025",
  "kpis_principales": [
    {"nombre": "...", "valor": "...", "tendencia": "sube|baja|neutro", "nota": "..."}
  ],
  "hallazgos": ["...", "..."],
  "riesgos": ["...", "..."],
  "recomendaciones": ["...", "..."],
  "texto_ejecutivo": "Párrafo de 3-4 oraciones para presentar a dirección."
}
"""

class SummaryRequest(BaseModel):
    periodo_inicio: date
    periodo_fin: date
    datos_facturacion: dict
    incluir_comparativo: bool = True

@app.post("/ia/resumen-ejecutivo")
async def generar_resumen(req: SummaryRequest, _: str = Depends(require_internal_key)):
    """Genera un reporte ejecutivo del período solicitado."""
    data_str = json.dumps(req.dict(), ensure_ascii=False, default=str)
    messages = [
        {"role": "user", "content": f"Genera el resumen ejecutivo para estos datos:\n\n{data_str}"}
    ]
    raw = await call_claude(messages, SUMMARY_SYSTEM, max_tokens=1500)

    try:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {"texto_raw": raw}


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    """Verifica que el servicio y la API key de Anthropic estén configurados."""
    return {
        "service": "ia",
        "status": "ok",
        "model": CLAUDE_MODEL,
        "api_key_configured": bool(ANTHROPIC_API_KEY) and ANTHROPIC_API_KEY.startswith("sk-ant-"),
        "modules": ["extraccion_pdf", "chat_fiscal", "anomalias", "conciliacion", "resumen_ejecutivo"],
    }
