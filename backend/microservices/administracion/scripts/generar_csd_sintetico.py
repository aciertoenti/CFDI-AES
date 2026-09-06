"""
Generador de CSD SINTETICOS para pruebas (zg2mOjI).

NO es una migracion de Alembic ni de datos: no toca la base de datos, no
lee filas, no cambia esquema. Es una herramienta de dev que crea archivos
en disco - un par certificado/llave X.509 autofirmado con un RFC INVENTADO -
para poder ejercitar el codigo que lee, parsea, cachea y valida CSD sin
necesitar credenciales fiscales reales.

Uso (dentro del contenedor de administracion, o local si cryptography esta
instalado):

    python scripts/generar_csd_sintetico.py                # 1 CSD moral
    python scripts/generar_csd_sintetico.py 3              # 3 CSD, tipo alterno
    python scripts/generar_csd_sintetico.py 2 --tipo fisica
    python scripts/generar_csd_sintetico.py 1 --prefijo ZZZ --out /tmp/csd

Salida por cada CSD (en el directorio --out, default ./csd_sintetico_out/):
    <RFC>.cer            certificado X.509 en DER
    <RFC>.key            llave privada en DER, PKCS#8, CIFRADA con la password
    <RFC>_password.txt   la password (archivo SEPARADO del .key a proposito,
                         para que no se confunda con un bundle de credencial real)

===============================================================================
ADVERTENCIA - LEER
===============================================================================
Los certificados que produce este script son 100% SINTETICOS:
  - Autofirmados (issuer == subject). NO emitidos por la Autoridad
    Certificadora del SAT.
  - Con un RFC INVENTADO (formato valido, contenido falso).
  - Sin NINGUNA validez fiscal.

JAMAS deben usarse para intentar timbrar contra el sandbox ni la
produccion de Finkok/el PAC: seran rechazados (el RFC no esta en el padron
del SAT) y, aunque no lo fueran, no producirian un comprobante valido.

Sirven UNICAMENTE para pruebas de codigo que necesita un CSD "bien
formado" pero no fiscalmente real:
  - alta de emisores multiples (validacion RFC-del-cert == RFC-declarado,
    ver administracion/csd_rfc.py y el 422 en POST /admin/emisores)
  - invalidacion de cache de CSD en facturacion (_csd_cache / el endpoint
    /internal/csd-cache/invalidar)
  - aislamiento multi-negocio de CSD

Para pruebas que SI requieren timbrado real (sandbox), usar los CSD reales
del SAT que ya viven en certs_test/ (EKU9003173C9, IVD920810GU2, etc.).
===============================================================================
"""
import argparse
import base64
import os
import secrets
import string
import sys
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# RFCs reales (de prueba del SAT o genericos) que NUNCA debe generar este
# script - si por azar cae en uno, se descarta y reintenta.
RFC_REALES_PROHIBIDOS = {
    "EKU9003173C9", "IIA040805DZ4", "IVD920810GU2", "MISC491214B86",
    "XIQB891116QE4", "RAHP7112093H0",
    "XAXX010101000", "XEXX010101000",  # genericos del SAT
}

MARCA_SINTETICO = "CSD SINTETICO - NO VALIDO PARA TIMBRADO REAL"
ANIOS_VIGENCIA = 4          # los CSD del SAT duran 4 anios
RSA_BITS = 2048             # estandar del SAT

# Tabla de peso del digito verificador del RFC (misma que usa satcfdi:
# satcfdi/models/rfc.py -> RFC_Verify_Chars). El generador calcula el ultimo
# caracter para que el RFC pase tanto el regex como el checksum mod-11 de
# satcfdi, ademas del regex del SAT.
RFC_VERIFY_CHARS = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ"


def _digito_verificador(rfc_sin_dv: str, es_moral: bool) -> str:
    """
    Calcula el ultimo caracter del RFC (posicion i=1 en la cadena invertida)
    para que sum(index(c) * i) % 11 == 0, con el sumando 481 extra si es
    persona moral. El resultado siempre cae en '0'..'9' o 'A' (indice 0..10),
    que es justo lo que exige el regex del SAT para esa posicion.
    """
    tot = 481 if es_moral else 0
    # el RFC completo tendra un caracter mas al final -> ese va en i=1, y el
    # resto se recorre a i=2,3,... sobre la cadena invertida.
    for i, c in enumerate(rfc_sin_dv[::-1], start=2):
        tot += RFC_VERIFY_CHARS.index(c) * i
    idx = (-tot) % 11
    return RFC_VERIFY_CHARS[idx]  # 0..10 -> '0'..'9','A'


def _rfc_sintetico(tipo: str, prefijo: str) -> str:
    """
    RFC con formato VALIDO pero contenido INVENTADO.
      moral  : 3 letras + AAMMDD + 3 homoclave  = 12 chars
      fisica : 4 letras + AAMMDD + 3 homoclave  = 13 chars
    'prefijo' fija las primeras letras (default 'SIN' de sintetico); el resto
    de letras y la fecha son aleatorias (dd 01-28, mm 01-12 para caer siempre
    en un dia valido). De la homoclave, los 2 primeros caracteres son
    aleatorios [A-Z0-9] y el 3ro es el DIGITO VERIFICADOR calculado, de modo
    que el RFC pasa el regex del SAT Y el checksum mod-11 de satcfdi.
    """
    n_letras = 3 if tipo == "moral" else 4
    letras = (prefijo.upper() + "".join(secrets.choice(string.ascii_uppercase) for _ in range(n_letras)))[:n_letras]
    aa = f"{secrets.randbelow(100):02d}"
    mm = f"{secrets.randbelow(12) + 1:02d}"
    dd = f"{secrets.randbelow(28) + 1:02d}"
    homo2 = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(2))
    base = f"{letras}{aa}{mm}{dd}{homo2}"
    dv = _digito_verificador(base, es_moral=(n_letras == 3))
    return f"{base}{dv}"


def _generar_rfc(tipo: str, prefijo: str, ya_usados: set) -> str:
    for _ in range(1000):
        rfc = _rfc_sintetico(tipo, prefijo)
        if rfc not in RFC_REALES_PROHIBIDOS and rfc not in ya_usados:
            return rfc
    raise RuntimeError("No se pudo generar un RFC sintetico unico (1000 intentos)")


def generar_uno(tipo: str, prefijo: str, out_dir: str, ya_usados: set) -> dict:
    rfc = _generar_rfc(tipo, prefijo, ya_usados)
    ya_usados.add(rfc)

    key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)

    # Subject: x500UniqueIdentifier (OID 2.5.4.45) = el RFC, SIN "/" - asi
    # administracion/csd_rfc.py (.split("/")[0].strip()) y satcfdi
    # Signer.rfc recuperan el RFC intacto. La marca de "sintetico" va en
    # CN/O/OU, que NO tocan ese parseo.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, rfc),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{MARCA_SINTETICO} ({rfc})"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CSD SINTETICO CFDI-AES (NO SAT)"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "scripts/generar_csd_sintetico.py"),
    ])

    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)                       # autofirmado: issuer == subject
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=5))   # margen por reloj
        .not_valid_after(ahora + timedelta(days=365 * ANIOS_VIGENCIA))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key=key, algorithm=hashes.SHA256())
    )

    password = secrets.token_urlsafe(18)   # aleatoria, NUNCA un valor fijo

    cert_der = cert.public_bytes(serialization.Encoding.DER)
    key_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )

    os.makedirs(out_dir, exist_ok=True)
    # el propio directorio de salida se auto-ignora: contiene material de
    # llave privada (sintetico) y passwords, nunca debe entrar a git.
    gitignore_path = os.path.join(out_dir, ".gitignore")
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("# CSD sinteticos + passwords - NO versionar\n*\n")

    cer_path = os.path.join(out_dir, f"{rfc}.cer")
    key_path = os.path.join(out_dir, f"{rfc}.key")
    pw_path = os.path.join(out_dir, f"{rfc}_password.txt")
    with open(cer_path, "wb") as f:
        f.write(cert_der)
    with open(key_path, "wb") as f:
        f.write(key_der)
    with open(pw_path, "w", encoding="utf-8") as f:
        f.write(
            f"{password}\n\n"
            f"# password del CSD SINTETICO {rfc}\n"
            f"# archivo SEPARADO del .key a proposito - NO es una credencial real.\n"
        )

    return {
        "rfc": rfc,
        "tipo": tipo,
        "cer": cer_path,
        "key": key_path,
        "password_file": pw_path,
        "password": password,
        "cert_base64": base64.b64encode(cert_der).decode(),
        "key_base64": base64.b64encode(key_der).decode(),
        "vigente_hasta": (ahora + timedelta(days=365 * ANIOS_VIGENCIA)).date().isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Genera N CSD SINTETICOS (autofirmados, RFC inventado) para pruebas. NO validos para timbrar.",
    )
    ap.add_argument("n", nargs="?", type=int, default=1, help="cuantos CSD generar (default 1)")
    ap.add_argument("--tipo", choices=["moral", "fisica", "alterna"], default="alterna",
                    help="tipo de RFC: moral (12), fisica (13), o alterna entre ambos (default)")
    ap.add_argument("--prefijo", default="SIN",
                    help="primeras letras del RFC (default 'SIN' de sintetico)")
    ap.add_argument("--out", default="./csd_sintetico_out",
                    help="directorio de salida (default ./csd_sintetico_out)")
    args = ap.parse_args()

    if args.n < 1:
        print("n debe ser >= 1", file=sys.stderr)
        sys.exit(2)

    print("=" * 70)
    print("  GENERANDO CSD SINTETICOS - NO VALIDOS PARA TIMBRADO REAL")
    print("=" * 70)

    ya_usados: set = set()
    generados = []
    for i in range(args.n):
        if args.tipo == "alterna":
            tipo = "moral" if i % 2 == 0 else "fisica"
        else:
            tipo = args.tipo
        info = generar_uno(tipo, args.prefijo, args.out, ya_usados)
        generados.append(info)
        print(f"\n[{i + 1}/{args.n}] RFC sintetico: {info['rfc']}  ({info['tipo']}, vigente hasta {info['vigente_hasta']})")
        print(f"    cert : {info['cer']}")
        print(f"    key  : {info['key']}  (DER, PKCS#8, cifrada)")
        print(f"    pass : {info['password_file']}")

    print("\n" + "-" * 70)
    print("Para dar de alta un emisor de prueba con uno de estos CSD (via gateway):")
    print("  POST /admin/emisores  (Authorization: Bearer <jwt>)")
    print('  body: {"razon_social":"...","rfc":"<RFC>","regimen_fiscal":"601",')
    print('         "codigo_postal":"00000","csd_cert_base64":"<b64 del .cer>",')
    print('         "csd_key_base64":"<b64 del .key>","csd_password":"<password>"}')
    print("-" * 70)
    print("RECORDATORIO: estos archivos contienen material de llave privada (sintetica)")
    print(f"y una password. NO los subas a git. Se escribio {os.path.join(args.out, '.gitignore')}")
    print("con '*' para que el directorio de salida se auto-ignore; ademas *.cer y *.key")
    print("ya estan ignorados globalmente en el repo.")


if __name__ == "__main__":
    main()
