"""
Catalogo c_RegimenFiscal / c_UsoCFDI del SAT (CFDI 4.0), para validar el
receptor ANTES de llamar a Finkok (pieza 5 del epic POS ligero, zg5b-ZE -
portal publico de autofacturacion individual, 05 sep 2026).

COPIA INTENCIONAL, no import cruzado: el catalogo real ya vive en
backend/microservices/whatsapp_bot/services/fiscal_validator.py (mismos
dict CATALOGO_REGIMEN_FISCAL/CATALOGO_USO_CFDI, mismas funciones
validate_regimen_fiscal/validate_uso_cfdi). NO se importa directo porque
whatsapp_bot y facturacion son builds Docker independientes con
build-context distinto: facturacion construye con context=./backend
(por eso puede hacer `COPY shared /app/shared`, ver Dockerfile), pero
whatsapp_bot construye con context=./backend/microservices/whatsapp_bot
- sin acceso a backend/shared/. Unificarlo en backend/shared/ es la
solucion correcta a mediano plazo, pero exige tocar el build de
whatsapp_bot (docker-compose.yml + su Dockerfile + sus 2 imports
internos) - un servicio que hoy funciona en produccion y que no es parte
del alcance de esta pieza. Decision explicita (05 sep 2026): copiar solo
lo necesario aqui en vez de arriesgar ese refactor mas amplio sin que se
haya pedido. Si el catalogo del SAT cambia, hay que actualizar AMBAS
copias (aqui y en whatsapp_bot) hasta que se resuelva la unificacion.

Fuente original de los catalogos: github.com/phpcfdi/resources-sat-catalogs,
tabla cfdi_40_usos_cfdi, snapshot version.txt 10.15.20260821 (espejo de
dominio publico del Anexo 20 del SAT). Extraido y verificado el 02 sep
2026 (ver whatsapp_bot/services/fiscal_validator.py para el detalle).
"""
from __future__ import annotations

from dataclasses import dataclass

# ─── Catalogo c_RegimenFiscal (SAT, vigente 2024) ────────────────────────────
CATALOGO_REGIMEN_FISCAL: dict[str, str] = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "609": "Consolidación",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Régimen de los ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Producción que optan por diferir sus ingresos",
    "621": "Incorporación Fiscal",
    "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}

# ─── Catalogo c_UsoCFDI (CFDI 4.0) ──────────────────────────────────────────
# "fisica"/"moral": True si aplica a ese tipo de persona.
# "regimenes": codigos c_RegimenFiscal del RECEPTOR validos para este uso
#              (columna "regimenes_fiscales_receptores" del catalogo oficial).
CATALOGO_USO_CFDI: dict[str, dict] = {
    "CN01": {"desc": "Nómina", "fisica": True, "moral": False, "regimenes": ["605"]},
    "CP01": {"desc": "Pagos", "fisica": True, "moral": True, "regimenes": ["601", "603", "605", "606", "608", "610", "611", "612", "614", "616", "620", "621", "622", "623", "624", "607", "615", "625", "626"]},
    "D01": {"desc": "Honorarios médicos, dentales y gastos hospitalarios.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D02": {"desc": "Gastos médicos por incapacidad o discapacidad.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D03": {"desc": "Gastos funerales.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D04": {"desc": "Donativos.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D05": {"desc": "Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación).", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D06": {"desc": "Aportaciones voluntarias al SAR.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D07": {"desc": "Primas por seguros de gastos médicos.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D08": {"desc": "Gastos de transportación escolar obligatoria.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D09": {"desc": "Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones.", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "D10": {"desc": "Pagos por servicios educativos (colegiaturas).", "fisica": True, "moral": False, "regimenes": ["605", "606", "608", "611", "612", "614", "607", "615", "625"]},
    "G01": {"desc": "Adquisición de mercancías.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "G02": {"desc": "Devoluciones, descuentos o bonificaciones.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "616", "620", "621", "622", "623", "624", "625", "626"]},
    "G03": {"desc": "Gastos en general.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I01": {"desc": "Construcciones.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I02": {"desc": "Mobiliario y equipo de oficina por inversiones.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I03": {"desc": "Equipo de transporte.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I04": {"desc": "Equipo de computo y accesorios.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I05": {"desc": "Dados, troqueles, moldes, matrices y herramental.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I06": {"desc": "Comunicaciones telefónicas.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I07": {"desc": "Comunicaciones satelitales.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "I08": {"desc": "Otra maquinaria y equipo.", "fisica": True, "moral": True, "regimenes": ["601", "603", "606", "612", "620", "621", "622", "623", "624", "625", "626"]},
    "S01": {"desc": "Sin efectos fiscales.", "fisica": True, "moral": True, "regimenes": ["601", "603", "605", "606", "608", "610", "611", "612", "614", "616", "620", "621", "622", "623", "624", "607", "615", "625", "626"]},
}

# Regimenes de personas morales (vs fisicas)
REGIMENES_PERSONA_MORAL: set[str] = {"601", "603", "609", "620", "621", "622", "623", "624"}


@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None


def validate_regimen_fiscal(codigo: str) -> ValidationResult:
    """Valida contra el catalogo c_RegimenFiscal del SAT."""
    codigo = codigo.strip()
    if codigo not in CATALOGO_REGIMEN_FISCAL:
        return ValidationResult(
            valid=False,
            error=f"Régimen fiscal '{codigo}' no reconocido por el catálogo c_RegimenFiscal del SAT.",
        )
    return ValidationResult(valid=True)


def validate_uso_cfdi(uso: str, regimen_fiscal: str) -> ValidationResult:
    """
    Valida Uso CFDI contra c_UsoCFDI y su compatibilidad con el regimen
    fiscal del receptor (fisica/moral + tabla oficial de combinaciones
    validas). regimen_fiscal se asume YA validado por validate_regimen_fiscal
    (llamar esa primero) - aqui no se vuelve a chequear que exista.
    """
    uso = uso.strip().upper()
    if uso not in CATALOGO_USO_CFDI:
        return ValidationResult(
            valid=False,
            error=f"Uso CFDI '{uso}' no reconocido por el catálogo c_UsoCFDI del SAT.",
        )

    entry = CATALOGO_USO_CFDI[uso]
    es_moral = regimen_fiscal in REGIMENES_PERSONA_MORAL
    if es_moral and not entry["moral"]:
        return ValidationResult(
            valid=False,
            error=f"El uso CFDI '{uso}' no es compatible con personas morales (régimen {regimen_fiscal}).",
        )
    if not es_moral and not entry["fisica"]:
        return ValidationResult(
            valid=False,
            error=f"El uso CFDI '{uso}' no es compatible con personas físicas (régimen {regimen_fiscal}).",
        )
    if regimen_fiscal not in entry["regimenes"]:
        return ValidationResult(
            valid=False,
            error=(
                f"El uso CFDI '{uso}' no es válido para el régimen fiscal "
                f"{regimen_fiscal} del receptor (catálogo oficial c_UsoCFDI)."
            ),
        )
    return ValidationResult(valid=True)
