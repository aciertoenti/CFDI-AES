// Automatización de las pruebas manuales del reporte 188
// (DeclaracionesAnualesModal.jsx) - reporte 190, 23 sep 2026.
//
// Los 16 casos usan los MISMOS números que el reporte 188 (comentarios
// "// Caso N" en cada test) para que el reporte de evidencia (190) se
// pueda leer lado a lado con 188 sin reinterpretar nada.
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
  llenarFormularioCompleto,
  borrarDocumentoPorNombre,
  dialogPrincipal,
  alertDialogConfirmacion,
  nombreArchivoE2E,
  bufferPdfSintetico,
} from "./helpers.js";

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
  await expect(page.locator("#da-ejercicio")).not.toBeVisible();
  await expect(dialogPrincipal(page).getByRole("button", { name: "+ Subir declaración" })).toBeVisible();
});

// ─── Casos 5-8: cierre CON cambios (aparece el alertdialog) ────────────

async function esperarConfirmacionConFocoEnSeguirEditando(page) {
  await expect(alertDialogConfirmacion(page)).toBeVisible();
  await expect(page.locator("#da-confirmar-seguir-editando")).toBeFocused();
}

test("Caso 5 - cierre con cambios por el fondo muestra confirmación", async ({ page }) => {
  await llenarFormularioCompleto(page, { caso: "05" });
  await page.mouse.click(5, 5);
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

test("Caso 6 - cierre con cambios por Esc muestra confirmación", async ({ page }) => {
  await llenarFormularioCompleto(page, { caso: "06" });
  await page.keyboard.press("Escape");
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

test("Caso 7 - cierre con cambios por el botón X muestra confirmación", async ({ page }) => {
  await llenarFormularioCompleto(page, { caso: "07" });
  await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).click();
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

test("Caso 8 - cierre con cambios por Cancelar muestra confirmación", async ({ page }) => {
  await llenarFormularioCompleto(page, { caso: "08" });
  await dialogPrincipal(page).getByRole("button", { name: "Cancelar" }).click();
  await esperarConfirmacionConFocoEnSeguirEditando(page);
});

// ─── Caso 9: "Seguir editando" conserva TODOS los campos + foco previo ─

test("Caso 9 - Seguir editando conserva los datos y devuelve el foco", async ({ page }) => {
  const nombreArchivo = nombreArchivoE2E("09");
  await page.locator("#da-ejercicio").selectOption({ index: 1 }); // distinto del default (index 0)
  const ejercicioElegido = await page.locator("#da-ejercicio").inputValue();
  await page.locator("#da-tipo-decl").selectOption("complementaria");
  await page.locator("#da-numero-comp").fill("3");
  await page.locator("#da-tipo-doc").selectOption("acuse");
  await page.locator("#da-archivo").setInputFiles({ name: nombreArchivo, mimeType: "application/pdf", buffer: bufferPdfSintetico("09") });

  // Foco explícito en un campo especifico ANTES de intentar cerrar -
  // este es el campo que debe recuperar el foco despues de "Seguir editando".
  await page.locator("#da-numero-comp").focus();
  await page.keyboard.press("Escape");
  await esperarConfirmacionConFocoEnSeguirEditando(page);

  await page.locator("#da-confirmar-seguir-editando").click();

  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(alertDialogConfirmacion(page)).not.toBeVisible();
  await expect(page.locator("#da-ejercicio")).toHaveValue(ejercicioElegido);
  await expect(page.locator("#da-tipo-decl")).toHaveValue("complementaria");
  await expect(page.locator("#da-numero-comp")).toHaveValue("3");
  await expect(page.locator("#da-tipo-doc")).toHaveValue("acuse");
  await expect(page.locator("text=" + nombreArchivo)).toBeVisible();
  await expect(page.locator("#da-numero-comp")).toBeFocused();
});

// ─── Caso 10: Esc dentro de la confirmación = Seguir editando ─────────

test("Caso 10 - Esc dentro de la confirmación equivale a Seguir editando", async ({ page }) => {
  await llenarFormularioCompleto(page, { caso: "10" });
  await page.keyboard.press("Escape"); // dispara la confirmacion
  await esperarConfirmacionConFocoEnSeguirEditando(page);

  await page.keyboard.press("Escape"); // Esc DENTRO de la confirmacion
  await expect(alertDialogConfirmacion(page)).not.toBeVisible();
  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(page.locator("#da-ejercicio")).toBeVisible(); // sigue en el formulario, no cerro nada
});

// ─── Caso 11: Descartar desde fondo/Esc/X cierra el modal completo ────

test("Caso 11 - Descartar desde fondo, Esc y X cierra el modal completo", async ({ page }) => {
  await test.step("via el fondo", async () => {
    await llenarFormularioCompleto(page, { caso: "11a" });
    await page.mouse.click(5, 5);
    await expect(alertDialogConfirmacion(page)).toBeVisible();
    await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
    await expect(dialogPrincipal(page)).not.toBeVisible();
  });

  await test.step("via Esc", async () => {
    await abrirModalDeclaraciones(page);
    await abrirFormulario(page);
    await llenarFormularioCompleto(page, { caso: "11b" });
    await page.keyboard.press("Escape");
    await expect(alertDialogConfirmacion(page)).toBeVisible();
    await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
    await expect(dialogPrincipal(page)).not.toBeVisible();
  });

  await test.step("via el botón X", async () => {
    await abrirModalDeclaraciones(page);
    await abrirFormulario(page);
    await llenarFormularioCompleto(page, { caso: "11c" });
    await dialogPrincipal(page).getByRole("button", { name: "Cerrar" }).click();
    await expect(alertDialogConfirmacion(page)).toBeVisible();
    await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();
    await expect(dialogPrincipal(page)).not.toBeVisible();
  });
});

// ─── Caso 12: Descartar desde Cancelar vuelve a la lista, form limpio ──

test("Caso 12 - Descartar desde Cancelar vuelve a la lista y el formulario queda limpio al reabrir", async ({ page }) => {
  await llenarFormularioCompleto(page, { caso: "12" });
  await dialogPrincipal(page).getByRole("button", { name: "Cancelar" }).click();
  await expect(alertDialogConfirmacion(page)).toBeVisible();
  await alertDialogConfirmacion(page).getByRole("button", { name: "Descartar" }).click();

  await expect(dialogPrincipal(page)).toBeVisible();
  await expect(dialogPrincipal(page).getByRole("button", { name: "+ Subir declaración" })).toBeVisible();

  await abrirFormulario(page);
  const ejercicioLimpio = await page.locator("#da-ejercicio").inputValue();
  const primeraOpcion = await page.locator("#da-ejercicio option").first().getAttribute("value");
  expect(ejercicioLimpio).toBe(primeraOpcion); // vuelve al default (el mas reciente), no lo que se habia descartado
  await expect(page.locator("#da-tipo-decl")).toHaveValue("normal");
  await expect(page.getByText("Ningún archivo seleccionado")).toBeVisible();
});

// ─── Caso 13: tras guardar con éxito, cerrar ya no pide confirmación ───

test("Caso 13 - tras subir con éxito, cerrar ya no pide confirmación", async ({ page }) => {
  const nombreArchivo = nombreArchivoE2E("13");
  const maximo = await page.locator("#da-ejercicio option").first().textContent();
  await page.locator("#da-ejercicio").selectOption({ label: maximo });
  await page.locator("#da-archivo").setInputFiles({ name: nombreArchivo, mimeType: "application/pdf", buffer: bufferPdfSintetico("13") });

  await dialogPrincipal(page).getByRole("button", { name: "Guardar" }).click();
  await expect(dialogPrincipal(page).getByRole("button", { name: "+ Subir declaración" })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(nombreArchivo)).toBeVisible();

  // Ahora cerrar (fondo) - ya NO debe pedir confirmacion, el formulario
  // volvio a FORM_INICIAL tras el 201.
  await page.mouse.click(5, 5);
  await expect(dialogPrincipal(page)).not.toBeVisible();

  // Limpieza: reabrir, borrar lo subido.
  await abrirModalDeclaraciones(page);
  await borrarDocumentoPorNombre(page, nombreArchivo);
  await expect(page.getByText(nombreArchivo)).not.toBeVisible();
});

// ─── Caso 14: durante la subida, ninguna de las 4 vías cierra ─────────

test("Caso 14 - durante la subida ninguna de las 4 vías cierra el modal", async ({ page }) => {
  const nombreArchivo = nombreArchivoE2E("14");
  let liberar;
  const peticionLiberada = new Promise((resolve) => { liberar = resolve; });

  await page.route("**/declaraciones-anuales/documentos", async (route) => {
    if (route.request().method() === "POST") {
      await peticionLiberada; // retraso DETERMINISTA - no throttling, el test controla exactamente cuando continua
    }
    await route.continue();
  });

  await page.locator("#da-archivo").setInputFiles({ name: nombreArchivo, mimeType: "application/pdf", buffer: bufferPdfSintetico("14") });
  await dialogPrincipal(page).getByRole("button", { name: "Guardar" }).click();
  await expect(dialogPrincipal(page).getByRole("button", { name: "Subiendo…" })).toBeVisible();

  // Las 4 vias, todas deben ser no-op mientras subiendo=true.
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
  await expect(dialogPrincipal(page).getByRole("button", { name: "+ Subir declaración" })).toBeVisible({ timeout: 15000 });

  // Limpieza.
  await expect(page.getByText(nombreArchivo)).toBeVisible();
  await borrarDocumentoPorNombre(page, nombreArchivo);
  await expect(page.getByText(nombreArchivo)).not.toBeVisible();
});

// ─── Caso 15: "Seleccionar PDF" con teclado (Tab/Enter/Espacio) ───────

test("Caso 15 - Seleccionar PDF alcanzable con Tab y operable con Enter y Espacio", async ({ page }) => {
  const boton = page.getByRole("button", { name: "Seleccionar PDF" });
  await expect(boton).toBeVisible();

  // Alcanzable con Tab desde un punto conocido del formulario (no se
  // asume la posicion exacta - se tabula desde ejercicio hasta llegar).
  await page.locator("#da-ejercicio").focus();
  let alcanzado = false;
  for (let i = 0; i < 6 && !alcanzado; i++) {
    await page.keyboard.press("Tab");
    alcanzado = await boton.evaluate((el) => el === document.activeElement);
  }
  expect(alcanzado).toBe(true);

  // Enter abre el selector nativo.
  const chooserEnter = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const fc1 = await chooserEnter;
  expect(fc1.isMultiple()).toBe(false);
  await fc1.setFiles({ name: nombreArchivoE2E("15-enter"), mimeType: "application/pdf", buffer: bufferPdfSintetico("15-enter") });
  await expect(page.getByText(/e2e-declaraciones-15-enter/)).toBeVisible();

  // Espacio tambien lo abre (re-enfocar el boton primero).
  await boton.focus();
  const chooserSpace = page.waitForEvent("filechooser");
  await page.keyboard.press(" ");
  const fc2 = await chooserSpace;
  await fc2.setFiles({ name: nombreArchivoE2E("15-espacio"), mimeType: "application/pdf", buffer: bufferPdfSintetico("15-espacio") });
  await expect(page.getByText(/e2e-declaraciones-15-espacio/)).toBeVisible();

  // Nombre accesible correcto - la etiqueta real del campo, no un texto generico.
  await expect(page.locator("#da-archivo")).toHaveAccessibleName("Archivo PDF (máx. 5MB)");
});

// ─── Caso 16: escaneo axe (formulario y confirmación) ─────────────────

test("Caso 16 - escaneo de accesibilidad (axe) del formulario", async ({ page }, testInfo) => {
  const resultados = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
  await testInfo.attach("axe-formulario.json", {
    body: JSON.stringify(resultados.violations, null, 2),
    contentType: "application/json",
  });
  // Reporta TODAS las violaciones encontradas (pedido explicito) - el
  // test en si NO falla por violaciones (eso las ocultaria del reporte
  // si alguien luego decide ajustar el umbral); se adjuntan como
  // evidencia y se listan en el reporte 190 sin excepcion.
  console.log(`[axe-formulario] violaciones encontradas: ${resultados.violations.length}`);
  for (const v of resultados.violations) {
    console.log(`  - [${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} nodo(s))`);
  }
});

test("Caso 16 - escaneo de accesibilidad (axe) de la confirmación", async ({ page }, testInfo) => {
  await llenarFormularioCompleto(page, { caso: "16" });
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
});

// ─── Solo en el proyecto "movil": sin scroll horizontal ───────────────

test("Móvil - el modal no genera scroll horizontal (formulario)", async ({ page }) => {
  test.skip(test.info().project.name !== "movil", "Solo aplica al proyecto móvil");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});

test("Móvil - el modal no genera scroll horizontal (confirmación)", async ({ page }) => {
  test.skip(test.info().project.name !== "movil", "Solo aplica al proyecto móvil");
  await llenarFormularioCompleto(page, { caso: "movil-scroll" });
  await page.keyboard.press("Escape");
  await expect(alertDialogConfirmacion(page)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
