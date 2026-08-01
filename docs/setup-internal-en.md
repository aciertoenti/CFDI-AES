# Configuration Guide — CFDI-AES WhatsApp Bot
## Internal Technical Document | Version 1.0 | July 2026

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Secret Generation](#2-secret-generation)
3. [PAC Finkok Configuration](#3-pac-finkok-configuration)
4. [WhatsApp Business API Configuration (Meta)](#4-whatsapp-business-api-configuration-meta)
5. [ngrok Configuration](#5-ngrok-configuration)
6. [Stack Startup](#6-stack-startup)
7. [Webhook Registration in Meta](#7-webhook-registration-in-meta)
8. [System Verification](#8-system-verification)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

| Tool | Min Version | Verify with |
|---|---|---|
| Docker Desktop | 4.x | `docker --version` |
| Python | 3.12 | `python --version` |
| ngrok | 3.x | `ngrok version` |
| Git | 2.x | `git --version` |

**Clone the repository:**
```bash
git clone https://github.com/your-org/CFDI-AES.git
cd CFDI-AES
```

---

## 2. Secret Generation

Run in PowerShell from the project root:

```powershell
python -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"
python -c "import secrets; print('INTERNAL_API_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('WHATSAPP_VERIFY_TOKEN=' + secrets.token_urlsafe(24))"
```

> **[INSERT IMAGE: PowerShell terminal showing the three generated values — JWT_SECRET, INTERNAL_API_KEY and WHATSAPP_VERIFY_TOKEN]**

Copy the values to the `.env` file:
```bash
copy .env.example .env
```

Expected `.env` result:
```env
JWT_SECRET=54383c366502fd63...
INTERNAL_API_KEY=ef6233b9adcef8...
WHATSAPP_VERIFY_TOKEN=ZCdjqDmwd--Rtm...
```

---

## 3. PAC Finkok Configuration

### 3.1 Demo Environment (Testing)

1. Register at [https://finkok.com](https://finkok.com)
2. Confirm the activation email
3. Access the portal and obtain credentials

Update `.env`:
```env
PAC_URL=https://demo-facturacion.finkok.com/servicios/soap/stamp.wsdl
PAC_CANCEL_URL=https://demo-facturacion.finkok.com/servicios/soap/cancel.wsdl
PAC_USER=your_email@domain.com
PAC_PASS=your_password
```

### 3.2 Production Environment

Change only the URLs:
```env
PAC_URL=https://ws.finkok.com/servicios/soap/stamp.wsdl
PAC_CANCEL_URL=https://ws.finkok.com/servicios/soap/cancel.wsdl
```

---

## 4. WhatsApp Business API Configuration (Meta)

### 4.1 Create Developer Account

1. Go to [https://developers.facebook.com](https://developers.facebook.com)
2. Sign in with your Facebook account
3. Accept the Meta Platform Terms

### 4.2 Create the App

1. Dashboard → **Create app**
2. Type: **Business**
3. Name: `CFDI-AES-Bot`
4. Associate Business Manager account
5. Click **Create app**

> **[INSERT IMAGE: "My apps" panel showing the CFDI-AES-Bot app with App ID: 3166009700262242]**

### 4.3 Add WhatsApp

1. App panel → **Use cases**
2. Select **"Connect with customers via WhatsApp"**
3. Click **"Customize"**
4. Select **"Integrate via API"**

> **[INSERT IMAGE: "Choose your integration type" screen with "Integrate via API" button selected in blue, showing 3 steps: Try it, Production setup, Business verification]**

### 4.4 Get Credentials (Step 1 — Try it)

1. Left menu → **Basic configuration** → **Step 1. Try it**
2. Expand **"Get a WhatsApp test number"**

> **[INSERT IMAGE: "Step 1. Try it" screen showing: Test number +1 (555) 663-9018, Phone Number ID: 1152873881252049, WhatsApp Business Account ID: 1257549279733383, and the "Access token" field with "Generate token" button]**

3. Click **"Generate token"**
4. Select **"Test WhatsApp Business Account"** in the OAuth popup

> **[INSERT IMAGE: OAuth popup "Choose the WhatsApp accounts you want CFDI-AES-Bot to access" showing "Test WhatsApp Business Account" with checkbox]**

5. Copy the generated token

Update `.env`:
```env
WHATSAPP_TOKEN=EAAsBOKIWIBSI...  (complete token)
WHATSAPP_PHONE_NUMBER_ID=1152873881252049
```

### 4.5 Add Test Recipient Number

1. In section **"Send a message from your test number"**
2. **To** field → dropdown → **"Manage phone number list"**
3. Add number in format: `521XXXXXXXXXX` (Mexico)
4. Enter the verification code received via WhatsApp

> **[INSERT IMAGE: "Send a message from your test number" screen with recipient +52-55-3665-2444 selected and "Send message" button]**

---

## 5. ngrok Configuration

### 5.1 Install and Authenticate

ngrok available on Microsoft Store or [https://ngrok.com/download](https://ngrok.com/download).

Verify installation:
```powershell
ngrok version
# ngrok version 3.39.8
```

Authenticate with token from [https://dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken):

> **[INSERT IMAGE: ngrok dashboard showing "Your Authtoken" section with the token visible in the text field]**

```powershell
ngrok config add-authtoken YOUR_TOKEN_HERE
```

### 5.2 Expose the Bot

Open a dedicated terminal (keep it open):
```powershell
ngrok http 8006
```

Output:
```
Session Status    online
Forwarding        https://wolverine-disarray-protegee.ngrok-free.dev -> http://localhost:8006
```

> **[INSERT IMAGE: PowerShell terminal showing ngrok running with Session Status: online and the Forwarding URL]**

> **⚠️ Important:** The ngrok URL changes every time it restarts. For development use a static domain (see section 9).

---

## 6. Stack Startup

```powershell
cd C:\PersonalWorkspace\CFDI-AES
.\scripts\start-all.bat
```

Verify all services are active:
```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Verify the bot:
```
http://localhost:8006/health
```

Expected response:
```json
{"service":"whatsapp-bot","status":"ok","version":"1.0.0"}
```

> **[INSERT IMAGE: Browser showing localhost:8006/health with JSON response {"service":"whatsapp-bot","status":"ok","version":"1.0.0"}]**

---

## 7. Webhook Registration in Meta

1. Meta Developers → app **CFDI-AES-Bot**
2. **Use cases** → **Step 2: Production setup**
3. Expand **"Configure webhooks"**

> **[INSERT IMAGE: "Configure webhooks" section expanded showing "Callback URL" and "Verify token" fields with the "Verify and save" button]**

4. Fill in the fields:

| Field | Value |
|---|---|
| Callback URL | `https://YOUR-URL.ngrok-free.dev/webhook` |
| Verify token | Value of `WHATSAPP_VERIFY_TOKEN` in `.env` |

5. Click **"Verify and save"**
6. Expected log in bot:
```json
{"event": "webhook.verified", "level": "info"}
```

### 7.1 Subscribe to messages field

In the **"Webhook fields"** list, find `messages` and toggle to **"Subscribed"**.

> **[INSERT IMAGE: Webhook fields list showing "messages" with toggle in "Subscribed" position (blue)]**

---

## 8. System Verification

### 8.1 Manual Webhook Test

```powershell
$body = '{"object":"whatsapp_business_account","entry":[{"changes":[{"value":{"messages":[{"from":"525536652444","id":"test001","type":"text","text":{"body":"FACTURA"}}]}}]}]}'

Invoke-WebRequest -Uri "https://YOUR-URL.ngrok-free.dev/webhook" `
  -Method POST -ContentType "application/json" `
  -Body $body -UseBasicParsing
```

Expected response:
```json
{"status":"ok"}
```

### 8.2 Verify Bot Logs

```powershell
docker logs cfdi-aes-whatsapp_bot-1 --tail 10
```

Expected log:
```json
{"wa_id": "525536652444", "estado": "INICIO", "event": "state_machine.process"}
```

> **[INSERT IMAGE: ngrok dashboard showing POST /webhook with 200 OK and the JSON payload of the "FACTURA" message]**

### 8.3 WhatsApp End-to-End Test

1. Send message **"FACTURA"** to number `+1 (555) 663-9018`
2. Bot replies with privacy notice
3. Reply **"SÍ"** to continue the tax data capture flow

---

## 9. Troubleshooting

| Error | Cause | Solution |
|---|---|---|
| `ERR_EMPTY_RESPONSE` on `:3000` | Nginx not configured | Rebuild: `docker compose up --build frontend` |
| `ERR_NGROK_4018` | ngrok not authenticated | `ngrok config add-authtoken YOUR_TOKEN` |
| `#131030` Recipient not in allowed list | Number not in Meta test list | Add number in Step 1 → Recipient |
| `Object with ID does not exist` | Wrong `WHATSAPP_PHONE_NUMBER_ID` | Copy exact ID from Meta Developers |
| Bot not receiving messages | ngrok URL changed | Restart ngrok and update webhook in Meta |
| Token expired after 24h | Temporary Meta token | Generate new token in Step 1 → "Generate new token" |

### 9.1 Static ngrok Domain (Recommended)

To prevent URL changes on restart:

1. Go to [https://dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains)
2. Click **"New Domain"** (free plan includes 1 static domain)
3. Copy the assigned domain (e.g. `cfdi-aes-bot.ngrok-free.app`)
4. Always use:
```powershell
ngrok http --domain=cfdi-aes-bot.ngrok-free.app 8006
```
5. Update webhook in Meta with that fixed URL

---

## Environment Variables — Complete Reference

| Variable | Description | Example |
|---|---|---|
| `JWT_SECRET` | JWT token secret | `54383c366502fd63...` |
| `INTERNAL_API_KEY` | Inter-service key | `ef6233b9adcef8...` |
| `PAC_URL` | Finkok stamp URL | `https://demo-facturacion...` |
| `PAC_CANCEL_URL` | Finkok cancel URL | `https://demo-facturacion...` |
| `PAC_USER` | Finkok username | `email@domain.com` |
| `PAC_PASS` | Finkok password | `password` |
| `WHATSAPP_TOKEN` | Meta Cloud API token | `EAAsZCe...` |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp number ID | `1152873881252049` |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verify token | `ZCdjqDmwd--Rtm...` |
| `EMISOR_RFC_DEFAULT` | Issuer RFC | `DNS010101AAA` |
