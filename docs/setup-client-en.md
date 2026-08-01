# Activation Guide — WhatsApp Invoicing Bot
## CFDI-AES | User Guide | Version 1.0

---

Welcome. This guide walks you through activating the WhatsApp invoicing bot for your business, step by step, with no technical knowledge required.

---

## What You Need Before Starting

- An active Facebook Business account
- A dedicated phone number for WhatsApp Business (cannot have personal WhatsApp active)
- Docker Desktop installed on your computer
- Internet access

**Estimated time:** 60 to 90 minutes the first time.

---

## Step 1 — Prepare Security Credentials

These keys protect communication between services. You generate them yourself in seconds.

Open PowerShell and run these three lines one at a time:

```powershell
python -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"
python -c "import secrets; print('INTERNAL_API_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('WHATSAPP_VERIFY_TOKEN=' + secrets.token_urlsafe(24))"
```

Save the three values that appear — you will use them in the following steps.

> **[INSERT IMAGE: PowerShell terminal showing the three commands executed with their generated values]**

---

## Step 2 — Configure the Billing PAC (Finkok)

The PAC is the service that stamps invoices with Mexico's SAT tax authority.

**For testing (free):**

1. Go to [https://finkok.com](https://finkok.com) and create a free account
2. Confirm your email address
3. Note your username (email) and password

**For production:**
- Purchase a plan at [https://finkok.com](https://finkok.com)
- Finkok activates your credentials within 1-2 business days

---

## Step 3 — Create Your Meta App (WhatsApp Business)

### 3.1 Developer Account

1. Go to [https://developers.facebook.com](https://developers.facebook.com)
2. Sign in with your business Facebook account
3. Accept the terms when prompted

### 3.2 Create the Application

1. Click **"Create app"**
2. Choose type **"Business"**
3. Give it a name (for example: `MyBusiness-Bot`)
4. Associate your Facebook Business account
5. Click **"Create app"**

> **[INSERT IMAGE: Meta Developers panel showing the CFDI-AES-Bot app just created with its App Identifier]**

### 3.3 Enable WhatsApp in the App

1. In the app panel, click **"Use cases"**
2. Find **"Connect with customers via WhatsApp"**
3. Click the arrow on the right
4. Select **"Integrate via API"**

> **[INSERT IMAGE: "Choose your integration type" screen with "Integrate via API" selected, showing the 3 steps of the process]**

### 3.4 Get Your WhatsApp Credentials

1. In the left menu go to **Step 1. Try it**
2. In the **"Get a WhatsApp test number"** section you will see:
   - Your free test number
   - The **Phone Number ID** — write it down
3. Click **"Generate token"**
4. In the window that appears, select **"Test WhatsApp Business Account"** and click **"Continue"**

> **[INSERT IMAGE: "Step 1. Try it" screen showing number +1 (555) 663-9018, Phone Number ID and the access token field with "Generate token" button]**

> **[INSERT IMAGE: OAuth popup window to select the WhatsApp account, with "Test WhatsApp Business Account" available to select]**

5. Copy the complete token that appears in the **"Access token"** field

### 3.5 Add Your Number to Receive Test Messages

1. In the **"Send a message from your test number"** section
2. In the **To** field → open the dropdown → **"Manage phone number list"**
3. Add your cell number (format: `521XXXXXXXXXX` for Mexico)
4. Meta sends a code via WhatsApp — enter it to confirm

> **[INSERT IMAGE: "Send a message from your test number" screen with recipient +52-55-3665-2444 already selected in the dropdown]**

---

## Step 4 — Install and Configure ngrok

ngrok connects your computer to the internet so WhatsApp can send messages to your bot.

**Install from Microsoft Store:**
1. Open Microsoft Store
2. Search for "ngrok"
3. Click **"Get"** or **"Open"** if already installed

> **[INSERT IMAGE: Microsoft Store showing the ngrok app with the "Open" button (already installed)]**

**Create free account:**
1. Go to [https://ngrok.com](https://ngrok.com) and sign up
2. Go to [https://dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
3. Copy your authentication token

> **[INSERT IMAGE: ngrok dashboard showing the "Your Authtoken" section with the token in the text field]**

**Connect ngrok:**
```powershell
ngrok config add-authtoken YOUR_TOKEN_HERE
```

---

## Step 5 — Configure the Environment Variables File

1. In the project folder, copy the example file:
```powershell
copy .env.example .env
```

2. Open `.env` with Notepad and fill in these values with what you obtained in the previous steps:

```
JWT_SECRET=          ← from Step 1
INTERNAL_API_KEY=    ← from Step 1
PAC_URL=https://demo-facturacion.finkok.com/servicios/soap/stamp.wsdl
PAC_USER=            ← your Finkok email
PAC_PASS=            ← your Finkok password
WHATSAPP_TOKEN=      ← from Step 3.4
WHATSAPP_PHONE_NUMBER_ID=   ← from Step 3.4
WHATSAPP_VERIFY_TOKEN=      ← from Step 1
```

3. Save the file

---

## Step 6 — Start the System

1. Open PowerShell in the project folder
2. Run:
```powershell
.\scripts\start-all.bat
```

Wait 2-3 minutes while the services are built.

3. Verify the bot is working by opening in your browser:
```
http://localhost:8006/health
```

You should see:
```json
{"service":"whatsapp-bot","status":"ok","version":"1.0.0"}
```

> **[INSERT IMAGE: Browser showing localhost:8006/health with the JSON status ok response]**

---

## Step 7 — Connect WhatsApp to the Bot

### 7.1 Expose the Bot to the Internet

Open a new PowerShell terminal and run:
```powershell
ngrok http 8006
```

You will see a URL similar to:
```
https://wolverine-disarray-protegee.ngrok-free.dev
```

Copy that complete URL.

> **⚠️ Keep this terminal open while using the bot.**

### 7.2 Register the Webhook

1. Go to Meta Developers → your app → **Step 2: Production setup**
2. Expand **"Configure webhooks"**
3. Fill in the fields:
   - **Callback URL:** `https://YOUR-URL.ngrok-free.dev/webhook`
   - **Verify token:** the value of `WHATSAPP_VERIFY_TOKEN` from your `.env`
4. Click **"Verify and save"**

> **[INSERT IMAGE: "Configure webhooks" section showing the Callback URL and Verify token fields with the "Verify and save" button]**

### 7.3 Enable Message Reception

In the webhook fields list, find **"messages"** and toggle it to **"Subscribed"**.

> **[INSERT IMAGE: Webhook fields list with "messages" in "Subscribed" state (blue toggle activated)]**

---

## Step 8 — Test the Bot

From your cell phone, send a WhatsApp message to the test number:

**Number:** `+1 (555) 663-9018`
**Message:** `FACTURA`

The bot should reply with the privacy notice within 10 seconds.

Follow the flow:
1. Reply **"SÍ"** (Yes) to accept the privacy notice
2. Enter your **RFC** (tax ID)
3. Enter your **Business name**
4. Enter your **Postal Code**
5. Enter your **Tax Regime** (e.g. 601)
6. Enter the **CFDI Use** (e.g. G03)
7. Enter your **email address**
8. Enter the **ticket number** from your purchase
9. Confirm the data with **"SÍ"**
10. You will receive your invoice as XML and PDF

---

## Common Troubleshooting

**The bot does not respond to my messages**
- Verify ngrok is running in the terminal
- Verify the URL in Meta matches the current ngrok URL
- Meta tokens expire after 24 hours — generate a new one if it expired

**Error "number not in allowed list"**
- Your cell number must be added to the Meta recipients list (Step 3.5)

**The localhost:3000 page does not load**
- Wait 2-3 minutes after running `start-all.bat`
- Verify Docker Desktop is running

---

## Support

For technical support contact the development team with:
- Screenshot of the error
- Bot logs: `docker logs cfdi-aes-whatsapp_bot-1 --tail 20`
- System version: `docker compose version`
