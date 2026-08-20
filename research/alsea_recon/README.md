# Reconocimiento anti-bot: alsea.interfactura.com

## Contexto

Antes de invertir tiempo construyendo la automatización real de facturación
para Domino's/Alsea (siguiente destino tras abandonar OXXO por Incapsula —
ver `backend/microservices/portal_automation/`), se hizo un reconocimiento
pasivo controlado con Playwright para confirmar si `alsea.interfactura.com`
tiene protección anti-bot similar antes de repetir el mismo esfuerzo que se
perdió con OXXO.

Investigación preliminar (búsquedas web + WHOIS + scanners de terceros) ya
sugería que este portal NO usa Incapsula/Imperva/Akamai Bot
Manager/Cloudflare Bot Management/PerimeterX/DataDome — evidencia indirecta.
Este script (`recon.py`) confirma esa señal con evidencia real y controlada.

## Qué hace el script

Navegación **de solo lectura**: abre la home, selecciona la marca Domino's,
y localiza (sin llenar ni enviar) el formulario de captura de RFC/ticket.
En ningún momento escribe ni envía datos reales. Si detecta CAPTCHA,
challenge JS o cualquier bloqueo evidente, se detiene y lo reporta en vez de
intentar evadirlo.

Reutiliza el entorno de `portal_automation` (Playwright + Chromium ya
instalados en esa imagen Docker) vía `docker exec` — no instala nada nuevo.

## Conclusión

**No se encontró protección anti-bot en `alsea.interfactura.com`.**

- Flujo completo (home → selección de marca → formulario) en ~5 segundos
  totales, sin delays artificiales — contraste directo con los timeouts de
  varios minutos que se veían constantemente contra OXXO.
- Headers de respuesta limpios en el dominio propio del sitio. El único
  string capturado por el escáner (`cloudflare`) es un falso positivo:
  pertenece a `cdn.jsdelivr.net` (CDN público de terceros que sirve la
  librería genérica `alertifyjs`), no al dominio de Alsea.
- Sin CAPTCHA, sin iframe de reCAPTCHA/hCaptcha, sin elementos
  `id`/`class` con "challenge".
- La navegación real (no solo el click de Playwright) quedó confirmada de
  forma independiente: los beacons de Google Analytics (`google-analytics.com/g/collect`)
  registraron pageviews reales tanto para `Home` como para
  `wwwroot?opc=Dominos` — si un WAF hubiera interceptado/redirigido
  silenciosamente la navegación, ese segundo beacon con el `dl` correcto no
  habría llegado a dispararse igual.

## Nota sobre el stack real

El sitio es una **SPA Angular** (confirmado por el atributo `_ngcontent-c1`
en el DOM), no ASP.NET WebForms clásico como se asumió inicialmente solo
por convención de URL (`.aspx`/`wwwroot`). Esto es relevante para diseñar
la automatización real: los selectores estables van a ser de Angular
(atributos `_ngcontent-*`, bindings), no controles server-side clásicos
como en OXXO (JSF/PrimeFaces).

## Evidencia

Las capturas completas (screenshots, `network_log.json`, `resumen.json` de
cada corrida) **no se incluyen en este repo** — viven en el scratchpad de
la sesión y se copiaron a Downloads para revisión manual. No se subieron
porque no se revisó exhaustivamente que `network_log.json` (que registra
cada URL de red completa) esté libre de tokens/ids de sesión antes de
decidir si es publicable; más simple mantenerlo fuera del repo por ahora.

Si se necesita reproducir la evidencia, correr `recon.py` de nuevo genera
un directorio nuevo con timestamp (`/tmp/alsea_recon_<timestamp>/` dentro
del contenedor).

## Decisión resultante

Se procede a construir la automatización real de facturación para
Domino's/Alsea. El ticket ya pagado para pruebas está listo.
