"""
Cliente SOAP hacia Finkok (PAC).

Dos responsabilidades separadas:
  - registrar_emisor(): alta idempotente de un RFC emisor como cliente de
    la cuenta de Finkok (registration.wsdl). Sin esto, timbrar_factura()
    falla con "cliente no encontrado" para cualquier RFC nuevo.
  - timbrar_factura(): envia un XML ya firmado (generado con satcfdi) al
    servicio de timbrado (stamp.wsdl) y devuelve el UUID fiscal real.

Firmas de metodo obtenidas inspeccionando los WSDL reales con zeep, no
adivinadas.
"""
import logging
import os
from functools import lru_cache

import zeep

logger = logging.getLogger("finkok_client")

REGISTRATION_WSDL = os.environ.get(
    "FINKOK_REGISTRATION_URL",
    "https://demo-facturacion.finkok.com/servicios/soap/registration.wsdl",
)
STAMP_WSDL = os.environ.get(
    "PAC_URL", "https://demo-facturacion.finkok.com/servicios/soap/stamp.wsdl"
)

# (mensaje_usuario, es_reintentable)
# Referencia: backend/microservices/whatsapp_bot/services/facturacion_client.py
FINKOK_ERRORES: dict[str, tuple[str, bool]] = {
    "301": ("RFC del emisor no registrado en el PAC.", False),
    "302": ("RFC del receptor no válido en el SAT.", False),
    "307": ("Folio y serie ya utilizados. Se generará un nuevo folio.", True),
    "309": ("El SAT está saturado. Reintentando automáticamente...", True),
    "401": ("CSD del emisor expirado o cancelado. Contacta a soporte.", False),
    "708": ("El servicio del SAT no está disponible. Reintentando...", True),
    "709": ("Timeout del SAT. Reintentando...", True),
}


class FinkokError(Exception):
    def __init__(self, codigo: str, mensaje: str, reintentable: bool = False):
        self.codigo = codigo
        self.mensaje = mensaje
        self.reintentable = reintentable
        super().__init__(f"[{codigo}] {mensaje}")


def _pac_credentials() -> tuple[str, str]:
    user = os.environ.get("PAC_USER")
    password = os.environ.get("PAC_PASS")
    if not user or not password:
        raise RuntimeError("PAC_USER y PAC_PASS deben estar configurados en .env")
    return user, password


@lru_cache
def _registration_client() -> zeep.Client:
    return zeep.Client(REGISTRATION_WSDL)


@lru_cache
def _stamp_client() -> zeep.Client:
    return zeep.Client(STAMP_WSDL)


def registrar_emisor(
    rfc: str,
    cer_bytes: bytes,
    key_bytes: bytes,
    passphrase: str,
    tipo_persona: str = "M",
) -> dict:
    """
    Da de alta rfc como cliente de la cuenta de Finkok (necesario antes de
    poder timbrar a su nombre). Idempotente: si ya esta registrado, no
    falla ni intenta duplicar.
    """
    user, password = _pac_credentials()
    client = _registration_client()

    logger.info("Finkok registration.get: verificando si %s ya esta registrado", rfc)
    existente = client.service.get(
        reseller_username=user, reseller_password=password, taxpayer_id=rfc
    )
    usuarios = (existente.users.ResellerUser if existente.users else None) or []
    ya_registrado = any(u.taxpayer_id == rfc for u in usuarios)

    if ya_registrado:
        logger.info("Finkok: %s ya estaba registrado, no se duplica", rfc)
        return {"rfc": rfc, "ya_existia": True, "mensaje": existente.message}

    logger.info("Finkok registration.add: dando de alta %s", rfc)
    resultado = client.service.add(
        reseller_username=user,
        reseller_password=password,
        taxpayer_id=rfc,
        type_user=tipo_persona,
        coupon="",
        added="",
        cer=cer_bytes,
        key=key_bytes,
        passphrase=passphrase,
    )
    if not resultado.success:
        raise FinkokError("registration_add_failed", resultado.message, reintentable=False)

    logger.info("Finkok: %s registrado correctamente", rfc)
    return {"rfc": rfc, "ya_existia": False, "mensaje": resultado.message}


def timbrar_factura(xml_firmado: bytes) -> dict:
    """
    Envia un XML CFDI ya firmado (con satcfdi, sello propio del emisor ya
    aplicado) al servicio de timbrado de Finkok. Devuelve el UUID fiscal
    real y el XML timbrado con el sello del PAC.
    """
    user, password = _pac_credentials()
    client = _stamp_client()

    logger.info("Finkok stamp: enviando XML a timbrar")
    resultado = client.service.stamp(xml=xml_firmado, username=user, password=password)

    if resultado.UUID:
        logger.info("Finkok: timbrado exitoso, UUID=%s", resultado.UUID)
        return {
            "uuid": resultado.UUID,
            "xml_timbrado": resultado.xml,
            "fecha_timbrado": resultado.Fecha,
            "sello_sat": resultado.SatSeal,
            "no_certificado_sat": resultado.NoCertificadoSAT,
        }

    codigo = "desconocido"
    mensaje = resultado.faultstring or "Error desconocido del PAC"
    incidencias = (resultado.Incidencias.Incidencia if resultado.Incidencias else None) or []
    if incidencias:
        primera = incidencias[0]
        codigo = primera.CodigoError
        mensaje = primera.MensajeIncidencia or mensaje

    mensaje_amigable, reintentable = FINKOK_ERRORES.get(codigo, (mensaje, False))
    logger.error("Finkok: timbrado fallo codigo=%s mensaje=%s", codigo, mensaje_amigable)
    raise FinkokError(codigo, mensaje_amigable, reintentable)
