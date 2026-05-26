# CFDI-AES Webapp · Arquitectura de Microservicios

Sistema de facturación electrónica CFDI 4.0 migrado a webapp con microservicios Python/FastAPI y frontend React.

---

## Estructura del proyecto

```
cfdi-aes/
├── docker-compose.yml              ← Orquestación completa
├── frontend/                       ← React + Vite
│   ├── src/App.jsx                 ← App principal (sidebar + vistas)
│   └── package.json
├── gateway/                        ← API Gateway (puerto 8000)
│   └── main.py                     ← Auth JWT + proxy routing
└── services/
    ├── facturacion/main.py         ← Puerto 8001 – CFDI, timbrado, XML/PDF
    ├── administracion/main.py      ← Puerto 8002 – Emisores, Clientes, Series
    ├── addenda/main.py             ← Puerto 8003 – Addenda AES por cliente
    ├── reportes/main.py            ← Puerto 8004 – Reporte mensual, exportaciones
    └── auth/main.py                ← Puerto 8005 – Login, JWT, usuarios
```

---

## Microservicios

| Servicio        | Puerto | Base de datos         | Responsabilidad                              |
|----------------|--------|-----------------------|----------------------------------------------|
| API Gateway     | 8000   | –                     | Auth JWT, rate limiting, routing             |
| Facturación     | 8001   | PostgreSQL (facturas) | Nueva factura, timbrado PAC, generadas/recibidas |
| Administración  | 8002   | PostgreSQL (admin)    | Emisores, clientes, series, configuración    |
| Addenda AES     | 8003   | PostgreSQL (admin)    | Schemas de addenda por cadena comercial      |
| Reportes        | 8004   | PostgreSQL (facturas) | Reportes mensuales, exportación Excel        |
| Auth / Usuarios | 8005   | PostgreSQL (auth)     | Login, JWT, gestión de roles                 |

---

## Levantar el entorno de desarrollo

### Prerrequisitos
- Docker y Docker Compose v2
- Node.js 20+ (solo para desarrollo del frontend sin Docker)

### Con Docker (recomendado)

```bash
# 1. Clonar / copiar este directorio
cd cfdi-aes

# 2. Copiar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales de PAC (Finkok, Diverza, etc.)

# 3. Levantar todo
docker compose up --build

# URLs disponibles:
# Frontend:       http://localhost:3000
# API Gateway:    http://localhost:8000
# MinIO Console:  http://localhost:9001
```

### Sin Docker (solo microservicio)

```bash
cd services/facturacion

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Instalar dependencias
pip install fastapi uvicorn[standard] httpx pydantic python-jose[cryptography] \
            sqlalchemy asyncpg alembic boto3 python-multipart

# Ejecutar
uvicorn main:app --reload --port 8001

# Swagger UI: http://localhost:8001/docs
```

---

## Variables de entorno (.env)

```env
JWT_SECRET=genera_un_secret_seguro_aqui

# PAC para timbrado CFDI (ej: Finkok)
PAC_URL=https://ws.finkok.com/servicios/soap/stamp.wsdl
PAC_USER=tu_usuario_pac
PAC_PASS=tu_password_pac

# MinIO / S3
MINIO_ACCESS_KEY=minio_admin
MINIO_SECRET_KEY=minio_secret
```

---

## Endpoints principales

### Auth (vía Gateway)
```
POST /auth/login          → { access_token, expires_in }
POST /auth/logout
```

### Facturación
```
POST /facturas/timbrar    → Genera y timbra CFDI 4.0
GET  /facturas            → Lista con filtros
GET  /facturas/{uuid}     → Detalle
GET  /facturas/{uuid}/xml → Descarga XML
GET  /facturas/{uuid}/pdf → Descarga PDF
POST /facturas/{uuid}/cancelar
GET  /facturas/reporte/mensual
```

### Administración
```
GET/POST   /admin/clientes
GET/PUT    /admin/clientes/{rfc}
GET/POST   /admin/emisores
GET/POST   /admin/series
GET/PUT    /admin/config
```

### Addenda
```
GET  /addenda/schemas
GET  /addenda/{cliente}/schema
POST /addenda/aplicar
```

---

## Stack tecnológico

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy (async) + PostgreSQL
- **Auth:** JWT (python-jose) + bcrypt
- **Event bus:** Redis Pub/Sub
- **Almacenamiento XML/PDF:** MinIO (compatible S3)
- **Frontend:** React 18 + Vite
- **Timbrado:** PAC (Finkok/Diverza/FiscoClic) vía SOAP/REST
- **Contenedores:** Docker Compose (dev) → Kubernetes (producción)

---

## Siguientes pasos

1. **Integrar PAC real** – agregar cliente SOAP en `services/facturacion/pac_client.py`
2. **Builder CFDI XML** – usar `lxml` para generar XML válido CFDI 4.0 con catálogos SAT
3. **Firma digital CSD** – integrar `xmlsec` o llamar servicio de firmado
4. **Autenticación real** – conectar BD de usuarios en `services/auth/main.py`
5. **Almacenamiento** – configurar bucket MinIO y subir XMLs/PDFs generados
6. **CI/CD** – agregar GitHub Actions para tests y despliegue
