"""
Validacion de PDFs de declaraciones anuales (Parte B, 22 sep 2026).

Alcance deliberadamente angosto - este modulo SOLO valida que el archivo
sea un PDF real y este dentro del tamano permitido. NO parsea el
contenido del PDF (fuera de alcance explicito de la tarea), NO extrae
texto ni montos.

Mismo patron ya establecido en logo_storage.py (validar_logo): magic
bytes reales, nunca el Content-Type que declare el cliente - un cliente
API directo (saltandose el navegador/frontend) puede mandar cualquier
extension/header con cualquier contenido.
"""
import hashlib
import os
import re
from datetime import datetime

# Configurable por variable de entorno (pedido explicito) - default 5MB.
# Constante nombrada, nunca un numero magico suelto en el codigo que la usa.
MAX_DECLARACION_PDF_BYTES = int(os.environ.get("MAX_DECLARACION_PDF_BYTES", 5 * 1024 * 1024))

# Ejercicio minimo aceptado - CORREGIDO 22 sep 2026 (reporte 185/C2):
# el valor original (2014) se descarto al revisar documentos reales del
# titular - existen acuses reales desde el ejercicio 2013, asi que 2014
# rechazaba datos reales que si hacia falta soportar. 2000 da margen
# amplio sin caer en un limite arbitrario adivinado - mismo criterio de
# "nunca un margen adivinado" ya aplicado en otras partes del proyecto
# (fixes de thinking/max_tokens, zg7ilnY/zg4pAxA).
#
# DUPLICADO a proposito en el frontend
# (DeclaracionesAnualesModal.jsx, misma constante con este mismo
# comentario) - no hay endpoint dedicado a exponer este rango (ver
# reporte 183, "Pendientes y riesgos" punto 3). Si este valor cambia de
# nuevo, actualizar tambien el frontend a mano.
EJERCICIO_MINIMO = 2000

TIPOS_DECLARACION_VALIDOS = ("normal", "complementaria")
TIPOS_DOCUMENTO_VALIDOS = ("declaracion", "acuse", "comprobante_pago")


def ejercicio_maximo_valido() -> int:
    """Año actual - 1 (calculado, nunca hardcodeado) - una declaracion
    anual del ejercicio EN CURSO no existe todavia (se presenta el año
    siguiente)."""
    return datetime.now().year - 1


def validar_pdf(contenido: bytes) -> None:
    """Valida tamano y formato REAL por magic bytes (%PDF- al inicio del
    archivo, firma estandar de PDF/ISO 32000) - lanza ValueError con un
    mensaje apto para un 422 si algo no cumple. NO valida que el PDF sea
    parseable/bien formado mas alla de la firma - no se necesita abrir
    el archivo para esta funcionalidad (solo se guarda y se sirve tal
    cual, nunca se procesa su contenido)."""
    if not contenido:
        raise ValueError("El archivo esta vacio")
    if len(contenido) > MAX_DECLARACION_PDF_BYTES:
        raise ValueError(
            f"El archivo no debe exceder {MAX_DECLARACION_PDF_BYTES // (1024 * 1024)}MB"
        )
    if not contenido.startswith(b"%PDF-"):
        raise ValueError("El archivo no es un PDF valido (firma %PDF- ausente)")


def validar_ejercicio(ejercicio: int) -> None:
    maximo = ejercicio_maximo_valido()
    if ejercicio < EJERCICIO_MINIMO or ejercicio > maximo:
        raise ValueError(
            f"El ejercicio debe estar entre {EJERCICIO_MINIMO} y {maximo}"
        )


def validar_tipo_declaracion(tipo_declaracion: str, numero_complementaria) -> None:
    """SIN TOPE superior en numero_complementaria (corregido 22 sep 2026,
    reporte 185/C3): el limite general de Art. 32 CFF es de 3
    modificaciones, pero ese mismo articulo tiene excepciones (ej.
    declaraciones complementarias por dictamen, por correccion derivada
    de facultades de comprobacion, entre otras) que permiten mas de 3 -
    documentos reales del titular confirman casos asi. Se valida solo
    que sea un entero >= 1, no un rango cerrado."""
    if tipo_declaracion not in TIPOS_DECLARACION_VALIDOS:
        raise ValueError(f"tipo_declaracion invalido - usa uno de {TIPOS_DECLARACION_VALIDOS}")
    if tipo_declaracion == "normal" and numero_complementaria is not None:
        raise ValueError("numero_complementaria debe ser nulo cuando tipo_declaracion='normal'")
    if tipo_declaracion == "complementaria":
        if numero_complementaria is None or numero_complementaria < 1:
            raise ValueError(
                "numero_complementaria es obligatorio (entero >= 1) cuando tipo_declaracion='complementaria'"
            )


def validar_tipo_documento(tipo_documento: str) -> None:
    if tipo_documento not in TIPOS_DOCUMENTO_VALIDOS:
        raise ValueError(f"tipo_documento invalido - usa uno de {TIPOS_DOCUMENTO_VALIDOS}")


def calcular_sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


# Caracteres permitidos en el nombre de archivo mostrado/descargado:
# letras/digitos ASCII, espacio, punto, guion, guion bajo, parentesis -
# cualquier otro caracter (incluidos separadores de ruta / y \, y
# caracteres de control) se reemplaza por "_". Previene 2 cosas
# distintas: (1) que un nombre con "../" o similar se use para construir
# una ruta de archivo en algun punto futuro del codigo (aunque hoy nada
# lo hace - defensa en profundidad), y (2) que un Content-Disposition mal
# escapado permita header injection (\r\n en el nombre).
_NOMBRE_SEGURO_RE = re.compile(r"[^A-Za-z0-9 ._()\-]")


def sanitizar_nombre_archivo(nombre: str) -> str:
    """Para mostrar/usar en Content-Disposition - NUNCA se usa para
    decidir donde/como se guarda el archivo (el contenido va cifrado en
    una columna de BD, no en un filesystem)."""
    limpio = _NOMBRE_SEGURO_RE.sub("_", nombre or "")
    limpio = limpio.strip() or "documento.pdf"
    return limpio[:255]
