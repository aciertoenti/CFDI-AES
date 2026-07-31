# Scripts de inicio y parada — CFDI-AES

## Archivos

| Script | Descripción |
|---|---|
| `start-all.bat` | Inicia todo el stack con `docker compose up --build -d` |
| `stop-all.bat` | Detiene el stack con `docker compose down` |
| `start-local.bat` | Levanta `api_gateway` y `auth_usuarios` sin Docker (`uvicorn` directo), cargando las variables del `.env` de la raíz (incluido `JWT_SECRET`) automáticamente |

## Requisitos

- Docker Desktop instalado y en ejecución
- `docker compose` v2 disponible en la terminal

## Uso

Doble clic en el archivo `.bat`, o desde PowerShell/CMD:

```bat
.\scripts\start-all.bat
.\scripts\stop-all.bat
```

Los scripts funcionan desde cualquier ubicación — ajustan el directorio de trabajo automáticamente.

## Primera vez

1. Copia las variables de entorno:
   ```bat
   copy .env.example .env
   ```
2. Edita `.env` con tus credenciales reales (PAC, WhatsApp, etc.)
3. Ejecuta `start-all.bat`

> El script detecta automáticamente si falta `.env` y crea uno desde `.env.example`.

## URLs al arrancar

| Servicio | URL |
|---|---|
| Frontend React | http://localhost:3000 |
| API Gateway | http://localhost:8000 |
| WhatsApp Bot | http://localhost:8006 |
| WhatsApp Bot Docs | http://localhost:8006/docs |
| MinIO Console | http://localhost:9001 |

## Puertos por microservicio

| Servicio | Puerto |
|---|---|
| Gateway | 8000 |
| Facturación | 8001 |
| Administración | 8002 |
| Addenda AES | 8003 |
| Reportes | 8004 |
| Auth | 8005 |
| WhatsApp Bot | 8006 |

## Correr api_gateway / auth_usuarios sin Docker

```bat
.\scripts\start-local.bat
```

Requiere haber instalado las dependencias antes (`pip install -r requirements.txt`) en `backend/api_gateway` y `backend/microservices/auth_usuarios`. El script lee el `.env` de la raíz, exporta sus variables (incluido `JWT_SECRET`) en la sesión y abre cada servicio en su propia ventana de `cmd` con `uvicorn --reload`. Ciérralas para detenerlos.

> El Gateway sigue enrutando a los demás microservicios usando nombres de red de Docker (`facturacion`, `administracion`, etc.) — si esos servicios no corren también accesibles con esos hostnames, el proxy hacia ellos fallará aunque `/health` sí responda.

## Solución de problemas

- **Error al arrancar**: Verifica que Docker Desktop esté activo y no haya conflictos de puertos
- **ERR_EMPTY_RESPONSE en :3000**: El frontend usa nginx internamente en el puerto 80 — el mapeo es `3000:80`, es correcto
- **Bot no responde webhook**: Asegúrate de que `WHATSAPP_TOKEN` y `WHATSAPP_VERIFY_TOKEN` estén en el `.env`
