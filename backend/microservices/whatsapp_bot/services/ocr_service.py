"""
OCR de Constancia de Situación Fiscal (CSF) del SAT.
Soporta imagen (JPG/PNG) y PDF de una página.
Extrae: RFC, Razón Social, CP, Régimen Fiscal.
Verifica el RFC extraído contra el RFC ya capturado en la conversación.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional

from core.logging import get_logger

logger = get_logger(__name__)

# Intentamos importar dependencias de OCR.
# Si no están disponibles (en tests), el servicio retorna un resultado vacío.
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("ocr.tesseract_not_available", msg="pytesseract/Pillow no disponibles")

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# ─── Regex para extracción ────────────────────────────────────────────────────

_RE_RFC = re.compile(
    r"RFC[:\s]*([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})",
    re.IGNORECASE,
)
_RE_CP = re.compile(
    r"(?:Código Postal|C\.P\.|CP)[:\s]*(\d{5})",
    re.IGNORECASE,
)
_RE_REGIMEN = re.compile(
    r"Régimen[^:]*:[:\s]*(\d{3})",
    re.IGNORECASE,
)
_RE_RAZON_SOCIAL = re.compile(
    r"(?:Nombre|Razón Social|Denominación)[:\s]*([A-ZÁÉÍÓÚÜÑ][^\n]{3,100})",
    re.IGNORECASE,
)


@dataclass
class CSFResult:
    rfc: Optional[str] = None
    razon_social: Optional[str] = None
    codigo_postal: Optional[str] = None
    regimen_fiscal: Optional[str] = None
    confianza: float = 0.0  # 0.0 – 1.0
    raw_text: str = ""
    error: Optional[str] = None

    def verificar_rfc(self, rfc_capturado: str) -> bool:
        """Verifica que el RFC del OCR coincida con el capturado por texto."""
        if not self.rfc or not rfc_capturado:
            return False
        return self.rfc.upper().strip() == rfc_capturado.upper().strip()


def _extraer_texto_imagen(contenido: bytes) -> str:
    """Extrae texto de imagen con Tesseract."""
    if not OCR_AVAILABLE:
        raise RuntimeError("pytesseract no está disponible")
    img = Image.open(io.BytesIO(contenido))
    # Modo de página 6 = bloque de texto uniforme (mejor para documentos oficiales)
    texto = pytesseract.image_to_string(
        img,
        lang="spa",
        config="--psm 6",
    )
    return texto


def _extraer_texto_pdf(contenido: bytes) -> str:
    """Extrae texto de la primera página del PDF."""
    if not PDF_AVAILABLE:
        raise RuntimeError("PyPDF2 no está disponible")
    reader = PyPDF2.PdfReader(io.BytesIO(contenido))
    if not reader.pages:
        return ""
    return reader.pages[0].extract_text() or ""


def _parsear_texto(texto: str) -> CSFResult:
    """Aplica regex al texto extraído y calcula la confianza."""
    result = CSFResult(raw_text=texto[:2000])  # guardamos extracto para debug

    m = _RE_RFC.search(texto)
    if m:
        result.rfc = m.group(1).upper()

    m = _RE_CP.search(texto)
    if m:
        result.codigo_postal = m.group(1)

    m = _RE_REGIMEN.search(texto)
    if m:
        result.regimen_fiscal = m.group(1)

    m = _RE_RAZON_SOCIAL.search(texto)
    if m:
        result.razon_social = m.group(1).strip()[:300]

    # Confianza: fracción de campos que pudimos extraer
    campos = [result.rfc, result.razon_social, result.codigo_postal, result.regimen_fiscal]
    result.confianza = sum(1 for c in campos if c) / len(campos)

    return result


async def procesar_csf(
    contenido: bytes,
    tipo_mime: str,
    rfc_capturado: Optional[str] = None,
) -> CSFResult:
    """
    Procesa una Constancia de Situación Fiscal y retorna los campos extraídos.

    Args:
        contenido: bytes del archivo (imagen o PDF)
        tipo_mime: "image/jpeg" | "image/png" | "application/pdf"
        rfc_capturado: RFC que el usuario indicó por texto (para verificación cruzada)
    """
    try:
        if tipo_mime in ("image/jpeg", "image/jpg", "image/png"):
            texto = _extraer_texto_imagen(contenido)
        elif tipo_mime == "application/pdf":
            texto = _extraer_texto_pdf(contenido)
        else:
            return CSFResult(error=f"Tipo de archivo no soportado: {tipo_mime}")

        result = _parsear_texto(texto)

        if rfc_capturado and not result.verificar_rfc(rfc_capturado):
            logger.warning(
                "ocr.rfc_mismatch",
                rfc_ocr=result.rfc,
                rfc_capturado=rfc_capturado,
            )
            result.error = (
                f"El RFC en la constancia ({result.rfc}) no coincide con el "
                f"RFC que indicaste ({rfc_capturado}). Por favor verifica."
            )

        logger.info(
            "ocr.procesado",
            confianza=result.confianza,
            campos_encontrados=sum(
                1 for c in [result.rfc, result.razon_social, result.codigo_postal, result.regimen_fiscal] if c
            ),
        )
        return result

    except Exception as exc:
        logger.error("ocr.error", error=str(exc))
        return CSFResult(error=f"Error al procesar el documento: {exc}")
