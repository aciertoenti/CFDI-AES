# CFDI-AES WhatsApp Bot

Microservicio de chatbot para WhatsApp que captura datos fiscales, los valida y genera facturas CFDI 4.0 a través del microservicio de Facturación existente.

**Puerto:** 8006 | **Python:** 3.12 | **Framework:** FastAPI + Pydantic v2

---

## Flujo de conversación

```
Usuario escribe "FACTURA"
        │
        ▼
[INICIO] ──────────────────────────────────────────►
        │
        ▼
[ESPERANDO_OPTIN]
  Envía aviso de privacidad y solicita consentimiento
        │
        ├── NO → [CERRADA]
        │
        ▼ SÍ
[CAPTURA_RFC]
  Valida: regex + estructura SAT + dígito verificador
  Permite imagen/PDF (OCR de Constancia de Situación Fiscal)
        │
        ▼
[CAPTURA_RAZON_SOCIAL]
        │
        ▼
[CAPTURA_CP]
  Valida: 5 dígitos, rango México
        │
        ▼
[CAPTURA_REGIMEN]
  Valida contra c_RegimenFiscal SAT
  Permite enviar CSF como imagen para auto-llenado
        │
        ▼
[CAPTURA_USO_CFDI]
  Valida contra c_UsoCFDI SAT + compatibilidad régimen-persona
        │
        ▼
[CAPTURA_EMAIL]
        │
        ▼
[CAPTURA_TICKET]
  Número de ticket/folio del punto de venta
        │
        ▼
[CONFIRMACION]
  Muestra resumen completo
        │
        ├── NO → vuelve a CAPTURA_RFC
        │
        ▼ SÍ
[TIMBRADO]
  POST /facturas/timbrar (con idempotency key)
  Reintentos automáticos para errores del PAC/SAT
        │
        ▼
[ENTREGA]
  Envía XML + PDF por WhatsApp
  Envía al correo registrado
        │
        ▼
[CERRADA] ── timeout 30 min de inactividad

Flujo paralelo de cancelación:
[CERRADA/ENTREGA] → usuario escribe "CANCELAR"
        │
        ▼
[CANCELACION_SOLICITADA]
  Solicita confirmación
        │
        ▼
POST /facturas/{uuid}/cancelar
        │
        ▼
[CERRADA]
```

---

## Variables de entorno requeridas

Copiar `.env.example` como `.env`:

```bash
cp .env.example .env
```

| Variable | Requerida | Descripción |
|---|---|---|
| `WHATSAPP_TOKEN` | ✅ | Token de la Cloud API de Meta |
| `WHATSAPP_PHONE_NUMBER_ID` | ✅ | ID del número registrado en Meta |
| `WHATSAPP_VERIFY_TOKEN` | ✅ | Token de verificación del webhook |
| `INTERNAL_API_KEY` | ✅ | Clave para autenticación inter-servicios |
| `JWT_SECRET` | ✅ | Mismo valor que en el API Gateway |
| `DATABASE_URL` | ✅ | PostgreSQL async (asyncpg) |
| `REDIS_URL` | ✅ | Redis (base de datos /2 por defecto) |
| `FACTURACION_URL` | ✅ | URL del microservicio de Facturación |
| `EMISOR_RFC_DEFAULT` | ✅ | RFC del emisor para las facturas |
| `PRIVACY_NOTICE_URL` | opcional | URL del aviso de privacidad |

---

## Instalación local (sin Docker)

```bash
# Prerrequisitos del sistema
# macOS: brew install tesseract tesseract-lang poppler
# Ubuntu: apt-get install tesseract-ocr tesseract-ocr-spa poppler-utils

cd backend/microservices/whatsapp_bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Editar .env con tus valores

uvicorn main:app --reload --port 8006
# Docs: http://localhost:8006/docs
```

---

## Ejecutar tests

```bash
cd backend/microservices/whatsapp_bot
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Con Docker (stack completo)

```bash
# Desde la raíz del proyecto
docker compose up --build whatsapp_bot

# Solo el bot (si el resto del stack ya está corriendo)
docker compose up --build whatsapp_bot postgres_bot
```

---

## Configurar el webhook de Meta

1. Ngrok para desarrollo local:
   ```bash
   ngrok http 8006
   # Copia la URL: https://xxxx.ngrok.io
   ```

2. En Meta Developers → WhatsApp → Configuración → Webhooks:
   - URL: `https://xxxx.ngrok.io/webhook`
   - Token de verificación: el valor de `WHATSAPP_VERIFY_TOKEN`
   - Suscribir a: `messages`

---

## Arquitectura de seguridad

- **CSD / llave privada del emisor**: nunca toca este microservicio. Vive exclusivamente en `facturacion-service`.
- **Datos fiscales en logs**: los logs NUNCA registran RFC completo en nivel DEBUG ni contenido de mensajes (cumplimiento LFPDPPP).
- **Secretos**: solo se leen de variables de entorno, nunca hardcodeados.
- **Autenticación inter-servicios**: `X-Internal-Key` header en todas las llamadas internas.
- **Retención**: los datos fiscales se conservan 5 años (obligación SAT). Configurable en `DATA_RETENTION_DAYS`.
- **Opt-in explícito**: el aviso de privacidad se envía en el primer contacto y se requiere consentimiento antes de capturar cualquier dato.

---

## Endpoints

### Públicos (expuestos vía API Gateway)
```
GET  /webhook   → Verificación de webhook Meta
POST /webhook   → Recepción de mensajes WhatsApp
GET  /health    → Health check
GET  /metrics   → Métricas Prometheus
```

### Internos (requieren X-Internal-Key)
```
POST /bot/factura              → Timbrar vía API (sin flujo WhatsApp)
POST /bot/cancelar/{uuid_cfdi} → Solicitar cancelación
GET  /bot/sesion/{wa_id}       → Consultar estado de sesión
```

---

## Supuestos documentados

| # | Supuesto | Impacto si es diferente |
|---|---|---|
| 1 | **PAC: Finkok** vía SOAP. Errores mapeados según wiki.finkok.com | Actualizar `FINKOK_ERRORES` en `facturacion_client.py` |
| 2 | **WhatsApp Cloud API directa de Meta** (no Twilio/360dialog) | Cambiar URLs base en `whatsapp_client.py` |
| 3 | El microservicio de Facturación soporta **idempotency key** en header | Implementar en `facturacion-service` si no existe |
| 4 | Las URLs de XML/PDF en MinIO son **accesibles públicamente** por Meta para enviarlas como documentos | Configurar bucket público en MinIO o usar URLs firmadas |
| 5 | El **subtotal y concepto** del ticket vienen del POS (no capturados en la conversación) | Ampliar la máquina de estados para capturarlos |
