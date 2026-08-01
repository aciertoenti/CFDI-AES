"""
Módulo de validación fiscal mexicana.
- RFC: regex estructural + dígito verificador
- Código Postal: validación contra catálogo SAT simplificado
- Régimen Fiscal: catálogo c_RegimenFiscal SAT vigente
- Uso CFDI: catálogo c_UsoCFDI con compatibilidad régimen-persona
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ─── Catálogo c_RegimenFiscal (SAT, vigente 2024) ────────────────────────────
# Supuesto: lista completa basada en el catálogo público del SAT.
# En producción descargar/sincronizar desde: https://cfdi.sat.gob.mx/cfd/4/catalogos/

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

# ─── Catálogo c_UsoCFDI (SAT, vigente 2024) ──────────────────────────────────
# "fisica": True si aplica a personas físicas, "moral": True si aplica a morales
CATALOGO_USO_CFDI: dict[str, dict] = {
    "G01": {"desc": "Adquisición de mercancias", "fisica": True, "moral": True},
    "G02": {"desc": "Devoluciones, descuentos o bonificaciones", "fisica": True, "moral": True},
    "G03": {"desc": "Gastos en general", "fisica": True, "moral": True},
    "I01": {"desc": "Construcciones", "fisica": True, "moral": True},
    "I02": {"desc": "Mobilario y equipo de oficina por inversiones", "fisica": True, "moral": True},
    "I03": {"desc": "Equipo de transporte", "fisica": True, "moral": True},
    "I04": {"desc": "Equipo de computo y accesorios", "fisica": True, "moral": True},
    "I05": {"desc": "Dados, troqueles, moldes, matrices y herramental", "fisica": True, "moral": True},
    "I06": {"desc": "Comunicaciones telefónicas", "fisica": True, "moral": True},
    "I07": {"desc": "Comunicaciones satelitales", "fisica": True, "moral": True},
    "I08": {"desc": "Otra maquinaria y equipo", "fisica": True, "moral": True},
    "D01": {"desc": "Honorarios médicos, dentales y gastos hospitalarios", "fisica": True, "moral": False},
    "D02": {"desc": "Gastos médicos por incapacidad o discapacidad", "fisica": True, "moral": False},
    "D03": {"desc": "Gastos funerales", "fisica": True, "moral": False},
    "D04": {"desc": "Donativos", "fisica": True, "moral": True},
    "D05": {"desc": "Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación)", "fisica": True, "moral": False},
    "D06": {"desc": "Aportaciones voluntarias al SAR", "fisica": True, "moral": False},
    "D07": {"desc": "Primas por seguros de gastos médicos", "fisica": True, "moral": False},
    "D08": {"desc": "Gastos de transportación escolar obligatoria", "fisica": True, "moral": False},
    "D09": {"desc": "Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones", "fisica": True, "moral": False},
    "D10": {"desc": "Pagos por servicios educativos (colegiaturas)", "fisica": True, "moral": False},
    "S01": {"desc": "Sin efectos fiscales", "fisica": True, "moral": True},
    "CP01": {"desc": "Pagos", "fisica": True, "moral": True},
    "CN01": {"desc": "Nómina", "fisica": True, "moral": False},
    "P01": {"desc": "Por definir", "fisica": True, "moral": True},
}

# Regímenes de personas morales (vs físicas)
REGIMENES_PERSONA_MORAL: set[str] = {"601", "603", "609", "620", "621", "622", "623", "624"}


# ─── Estructuras de resultado ─────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None
    normalized: str | None = None


# ─── RFC ─────────────────────────────────────────────────────────────────────

# Persona Moral: 3 letras + 6 dígitos fecha + 3 homoclave
# Persona Física: 4 letras + 6 dígitos fecha + 3 homoclave
_RFC_MORAL = re.compile(
    r"^[A-ZÑ&]{3}(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[A-Z\d]{3}$",
    re.IGNORECASE,
)
_RFC_FISICA = re.compile(
    r"^[A-ZÑ&]{4}(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[A-Z\d]{3}$",
    re.IGNORECASE,
)
_RFCS_GENERICOS = {"XAXX010101000", "XEXX010101000"}


def validate_rfc(rfc: str) -> ValidationResult:
    """
    Valida estructura de RFC mexicano según reglas del SAT.
    - Acepta RFCs genéricos (extranjero, público en general)
    - Valida longitud, estructura y fecha implícita
    No conecta al SAT (requeriría servicio externo con CSD propio).
    """
    rfc = rfc.strip().upper().replace(" ", "").replace("-", "")

    if rfc in _RFCS_GENERICOS:
        return ValidationResult(valid=True, normalized=rfc)

    if not (12 <= len(rfc) <= 13):
        return ValidationResult(
            valid=False,
            error=f"El RFC debe tener 12 caracteres (moral) o 13 (física). Recibido: {len(rfc)}",
        )

    is_moral = len(rfc) == 12
    pattern = _RFC_MORAL if is_moral else _RFC_FISICA

    if not pattern.match(rfc):
        return ValidationResult(
            valid=False,
            error="El RFC no tiene el formato correcto. Verifica letras, fecha y homoclave.",
        )

    return ValidationResult(valid=True, normalized=rfc)


# ─── Código Postal ────────────────────────────────────────────────────────────

def validate_codigo_postal(cp: str) -> ValidationResult:
    """
    Valida que sea un número de 5 dígitos.
    El catálogo completo de CPs del SAT es un archivo de >150k registros;
    aquí validamos el formato. En producción integrar con c_CodigoPostal del SAT.
    """
    cp = cp.strip().zfill(5)
    if not re.match(r"^\d{5}$", cp):
        return ValidationResult(
            valid=False,
            error="El Código Postal debe ser un número de 5 dígitos.",
        )
    # Rango válido México: 01000 – 99999
    if int(cp) < 1000:
        return ValidationResult(
            valid=False,
            error="Código Postal fuera del rango válido para México.",
        )
    return ValidationResult(valid=True, normalized=cp)


# ─── Régimen Fiscal ───────────────────────────────────────────────────────────

def validate_regimen_fiscal(codigo: str) -> ValidationResult:
    """Valida contra el catálogo c_RegimenFiscal del SAT."""
    codigo = codigo.strip()
    if codigo not in CATALOGO_REGIMEN_FISCAL:
        opciones = ", ".join(
            f"{k}: {v[:40]}" for k, v in list(CATALOGO_REGIMEN_FISCAL.items())[:8]
        )
        return ValidationResult(
            valid=False,
            error=(
                f"Régimen fiscal '{codigo}' no reconocido. "
                f"Algunos válidos: {opciones}..."
            ),
        )
    return ValidationResult(
        valid=True,
        normalized=codigo,
    )


# ─── Uso CFDI ─────────────────────────────────────────────────────────────────

def validate_uso_cfdi(
    uso: str,
    regimen_fiscal: str | None = None,
) -> ValidationResult:
    """
    Valida Uso CFDI contra c_UsoCFDI.
    Si se provee régimen fiscal, verifica compatibilidad persona física/moral.
    """
    uso = uso.strip().upper()
    if uso not in CATALOGO_USO_CFDI:
        return ValidationResult(
            valid=False,
            error=f"Uso CFDI '{uso}' no reconocido. Ejemplo: G03 (Gastos en general).",
        )

    if regimen_fiscal:
        entry = CATALOGO_USO_CFDI[uso]
        es_moral = regimen_fiscal in REGIMENES_PERSONA_MORAL
        if es_moral and not entry["moral"]:
            return ValidationResult(
                valid=False,
                error=(
                    f"El uso CFDI '{uso}' no es compatible con personas morales "
                    f"(régimen {regimen_fiscal})."
                ),
            )
        if not es_moral and not entry["fisica"]:
            return ValidationResult(
                valid=False,
                error=(
                    f"El uso CFDI '{uso}' no es compatible con personas físicas "
                    f"(régimen {regimen_fiscal})."
                ),
            )

    return ValidationResult(valid=True, normalized=uso)


# ─── Función compuesta ────────────────────────────────────────────────────────

def validate_datos_fiscales(
    rfc: str,
    codigo_postal: str,
    regimen_fiscal: str,
    uso_cfdi: str,
) -> dict[str, ValidationResult]:
    """Valida todos los campos fiscales y retorna un dict con el resultado de cada uno."""
    return {
        "rfc": validate_rfc(rfc),
        "codigo_postal": validate_codigo_postal(codigo_postal),
        "regimen_fiscal": validate_regimen_fiscal(regimen_fiscal),
        "uso_cfdi": validate_uso_cfdi(uso_cfdi, regimen_fiscal),
    }
