"""
WhatsApp Bot — Microservicio CFDI-AES
Puerto: 8006
Responsabilidades:
  - Webhook WhatsApp Business Cloud API (Meta)
  - Máquina de estados de conversación
  - Validación fiscal (RFC, CP, Régimen, Uso CFDI, OCR CSF)
  - Cliente hacia microservicio Facturación (con idempotencia y reintentos)
  - Flujo de cancelación CFDI
  - Persistencia en PostgreSQL + sesiones en Redis
  - Logs estructurados JSON + métricas Prometheus
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.requests import Request
from starlette.responses import Response

from core.config import settings
from core.logging import configure_logging, get_logger
from models.database import create_tables
from routes.internal import router as internal_router
from routes.webhook import router as webhook_router

configure_logging()
logger = get_logger(__name__)

# ─── Métricas Prometheus ──────────────────────────────────────────────────────

facturas_generadas = Counter(
    "whatsapp_bot_facturas_total",
    "Total de facturas timbradas vía WhatsApp",
    ["estado"],  # labels: "ok", "error_pac", "error_sat", "doble"
)
timbrado_duration = Histogram(
    "whatsapp_bot_timbrado_seconds",
    "Duración del timbrado (llamada a facturacion-service)",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)
mensajes_recibidos = Counter(
    "whatsapp_bot_mensajes_total",
    "Total de mensajes recibidos de WhatsApp",
    ["tipo"],  # text, image, document, etc.
)


# ─── Lifespan (arranque y apagado) ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("whatsapp_bot.startup", env=settings.environment)
    # Crear tablas en desarrollo (producción usa Alembic migrations)
    if settings.environment == "development":
        await create_tables()
    yield
    logger.info("whatsapp_bot.shutdown")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CFDI-AES – WhatsApp Bot",
    version="1.0.0",
    description=(
        "Microservicio de chatbot WhatsApp para captura, validación y "
        "timbrado de CFDI 4.0. Integrado con CFDI-AES Facturación."
    ),
    lifespan=lifespan,
    # En producción deshabilitar docs o protegerlos con auth
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(webhook_router)
app.include_router(internal_router)


# ─── Endpoints de infraestructura ────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"service": "whatsapp-bot", "status": "ok", "version": "1.0.0"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Endpoint para Prometheus scrape."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "CFDI-AES WhatsApp Bot",
        "docs": "/docs" if settings.environment == "development" else "disabled",
        "health": "/health",
    }
