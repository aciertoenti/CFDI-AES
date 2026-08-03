# Guía de Activación — Bot de Facturación por WhatsApp
## CFDI-AES | Guía para el Usuario | Versión 1.0

---

Bienvenido. Esta guía te explica cómo activar el bot de facturación de WhatsApp en tu negocio, paso a paso, sin necesidad de conocimientos técnicos.

---

## Lo que necesitas antes de empezar

- Una cuenta de Facebook Business activa
- Un número de teléfono dedicado para WhatsApp Business (no puede tener WhatsApp Personal activo)
- Docker Desktop instalado en tu computadora
- Acceso a internet

**Tiempo estimado:** 60 a 90 minutos la primera vez.

---

## Paso 1 — Preparar las credenciales de seguridad

Estas claves protegen la comunicación entre los servicios. Las generas tú mismo en un segundo.

Abre PowerShell y ejecuta estas tres líneas una por una:

```powershell
python -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"
python -c "import secrets; print('INTERNAL_API_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('WHATSAPP_VERIFY_TOKEN=' + secrets.token_urlsafe(24))"
```

Guarda los tres valores que aparecen — los usarás en los siguientes pasos.

> **[INSERTAR IMAGEN: Pantalla de PowerShell mostrando los tres comandos ejecutados con sus valores generados]**

---

## Paso 2 — Configurar el PAC de facturación (Finkok)

El PAC es el servicio que timbra las facturas ante el SAT.

**Para pruebas (gratis):**

1. Ve a [https://finkok.com](https://finkok.com) y crea una cuenta gratuita
2. Confirma tu correo electrónico
3. Anota tu usuario (correo) y contraseña

**Para producción:**
- Contrata un plan en [https://finkok.com](https://finkok.com)
- Finkok te activa las credenciales en 1-2 días hábiles

---

## Paso 3 — Crear tu app en Meta (WhatsApp Business)

### 3.1 Cuenta de desarrollador

1. Ve a [https://developers.facebook.com](https://developers.facebook.com)
2. Inicia sesión con tu cuenta de Facebook de empresa
3. Acepta los términos cuando te los solicite

### 3.2 Crear la aplicación

1. Haz clic en **"Crear app"**
2. Elige tipo **"Business"**
3. Dale un nombre (por ejemplo: `MiEmpresa-Bot`)
4. Asocia tu cuenta de negocio de Facebook
5. Haz clic en **"Crear app"**

> **[INSERTAR IMAGEN: Panel de Meta Developers mostrando la app CFDI-AES-Bot recién creada con su Identificador de app]**

### 3.3 Activar WhatsApp en la app

1. En el panel de tu app, haz clic en **"Casos de uso"**
2. Busca **"Conectarte con los clientes a través de WhatsApp"**
3. Haz clic en la flecha de la derecha
4. Selecciona **"Integrar con la API"**

> **[INSERTAR IMAGEN: Pantalla "Elige tu tipo de integración" con "Integrar con la API" seleccionado, mostrando los 3 pasos del proceso]**

### 3.4 Obtener tus credenciales de WhatsApp

1. En el menú lateral ve a **Paso 1. Pruébalo**
2. En la sección **"Solicita un número de prueba"** verás:
   - Tu número de prueba gratuito
   - El **Phone Number ID** — anótalo
3. Haz clic en **"Generar token"**
4. En la ventana que aparece, selecciona **"Test WhatsApp Business Account"** y haz clic en **"Continuar"**

> **[INSERTAR IMAGEN: Pantalla "Paso 1. Pruébalo" mostrando el número +1 (555) 000-0000, Phone Number ID y el campo de Token de acceso con botón "Generar token"]**

> **[INSERTAR IMAGEN: Ventana popup para seleccionar la cuenta de WhatsApp, con "Test WhatsApp Business Account" disponible para seleccionar]**

5. Copia el token completo que aparece en el campo **"Token de acceso"**

### 3.5 Agregar tu número para recibir mensajes de prueba

1. En la sección **"Envía un mensaje desde tu número de prueba"**
2. En el campo **Destinatario** → abre el dropdown → **"Administrar lista de números"**
3. Agrega tu número de celular (formato: `521XXXXXXXXXX` para México)
4. Meta te envía un código por WhatsApp — ingrésalo para confirmar

> **[INSERTAR IMAGEN: Pantalla "Envía un mensaje desde tu número de prueba" con el destinatario +52-55-0000-0000 ya seleccionado en el dropdown]**

---

## Paso 4 — Instalar y configurar ngrok

ngrok conecta tu computadora al internet para que WhatsApp pueda enviar mensajes a tu bot.

**Instalar desde Microsoft Store:**
1. Abre Microsoft Store
2. Busca "ngrok"
3. Haz clic en **"Obtener"** o **"Abrir"** si ya está instalado

> **[INSERTAR IMAGEN: Microsoft Store mostrando la app de ngrok con el botón "Abrir" (ya instalado)]**

**Crear cuenta gratuita:**
1. Ve a [https://ngrok.com](https://ngrok.com) y regístrate
2. Ve a [https://dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
3. Copia tu token de autenticación

> **[INSERTAR IMAGEN: Dashboard de ngrok mostrando la sección "Your Authtoken" con el token en el campo de texto]**

**Conectar ngrok:**
```powershell
ngrok config add-authtoken TU_TOKEN_AQUI
```

---

## Paso 5 — Configurar el archivo de variables

1. En la carpeta del proyecto, copia el archivo de ejemplo:
```powershell
copy .env.example .env
```

2. Abre `.env` con el Bloc de notas y llena estos valores con lo que obtuviste en los pasos anteriores:

```
JWT_SECRET=          ← del Paso 1
INTERNAL_API_KEY=    ← del Paso 1
PAC_URL=https://demo-facturacion.finkok.com/servicios/soap/stamp.wsdl
PAC_USER=            ← tu correo de Finkok
PAC_PASS=            ← tu contraseña de Finkok
WHATSAPP_TOKEN=      ← del Paso 3.4
WHATSAPP_PHONE_NUMBER_ID=   ← del Paso 3.4
WHATSAPP_VERIFY_TOKEN=      ← del Paso 1
```

3. Guarda el archivo

---

## Paso 6 — Iniciar el sistema

1. Abre PowerShell en la carpeta del proyecto
2. Ejecuta:
```powershell
.\scripts\start-all.bat
```

Espera 2-3 minutos mientras se construyen los servicios.

3. Verifica que el bot está funcionando abriendo en tu navegador:
```
http://localhost:8006/health
```

Debes ver:
```json
{"service":"whatsapp-bot","status":"ok","version":"1.0.0"}
```

> **[INSERTAR IMAGEN: Navegador mostrando localhost:8006/health con la respuesta JSON de estado ok]**

---

## Paso 7 — Conectar WhatsApp con el bot

### 7.1 Exponer el bot al internet

Abre una nueva terminal PowerShell y ejecuta:
```powershell
ngrok http 8006
```

Verás una URL similar a:
```
https://wolverine-disarray-protegee.ngrok-free.dev
```

Copia esa URL completa.

> **⚠️ Mantén esta terminal abierta mientras uses el bot.**

### 7.2 Registrar el webhook

1. Ve a Meta Developers → tu app → **Paso 2: Configuración de producción**
2. Expande **"Configurar webhooks"**
3. Llena los campos:
   - **URL de devolución de llamada:** `https://TU-URL.ngrok-free.dev/webhook`
   - **Token de verificación:** el valor de `WHATSAPP_VERIFY_TOKEN` de tu `.env`
4. Haz clic en **"Verificar y guardar"**

> **[INSERTAR IMAGEN: Sección "Configurar webhooks" mostrando los campos URL de devolución de llamada y Token de verificación con el botón "Verificar y guardar"]**

### 7.3 Activar recepción de mensajes

En la lista de campos del webhook, busca **"messages"** y activa el interruptor a **"Suscritos"**.

> **[INSERTAR IMAGEN: Lista de campos del webhook con "messages" en estado "Suscritos" (toggle azul activado)]**

---

## Paso 8 — Probar el bot

Desde tu celular, envía un mensaje de WhatsApp al número de prueba:

**Número:** `+1 (555) 000-0000`
**Mensaje:** `FACTURA`

El bot debe responderte con el aviso de privacidad en menos de 10 segundos.

Sigue el flujo:
1. Responde **"SÍ"** para aceptar el aviso de privacidad
2. Ingresa tu **RFC**
3. Ingresa tu **Razón Social**
4. Ingresa tu **Código Postal**
5. Ingresa tu **Régimen Fiscal** (ej: 601)
6. Ingresa el **Uso CFDI** (ej: G03)
7. Ingresa tu **correo electrónico**
8. Ingresa el **número de ticket** de tu compra
9. Confirma los datos con **"SÍ"**
10. Recibirás tu factura en XML y PDF

---

## Solución de problemas frecuentes

**El bot no responde a mis mensajes**
- Verifica que ngrok esté corriendo en la terminal
- Verifica que la URL en Meta coincide con la URL actual de ngrok
- El token de Meta dura 24 horas — genera uno nuevo si venció

**Error "número no en lista de autorizados"**
- Tu número de celular debe estar agregado en la lista de destinatarios de Meta (Paso 3.5)

**La página localhost:3000 no carga**
- Espera 2-3 minutos después de ejecutar `start-all.bat`
- Verifica que Docker Desktop esté corriendo

---

## Soporte

Para soporte técnico contactar al equipo de desarrollo con:
- Captura del error
- Logs del bot: `docker logs cfdi-aes-whatsapp_bot-1 --tail 20`
- Versión del sistema: `docker compose version`
