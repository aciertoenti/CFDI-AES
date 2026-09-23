// Configuración de Playwright para las pruebas E2E del modal de
// declaraciones anuales (reporte 190, automatización del reporte 188).
//
// Solo Chromium (pedido explicito) - 2 proyectos: escritorio (1280x800,
// viewport fijo) y móvil (emulación de un teléfono estándar de
// Playwright, Pixel 7 - dispositivo Android real que Playwright ya trae
// definido en su catálogo de `devices`, no un viewport inventado a mano).
//
// Las pruebas corren CONTRA LOS CONTENEDORES YA LEVANTADOS (pedido
// explicito) - `webServer` de Playwright NO se usa a propósito (eso
// levantaría un servidor nuevo); baseURL apunta directo al frontend real
// en docker-compose (puerto 3000, nginx -> nginx.conf proxea /api al
// gateway).
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // los tests de la suite comparten el mismo emisor/negocio real - evita choques de datos entre pruebas concurrentes
  // BUG REAL ENCONTRADO AL CORRER capturas.spec.js: `fullyParallel:false`
  // solo serializa los tests DENTRO de un mismo archivo/proyecto - con 2
  // proyectos (escritorio/movil) Playwright seguia lanzando ambos EN
  // PARALELO (se vio literal "Running 2 tests using 2 workers"), contra
  // el MISMO emisor/negocio real. `workers:1` fuerza a toda la suite
  // (todos los archivos, todos los proyectos) a correr en un solo
  // worker, secuencial de principio a fin - la unica forma real de
  // eliminar el riesgo de choque de datos entre escritorio y movil.
  workers: 1,
  retries: 0, // un test que falla debe reportarse tal cual, no reintentarse hasta que pase (regla explicita de la tarea)
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Nunca capturar valores de campos de contraseña en trazas/video
    // (regla explicita de la tarea) - Playwright enmascara inputs
    // type="password" por defecto en las trazas de acciones (no aparece
    // el valor tecleado), pero se desactiva ademas la grabacion de video
    // por completo (no solo la mascara de password) para no dejar ningun
    // rastro visual del formulario de login en disco.
    video: "off",
  },
  projects: [
    {
      name: "escritorio",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "movil",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
