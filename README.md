# CFDI-AES — Plataforma de Facturación Electrónica CFDI 4.0

Sistema de facturación electrónica basado en microservicios (FastAPI + PostgreSQL + Docker) con frontend React y chatbot WhatsApp integrado.

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async |
| Frontend | React 18, Vite, Nginx |
| Base de datos | PostgreSQL 16 (3 instancias independientes) |
| Cache / Sesiones | Redis 7 |
| Almacenamiento XML/PDF | MinIO (compatible S3) |
| PAC timbrado | Finkok (SOAP/REST) |
| WhatsApp | Meta Business Cloud API |
| Contenedores | Docker Compose (dev) |

---

## Microservicios

| Servicio | Puerto | Responsabilidad |
|---|---|---|
| API Gateway | 8000 | Auth JWT, routing centralizado |
| Facturación | 8001 | Timbrado CFDI 4.0, XML/PDF, cancelación |
| Administración | 8002 | Emisores, clientes, series, configuración |
| Addenda AES | 8003 | Schemas de addenda por cadena comercial |
| Reportes | 8004 | Reportes mensuales, exportación |
| Auth / Usuarios | 8005 | Login, JWT, gestión de roles |
| **WhatsApp Bot** | **8006** | **Chatbot para facturación vía WhatsApp** |
| Frontend | 3000 | UI React (Nginx) |

---

## Inicio rápido

### Prerrequisitos
- Docker Desktop instalado y corriendo
- `docker compose` v2 disponible

### 1. Variables de entorno
```bat
copy .env.example .env
```
Editar `.env` con credenciales reales (PAC Finkok, WhatsApp API, JWT secret).

### 2. Levantar el stack
```bat
.\scripts\start-all.bat
```

O directamente:
```bash
docker compose up --build -d
```

### 3. Verificar
```
Frontend:         http://localhost:3000
API Gateway:      http://localhost:8000/health
WhatsApp Bot:     http://localhost:8006/health
WhatsApp Bot Docs: http://localhost:8006/docs
MinIO Console:    http://localhost:9001
```

### 4. Detener
```bat
.\scripts\stop-all.bat
```

---

## Estructura del proyecto

```
CFDI-AES/
├── .env.example                    ← Variables de entorno (copiar como .env)
├── docker-compose.yml              ← Orquestación completa del stack
├── scripts/
│   ├── start-all.bat               ← Inicia todo el stack
│   └── stop-all.bat                ← Detiene todo el stack
├── backend/
│   ├── api_gateway/                ← Gateway JWT + proxy (puerto 8000)
│   └── microservices/
│       ├── facturacion/            ← CFDI 4.0, timbrado PAC (puerto 8001)
│       ├── administracion/         ← Emisores, clientes, series (puerto 8002)
│       ├── addenda_aes/            ← Addenda por cadena comercial (puerto 8003)
│       ├── reportes/               ← Reportes mensuales (puerto 8004)
│       ├── auth_usuarios/          ← Login, JWT, roles (puerto 8005)
│       └── whatsapp_bot/           ← Chatbot WhatsApp CFDI (puerto 8006)
│           ├── core/               ← Config, logging, seguridad
│           ├── models/             ← ORM SQLAlchemy + Pydantic schemas
│           ├── routes/             ← Webhook WhatsApp + API interna
│           ├── services/           ← Estado, validadores, OCR, clientes HTTP
│           └── tests/              ← 67 tests unitarios e integración
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 ← App principal
│   │   ├── services/api.js         ← Cliente HTTP centralizado
│   │   └── components/             ← Componentes React
│   ├── Dockerfile                  ← Build multi-stage + Nginx
│   └── nginx.conf                  ← Config Nginx con SPA routing
├── docs/
│   ├── README.md                   ← Documentación de arquitectura
│   └── CFDI-AES_Roadmap.md        ← Roadmap de fases
└── .github/
    └── workflows/
        └── whatsapp-bot.yml        ← CI/CD: lint, tests, Docker build
```

---

## WhatsApp Bot — Flujo de conversación

```
FACTURA/HOLA → Aviso de privacidad → Opt-in
  → RFC → Razón Social → CP → Régimen → Uso CFDI → Email → Ticket
  → Confirmación → Timbrado PAC → Entrega XML + PDF
```

Ver documentación completa: [`backend/microservices/whatsapp_bot/README.md`](backend/microservices/whatsapp_bot/README.md)

---

## Ejecutar tests

```bash
cd backend/microservices/whatsapp_bot
python -m pytest tests/ -v
# 67 passed
```

---

## Variables de entorno requeridas

Ver `.env.example` en la raíz para la lista completa.

Variables mínimas para levantar:

| Variable | Descripción |
|---|---|
| `JWT_SECRET` | Secret para firmar tokens JWT |
| `INTERNAL_API_KEY` | Clave inter-servicios (bot ↔ facturación) |
| `PAC_USER` / `PAC_PASS` | Credenciales Finkok |
| `WHATSAPP_TOKEN` | Token Cloud API Meta |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número WhatsApp |
| `WHATSAPP_VERIFY_TOKEN` | Token de verificación del webhook |

---

## Documentación

- [Mapa de dependencias del backlog](docs/BACKLOG-DEPENDENCIES.md) — Diagrama Mermaid con las fases y dependencias entre tareas pendientes del proyecto.
