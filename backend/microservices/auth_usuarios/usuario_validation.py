"""
Validacion de "usuario" - credencial de login alterna al RFC personal
(no lo reemplaza, ver Usuario.usuario en database.py). Mismo estilo que
rfc_validation.py: una funcion pura, sin dependencias externas.
"""
import re

# 6-10 caracteres, empieza con letra, resto letras/numeros/guion_bajo.
# Se normaliza a MAYUSCULAS antes de validar/guardar (mismo patron que el
# RFC) - este regex ya asume que el valor recibido viene en mayusculas.
_USUARIO_REGEX = re.compile(r"[A-Z][A-Z0-9_]{5,9}")


def es_usuario_valido(usuario: str) -> bool:
    """
    True si `usuario` (ya en MAYUSCULAS) tiene 6-10 caracteres, empieza con
    una letra y el resto son letras, numeros o guion bajo.
    """
    usuario = usuario.upper()
    return bool(_USUARIO_REGEX.fullmatch(usuario))
