from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


class DatosTicketOxxo(BaseModel):
    fecha_venta: str  # formato DD/MM/AAAA
    folio_venta: str
    id_venta: str
    total: float


class DatosFiscales(BaseModel):
    rfc: str
    razon_social: str
    calle: str
    numero_ext: str
    numero_int: Optional[str] = None
    colonia: str
    delegacion_municipio: str
    codigo_postal: str
    estado: str
    regimen_fiscal: str
    uso_cfdi: str
    email: str


class SolicitudFacturaOxxo(BaseModel):
    ticket: DatosTicketOxxo
    fiscal: DatosFiscales


# Mapeo codigo SAT -> texto EXACTO del catalogo de Regimen Fiscal en el
# portal de OXXO. Antes se guardaba el GUID de cada <option>, pero se
# confirmo con dos corridas reales (19 ago 2026) que esos GUIDs son tokens
# de sesion/vista de JSF - cambian en cada carga de pagina, no son ids
# estables de catalogo. El texto visible si es estable (es el catalogo SAT),
# asi que se selecciona por label= en vez de value=.
REGIMEN_FISCAL_OXXO = {
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Régimen de los ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales",
    "621": "Incorporación Fiscal",
    "625": "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}


@app.post("/portal/oxxo/facturar")
async def facturar_oxxo(solicitud: SolicitudFacturaOxxo):
    async with async_playwright() as p:
        # PENDIENTE (19 ago 2026): el dropdown de Regimen Fiscal
        # (#form:selectOneMenuRegFis) no abre su panel con ningun target de
        # click probado (trigger, contenedor, label), con o sin
        # playwright-stealth. El <select> real SI se puebla via AJAX tras
        # llenar RFC+CP (confirmado, usar label= no value= al seleccionar -
        # ver REGIMEN_FISCAL_OXXO), pero el panel visual de PrimeFaces nunca
        # se abre. Se probo headless=False + xvfb-run, pero xvfb-run se
        # atoraba antes de arrancar uvicorn (bloqueador de infraestructura
        # aparte, sin resolver) - revertido a headless=True mientras se
        # retoma esto. Ver tarjeta del Project para detalle completo.
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="es-MX",
            timezone_id="America/Mexico_City",
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        await page.goto(
            "https://www4.oxxo.com:9443/facturacionElectronica-web/views/layout/inicio.do"
        )

        # Cerrar el popup de ayuda si aparece (el que vimos en el screenshot)
        try:
            await page.click("text=×", timeout=3000)
        except Exception:
            pass

        # Paso 1: llenar datos del ticket
        # fecha_input tiene datepicker - intentamos fill directo primero,
        # si falla habrá que investigar el widget de calendario específico
        await page.fill("#form\\:folio", solicitud.ticket.folio_venta)
        await page.fill("#form\\:venta", solicitud.ticket.id_venta)
        await page.fill("#form\\:total", f"{solicitud.ticket.total:.2f}")

        # Cerrar el modal de ayuda (se reabre solo al llenar los campos del
        # ticket) - si no, bloquea el click en fecha_input igual que bloqueaba
        # el click en "Validar Ticket".
        try:
            await page.wait_for_selector(
                "#form\\:dlgInfoTicket .ui-dialog-titlebar-close",
                state="visible",
                timeout=5000
            )
            await page.click("#form\\:dlgInfoTicket .ui-dialog-titlebar-close")
            await page.wait_for_timeout(500)
        except Exception as exc:
            print(f"Modal no encontrado o no se pudo cerrar: {exc}")

        # Seleccionar fecha_venta en el datepicker (jQuery UI puro, sin
        # <select> de mes/año - confirmado con el HTML real capturado: mes/año
        # son texto en .ui-datepicker-month/.ui-datepicker-year, navegacion
        # via .ui-datepicker-prev/.ui-datepicker-next, dias en
        # td[data-month][data-year] > a.ui-state-default).
        dia, mes, anio = solicitud.ticket.fecha_venta.split("/")
        dia_objetivo = int(dia)
        mes_objetivo = int(mes) - 1  # data-month es 0-indexado
        anio_objetivo = int(anio)

        meses_es = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        ]

        await page.click("#form\\:fecha_input")
        await page.wait_for_selector("#ui-datepicker-div", state="visible", timeout=5000)

        for _ in range(24):  # salvaguarda contra loop infinito
            mes_actual_txt = await page.text_content(".ui-datepicker-month")
            anio_actual_txt = await page.text_content(".ui-datepicker-year")
            mes_actual = meses_es.index(mes_actual_txt.strip())
            anio_actual = int(anio_actual_txt.strip())

            if (anio_actual, mes_actual) == (anio_objetivo, mes_objetivo):
                await page.click(
                    f'td[data-month="{mes_objetivo}"][data-year="{anio_objetivo}"] '
                    f'a.ui-state-default:text-is("{dia_objetivo}")'
                )
                break

            if (anio_actual, mes_actual) < (anio_objetivo, mes_objetivo):
                await page.click(".ui-datepicker-next")
            else:
                await page.click(".ui-datepicker-prev")
            await page.wait_for_timeout(300)
        else:
            await browser.close()
            return {
                "status": "error_datepicker",
                "detalle": f"No se pudo navegar el datepicker hasta {solicitud.ticket.fecha_venta}",
            }

        await page.wait_for_timeout(500)

        # ── Modal de ayuda + Validar Ticket ──
        try:
            await page.wait_for_selector(
                "#form\\:dlgInfoTicket .ui-dialog-titlebar-close",
                state="visible",
                timeout=5000
            )
            await page.click("#form\\:dlgInfoTicket .ui-dialog-titlebar-close")
            await page.wait_for_timeout(500)  # dar tiempo a que la animación de cierre termine
        except Exception as exc:
            # Si no aparece o no se puede cerrar, seguimos - puede que a veces no salga
            print(f"Modal no encontrado o no se pudo cerrar: {exc}")

        await page.screenshot(path="/tmp/oxxo_paso2_ticket_lleno.png", full_page=True)

        try:
            await page.click("text=Validar Ticket", timeout=10000)
        except Exception as exc:
            await page.screenshot(path="/tmp/oxxo_debug_click_fallido.png", full_page=True)
            html_debug = await page.content()
            with open("/tmp/oxxo_debug_click_fallido.html", "w", encoding="utf-8") as f:
                f.write(html_debug)
            await browser.close()
            return {
                "status": "error_click_validar",
                "detalle": str(exc),
                "nota": "Revisar oxxo_debug_click_fallido (.png y .html)",
            }

        await page.wait_for_timeout(3000)
        await page.screenshot(path="/tmp/oxxo_paso3_post_validar.png", full_page=True)

        # "Validar Ticket" solo confirma el ticket inline - el warning "Ticket
        # pendiente por validar" sigue visible y la Seccion 2 (RFC, etc.) sigue
        # disabled hasta hacer click en "Continuar".
        try:
            await page.click("#form\\:continuar", timeout=5000)
            # Esperar de verdad a que el AJAX habilite RFC, en vez de un
            # timeout fijo - confirmado con un 500 real donde el click
            # "funciono" pero el campo seguia disabled 30s despues.
            await page.wait_for_function(
                """() => {
                    const el = document.querySelector('#form\\\\:rfc');
                    return el && !el.disabled;
                }""",
                timeout=15000,
            )
        except Exception as exc:
            print(f"No se pudo dar click en Continuar o RFC no se habilito: {exc}")

        # DEBUG temporal: llenar RFC + domicilio (Estado/Regimen Fiscal/Uso CFDI
        # estan disabled con catalogo vacio hasta entonces, confirmado con el
        # HTML real) y capturar el HTML resultante para ver las opciones reales
        # de los 3 dropdowns antes de escribir la logica de seleccion.
        await page.fill("#form\\:rfc", solicitud.fiscal.rfc)
        await page.fill("#form\\:razon", solicitud.fiscal.razon_social)
        await page.fill("#form\\:calle", solicitud.fiscal.calle)
        await page.fill("#form\\:ext", solicitud.fiscal.numero_ext)
        if solicitud.fiscal.numero_int:
            await page.fill("#form\\:int", solicitud.fiscal.numero_int)
        await page.fill("#form\\:colonia", solicitud.fiscal.colonia)
        await page.fill("#form\\:dele", solicitud.fiscal.delegacion_municipio)
        await page.fill("#form\\:codigo", solicitud.fiscal.codigo_postal)

        # Esperar a que el AJAX de RFC/CP realmente termine de poblar el
        # <select> de Regimen Fiscal (un wait_for_timeout fijo es fragil -
        # confirmado con un 500 real donde el AJAX tardo mas de 3000ms).
        # Mientras no responde, el select solo tiene la opcion placeholder
        # vacia (1 <option>); esperamos a que haya mas de 1.
        await page.wait_for_function(
            """() => {
                const sel = document.querySelector('#form\\\\:selectOneMenuRegFis_input');
                return sel && sel.options.length > 1;
            }""",
            timeout=15000,
        )

        regimen_texto = REGIMEN_FISCAL_OXXO.get(solicitud.fiscal.regimen_fiscal)
        if not regimen_texto:
            await browser.close()
            return {
                "status": "error_regimen_no_mapeado",
                "detalle": f"Régimen {solicitud.fiscal.regimen_fiscal} no está en REGIMEN_FISCAL_OXXO",
            }

        # select_option(force=True) sobre el <select> oculto NO funciono -
        # confirmado con un 500 real donde el HTML resultante seguia
        # mostrando la opcion placeholder como selected y Uso CFDI seguia
        # disabled. PrimeFaces no escucha el evento 'change' nativo del
        # select oculto, solo reacciona a clicks en su widget visual falso.
        # Se interactua con el widget real: abrir el panel + click en el
        # <li data-label="..."> con el texto exacto.
        #
        # El primer intento de click en el <div> contenedor completo no
        # abrio el panel (confirmado con un 500 real, timeout de 3000ms
        # esperando visibilidad) - el modal de ayuda pudo haberse vuelto a
        # abrir (mismo patron ya visto 2 veces) y/o el click necesita
        # apuntar al icono trigger especifico, no al div completo.
        try:
            await page.wait_for_selector(
                "#form\\:dlgInfoTicket .ui-dialog-titlebar-close",
                state="visible",
                timeout=3000
            )
            await page.click("#form\\:dlgInfoTicket .ui-dialog-titlebar-close")
            await page.wait_for_timeout(500)
        except Exception as exc:
            print(f"Modal no encontrado o no se pudo cerrar (previo a RegFis): {exc}")

        # El trigger existia en el DOM pero Playwright lo reporto "not
        # visible" durante 30s completos (confirmado con un 500 real) - el
        # HTML capturado justo despues del fallo mostraba el widget ya
        # habilitado y normal, sin nada tapandolo -> era timing: el widget
        # aun completaba su propia transicion visual de disabled->enabled
        # cuando intentamos el click (wait_for_function anterior solo
        # esperaba a que el <select> tuviera opciones, no a que el widget
        # visual terminara de habilitarse). Esperamos explicitamente a que
        # el div del widget ya no tenga la clase ui-state-disabled.
        try:
            await page.wait_for_function(
                """() => {
                    const w = document.querySelector('#form\\\\:selectOneMenuRegFis');
                    return w && !w.classList.contains('ui-state-disabled');
                }""",
                timeout=15000,
            )
        except Exception as exc:
            print(f"Widget RegFis no termino de habilitarse: {exc}")

        # Ni el trigger (height:0, bug de CSS de OXXO) ni el <div> contenedor
        # completo abrieron el panel. Volcar las dimensiones de todos los
        # hijos confirmo el objetivo real: LABEL#..._label (width:243,
        # height:24 - dimensiones reales, es el area de texto visible del
        # dropdown donde PrimeFaces ata su listener de click).
        try:
            await page.click("#form\\:selectOneMenuRegFis_label", timeout=10000)
            await page.wait_for_selector(
                "#form\\:selectOneMenuRegFis_panel", state="visible", timeout=5000
            )
            await page.click(f'#form\\:selectOneMenuRegFis_panel li[data-label="{regimen_texto}"]')
        except Exception as exc:
            await page.screenshot(path="/tmp/oxxo_debug_regfis_fallido.png", full_page=True)
            html_debug = await page.content()
            with open("/tmp/oxxo_debug_regfis_fallido.html", "w", encoding="utf-8") as f:
                f.write(html_debug)
            await browser.close()
            return {
                "status": "error_regfis_trigger",
                "detalle": str(exc),
                "nota": "Revisar oxxo_debug_regfis_fallido (.png y .html)",
            }

        await page.wait_for_timeout(2000)  # esperar AJAX que habilita Uso CFDI

        # DEBUG temporal: capturar de nuevo Uso CFDI, ahora que sabemos que
        # probablemente use el mismo patron de widget (panel + li[data-label])
        html_uso_cfdi = await page.content()
        with open("/tmp/oxxo_uso_cfdi_opciones2.html", "w", encoding="utf-8") as f:
            f.write(html_uso_cfdi)
        await page.screenshot(path="/tmp/oxxo_uso_cfdi2.png", full_page=True)

        await browser.close()
        return {"status": "debug_uso_cfdi_v2", "nota": "Confirmar si el regimen quedo seleccionado y ver panel de Uso CFDI"}
