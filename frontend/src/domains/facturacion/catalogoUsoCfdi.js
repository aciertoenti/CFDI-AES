// Catálogo c_UsoCFDI (CFDI 4.0) — espejo del que vive en el backend
// (whatsapp_bot/services/fiscal_validator.py::CATALOGO_USO_CFDI).
//
// Fuente: github.com/phpcfdi/resources-sat-catalogs, tabla cfdi_40_usos_cfdi,
// snapshot version.txt 10.15.20260821 (espejo de dominio público del Anexo 20
// del SAT). Extraído y verificado el 02 sep 2026. Regenerar ambos (este archivo
// y el dict de Python) cuando el SAT republique c_UsoCFDI.
//
//   fisica / moral : true si el uso aplica a ese tipo de persona.
//   regimenes      : códigos c_RegimenFiscal del RECEPTOR válidos para el uso
//                    (columna "regimenes_fiscales_receptores" del catálogo).
//
// Están los 24 usos aunque hoy la UI de Nueva Factura solo ofrezca 3 (G03/G01/
// S01, ver USOS_V1 en NuevaFactura.jsx). El catálogo es la fuente completa para
// cuando se expanda el dropdown. "P01" NO existe en CFDI 4.0 (removido desde 3.3).
export const CATALOGO_USO_CFDI = {
  CN01: { desc: "Nómina", fisica: true, moral: false, regimenes: ["605"] },
  CP01: { desc: "Pagos", fisica: true, moral: true, regimenes: ["601", "603", "605", "606", "608", "610", "611", "612", "614", "616", "620", "621", "622", "623", "624", "607", "615", "625", "626"] },
  D01: { desc: "Honorarios médicos, dentales y gastos hospitalarios.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D02: { desc: "Gastos médicos por incapacidad o discapacidad.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D03: { desc: "Gastos funerales.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D04: { desc: "Donativos.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D05: { desc: "Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación).", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D06: { desc: "Aportaciones voluntarias al SAR.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D07: { desc: "Primas por seguros de gastos médicos.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D08: { desc: "Gastos de transportación escolar obligatoria.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D09: { desc: "Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones.", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  D10: { desc: "Pagos por servicios educativos (colegiaturas).", fisica: true, moral: false, regimenes: ["605", "606", "608", "611", "612", "614", "607", "615", "625"] },
  G01: { desc: "Adquisición de mercancías.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  G02: { desc: "Devoluciones, descuentos o bonificaciones.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "616", "620", "621", "622", "623", "624", "625", "626"] },
  G03: { desc: "Gastos en general.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I01: { desc: "Construcciones.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I02: { desc: "Mobiliario y equipo de oficina por inversiones.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I03: { desc: "Equipo de transporte.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I04: { desc: "Equipo de computo y accesorios.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I05: { desc: "Dados, troqueles, moldes, matrices y herramental.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I06: { desc: "Comunicaciones telefónicas.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I07: { desc: "Comunicaciones satelitales.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  I08: { desc: "Otra maquinaria y equipo.", fisica: true, moral: true, regimenes: ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"] },
  S01: { desc: "Sin efectos fiscales.", fisica: true, moral: true, regimenes: ["601", "603", "605", "606", "608", "610", "611", "612", "614", "616", "620", "621", "622", "623", "624", "607", "615", "625", "626"] },
};

// Dado el régimen fiscal del receptor y una lista de claves de uso candidatas
// (ej. ["G03","G01","S01"]), regresa solo las válidas para ese régimen según
// el catálogo oficial. Si no se conoce el régimen (vacío/undefined) no se puede
// filtrar: se regresa la lista candidata tal cual.
export function usosValidosParaRegimen(regimenReceptor, usosDisponibles) {
  if (!regimenReceptor) return [...usosDisponibles];
  return usosDisponibles.filter((clave) => {
    const entry = CATALOGO_USO_CFDI[clave];
    return entry && entry.regimenes.includes(regimenReceptor);
  });
}
