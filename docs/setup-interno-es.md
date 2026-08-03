# Guía de Configuración — CFDI-AES WhatsApp Bot
## Documento Técnico Interno | Versión 1.0 | Julio 2026

---

## Índice
1. [Prerrequisitos](#1-prerrequisitos)
2. [Generación de secretos](#2-generación-de-secretos)
3. [Configuración PAC Finkok](#3-configuración-pac-finkok)
4. [Configuración WhatsApp Business API (Meta)](#4-configuración-whatsapp-business-api-meta)
5. [Configuración ngrok](#5-configuración-ngrok)
6. [Levantar el stack](#6-levantar-el-stack)
7. [Registro del webhook en Meta](#7-registro-del-webhook-en-meta)
8. [Verificación del sistema](#8-verificación-del-sistema)
9. [Solución de problemas](#9-solución-de-problemas)

---

## 1. Prerrequisitos

| Herramienta | Versión mínima | Verificar con |
|---|---|---|
| Docker Desktop | 4.x | `docker --version` |
| Python | 3.12 | `python --version` |
| ngrok | 3.x | `ngrok version` |
| Git | 2.x | `git --version` |

**Clonar el repositorio:**
```bash
git clone https://github.com/tu-org/CFDI-AES.git
cd CFDI-AES
```

---

## 2. Generación de secretos

Ejecutar en PowerShell desde la raíz del proyecto:

```powershell
python -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"
python -c "import secrets; print('INTERNAL_API_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('WHATSAPP_VERIFY_TOKEN=' + secrets.token_urlsafe(24))"
```

> **[INSERTAR IMAGEN: Captura de PowerShell mostrando los tres valores generados — JWT_SECRET, INTERNAL_API_KEY y WHATSAPP_VERIFY_TOKEN]**

Copiar los valores al archivo `.env`:
```bash
copy .env.example .env
```

Resultado esperado en `.env`:
```env
JWT_SECRET=54383c366502fd63...
INTERNAL_API_KEY=ef6233b9adcef8...
WHATSAPP_VERIFY_TOKEN=ZCdjqDmwd--Rtm...
```

---

## 3. Configuración PAC Finkok

### 3.1 Ambiente de pruebas (Demo)

1. Registrarse en [https://finkok.com](https://finkok.com)
2. Confirmar el correo de activación
3. Acceder al portal y obtener credenciales

Actualizar `.env`:
```env
PAC_URL=https://demo-facturacion.finkok.com/servicios/soap/stamp.wsdl
PAC_CANCEL_URL=https://demo-facturacion.finkok.com/servicios/soap/cancel.wsdl
PAC_USER=tu_correo@dominio.com
PAC_PASS=tu_contraseña
```

### 3.2 Ambiente de producción

Cambiar únicamente las URLs:
```env
PAC_URL=https://ws.finkok.com/servicios/soap/stamp.wsdl
PAC_CANCEL_URL=https://ws.finkok.com/servicios/soap/cancel.wsdl
```

---

## 4. Configuración WhatsApp Business API (Meta)

### 4.1 Crear cuenta de desarrollador

1. Ir a [https://developers.facebook.com](https://developers.facebook.com)
2. Iniciar sesión con cuenta de Facebook
3. Aceptar términos de la Plataforma de Meta

### 4.2 Crear la app

1. Dashboard → **Crear app**
2. Tipo: **Business**
3. Nombre: `CFDI-AES-Bot`
4. Asociar cuenta de negocio (Business Manager)
5. Clic en **Crear app**

> **[INSERTAR IMAGEN: Pantalla "Mis apps" mostrando la app CFDI-AES-Bot recién creada con Identificador de app: 1111111111111111]**

### 4.3 Agregar WhatsApp

1. En el panel de la app → **Casos de uso**
2. Seleccionar **"Conectarte con los clientes a través de WhatsApp"**
3. Clic en **"Personalizar"**
4. Seleccionar **"Integrar con la API"**

> **[INSERTAR IMAGEN: Pantalla "Elige tu tipo de integración" con el botón "Integrar con la API" seleccionado en azul, mostrando los 3 pasos: Pruébalo, Configuración de producción, Verificación del negocio]**

### 4.4 Obtener credenciales (Paso 1 — Pruébalo)

1. Menú lateral → **Configuración básica** → **Paso 1. Pruébalo**
2. Expandir **"Solicita un número de prueba de WhatsApp"**

> **[INSERTAR IMAGEN: Pantalla "Paso 1. Pruébalo" mostrando: Número de prueba +1 (555) 000-0000, Phone Number ID: 1234567890123456, WhatsApp Business Account ID: 9876543210987654, y el campo "Token de acceso" con botón "Generar token"]**

3. Clic en **"Generar token"**
4. Seleccionar **"Test WhatsApp Business Account"** en el popup de OAuth

> **[INSERTAR IMAGEN: Popup de OAuth "Elige los cuentas de WhatsApp a los que quieres que acceda CFDI-AES-Bot" mostrando "Test WhatsApp Business Account" con checkbox para seleccionar]**

5. Copiar el token generado

Actualizar `.env`:
```env
WHATSAPP_TOKEN=EAAsBOKIWIBSI...  (token completo)
WHATSAPP_PHONE_NUMBER_ID=1234567890123456
```

### 4.5 Agregar número de prueba

1. En la sección **"Envía un mensaje desde tu número de prueba"**
2. Campo **Destinatario** → dropdown → **"Administrar lista de números"**
3. Agregar número en formato: `521XXXXXXXXXX` (México)
4. Ingresar código de verificación que llega por WhatsApp

> **[INSERTAR IMAGEN: Pantalla "Envía un mensaje desde tu número de prueba" mostrando número +1-555-000-0000, destinatario +52-55-0000-0000 seleccionado, y botón "Enviar mensaje"]**

---

## 5. Configuración ngrok

### 5.1 Instalar y autenticar

ngrok disponible en Microsoft Store o [https://ngrok.com/download](https://ngrok.com/download).

Verificar instalación:
```powershell
ngrok version
# ngrok version 3.39.8
```

Autenticar con token de [https://dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken):

> **[INSERTAR IMAGEN: Dashboard de ngrok mostrando "Your Authtoken" con el token visible en el campo]**

```powershell
ngrok config add-authtoken TU_TOKEN_AQUI
```

### 5.2 Exponer el bot

Abrir una terminal dedicada (mantenerla abierta):
```powershell
ngrok http 8006
```

Resultado:
```
Session Status    online
Forwarding        https://wolverine-disarray-protegee.ngrok-free.dev -> http://localhost:8006
```

> **[INSERTAR IMAGEN: Terminal PowerShell mostrando ngrok corriendo con Session Status: online y la URL de Forwarding]**

> **⚠️ Importante:** La URL de ngrok cambia cada vez que se reinicia. Para desarrollo usar un dominio estático (ver sección 9).

---

## 6. Levantar el stack

```powershell
cd C:\PersonalWorkspace\CFDI-AES
.\scripts\start-all.bat
```

Verificar que todos los servicios están activos:
```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Verificar el bot:
```
http://localhost:8006/health
```

Respuesta esperada:
```json
{"service":"whatsapp-bot","status":"ok","version":"1.0.0"}
```

> **[INSERTAR IMAGEN: Navegador mostrando localhost:8006/health con respuesta JSON {"service":"whatsapp-bot","status":"ok","version":"1.0.0"}]**

---

## 7. Registro del webhook en Meta

1. Meta Developers → app **CFDI-AES-Bot**
2. **Casos de uso** → **Paso 2: Configuración de producción**
3. Expandir **"Configurar webhooks"**

> **[INSERTAR IMAGEN: Sección "Configurar webhooks" expandida mostrando los campos "URL de devolución de llamada" y "Token de verificación" con el botón "Verificar y guardar"]**

4. Llenar los campos:

| Campo | Valor |
|---|---|
| URL de devolución de llamada | `https://TU-URL.ngrok-free.dev/webhook` |
| Token de verificación | Valor de `WHATSAPP_VERIFY_TOKEN` en `.env` |

5. Clic en **"Verificar y guardar"**
6. Resultado esperado en logs del bot:
```json
{"event": "webhook.verified", "level": "info"}
```

### 7.1 Suscribir campo messages

En la lista de **"Campos del webhook"**, buscar `messages` y activar el toggle a **"Suscritos"**.

> **[INSERTAR IMAGEN: Lista de campos del webhook mostrando "messages" con toggle en posición "Suscritos" (azul)]**

---

## 8. Verificación del sistema

### 8.1 Prueba manual del webhook

```powershell
$body = '{"object":"whatsapp_business_account","entry":[{"changes":[{"value":{"messages":[{"from":"525536652444","id":"test001","type":"text","text":{"body":"FACTURA"}}]}}]}]}'

Invoke-WebRequest -Uri "https://TU-URL.ngrok-free.dev/webhook" `
  -Method POST -ContentType "application/json" `
  -Body $body -UseBasicParsing
```

Respuesta esperada:
```json
{"status":"ok"}
```

### 8.2 Verificar logs del bot

```powershell
docker logs cfdi-aes-whatsapp_bot-1 --tail 10
```

Log esperado:
```json
{"wa_id": "525536652444", "estado": "INICIO", "event": "state_machine.process"}
```

> **[INSERTAR IMAGEN: Dashboard de ngrok mostrando POST /webhook con 200 OK y el payload JSON del mensaje "FACTURA"]**

### 8.3 Prueba desde WhatsApp

1. Enviar mensaje **"FACTURA"** al número `+1 (555) 000-0000`
2. El bot responde con el aviso de privacidad
3. Responder **"SÍ"** para continuar el flujo de captura de datos fiscales

---

## 9. Solución de problemas

| Error | Causa | Solución |
|---|---|---|
| `ERR_EMPTY_RESPONSE` en `:3000` | Nginx no estaba configurado | Reconstruir imagen: `docker compose up --build frontend` |
| `ERR_NGROK_4018` | ngrok no autenticado | `ngrok config add-authtoken TU_TOKEN` |
| `#131030` Recipient not in allowed list | Número no en lista de prueba Meta | Agregar número en Paso 1 → Destinatario |
| `Object with ID does not exist` | `WHATSAPP_PHONE_NUMBER_ID` incorrecto | Copiar ID exacto desde Meta Developers |
| Bot no recibe mensajes | URL de ngrok cambió | Reiniciar ngrok y actualizar webhook en Meta |
| Token expirado 24h | Token temporal de Meta | Generar nuevo token en Paso 1 → "Generar nuevo token" |

### 9.1 Dominio estático en ngrok (recomendado)

Para evitar que la URL cambie al reiniciar:

1. Ir a [https://dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains)
2. Clic en **"New Domain"** (plan gratuito incluye 1 dominio estático)
3. Copiar el dominio asignado (ej: `cfdi-aes-bot.ngrok-free.app`)
4. Usar siempre:
```powershell
ngrok http --domain=cfdi-aes-bot.ngrok-free.app 8006
```
5. Actualizar el webhook en Meta con esa URL fija

---

## Variables de entorno — Referencia completa

| Variable | Descripción | Ejemplo |
|---|---|---|
| `JWT_SECRET` | Secret para tokens JWT | `54383c366502fd63...` |
| `INTERNAL_API_KEY` | Clave inter-servicios | `ef6233b9adcef8...` |
| `PAC_URL` | URL timbrado Finkok | `https://demo-facturacion...` |
| `PAC_CANCEL_URL` | URL cancelación Finkok | `https://demo-facturacion...` |
| `PAC_USER` | Usuario Finkok | `correo@dominio.com` |
| `PAC_PASS` | Contraseña Finkok | `contraseña` |
| `WHATSAPP_TOKEN` | Token Cloud API Meta | `EAAsZCe...` |
| `WHATSAPP_PHONE_NUMBER_ID` | ID número WhatsApp | `1234567890123456` |
| `WHATSAPP_VERIFY_TOKEN` | Token verificación webhook | `ZCdjqDmwd--Rtm...` |
| `EMISOR_RFC_DEFAULT` | RFC del emisor | `DNS010101AAA` |
