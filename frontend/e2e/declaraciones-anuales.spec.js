// Automatización de las pruebas manuales del reporte 188/189 -
// reporte 190 (automatización), 189/189b (validación de contenido y
// borrado de declaraciones), 189d (REDISEÑO del flujo de subida:
// multi-archivo, sin campos editables, solo acuses reconocidos).
//
// Los casos 1-16 usan los MISMOS números que el reporte 188 (comentarios
// "// Caso N" en cada test) para que el reporte de evidencia se pueda
// leer lado a lado sin reinterpretar nada - la MECÁNICA de cada caso se
// adaptó al nuevo flujo multi-archivo (189d), pero el ESCENARIO que
// prueba cada uno es el mismo.
//
// Corre contra los CONTENEDORES YA LEVANTADOS (frontend:3000, vía nginx
// -> gateway:8000) - no se levanta ningún servidor nuevo (ver
// playwright.config.js, sin `webServer`).
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  login,
  abrirModalDeclaraciones,
  abrirFormulario,
  agregarArchivos,
  agregarAcuseValido,
  borrarDeclaracionPorArchivo,
  dialogPrincipal,
  alertDialogConfirmacion,
  nombreArchivoE2E,
  bufferPdfSintetico,
  bufferAcuseSintetico,
  bufferOpinionCumplimientoSintetica,
} from "./helpers.js";

// Reporte 189d2 - los escaneos de axe (Caso 16) antes SOLO reportaban,
// nunca fallaban - así fue como la violación real "nested-interactive"
// introducida por 189d pasó desapercibida (la corrida E2E completa
// pasaba igual, axe solo la imprimía en consola). Ahora la prueba FALLA
// ante cualquier violación cuyo id no esté en esta lista explícita -
// "color-contrast" es la ÚNICA conocida hoy (tarjeta J,
// PVTI_lAHOBYC0Os4BfCxZzg8U3wI, sin corregir - fuera de alcance de este
// reporte). Vaciar esta lista en cuanto esa tarjeta se resuelva - dejarla
// con entradas ya corregidas sería tan malo como no tener la lista.
const VIOLACIONES_CONOCIDAS = ["color-contrast"];

test.beforeEach(async ({ page }) => {
  await login(page);
  await abrirModalDeclaraciones(page);
  await abrirFormulario(page);
});

// ─── Casos 1-4: cierre SIN cambios (comportamiento directo, sin aviso) ─

test("Caso 1 - cierre sin cambios por el fondo", async ({ page }) => {
  await page.mouse.click(5, 5); // fuera de la tarjeta del modal, dentro del overlay
  await expect(dialogPrincipal(page)).not.toBeVisible();
});

test("Caso 2 - cierre sin cambios por Esc", async ({ page }) => {
  await page.keyboard.press("Escape");
  await expect(dialogPrincipal(page)).not.toBeVisible();
});

test("Caso 3 - cierre sin cambios por el botón X", async ({ page }) => {
  await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).click();
  await expect(dialogPrincipal(page)).not.toBeVisible();
});

test("Caso 4 - cierre sin cambios por Cancelar (vuelve a la lista, no cierra el modal)", async ({ page }) => {
  await dialogPrincipal(page).getByRole("button", { name: "Cancelar" }).click();
  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(page.locator("#da-archivos")).not.toBeVisible();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible();
});

// ─── Casos 5-8: cierre CON cambios (aparece el alertdialog) ────────────

async function esperarConfirmacionConFocoEnSeguirEditando(page) {
  await expect(alertDialogConfirmacion(page)).toBeVisible();
  await expect(page.locator("#da-confirmar-seguir-editando")).toBeFocused();
}

test("Caso 5 - cierre con cambios por el fondo muestra confirmación", async ({ page }) => {
  await agregarAcuseValido(page, { caso: "05" });
  await page.mouse.click(5, 5);
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

test("Caso 6 - cierre con cambios por Esc muestra confirmación", async ({ page }) => {
  await agregarAcuseValido(page, { caso: "06" });
  await page.keyboard.press("Escape");
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

test("Caso 7 - cierre con cambios por el botón X muestra confirmación", async ({ page }) => {
  await agregarAcuseValido(page, { caso: "07" });
  await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).click();
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

test("Caso 8 - cierre con cambios por Cancelar muestra confirmación", async ({ page }) => {
  await agregarAcuseValido(page, { caso: "08" });
  await dialogPrincipal(page).getByRole("button", { name: "Cancelar" }).click();
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

// Reporte 189d3 - hallazgo real de la corrida E2E del usuario: el Caso 5
// falló porque el clic en el fondo ocurrió mientras el PDF SEGUÍA en
// análisis - "sucio" solo contaba acuses válidos, así que el modal se
// cerró sin preguntar y perdió el archivo. Corregido: 'analizando'
// ahora también ensucia (B2). Esta prueba fuerza ese estado de forma
// DETERMINISTA (retiene /analizar con page.route, nunca depende del
// tiempo real del servidor) en vez de asumir que el análisis real vaya
// a seguir en vuelo cuando el test intenta cerrar.
test("Caso 189d3 - cierre con cambios MIENTRAS el análisis está en curso muestra confirmación", async ({ page }) => {
  let liberar;
  const analisisLiberado = new Promise((resolve) => { liberar = resolve; });
  await page.route("**/declaraciones-anuales/analizar", async (route) => {
    await analisisLiberado; // retraso DETERMINISTA - el test controla exactamente cuando continua
    await route.continue();
  });

  const nombreArchivo = nombreArchivoE2E("189d3");
  await page.locator("#da-archivos").setInputFiles({
    name: nombreArchivo,
    mimeType: "application/pdf",
    buffer: bufferAcuseSintetico({ numeroOperacion: `OP189D3${Date.now()}` }),
  });

  // El archivo sigue "Analizando…" a propósito (la ruta está retenida) -
  // el clic en el fondo debe mostrar la confirmación de todas formas.
  await expect(dialogPrincipal(page).getByText("Analizando…")).toBeVisible();
  await page.mouse.click(5, 5);
  await esperarConfirmacionConFocoEnSeguirEditando(page);

  // Limpieza: liberar la petición retenida (para no dejar el route
  // handler colgado) y descartar, para no ensuciar la prueba siguiente.
  liberar();
  await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
  await expect(dialogPrincipal(page)).not.toBeVisible();
});

// ─── Caso 9: "Seguir editando" conserva la cola de archivos + foco previo ─

test("Caso 9 - Seguir editando conserva la cola de archivos y devuelve el foco", async ({ page }) => {
  // Un archivo VÁLIDO (ensucia) + uno RECHAZADO (opinión) - confirma que
  // AMBOS sobreviven el viaje de ida y vuelta por la confirmación, no
  // solo el que activó la guardia.
  const nombreValido = await agregarAcuseValido(page, { caso: "09" });
  const nombreOpinion = nombreArchivoE2E("09-opinion");
  await agregarArchivos(page, [{ name: nombreOpinion, mimeType: "application/pdf", buffer: bufferOpinionCumplimientoSintetica() }]);

  const botonQuitar = dialogPrincipal(page).locator("li").filter({ hasText: nombreValido }).getByRole("button", { name: /Quitar/ });
  await botonQuitar.focus();
  await page.keyboard.press("Escape");
  await esperarConfirmacionConFocoEnSeguirEditando(page);

  await page.locator("#da-confirmar-seguir-editando").click();

  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(alertDialogConfirmacion(page)).not.toBeVisible();
  await expect(page.getByText(nombreValido)).toBeVisible();
  await expect(page.getByText(nombreOpinion)).toBeVisible();
  await expect(botonQuitar).toBeFocused();
});

// ─── Caso 10: Esc dentro de la confirmación = Seguir editando ─────────

test("Caso 10 - Esc dentro de la confirmación equivale a Seguir editando", async ({ page }) => {
  await agregarAcuseValido(page, { caso: "10" });
  await page.keyboard.press("Escape"); // dispara la confirmacion
  await esperarConfirmacionConFocoEnSeguirEditando(page);

  await page.keyboard.press("Escape"); // Esc DENTRO de la confirmacion
  await expect(alertDialogConfirmacion(page)).not.toBeVisible();
  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(page.locator("#da-archivos")).toBeAttached(); // sigue en la vista de subida, no cerro nada
});

// ─── Caso 11: Descartar desde fondo/Esc/X cierra el modal completo ────

test("Caso 11 - Descartar desde fondo, Esc y X cierra el modal completo", async ({ page }) => {
  await test.step("via el fondo", async () => {
    await agregarAcuseValido(page, { caso: "11a" });
    await page.mouse.click(5, 5);
    await expect(alertDialogConfirmacion(page)).toBeVisible();
    await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
    await expect(dialogPrincipal(page)).not.toBeVisible();
  });

  await test.step("via Esc", async () => {
    await abrirModalDeclaraciones(page);
    await abrirFormulario(page);
    await agregarAcuseValido(page, { caso: "11b" });
    await page.keyboard.press("Escape");
    await expect(alertDialogConfirmacion(page)).toBeVisible();
    await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
    await expect(dialogPrincipal(page)).not.toBeVisible();
  });

  await test.step("via el botón X", async () => {
    await abrirModalDeclaraciones(page);
    await abrirFormulario(page);
    await agregarAcuseValido(page, { caso: "11c" });
    await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).click();
    await expect(alertDialogConfirmacion(page)).toBeVisible();
    await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
    await expect(dialogPrincipal(page)).not.toBeVisible();
  });
});

// ─── Caso 12: Descartar desde Cancelar vuelve a la lista, cola vacía ──

test("Caso 12 - Descartar desde Cancelar vuelve a la lista y la cola queda vacía al reabrir", async ({ page }) => {
  await agregarAcuseValido(page, { caso: "12" });
  await dialogPrincipal(page).getByRole("button", { name: "Cancelar" }).click();
  await expect(alertDialogConfirmacion(page)).toBeVisible();
  await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();

  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible();

  await abrirFormulario(page);
  // Cola vacia al reabrir - sin resultados de la corrida anterior, y el
  // boton de guardar en su estado inicial (0 acuses).
  await expect(dialogPrincipal(page).locator("li")).toHaveCount(0);
  await expect(dialogPrincipal(page).getByRole("button", { name: "Guardar 0 acuses" })).toBeVisible();
});

// ─── Caso 13: tras guardar con éxito, cerrar ya no pide confirmación ───

test("Caso 13 - tras subir con éxito, cerrar ya no pide confirmación", async ({ page }) => {
  const nombreArchivo = await agregarAcuseValido(page, { caso: "13" });

  await dialogPrincipal(page).getByRole("button", { name: "Guardar 1 acuse" }).click();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(nombreArchivo)).toBeVisible();

  // Ahora cerrar (fondo) - ya NO debe pedir confirmacion, la cola volvio
  // a estar vacia tras el 201.
  await page.mouse.click(5, 5);
  await expect(dialogPrincipal(page)).not.toBeVisible();

  // Limpieza: reabrir, borrar lo subido.
  await abrirModalDeclaraciones(page);
  await borrarDeclaracionPorArchivo(page, nombreArchivo);
  await expect(page.getByText(nombreArchivo)).not.toBeVisible();
});

// ─── Caso 14: durante la subida, ninguna de las 4 vías cierra ─────────

test("Caso 14 - durante la subida ninguna de las 4 vías cierra el modal", async ({ page }) => {
  const nombreArchivo = await agregarAcuseValido(page, { caso: "14" });
  let liberar;
  const peticionLiberada = new Promise((resolve) => { liberar = resolve; });

  await page.route("**/declaraciones-anuales/documentos", async (route) => {
    if (route.request().method() === "POST") {
      await peticionLiberada; // retraso DETERMINISTA - no throttling, el test controla exactamente cuando continua
    }
    await route.continue();
  });

  await dialogPrincipal(page).getByRole("button", { name: "Guardar 1 acuse" }).click();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Guardando…" })).toBeVisible();

  // Las 4 vias, todas deben ser no-op mientras guardando=true.
  await page.mouse.click(5, 5);
  await expect(dialogPrincipal(page)).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(alertDialogConfirmacion(page)).not.toBeVisible();

  await expect(dialogPrincipal(page).getByRole("button", { name: "Cerrar" })).toBeDisabled();
  await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).click({ force: true });
  await expect(dialogPrincipal(page)).toBeVisible();

  await expect(dialogPrincipal(page).getByRole("button", { name: "Cancelar" })).toBeDisabled();

  liberar();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible({ timeout: 15000 });

  // Limpieza.
  await expect(page.getByText(nombreArchivo)).toBeVisible();
  await borrarDeclaracionPorArchivo(page, nombreArchivo);
  await expect(page.getByText(nombreArchivo)).not.toBeVisible();
});

// ─── Caso 15: "Seleccionar PDF" alcanzable con Tab y operable con Enter/Espacio ─
// Actualizado en 189d2: el control ya no es el DIV dropzone (role="button",
// manejo manual de teclado) - ver A1 del reporte 189d2, corrigió una
// violación real de axe (nested-interactive: un <input> anidado dentro
// de un control con role="button"). Ahora es un <button> NATIVO
// "Seleccionar PDF" - Enter/Espacio los maneja el navegador solo, sin
// código propio que probar aquí (si el <button> real los activa, ya se
// sabe que funcionan; lo que sí hay que confirmar es que dispara el
// selector de archivos correcto).

test('Caso 15 - "Seleccionar PDF" alcanzable con Tab y operable con Enter y Espacio', async ({ page }) => {
  const boton = dialogPrincipal(page).getByRole("button", { name: "Seleccionar PDF" });
  await expect(boton).toBeVisible();

  // Alcanzable con Tab desde un punto conocido (el boton Cerrar, siempre
  // presente) - no se asume la posicion exacta.
  await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).focus();
  let alcanzado = false;
  for (let i = 0; i < 4 && !alcanzado; i++) {
    await page.keyboard.press("Tab");
    alcanzado = await boton.evaluate((el) => el === document.activeElement);
  }
  expect(alcanzado).toBe(true);

  // Enter abre el selector nativo (comportamiento nativo del <button>,
  // sin manejo manual de teclas).
  const chooserEnter = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const fc1 = await chooserEnter;
  expect(fc1.isMultiple()).toBe(true); // el input acepta varios (189d)
  await fc1.setFiles({ name: nombreArchivoE2E("15-enter"), mimeType: "application/pdf", buffer: bufferPdfSintetico("15-enter") });
  await expect(page.getByText(/e2e-declaraciones-15-enter/)).toBeVisible();

  // Espacio tambien lo abre (re-enfocar el boton primero).
  await boton.focus();
  const chooserSpace = page.waitForEvent("filechooser");
  await page.keyboard.press(" ");
  const fc2 = await chooserSpace;
  await fc2.setFiles({ name: nombreArchivoE2E("15-espacio"), mimeType: "application/pdf", buffer: bufferPdfSintetico("15-espacio") });
  await expect(page.getByText(/e2e-declaraciones-15-espacio/)).toBeVisible();

  // Nombre accesible correcto - la etiqueta real del boton (el <input>
  // nativo queda aria-hidden a propósito, ver el componente).
  await expect(boton).toHaveAccessibleName("Seleccionar PDF");
});

// ─── Caso 16: escaneo IA de accesibilidad (axe) ────────────────────────

test("Caso 16 - escaneo de accesibilidad (axe) del formulario", async ({ page }, testInfo) => {
  const resultados = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
  await testInfo.attach("axe-formulario.json", {
    body: JSON.stringify(resultados.violations, null, 2),
    contentType: "application/json",
  });
  // Reporta TODAS las violaciones encontradas, conocidas o no (pedido
  // explicito) - la lista de abajo decide si la prueba FALLA, nunca si
  // se imprime.
  console.log(`[axe-formulario] violaciones encontradas: ${resultados.violations.length}`);
  for (const v of resultados.violations) {
    console.log(`  - [${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} nodo(s))`);
  }
  const inesperadas = resultados.violations.filter(v => !VIOLACIONES_CONOCIDAS.includes(v.id));
  expect(inesperadas.map(v => v.id), `Violaciones de axe NO listadas en VIOLACIONES_CONOCIDAS: ${inesperadas.map(v => v.id).join(", ")}`).toEqual([]);
});

test("Caso 16 - escaneo de accesibilidad (axe) de la confirmación", async ({ page }, testInfo) => {
  await agregarAcuseValido(page, { caso: "16" });
  await page.keyboard.press("Escape");
  await expect(alertDialogConfirmacion(page)).toBeVisible();

  const resultados = await new AxeBuilder({ page }).include('[role="alertdialog"]').analyze();
  await testInfo.attach("axe-confirmacion.json", {
    body: JSON.stringify(resultados.violations, null, 2),
    contentType: "application/json",
  });
  console.log(`[axe-confirmacion] violaciones encontradas: ${resultados.violations.length}`);
  for (const v of resultados.violations) {
    console.log(`  - [${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} nodo(s))`);
  }
  const inesperadas = resultados.violations.filter(v => !VIOLACIONES_CONOCIDAS.includes(v.id));
  expect(inesperadas.map(v => v.id), `Violaciones de axe NO listadas en VIOLACIONES_CONOCIDAS: ${inesperadas.map(v => v.id).join(", ")}`).toEqual([]);
});

// ─── Casos del reporte 189/189b/189d: validación de contenido, borrado
// completo de declaraciones, y el rediseño del flujo de subida ────────

test("Caso 189-1 - acuse válido: resultado correcto en la cola, guardar, aparece en la lista sin NaN/Invalid Date", async ({ page }) => {
  const ejercicio = 2019; // fijo y distinto de "hoy" para no depender de la fecha de la corrida
  const nombreArchivo = await agregarAcuseValido(page, { caso: "189-1", ejercicio });

  const fila = dialogPrincipal(page).locator("li").filter({ hasText: nombreArchivo });
  await expect(fila.getByText(`Ejercicio ${ejercicio}`)).toBeVisible();
  await expect(fila.getByText("Normal", { exact: false })).toBeVisible();

  await dialogPrincipal(page).getByRole("button", { name: "Guardar 1 acuse" }).click();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible({ timeout: 15000 });

  const tarjeta = dialogPrincipal(page)
    .locator("div")
    .filter({ hasText: `Ejercicio ${ejercicio}` })
    .filter({ hasText: nombreArchivo })
    .last();
  await expect(tarjeta).toBeVisible();
  await expect(tarjeta.getByText("Presentada el", { exact: false })).toBeVisible();

  // Formato defensivo (189d, bug real de la prueba de usuario): nunca
  // "NaN" ni "Invalid Date" en ningun lado del dialogo.
  const texto = await dialogPrincipal(page).innerText();
  expect(texto).not.toContain("NaN");
  expect(texto).not.toContain("Invalid Date");

  // Limpieza.
  await borrarDeclaracionPorArchivo(page, nombreArchivo);
  await expect(page.getByText(nombreArchivo)).not.toBeVisible();
});

test("Caso 189-2 - opinión de cumplimiento: rechazada en la cola, Guardar queda en 0", async ({ page }) => {
  const nombreArchivo = nombreArchivoE2E("189-2");
  await agregarArchivos(page, [{ name: nombreArchivo, mimeType: "application/pdf", buffer: bufferOpinionCumplimientoSintetica() }]);

  const fila = dialogPrincipal(page).locator("li").filter({ hasText: nombreArchivo });
  await expect(fila.getByText("Esto es una opinión de cumplimiento", { exact: false })).toBeVisible();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Guardar 0 acuses" })).toBeDisabled();
});

test("Caso 189-3 - acuse con RFC ajeno: rechazado en la cola, Guardar queda en 0", async ({ page }) => {
  const nombreArchivo = nombreArchivoE2E("189-3");
  const rfcAjeno = "XAXX010101000"; // RFC generico, distinto de RFC_EMISOR_PRUEBA a proposito
  await agregarArchivos(page, [{
    name: nombreArchivo, mimeType: "application/pdf",
    buffer: bufferAcuseSintetico({ rfc: rfcAjeno, ejercicio: 2020, numeroOperacion: `OP189C${Date.now()}` }),
  }]);

  const fila = dialogPrincipal(page).locator("li").filter({ hasText: nombreArchivo });
  await expect(fila.getByText("Este documento pertenece a otro RFC")).toBeVisible();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Guardar 0 acuses" })).toBeDisabled();
});

test("Caso 189-4 - Borrar declaración: única acción de borrado por tarjeta, confirmación dentro del modal", async ({ page }) => {
  const ejercicio = 2018;
  const nombreArchivo = await agregarAcuseValido(page, { caso: "189-4", ejercicio });
  await dialogPrincipal(page).getByRole("button", { name: "Guardar 1 acuse" }).click();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible({ timeout: 15000 });

  const tarjeta = dialogPrincipal(page)
    .locator("div")
    .filter({ hasText: `Ejercicio ${ejercicio}` })
    .filter({ hasText: nombreArchivo })
    .last();

  // Única acción de borrado por tarjeta (pedido explícito R2) - ya no
  // existe un "Borrar" por documento, solo el de la declaración.
  await expect(tarjeta.getByRole("button", { name: "Borrar" })).toHaveCount(1);
  // Tampoco debe quedar un botón "Borrar" por-documento con otro nombre.
  await expect(tarjeta.getByRole("button", { name: "Descargar acuse" })).toHaveCount(1);

  const botonBorrarDecl = tarjeta.getByRole("button", { name: "Borrar" });
  await botonBorrarDecl.click();
  const confirmacion = page.getByRole("alertdialog", { name: "Borrar declaración" });
  await expect(confirmacion).toBeVisible();
  await expect(confirmacion.getByText(`Se borrarán la declaración de ejercicio ${ejercicio} y sus 1 documento`)).toBeVisible();
  await expect(page.locator("#da-confirmar-borrar-decl-cancelar")).toBeFocused();

  // Cancelar: la tarjeta sigue ahí, foco vuelve al botón que abrió esto.
  await confirmacion.getByRole("button", { name: "Cancelar" }).click();
  await expect(confirmacion).not.toBeVisible();
  await expect(botonBorrarDecl).toBeFocused();
  await expect(page.getByText(nombreArchivo)).toBeVisible();

  // Esc dentro de la confirmación equivale a Cancelar.
  await botonBorrarDecl.click();
  await expect(confirmacion).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(confirmacion).not.toBeVisible();
  await expect(page.getByText(nombreArchivo)).toBeVisible();

  // Confirmar de verdad: borra la declaración Y su documento en un solo paso.
  await botonBorrarDecl.click();
  await expect(confirmacion).toBeVisible();
  await confirmacion.getByRole("button", { name: "Borrar declaración" }).click();
  await expect(confirmacion).not.toBeVisible({ timeout: 15000 });
  await expect(page.getByText(nombreArchivo)).not.toBeVisible();
});

test("Caso 189-5 - un archivo rechazado NO ensucia el formulario (189d)", async ({ page }) => {
  const nombreArchivo = nombreArchivoE2E("189-5");
  await agregarArchivos(page, [{ name: nombreArchivo, mimeType: "application/pdf", buffer: bufferPdfSintetico("189-5") }]);

  const fila = dialogPrincipal(page).locator("li").filter({ hasText: nombreArchivo });
  await expect(fila.getByText("No reconocimos este archivo", { exact: false })).toBeVisible();

  // Cerrar (cualquiera de las 4 vías) NO debe pedir confirmación - no hay
  // ningún acuse VÁLIDO en la cola, solo uno rechazado.
  await page.mouse.click(5, 5);
  await expect(dialogPrincipal(page)).not.toBeVisible();
});

test("Caso 189-6 - subida múltiple: se guardan los válidos, se rechazan los demás con su motivo", async ({ page }) => {
  const v1 = nombreArchivoE2E("189-6-v1");
  const v2 = nombreArchivoE2E("189-6-v2");
  const op = nombreArchivoE2E("189-6-opinion");
  const nr = nombreArchivoE2E("189-6-noreconocido");

  await agregarArchivos(page, [
    { name: v1, mimeType: "application/pdf", buffer: bufferAcuseSintetico({ ejercicio: 2016, numeroOperacion: `OP6A${Date.now()}` }) },
    { name: v2, mimeType: "application/pdf", buffer: bufferAcuseSintetico({ ejercicio: 2017, numeroOperacion: `OP6B${Date.now()}` }) },
    { name: op, mimeType: "application/pdf", buffer: bufferOpinionCumplimientoSintetica() },
    { name: nr, mimeType: "application/pdf", buffer: bufferPdfSintetico("189-6-nr") },
  ]);

  await expect(dialogPrincipal(page).locator("li")).toHaveCount(4);
  await expect(dialogPrincipal(page).getByRole("button", { name: "Guardar 2 acuses" })).toBeVisible();
  await expect(dialogPrincipal(page).locator("li").filter({ hasText: op }).getByText("Esto es una opinión de cumplimiento", { exact: false })).toBeVisible();
  await expect(dialogPrincipal(page).locator("li").filter({ hasText: nr }).getByText("No reconocimos este archivo", { exact: false })).toBeVisible();

  await dialogPrincipal(page).getByRole("button", { name: "Guardar 2 acuses" }).click();
  // Los 2 validos se guardaron - vuelve automaticamente a la lista.
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subir acuses" })).toBeVisible({ timeout: 20000 });

  await expect(page.getByText(v1)).toBeVisible();
  await expect(page.getByText(v2)).toBeVisible();
  await expect(page.getByText(op)).not.toBeVisible();
  await expect(page.getByText(nr)).not.toBeVisible();

  // Limpieza.
  await borrarDeclaracionPorArchivo(page, v1);
  await borrarDeclaracionPorArchivo(page, v2);
  await expect(page.getByText(v1)).not.toBeVisible();
  await expect(page.getByText(v2)).not.toBeVisible();
});

// ─── Solo en el proyecto "movil": sin scroll horizontal ───────────────

test("Móvil - el modal no genera scroll horizontal (formulario)", async ({ page }) => {
  test.skip(test.info().project.name !== "movil", "Solo aplica al proyecto móvil");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});

test("Móvil - el modal no genera scroll horizontal (confirmación)", async ({ page }) => {
  test.skip(test.info().project.name !== "movil", "Solo aplica al proyecto móvil");
  await agregarAcuseValido(page, { caso: "movil-scroll" });
  await page.keyboard.press("Escape");
  await expect(alertDialogConfirmacion(page)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
