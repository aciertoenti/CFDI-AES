"""
Reconocimiento PASIVO de alsea.interfactura.com - SOLO LECTURA.

No envia ningun dato de ticket/RFC, no hace submit de ningun formulario.
Objetivo: confirmar o descartar proteccion anti-bot (WAF / challenge JS /
CAPTCHA) antes de invertir tiempo en automatizacion real - la investigacion
preliminar (busquedas web + WHOIS + scanners de terceros) sugiere que este
sitio NO usa Incapsula/Imperva/Akamai Bot Manager/Cloudflare Bot
Management/PerimeterX/DataDome (a diferencia de OXXO, donde SI se encontro
Incapsula y se descarto automatizar por eso). Este script busca confirmar
esa senal indirecta con evidencia real.

Si en cualquier punto aparece un CAPTCHA, challenge JS visible, o un bloqueo
evidente, el script se detiene y lo reporta - no intenta evadir nada.

Uso (dentro del contenedor portal_automation, que ya tiene Playwright +
Chromium instalados):
    python recon.py
"""
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = Path(f"/tmp/alsea_recon_{TIMESTAMP}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL_INICIO = "https://alsea.interfactura.com"

ANTIBOT_SIGNATURES = [
    "incapsula", "_incapsula_resource", "reese84", "distil", "px-captcha",
    "datadome", "perimeterx", "recaptcha", "hcaptcha", "turnstile",
    "akamai-bmp", "cf-challenge", "cloudflare",
]

HEADERS_SOSPECHOSOS = (
    "server", "x-powered-by", "set-cookie", "cf-ray", "cf-mitigated",
    "x-akamai-transformed", "x-iinfo", "x-distil-cs", "x-datadome",
)

network_log = []
resumen = {
    "url_inicio": URL_INICIO,
    "timestamp": TIMESTAMP,
    "antibot_strings_encontrados": [],
    "pasos": [],
    "bloqueado": False,
    "tipo_fallo": None,  # "anti_bot" o "fallo_tecnico" - distingue deteccion real de anti-bot vs un simple bug de selector/timeout
    "motivo_bloqueo": None,
    "screenshots": [],
}


def _marcar_fallo(tipo: str, motivo: str):
    """tipo debe ser 'anti_bot' o 'fallo_tecnico'. Un fallo_tecnico (ej.
    selector no encontrado, timeout de click) NO es evidencia de anti-bot -
    se distingue explicitamente para no confundir un bug del script con
    una deteccion real."""
    resumen["bloqueado"] = True
    resumen["tipo_fallo"] = tipo
    resumen["motivo_bloqueo"] = motivo


def _registrar_signature(fuente: str, sig: str, donde: str):
    entrada = f"{fuente}:{sig} ({donde})"
    if entrada not in resumen["antibot_strings_encontrados"]:
        resumen["antibot_strings_encontrados"].append(entrada)


def _escanear_texto(texto: str, fuente: str, donde: str):
    texto_lower = texto.lower()
    for sig in ANTIBOT_SIGNATURES:
        if sig in texto_lower:
            _registrar_signature(fuente, sig, donde)


def _on_request(request):
    network_log.append({
        "tipo": "request",
        "url": request.url,
        "method": request.method,
        "resource_type": request.resource_type,
        "ts": time.time(),
    })


def _on_response(response):
    headers = response.headers
    relevantes = {k: v for k, v in headers.items() if k.lower() in HEADERS_SOSPECHOSOS}
    network_log.append({
        "tipo": "response",
        "url": response.url,
        "status": response.status,
        "headers_relevantes": relevantes,
        "ts": time.time(),
    })
    for k, v in headers.items():
        _escanear_texto(f"{k}:{v}", "header", response.url)

    # Escanear el cuerpo de respuestas HTML/JS (no solo el DOM final) -
    # el payload de un anti-bot a veces vive en un .js separado que no
    # queda como texto plano visible en page.content().
    content_type = headers.get("content-type", "")
    if any(t in content_type for t in ("text/html", "javascript", "text/plain")):
        try:
            body = response.text()
            _escanear_texto(body, "body", response.url)
        except Exception:
            pass  # respuesta no disponible (redirect, binario, etc.) - no critico


def _detectar_captcha_o_bloqueo(page) -> str | None:
    """Retorna motivo de bloqueo si detecta algo, None si limpio."""
    html = page.content().lower()
    if "captcha" in html:
        return "Texto 'captcha' encontrado en el HTML renderizado"
    if page.locator("iframe[src*='recaptcha']").count() > 0:
        return "iframe de reCAPTCHA detectado"
    if page.locator("iframe[src*='hcaptcha']").count() > 0:
        return "iframe de hCaptcha detectado"
    if page.locator("[id*='challenge'], [class*='challenge']").count() > 0:
        return "Elemento con id/class 'challenge' detectado"
    return None


def _paso(nombre: str, page, inicio_ts: float):
    duracion = time.time() - inicio_ts
    screenshot_path = OUT_DIR / f"{nombre}.png"
    page.screenshot(path=str(screenshot_path), full_page=True)
    resumen["screenshots"].append(str(screenshot_path))
    resumen["pasos"].append({
        "nombre": nombre,
        "duracion_seg": round(duracion, 2),
        "url_final": page.url,
        "status_code": None,  # se llena en el caller si aplica
    })
    _escanear_texto(page.content(), "html_dom", nombre)
    print(f"[{nombre}] {duracion:.2f}s - {page.url}")

    motivo = _detectar_captcha_o_bloqueo(page)
    if motivo:
        _marcar_fallo("anti_bot", f"{motivo} (paso: {nombre})")
        print(f"  >>> BLOQUEO DETECTADO: {motivo}")
    return motivo


def _ejecutar_recon(page) -> bool:
    """Retorna True si debe seguir al siguiente paso, False si debe detenerse
    (bloqueo detectado o fallo tecnico ya registrado via _marcar_fallo)."""
    # ── Paso 1: home ──────────────────────────────────────────────
    t0 = time.time()
    resp = page.goto(URL_INICIO, wait_until="networkidle", timeout=30000)
    motivo = _paso("01_home", page, t0)
    resumen["pasos"][-1]["status_code"] = resp.status if resp else None
    if motivo:
        return False

    # ── Paso 2: intentar ubicar seleccion de marca (Dominos/Alsea) ──
    # Confirmado con 01_home.png: es una grilla de logos clickeables
    # (imagenes), no una lista de texto - el <li>Domino's Pizza</li>
    # que existia en el DOM era un elemento oculto (probable texto de
    # accesibilidad), por eso el primer intento fallo con "not visible".
    # Se busca primero por imagen (alt/src), y solo si eso no existe se
    # cae al texto visible como respaldo.
    t0 = time.time()
    candidato = None
    for patron in ["domino", "Domino"]:
        loc = page.locator(f"img[alt*='{patron}' i], img[src*='{patron}' i]")
        if loc.count() > 0:
            candidato = loc.first
            break
    if candidato is None:
        for texto_buscado in ["Domino", "DOMINO", "Domino's", "Dominos"]:
            loc = page.get_by_text(texto_buscado, exact=False)
            if loc.count() > 0 and loc.first.is_visible():
                candidato = loc.first
                break

    if candidato is None:
        nota = ("No se encontro un elemento con texto 'Domino/Dominos' en la home. "
                "Revisar 01_home.png y el HTML manualmente para ubicar el selector real.")
        resumen["pasos"].append({
            "nombre": "02_seleccion_marca",
            "duracion_seg": 0,
            "url_final": page.url,
            "nota": nota,
        })
        _marcar_fallo("fallo_tecnico", f"02_seleccion_marca: {nota}")
        print("[02_seleccion_marca] No se encontro candidato visible - deteniendo aqui.")
        return False

    try:
        candidato.click(timeout=5000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        nota = f"Click en candidato de marca fallo: {exc}"
        resumen["pasos"].append({
            "nombre": "02_seleccion_marca",
            "duracion_seg": round(time.time() - t0, 2),
            "url_final": page.url,
            "nota": nota,
        })
        _marcar_fallo("fallo_tecnico", f"02_seleccion_marca: {nota}")
        print(f"[02_seleccion_marca] Click fallo: {exc}")
        return False

    motivo = _paso("02_seleccion_marca", page, t0)
    if motivo:
        return False

    # ── Paso 3: intentar ubicar el formulario de folio/RFC ──────────
    # Solo se localiza y se documenta - NUNCA se llena ni se envia.
    t0 = time.time()
    campos_encontrados = []
    for patron in ["folio", "rfc", "ticket", "referencia"]:
        loc = page.locator(
            f"input[name*='{patron}' i], input[id*='{patron}' i]"
        )
        n = loc.count()
        if n > 0:
            campos_encontrados.append({"patron": patron, "cantidad": n})

    resumen["pasos"].append({
        "nombre": "03_formulario_datos",
        "duracion_seg": round(time.time() - t0, 2),
        "url_final": page.url,
        "campos_input_detectados": campos_encontrados,
    })
    _paso("03_formulario_datos", page, t0)
    return True


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.on("request", _on_request)
        page.on("response", _on_response)

        # Cualquier excepcion no capturada en un paso especifico (ej. el
        # page.goto() inicial reventando por timeout, sin try/except propio)
        # se atrapa aqui - garantiza que SIEMPRE se escriba resumen.json,
        # en vez de crashear con traceback crudo y perder toda la evidencia
        # ya recolectada hasta ese punto.
        try:
            _ejecutar_recon(page)
        except Exception as exc:
            nota = f"Excepcion no manejada durante el recon: {exc}"
            print(f"[ERROR] {nota}")
            _marcar_fallo("fallo_tecnico", nota)
            try:
                emergencia = OUT_DIR / "99_excepcion_no_manejada.png"
                page.screenshot(path=str(emergencia), full_page=True)
                resumen["screenshots"].append(str(emergencia))
            except Exception:
                pass  # si ni siquiera se puede tomar screenshot, seguir sin el

        browser.close()
        _finalizar()


def _finalizar():
    resumen["flujo_completado_sin_bloqueos"] = not resumen["bloqueado"]

    with open(OUT_DIR / "network_log.json", "w", encoding="utf-8") as f:
        json.dump(network_log, f, ensure_ascii=False, indent=2)

    with open(OUT_DIR / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    print("\n=== RESUMEN ===")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f"\nOutput completo en: {OUT_DIR}")


if __name__ == "__main__":
    main()
