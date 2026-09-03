// Catálogo c_RegimenFiscal (CFDI 4.0) — espejo del que debería usarse
// en el backend (hoy whatsapp_bot/services/fiscal_validator.py tiene
// una version desactualizada con 20 entradas que incluye "609"
// Consolidacion, OBSOLETO desde CFDI 4.0 - no usar esa fuente).
//
// Fuente: github.com/phpcfdi/resources-sat-catalogs, tabla
// cfdi_40_regimenes_fiscales, snapshot version.txt 10.15.20260821
// (espejo de dominio publico del Anexo 20 del SAT). Extraido y
// verificado el 03 sep 2026. Regenerar cuando el SAT republique
// c_RegimenFiscal.
//
// Creado como parte de zg5Lf6Q (Regimen fiscal obligatorio +
// guardado automatico en receptor manual, NuevaFactura.jsx) - punto
// (c) del plan de implementacion: "agregar campo regimen fiscal
// obligatorio con catalogo dedicado (usar el catalogo vigente de
// phpcfdi/19 entradas, NO el de fiscal_validator.py que tiene 609
// obsoleto/20 entradas)".
//
//   fisica / moral : true si el regimen aplica a ese tipo de persona.
export const CATALOGO_REGIMEN_FISCAL = {
  "601": { desc: "General de Ley Personas Morales", fisica: false, moral: true },
  "603": { desc: "Personas Morales con Fines no Lucrativos", fisica: false, moral: true },
  "605": { desc: "Sueldos y Salarios e Ingresos Asimilados a Salarios", fisica: true, moral: false },
  "606": { desc: "Arrendamiento", fisica: true, moral: false },
  "607": { desc: "Régimen de Enajenación o Adquisición de Bienes", fisica: true, moral: false },
  "608": { desc: "Demás ingresos", fisica: true, moral: false },
  "610": { desc: "Residentes en el Extranjero sin Establecimiento Permanente en México", fisica: true, moral: true },
  "611": { desc: "Ingresos por Dividendos (socios y accionistas)", fisica: true, moral: false },
  "612": { desc: "Personas Físicas con Actividades Empresariales y Profesionales", fisica: true, moral: false },
  "614": { desc: "Ingresos por intereses", fisica: true, moral: false },
  "615": { desc: "Régimen de los ingresos por obtención de premios", fisica: true, moral: false },
  "616": { desc: "Sin obligaciones fiscales", fisica: true, moral: false },
  "620": { desc: "Sociedades Cooperativas de Producción que optan por diferir sus ingresos", fisica: false, moral: true },
  "621": { desc: "Incorporación Fiscal", fisica: true, moral: false },
  "622": { desc: "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras", fisica: false, moral: true },
  "623": { desc: "Opcional para Grupos de Sociedades", fisica: false, moral: true },
  "624": { desc: "Coordinados", fisica: false, moral: true },
  "625": { desc: "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas", fisica: true, moral: false },
  "626": { desc: "Régimen Simplificado de Confianza", fisica: true, moral: true },
};
