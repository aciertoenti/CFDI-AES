"""
Validacion de RFC de persona fisica (13 caracteres) - formato + digito
verificador real.

Algoritmo y tabla de caracteres tomados de satcfdi.models.rfc (satcfdi.RFC,
ya usado en facturacion para todo lo demas de CFDI/SAT) - se porta solo el
algoritmo (regex + checksum modulo 11), sin agregar satcfdi como dependencia
de este servicio a proposito: satcfdi trae weasyprint/lxml/cairo (generacion
de PDF, parsing de XML pesado) que no tienen nada que ver con auth_usuarios
e inflarian su imagen de Docker (y su superficie de build) sin necesidad -
este servicio hoy no tiene ninguna dependencia nativa/pesada. El algoritmo en
si es estable (no ha cambiado en anios), asi que portarlo no crea deuda real.
"""
import re

_RFC_PERSONA_FISICA_REGEX = re.compile(
    r"[A-Z&Ñ]{4}[0-9]{2}(?:0[1-9]|1[012])(?:0[1-9]|[12][0-9]|3[01])[A-Z0-9]{2}[0-9A]"
)
_RFC_VERIFY_CHARS = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ"


def es_rfc_persona_fisica_valido(rfc: str) -> bool:
    """
    True si `rfc` tiene el formato de persona fisica (4 letras + AAMMDD +
    homoclave de 3 caracteres, 13 en total) Y su digito verificador (ultimo
    caracter de la homoclave) es matematicamente correcto - no solo el
    formato. Mismo algoritmo que usa satcfdi.models.rfc.RFC.is_valid().
    """
    rfc = rfc.upper()
    if len(rfc) != 13 or not _RFC_PERSONA_FISICA_REGEX.fullmatch(rfc):
        return False

    total = 0
    for posicion, caracter in enumerate(reversed(rfc), start=1):
        indice = _RFC_VERIFY_CHARS.find(caracter)
        if indice == -1:
            return False
        total += indice * posicion
    return total % 11 == 0
