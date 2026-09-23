// Helpers compartidos - pruebas E2E del modal de declaraciones anuales
// (reporte 190, automatizacion del reporte 188).
//
// Credenciales SOLO via E2E_USUARIO/E2E_PASSWORD (variables de entorno,
// pedido explicito) - nunca escritas aqui ni en ningun otro archivo del
// repo. Si faltan, las pruebas fallan de inmediato con un mensaje claro
// (fail-closed, mismo criterio que el resto del proyecto) en vez de
// intentar algo con un valor vacio.
import { expect } from "@playwright/test";

export const E2E_USUARIO = process.env.E2E_USUARIO;
export const E2E_PASSWORD = process.env.E2E_PASSWORD;

export function credencialesConfiguradas() {
  return Boolean(E2E_USUARIO && E2E_PASSWORD);
}

// RFC real de prueba usado en 183/185 (persona moral, negocio 1 - el
// mismo negocio de la cuenta E2E_USUARIO) - NO usar un RFC de persona
// fisica real (regla ya establecida desde la investigacion de
// declaraciones anuales, ver reporte 182: EKU9003173C9 solo como
// contenedor tecnico, nunca como "caso de uso" fiscal real).
export const RFC_EMISOR_PRUEBA = "EKU9003173C9";

// Nombres de archivo con un prefijo reconocible - permite al hook de
// limpieza final (afterAll) distinguir documentos creados por ESTA
// suite de cualquier otro documento real que pudiera existir para el
// mismo emisor, sin borrar a ciegas.
export function nombreArchivoE2E(caso) {
  return `e2e-declaraciones-${caso}-${Date.now()}.pdf`;
}

// PDF SINTETICO minimo (nunca un PDF real del titular - regla explicita
// de la tarea, Downloads/cfdi tiene documentos fiscales personales
// reales). Firma %PDF- real (misma tecnica ya usada en 183/185/188 para
// las pruebas de backend) - no necesita ser parseable de verdad, el
// backend/frontend nunca abren el contenido, solo verifican la firma y
// el tamaño.
export function bufferPdfSintetico(etiqueta = "") {
  const texto = `Declaracion sintetica E2E - ${etiqueta} - ${new Date().toISOString()} - NO es un documento fiscal real, generado por la suite de pruebas 190.`;
  return Buffer.from(`%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\n${texto}\n%%EOF`, "binary");
}

// ─── PDFs sinteticos con CAPA DE TEXTO REAL (reporte 189) ──────────────────
//
// bufferPdfSintetico() de arriba (sin xref valido) es SUFICIENTE para los
// casos 1-16 (190/188): solo prueban la guardia de cambios/foco/a11y, nunca
// dependen de que el backend clasifique el contenido - de hecho el nuevo
// backend (189) lo clasifica NO_RECONOCIDO, que es justo el estado que esos
// casos necesitan (formulario manual, puede_guardar=true).
//
// Los 3 casos NUEVOS de 189 (acuse -> tarjeta de confirmacion, opinion ->
// rechazo, RFC ajeno -> rechazo) si necesitan que pypdf pueda abrir el
// archivo y extraer texto real - construirPdfConTexto() arma un PDF minimo
// pero VALIDO a mano (Catalog/Pages/Page/Font/Contents + tabla xref con
// offsets de bytes calculados en el momento) en vez de agregar una
// dependencia nueva (pdf-lib/pdfkit) solo para esto - mismo criterio de "sin
// dependencias innecesarias" ya aplicado en el backend (pypdf sobre
// PyMuPDF/pdfplumber, reportlab solo en tests de backend, nunca en la
// imagen de produccion).
//
// Los renglones se escriben SIN acentos a proposito - el backend normaliza
// (NFKD + upper) antes de comparar contra los marcadores, que ya estan
// escritos sin acento en declaraciones_pdf.py, asi que el acento es
// irrelevante para la clasificacion/extraccion; omitirlo aqui evita
// cualquier ambigüedad de conteo de bytes en la tabla xref (contenido
// puramente ASCII, 1 caracter = 1 byte, sin tener que decidir entre
// latin1/utf-8 al calcular offsets).
function _escaparCadenaPdf(texto) {
  return String(texto).replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function construirPdfConTexto(lineas) {
  let y = 750;
  const cuerpo = ["BT", "/F1 10 Tf"];
  for (const linea of lineas) {
    cuerpo.push(`1 0 0 1 50 ${y} Tm`);
    cuerpo.push(`(${_escaparCadenaPdf(linea)}) Tj`);
    y -= 16;
  }
  cuerpo.push("ET");
  const streamContenido = cuerpo.join("\n");

  // 5 objetos indirectos: 1 Catalog, 2 Pages, 3 Page, 4 Contents (stream),
  // 5 Font. Orden y numeros fijos a proposito (mas simple que resolverlos
  // dinamicamente) - suficiente para un documento de 1 pagina.
  const objetos = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${streamContenido.length} >>\nstream\n${streamContenido}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];

  let pdf = "%PDF-1.4\n";
  const offsets = [0]; // offsets[0] = objeto libre 0, no se usa
  for (let i = 0; i < objetos.length; i++) {
    offsets.push(pdf.length); // ASCII puro en todo el documento: 1 char = 1 byte, .length es el offset real
    pdf += `${i + 1} 0 obj\n${objetos[i]}\nendobj\n`;
  }
  const offsetXref = pdf.length;
  let xref = `xref\n0 ${objetos.length + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= objetos.length; i++) {
    xref += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += xref;
  pdf += `trailer\n<< /Size ${objetos.length + 1} /Root 1 0 R >>\nstartxref\n${offsetXref}\n%%EOF`;

  return Buffer.from(pdf, "binary");
}

// Formato RECIENTE (el que usa /analizar y /documentos hoy para persona
// fisica, ver declaraciones_pdf.py): "RFC:", "Numero de operacion:".
export function bufferAcuseSintetico({
  rfc = RFC_EMISOR_PRUEBA,
  ejercicio = new Date().getFullYear() - 1,
  numeroOperacion = `OP${Date.now()}`,
  fecha = "15/03/2026",
  hora = "10:30:00",
} = {}) {
  return construirPdfConTexto([
    "SERVICIO DE ADMINISTRACION TRIBUTARIA",
    "ACUSE DE RECIBO",
    `DECLARACION DEL EJERCICIO ${ejercicio}`,
    `RFC: ${rfc}`,
    `Numero de operacion: ${numeroOperacion}`,
    `Fecha y hora de presentacion: ${fecha} ${hora}`,
    "SALDO A FAVOR: $0.00",
    "CANTIDAD A CARGO: $0.00",
    "CANTIDAD A PAGAR: $0.00",
    "INGRESOS QUE DECLARA",
    "Sueldos, salarios y asimilados",
    "ANEXOS QUE PRESENTA",
  ]);
}

export function bufferOpinionCumplimientoSintetica({ rfc = RFC_EMISOR_PRUEBA } = {}) {
  return construirPdfConTexto([
    "SERVICIO DE ADMINISTRACION TRIBUTARIA",
    "Opinion del cumplimiento de obligaciones fiscales",
    `RFC: ${rfc}`,
    "Sentido: Positivo",
  ]);
}

export async function login(page) {
  if (!credencialesConfiguradas()) {
    throw new Error(
      "Faltan E2E_USUARIO/E2E_PASSWORD en el entorno - defínelas en la terminal antes de correr la suite (nunca las escribas en un archivo).",
    );
  }
  // "/" renderiza PlanesLanding (pagina de mercadeo publica), NO el login
  // directo - hallazgo real de E0 corregido tras la primera corrida (ver
  // reporte 190): App.jsx expone un query param publico "?vista=login"
  // pensado exactamente para esto (recarga a mitad de registro, etc.),
  // asi que se usa esa ruta en vez de simular clics en el menu hamburguesa
  // de la landing (mas fragil y ajeno a lo que se esta probando aqui).
  await page.goto("/?vista=login");
  await page.locator("#login-rfc").fill(E2E_USUARIO);
  await page.locator("#login-password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();

  // ModalPrivacidadPruebas.jsx: aviso de privacidad OBLIGATORIO que
  // aparece tras CUALQUIER login real exitoso (useAuth.js: es estado de
  // React, no persistido - reaparece en cada login, incluyendo cada test
  // con su propio contexto de navegador nuevo). A proposito no tiene X,
  // Esc ni cierre por backdrop (ver comentario en el propio componente) -
  // la unica salida es marcar el checkbox y dar clic en "Entendido".
  // Hallazgo real de E0 (no es un bug: es el comportamiento diseñado).
  const avisoPruebas = page.getByRole("dialog", { name: /AVISO DE PRIVACIDAD/ });
  await avisoPruebas.waitFor({ state: "visible", timeout: 15000 });
  await avisoPruebas.getByRole("checkbox").check();
  await avisoPruebas.getByRole("button", { name: "Entendido" }).click();
  await expect(avisoPruebas).not.toBeVisible();

  // BUG REAL EN ESTE HELPER (encontrado al correr el proyecto "movil", no
  // es un bug de la app): en isMobile, AppShell.jsx NO renderiza el
  // sidebar de forma persistente - solo existe dentro de un drawer
  // (`isMobile&&drawerOpen&&<aside>...`), cerrado por default
  // (`drawerOpen` inicia en false), alcanzable unicamente con el boton
  // hamburguesa ("Abrir menú") del header. Esperar el texto
  // "Administración" del sidebar colgaba 15s en movil porque el sidebar
  // ni siquiera esta montado. "Salir" (boton "Cerrar sesión" del header)
  // SI se renderiza siempre, sin importar el viewport - es la señal
  // correcta y agnostica de viewport de que el login realmente termino.
  await page.getByRole("button", { name: "Salir" }).waitFor({ state: "visible", timeout: 15000 });
}

// En movil, el sidebar vive dentro de un drawer cerrado por default - hay
// que abrirlo con el boton hamburguesa antes de poder ver/clickear
// cualquier item de navegacion. En escritorio ese boton no existe
// (isVisible() resuelve false sin esperar el timeout completo gracias al
// short-circuit por defecto de Playwright para comprobaciones de estado).
async function abrirMenuSiEsMovil(page) {
  const botonMenu = page.getByRole("button", { name: "Abrir menú" });
  if (await botonMenu.isVisible()) {
    await botonMenu.click();
  }
}

// Nav real (AppShell.jsx) - hallazgo de E0: los items del sidebar son
// <div onClick=...> planos, SIN role="button" ni tabIndex - no hay forma
// de ubicarlos con getByRole. Se usa getByText (etiqueta visible/
// accesible por texto) como alternativa mas cercana disponible - ver
// reporte 190, seccion E0, hallazgo documentado explicitamente.
export async function irAEmisores(page) {
  await abrirMenuSiEsMovil(page);
  // "Emisores" tambien aparece en el contenido principal (titulo de la
  // vista, encabezados) ademas del item del menu - se acota a la
  // navegacion (AppShell.jsx la envuelve en un <nav>, aunque los items en
  // si no tengan role/tabIndex propio, ver hallazgo de E0) para evitar el
  // "strict mode violation" de Playwright con multiples coincidencias.
  const itemEmisores = page.getByRole("navigation").getByText("Emisores", { exact: true });
  // BUG REAL EN ESTE HELPER (encontrado en la primera corrida, no es un
  // bug de la app): "Administración" es un acordeon que TOGGLEA
  // expanded["admin"] en cada clic (AppShell.jsx SidebarNav, linea
  // onClick={()=>toggle(item.id)}) - si esta funcion se llama dos veces
  // en la misma sesion (ej. reabrir el modal para la limpieza al final
  // de una prueba), el segundo clic COLIERRA el submenu en vez de
  // abrirlo, y la espera de "Emisores" cuelga hasta el timeout. Por eso
  // solo se hace clic en "Administración" si "Emisores" NO esta ya
  // visible (idempotente).
  if (!(await itemEmisores.isVisible())) {
    await page.getByText("Administración", { exact: true }).click();
  }
  await itemEmisores.click();
  await page.getByText(RFC_EMISOR_PRUEBA, { exact: true }).first().waitFor({ state: "visible" });
}

// Localiza la tarjeta del emisor de prueba especifico entre varias
// (negocio 1 tiene mas de 1 emisor) - Card (atoms.jsx) es un <div> sin
// role/data-testid propio, asi que se compone un locator que exige AMBOS
// textos (RFC + el boton "Declaraciones anuales") dentro del mismo
// contenedor, tomando el mas interno (.last() - en orden de documento,
// el div mas anidado que cumple el filtro aparece despues que sus
// ancestros en la lista de coincidencias de Playwright).
export function tarjetaEmisorPrueba(page) {
  return page
    .locator("div")
    .filter({ hasText: RFC_EMISOR_PRUEBA })
    .filter({ has: page.getByRole("button", { name: "Declaraciones anuales" }) })
    .last();
}

export async function abrirModalDeclaraciones(page) {
  await irAEmisores(page);
  await tarjetaEmisorPrueba(page).getByRole("button", { name: "Declaraciones anuales" }).click();
  await expect(dialogPrincipal(page)).toBeVisible();
}

export function dialogPrincipal(page) {
  return page.getByRole("dialog", { name: "Declaraciones anuales" });
}

export function alertDialogConfirmacion(page) {
  return page.getByRole("alertdialog");
}

export async function abrirFormulario(page) {
  await dialogPrincipal(page).getByRole("button", { name: "+ Subir declaración" }).click();
  await expect(page.locator("#da-ejercicio")).toBeVisible();
}

// Tras elegir un archivo (reporte 189), el modal dispara automaticamente
// POST .../analizar y muestra "Analizando documento…" (aria-live="polite")
// mientras espera la respuesta - Guardar queda deshabilitado durante ese
// instante (puedeGuardar = !analizando && ...). Los casos que suben un
// archivo y luego hacen clic en Guardar deben esperar a que esa ronda
// async termine antes de intentar el clic (Playwright no lo espera solo
// porque el input ya tiene el archivo).
export async function esperarAnalisisCompleto(page) {
  await expect(dialogPrincipal(page).getByText("Analizando documento…")).not.toBeVisible({ timeout: 15000 });
}

// "Ensucia" el formulario completo (los 4 campos + archivo) - usado por
// los casos que necesitan confirmar que TODOS los campos se conservan
// (caso 9), y por los casos 5-8/10-12/14 que solo necesitan CUALQUIER
// campo distinto del inicial para activar la guardia.
export async function llenarFormularioCompleto(page, { caso = "sucio" } = {}) {
  const ejercicioSelect = page.locator("#da-ejercicio");
  const opciones = await ejercicioSelect.locator("option").allTextContents();
  // El default ya es el ejercicio MAS RECIENTE (primera opcion) - se
  // elige la ULTIMA opcion (la mas vieja) para garantizar un valor
  // distinto del inicial sin asumir cuantos años hay en la lista.
  await ejercicioSelect.selectOption({ label: opciones[opciones.length - 1] });
  await page.locator("#da-tipo-decl").selectOption("complementaria");
  await page.locator("#da-numero-comp").fill("2");
  await page.locator("#da-tipo-doc").selectOption("acuse");
  await page.locator("#da-archivo").setInputFiles({
    name: nombreArchivoE2E(caso),
    mimeType: "application/pdf",
    buffer: bufferPdfSintetico(caso),
  });
}

// Borra (via UI, con el mismo window.confirm real que usa la app) un
// documento por nombre visible en la lista - usado por la limpieza de
// cada prueba que sube algo de verdad. Registra el handler de dialogo
// ANTES del clic (Playwright autodescarta los dialogos nativos por
// default si no hay un handler registrado a tiempo).
export async function borrarDocumentoPorNombre(page, nombreArchivo) {
  page.once("dialog", (dialog) => dialog.accept());
  // BUG REAL EN ESTE HELPER (encontrado al re-correr la suite, no es un
  // bug de la app): `.locator("div", {hasText})` sin mas filtro hace
  // match de CUALQUIER div ancestro que contenga el texto, incluido el
  // <div> mas interno que solo envuelve el nombre del archivo (JSX del
  // modal: el nombre y el boton "Borrar" viven en divs HERMANOS, no uno
  // dentro del otro) - `.last()` terminaba quedandose con ese div mas
  // interno, que nunca contiene el boton "Borrar" como descendiente, y
  // el `getByRole` subsiguiente colgaba hasta el timeout. Mismo patron
  // de composicion ya usado (y verificado) en tarjetaEmisorPrueba: exigir
  // AMBOS (el texto Y el boton "Borrar" como descendiente) antes de
  // tomar `.last()` - asi se selecciona el <div key={doc.id}> real (la
  // fila completa), no un div interno sin el boton.
  const fila = dialogPrincipal(page)
    .locator("div")
    .filter({ hasText: nombreArchivo })
    .filter({ has: page.getByRole("button", { name: "Borrar" }) })
    .last();
  await fila.getByRole("button", { name: "Borrar" }).click();
}
