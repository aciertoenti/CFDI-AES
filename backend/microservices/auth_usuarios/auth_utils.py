from typing import Optional

PLACEHOLDER_EMAIL = "sin-email@local.dev"


def normalizar_email_opcional(email: Optional[str]) -> str:
    """Normaliza emails opcionales para ambientes sin registro real de correo."""
    if email is None:
        return PLACEHOLDER_EMAIL
    email = email.strip()
    if not email:
        return PLACEHOLDER_EMAIL
    return email.lower()


def obtener_email_seguro(email: Optional[str]) -> str:
    """Devuelve un email legible y seguro cuando aún no hay correo real registrado."""
    return normalizar_email_opcional(email)
