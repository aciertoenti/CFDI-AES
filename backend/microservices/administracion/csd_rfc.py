"""
Extraccion del RFC embebido en un certificado CSD del SAT (.cer, DER).

Campo confirmado empiricamente (no por documentacion): x500UniqueIdentifier
(OID 2.5.4.45) del Subject, con formato "RFC / CURP_o_RFC_representante"
(ej. "EKU9003173C9 / VADA800927DJ3" en el CSD real de prueba del proyecto,
persona moral). El RFC buscado es la parte antes del " / ". serialNumber
(OID 2.5.4.5) NO sirve para esto - viene vacio en la primera parte.

Verificado contra satcfdi.models.Signer.rfc (ya usado en facturacion como
fuente confiable) sobre el mismo certificado: ambos coinciden
("EKU9003173C9"). No se agrega satcfdi como dependencia de este servicio
por lo mismo que rfc_validation.py en auth_usuarios: trae weasyprint/lxml/
cairo, peso injustificado solo para leer un campo del certificado -
cryptography ya es dependencia real de administracion (CifradoFernet).

Limitacion conocida: solo verificado contra un CSD real de persona moral
(unico disponible en certs_test/) - no se probo contra un certificado de
persona fisica real.
"""
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID


def extraer_rfc_de_certificado(cert_bytes: bytes) -> str:
    """
    Extrae el RFC embebido en un certificado CSD del SAT (DER). Lanza
    ValueError si el certificado no se puede parsear o no contiene el
    campo esperado - el llamador es responsable de convertir esto en un
    422, nunca dejar que reviente como 500.
    """
    try:
        cert = x509.load_der_x509_certificate(cert_bytes, default_backend())
        valores = cert.subject.get_attributes_for_oid(NameOID.X500_UNIQUE_IDENTIFIER)
        if not valores:
            raise ValueError("El certificado no contiene x500UniqueIdentifier")
        rfc = valores[0].value.split("/")[0].strip()
        if not rfc:
            raise ValueError("x500UniqueIdentifier no contiene un RFC reconocible")
        return rfc.upper()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"No se pudo leer el certificado: {e}")
