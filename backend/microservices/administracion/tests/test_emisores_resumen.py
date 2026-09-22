"""
Tests del dashboard multi-emisor (vigencia CSD + concentracion de
facturas por emisor):
  - csd_rfc.extraer_vigencia_hasta_de_certificado() - parseo x509 puro.
  - crear_emisor()/actualizar_emisor() poblando vigencia_csd_hasta al vuelo.
  - GET /admin/negocios/{id}/emisores-resumen (obtener_emisores_resumen).

Certificados sinteticos generados EN el test (mismo criterio que
scripts/generar_csd_sintetico.py, pero inline para controlar la fecha de
vencimiento exacta que cada caso necesita) - autofirmados, RFC inventado,
sin validez fiscal, solo para ejercitar el parseo x509 real (no un mock
del parseo en si: cryptography SI corre sobre bytes DER reales).

DB real para crear_emisor/actualizar_emisor/obtener_emisores_resumen
(mismo patron que test_listar_emisores_orden.py - la logica interesante
es lo que realmente queda en Postgres), httpx mockeado para las llamadas
a facturacion (mismo patron que test_resumen_negocio.py).
"""
import base64
from datetime import date, datetime, timedelta, timezone

import httpx
import main
import pytest
import pytest_asyncio
from certs_reales_sat import CSD_REALES, FIEL_REALES
from certs_reales_sat import PASSWORD as PASSWORD_CERTS_REALES
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from csd_rfc import extraer_vigencia_hasta_de_certificado
from database import AsyncSessionLocal, Efirma, Emisor, Negocio, engine
from fastapi import HTTPException
from main import (
    EmisorCreate,
    actualizar_emisor,
    crear_emisor,
    obtener_emisores_resumen,
)
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _pool_por_test():
    await engine.dispose()
    yield


def _cert_sintetico_der(*, rfc: str, dias_vigencia: int, otro_rfc_representante: str = "TEST010101TS1") -> bytes:
    """Certificado x509 autofirmado, DER, con x500UniqueIdentifier
    "RFC / repr" (mismo campo que csd_rfc.py lee) y not_valid_after =
    hoy + dias_vigencia (puede ser negativo, para simular uno YA vencido)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "TEST CSD SINTETICO"),
        x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, f"{rfc} / {otro_rfc_representante}"),
    ])
    ahora = datetime.now(timezone.utc)
    vence = ahora + timedelta(days=dias_vigencia)
    # not_valid_before SIEMPRE 1 dia antes de vence, sin importar si
    # dias_vigencia es negativo (cert ya vencido) - cryptography exige
    # not_valid_before < not_valid_after o lanza ValueError al construir.
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(vence - timedelta(days=1))
        .not_valid_after(vence)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.DER)


def _cert_sintetico_base64(**kwargs) -> str:
    return base64.b64encode(_cert_sintetico_der(**kwargs)).decode()


# Password fija SOLO para este helper (par cert/key sintetico, sin validez
# fiscal) - a diferencia de generar_csd_sintetico.py (password aleatoria por
# archivo en disco), aqui no hay archivo que proteger: el par vive en memoria
# durante el test y se descarta al terminar.
_PASSWORD_CSD_SINTETICO = "test-password-csd-sintetico"


def _cert_y_key_sinteticos_csd(*, rfc: str, dias_vigencia: int, otro_rfc_representante: str = "TEST010101TS1") -> tuple[str, str, str]:
    """Como _cert_sintetico_der, pero con 2 diferencias necesarias desde
    zg7DuHM: (1) el KeyUsage queda con el perfil REAL de un CSD (solo
    digital_signature+content_commitment, sin ExtendedKeyUsage) - el mismo
    patron confirmado empiricamente sobre los 9 certificados reales de
    certs_reales_sat.py - para que _validar_certificado_es_csd() lo acepte;
    (2) devuelve TAMBIEN la llave privada real (DER, PKCS8, cifrada), no la
    descarta, para que _validar_cert_key_pairing() tenga con que emparejar.

    _cert_sintetico_der() (sin extensiones, llave descartada) se deja
    intacto para los demas tests de este archivo que no pasan por
    crear_emisor/actualizar_emisor (construyen el Emisor directo en BD) - no
    les afecta la nueva validacion y no necesitan este costo extra.

    Devuelve (cert_base64, key_base64, password)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "TEST CSD SINTETICO (perfil CSD real)"),
        x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, f"{rfc} / {otro_rfc_representante}"),
    ])
    ahora = datetime.now(timezone.utc)
    vence = ahora + timedelta(days=dias_vigencia)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(vence - timedelta(days=1))
        .not_valid_after(vence)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    cert_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
    key_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(_PASSWORD_CSD_SINTETICO.encode()),
    )
    key_b64 = base64.b64encode(key_der).decode()
    return cert_b64, key_b64, _PASSWORD_CSD_SINTETICO


# ─── extraer_vigencia_hasta_de_certificado (parseo puro) ────────────────────

def test_extrae_vigencia_hasta_de_cert_valido():
    cert_bytes = _cert_sintetico_der(rfc="AAAA800101AA1", dias_vigencia=100)
    vigencia = extraer_vigencia_hasta_de_certificado(cert_bytes)
    esperado = date.today() + timedelta(days=100)
    # +-1 dia de margen por el corte a medianoche UTC vs hora local del runner.
    assert abs((vigencia - esperado).days) <= 1


def test_cert_ya_vencido_igual_extrae_la_fecha_pasada():
    """El parseo NO rechaza un cert vencido - solo lee el campo. Rechazar
    (o no) es decision del llamador (ver 8. en _validar_material_efirma,
    que SI rechaza para e.firma; el CSD del dashboard no rechaza nada,
    solo informa vigencia_csd_hasta en el pasado)."""
    cert_bytes = _cert_sintetico_der(rfc="AAAA800101AA1", dias_vigencia=-500)
    vigencia = extraer_vigencia_hasta_de_certificado(cert_bytes)
    assert vigencia < date.today()


def test_bytes_corruptos_lanza_valueerror_no_crashea():
    with pytest.raises(ValueError):
        extraer_vigencia_hasta_de_certificado(b"esto-no-es-un-certificado-der-valido" * 5)


def test_bytes_vacios_lanza_valueerror():
    with pytest.raises(ValueError):
        extraer_vigencia_hasta_de_certificado(b"")


# ─── crear_emisor / actualizar_emisor poblando vigencia al vuelo ───────────

@pytest.fixture
async def negocio_temporal():
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST emisores-resumen", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
        await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
        await session.commit()


async def test_alta_de_emisor_puebla_vigencia_automaticamente(negocio_temporal):
    rfc = "BBBB850101BB1"
    # zg7DuHM: crear_emisor ahora valida tipo CSD + par cert<->key, asi que
    # ya no basta un cert sintetico sin extensiones + una key "dummy" (ver
    # _cert_y_key_sinteticos_csd) - el par debe ser real y de perfil CSD.
    cert_b64, key_b64, password = _cert_y_key_sinteticos_csd(rfc=rfc, dias_vigencia=365)
    body = EmisorCreate(
        razon_social="TEST alta con vigencia",
        rfc=rfc,
        regimen_fiscal="601",
        codigo_postal="00000",
        csd_cert_base64=cert_b64,
        csd_key_base64=key_b64,
        csd_password=password,
    )
    async with AsyncSessionLocal() as db:
        out = await crear_emisor(
            emisor=body, db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
        )
    assert out.rfc == rfc

    async with AsyncSessionLocal() as db:
        fila = (await db.execute(select(Emisor).where(Emisor.rfc == rfc))).scalar_one()
    esperado = date.today() + timedelta(days=365)
    assert fila.vigencia_csd_hasta is not None
    assert abs((fila.vigencia_csd_hasta - esperado).days) <= 1


async def test_reemplazo_de_csd_repuebla_vigencia(negocio_temporal):
    rfc = "CCCC850101CC1"
    # zg7DuHM: mismo motivo que test_alta_de_emisor_puebla_vigencia_automaticamente
    # arriba - crear_emisor Y actualizar_emisor ahora exigen par real de
    # perfil CSD, no "dummy".
    cert_viejo, key_viejo, password_viejo = _cert_y_key_sinteticos_csd(rfc=rfc, dias_vigencia=10)
    async with AsyncSessionLocal() as db:
        await crear_emisor(
            emisor=EmisorCreate(
                razon_social="TEST reemplazo", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_viejo, csd_key_base64=key_viejo, csd_password=password_viejo,
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
        )

    cert_nuevo, key_nuevo, password_nuevo = _cert_y_key_sinteticos_csd(rfc=rfc, dias_vigencia=800)
    async with AsyncSessionLocal() as db:
        out = await actualizar_emisor(
            rfc=rfc,
            emisor=EmisorCreate(
                razon_social="TEST reemplazo", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_nuevo, csd_key_base64=key_nuevo, csd_password=password_nuevo,
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    assert out.rfc == rfc

    async with AsyncSessionLocal() as db:
        fila = (await db.execute(select(Emisor).where(Emisor.rfc == rfc))).scalar_one()
    esperado = date.today() + timedelta(days=800)
    # Debe reflejar el cert NUEVO (800 dias), no el viejo (10 dias).
    assert abs((fila.vigencia_csd_hasta - esperado).days) <= 1


# ─── GET /admin/negocios/{id}/emisores-resumen ──────────────────────────────

class _FakeHttpResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class _FakeHttpClient:
    """A diferencia de test_resumen_negocio.py (una sola respuesta fija),
    aqui el endpoint hace UN GET por emisor - la respuesta depende del
    emisor_rfc en los params, para probar que cada emisor recibe SU
    propio facturas_mes, no uno compartido por error."""
    def __init__(self, respuestas_por_rfc):
        self._respuestas = respuestas_por_rfc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        rfc = (params or {}).get("emisor_rfc")
        return self._respuestas.get(rfc, _FakeHttpResp(status_code=500))


def _patch_facturacion_por_rfc(monkeypatch, respuestas_por_rfc):
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda *a, **k: _FakeHttpClient(respuestas_por_rfc),
    )


def _efirma_dummy(*, rfc_titular, negocio_id, vigencia_hasta, estado="Activo"):
    return Efirma(
        rfc_titular=rfc_titular, negocio_id=negocio_id,
        cert_base64="dummy", key_base64_cifrado="dummy", password_cifrado="dummy",
        vigencia_desde=date(2024, 1, 1), vigencia_hasta=vigencia_hasta, estado=estado,
    )


@pytest.fixture
async def negocio_con_2_emisores():
    """Simula el caso real (negocio 11, Pedro): 2 emisores Activos, uno
    con vigencia poblada y otro sin ella (certificado no parseable en su
    momento) - para probar que dias_restantes sale None sin tronar.
    DDDD850101DD1 ademas tiene una e.firma REAL con vigencia DISTINTA a su
    CSD (caso sano) - EEEE850101EE1 no tiene ninguna e.firma registrada."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST multi-emisor", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        e1 = Emisor(
            negocio_id=negocio_id, rfc="DDDD850101DD1", razon_social="Emisor uno",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=date.today() + timedelta(days=15),  # urgente
        )
        e2 = Emisor(
            negocio_id=negocio_id, rfc="EEEE850101EE1", razon_social="Emisor dos",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=None,  # cert nunca parseable, como GWT010101AA1
        )
        e3_inactivo = Emisor(
            negocio_id=negocio_id, rfc="FFFF850101FF1", razon_social="Emisor inactivo",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Inactivo", vigencia_csd_hasta=date.today() + timedelta(days=500),
        )
        session.add_all([e1, e2, e3_inactivo])

        # e.firma de DDDD850101DD1 - vigencia DISTINTA a su CSD (700 dias
        # vs 15 del CSD) - caso sano, sin confusion de archivos.
        session.add(_efirma_dummy(
            rfc_titular="DDDD850101DD1", negocio_id=negocio_id,
            vigencia_hasta=date.today() + timedelta(days=700),
        ))
        # e.firma vieja/reemplazada de DDDD850101DD1 (estado != Activo) -
        # NO debe contarse, prueba que el filtro por estado="Activo" es real.
        session.add(_efirma_dummy(
            rfc_titular="DDDD850101DD1", negocio_id=negocio_id,
            vigencia_hasta=date.today() + timedelta(days=1), estado="Reemplazada",
        ))
        await session.commit()
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
        await session.execute(Efirma.__table__.delete().where(Efirma.negocio_id == negocio_id))
        await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
        await session.commit()


async def test_emisores_resumen_solo_activos_con_facturas_y_dias_por_emisor(monkeypatch, negocio_con_2_emisores):
    _patch_facturacion_por_rfc(monkeypatch, {
        "DDDD850101DD1": _FakeHttpResp(json_data={"facturas_mes": 7, "canceladas_mes": 0}),
        "EEEE850101EE1": _FakeHttpResp(json_data={"facturas_mes": 3, "canceladas_mes": 1}),
    })
    async with AsyncSessionLocal() as db:
        out = await obtener_emisores_resumen(
            negocio_id=negocio_con_2_emisores, db=db, x_negocio_id=str(negocio_con_2_emisores), x_usuario_rfc=None,
        )

    # Solo los 2 Activos - el Inactivo (FFFF...) NO debe aparecer.
    assert len(out) == 2
    por_rfc = {item.rfc: item for item in out}
    assert set(por_rfc.keys()) == {"DDDD850101DD1", "EEEE850101EE1"}

    d1 = por_rfc["DDDD850101DD1"]
    assert d1.facturas_mes == 7
    assert d1.dias_restantes == 15
    # e.firma con vigencia DISTINTA al CSD (700 dias vs 15) - la fila
    # "Reemplazada" (1 dia) NO debe colarse, solo la "Activo".
    assert d1.dias_restantes_efirma == 700
    assert d1.vigencia_efirma_hasta == date.today() + timedelta(days=700)
    # csd_cert_base64="dummy" no es base64 valido -> la comparacion de hash
    # degrada a False (nunca lanza) - caso "no-match normal".
    assert d1.csd_es_efirma_duplicada is False

    d2 = por_rfc["EEEE850101EE1"]
    assert d2.facturas_mes == 3
    assert d2.vigencia_csd_hasta is None
    assert d2.dias_restantes is None  # nunca inventado a partir de vigencia None
    # Sin ninguna e.firma registrada para este RFC - None, no error.
    assert d2.vigencia_efirma_hasta is None
    assert d2.dias_restantes_efirma is None
    assert d2.csd_es_efirma_duplicada is False  # sin e.firma, no se evalua nada


async def test_emisores_resumen_alerta_csd_y_efirma_con_la_misma_vigencia_pero_hash_distinto(monkeypatch):
    """Caso sintetico deliberado (el que mas riesgo tiene de romperse si la
    logica de las dos ramas colapsa): CSD y e.firma con la MISMA fecha de
    vigencia por COINCIDENCIA (mismo tramite el mismo dia, certificados
    genuinamente DISTINTOS - dos llaves RSA generadas por separado, hash
    distinto). Debe seguir el comportamiento de "misma fecha" (banner
    original en el frontend) - vigencia_csd_hasta NO se anula,
    csd_es_efirma_duplicada debe ser False. Esto es lo opuesto al caso de
    hash identico (ver test siguiente) - ambos casos son mutuamente
    excluyentes por construccion."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST alerta CSD=FIEL hash distinto", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        # Dos certificados sinteticos INDEPENDIENTES (llaves RSA distintas -
        # nunca coinciden en hash) generados con el mismo dias_vigencia, asi
        # que su fecha (.date(), sin hora) coincide en la practica.
        cert_csd_b64 = _cert_sintetico_base64(rfc="GGGG850101GG1", dias_vigencia=700)
        cert_efirma_b64 = _cert_sintetico_base64(rfc="GGGG850101GG1", dias_vigencia=700)
        assert cert_csd_b64 != cert_efirma_b64  # confirma que son genuinamente distintos

        misma_fecha = extraer_vigencia_hasta_de_certificado(base64.b64decode(cert_csd_b64))
        assert misma_fecha == extraer_vigencia_hasta_de_certificado(base64.b64decode(cert_efirma_b64))

        emisor = Emisor(
            negocio_id=negocio_id, rfc="GGGG850101GG1", razon_social="Emisor confundido",
            regimen_fiscal="625", codigo_postal="00000",
            csd_cert_base64=cert_csd_b64, csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=misma_fecha,
        )
        session.add(emisor)
        efirma = _efirma_dummy(rfc_titular="GGGG850101GG1", negocio_id=negocio_id, vigencia_hasta=misma_fecha)
        efirma.cert_base64 = cert_efirma_b64
        session.add(efirma)
        await session.commit()

    try:
        async with AsyncSessionLocal() as db:
            out = await obtener_emisores_resumen(negocio_id=negocio_id, db=db, x_negocio_id=str(negocio_id), x_usuario_rfc=None)
        assert len(out) == 1
        item = out[0]
        assert item.vigencia_csd_hasta == misma_fecha  # NO se anula
        assert item.vigencia_efirma_hasta == misma_fecha
        assert item.vigencia_csd_hasta == item.vigencia_efirma_hasta  # la señal del banner original
        assert item.csd_es_efirma_duplicada is False  # hash distinto -> NO es el caso de archivo duplicado
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
            await session.execute(Efirma.__table__.delete().where(Efirma.negocio_id == negocio_id))
            await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
            await session.commit()


async def test_emisores_resumen_hash_identico_anula_vigencia_csd_y_marca_duplicada(monkeypatch):
    """Caso real (RAHP7112093H0, 15-sep-2026): el CSD registrado es
    BYTE-POR-BYTE el mismo archivo que la e.firma. A diferencia del test
    anterior (misma fecha, hash distinto), aqui vigencia_csd_hasta SI debe
    anularse a None (aunque en la fila de Emisor haya una fecha real
    parseable guardada) y csd_es_efirma_duplicada debe ser True."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST hash identico", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        # UN SOLO certificado, usado para AMBOS campos - el caso real.
        cert_b64 = _cert_sintetico_base64(rfc="HHHH850101HH1", dias_vigencia=365)
        fecha_real = extraer_vigencia_hasta_de_certificado(base64.b64decode(cert_b64))

        emisor = Emisor(
            negocio_id=negocio_id, rfc="HHHH850101HH1", razon_social="Emisor con archivo duplicado",
            regimen_fiscal="625", codigo_postal="00000",
            csd_cert_base64=cert_b64, csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=fecha_real,  # fecha REAL, parseable - igual se anula
        )
        session.add(emisor)
        efirma = _efirma_dummy(rfc_titular="HHHH850101HH1", negocio_id=negocio_id, vigencia_hasta=fecha_real)
        efirma.cert_base64 = cert_b64  # el MISMO archivo
        session.add(efirma)
        await session.commit()

    try:
        async with AsyncSessionLocal() as db:
            out = await obtener_emisores_resumen(negocio_id=negocio_id, db=db, x_negocio_id=str(negocio_id), x_usuario_rfc=None)
        assert len(out) == 1
        item = out[0]
        assert item.csd_es_efirma_duplicada is True
        assert item.vigencia_csd_hasta is None  # anulado, aunque el CSD tuviera fecha real parseable
        assert item.dias_restantes is None
        assert item.vigencia_efirma_hasta == fecha_real  # la e.firma SI conserva su vigencia real
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
            await session.execute(Efirma.__table__.delete().where(Efirma.negocio_id == negocio_id))
            await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
            await session.commit()


async def test_emisores_resumen_certificado_corrupto_no_truena_al_comparar_hash(monkeypatch):
    """Certificado de Emisor corrupto (ej. GWT010101AA1 real) con una
    e.firma real y valida registrada para el mismo RFC - la comparacion de
    hash debe degradar a False (no se pudo confirmar que sean el mismo
    archivo) sin tronar el endpoint completo."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST cert corrupto vs efirma", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        cert_efirma_b64 = _cert_sintetico_base64(rfc="JJJJ850101JJ1", dias_vigencia=400)

        emisor = Emisor(
            negocio_id=negocio_id, rfc="JJJJ850101JJ1", razon_social="Emisor con CSD corrupto",
            regimen_fiscal="625", codigo_postal="00000",
            csd_cert_base64="esto-no-es-base64-valido-ni-cerca==", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=None,  # ya nunca se pudo parsear, ver backfill
        )
        session.add(emisor)
        efirma = _efirma_dummy(rfc_titular="JJJJ850101JJ1", negocio_id=negocio_id, vigencia_hasta=date.today() + timedelta(days=400))
        efirma.cert_base64 = cert_efirma_b64
        session.add(efirma)
        await session.commit()

    try:
        async with AsyncSessionLocal() as db:
            out = await obtener_emisores_resumen(negocio_id=negocio_id, db=db, x_negocio_id=str(negocio_id), x_usuario_rfc=None)
        assert len(out) == 1
        item = out[0]
        assert item.csd_es_efirma_duplicada is False  # degradado, nunca lanzo
        assert item.vigencia_csd_hasta is None  # ya era None desde antes, no relacionado al hash
        assert item.vigencia_efirma_hasta is not None  # la e.firma en si sigue leyendose bien
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
            await session.execute(Efirma.__table__.delete().where(Efirma.negocio_id == negocio_id))
            await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
            await session.commit()


async def test_emisores_resumen_degrada_facturas_mes_si_facturacion_cae(monkeypatch, negocio_con_2_emisores):
    _patch_facturacion_por_rfc(monkeypatch, {})  # sin entradas -> 500 para ambos rfc
    async with AsyncSessionLocal() as db:
        out = await obtener_emisores_resumen(
            negocio_id=negocio_con_2_emisores, db=db, x_negocio_id=str(negocio_con_2_emisores), x_usuario_rfc=None,
        )
    assert len(out) == 2
    assert all(item.facturas_mes is None for item in out)
    # vigencia/dias_restantes NO dependen de facturacion - siguen presentes.
    por_rfc = {item.rfc: item for item in out}
    assert por_rfc["DDDD850101DD1"].dias_restantes == 15


async def test_negocio_ajeno_es_404_no_403(negocio_con_2_emisores):
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await obtener_emisores_resumen(
                negocio_id=negocio_con_2_emisores, db=db, x_negocio_id="999999", x_usuario_rfc=None,
            )
    assert exc.value.status_code == 404


async def test_sin_efirma_nunca_compara_hash_y_no_toca_vigencia(monkeypatch):
    """Emisor con CSD real (vigencia parseable) y SIN ninguna e.firma
    registrada para su RFC - _csd_es_copia_de_efirma NUNCA debe
    ejecutarse (nada que comparar sin una e.firma), y vigencia_csd_hasta
    debe salir intacta, no anulada.

    A diferencia de otros tests que solo verifican el RESULTADO final,
    este monkeypatchea _csd_es_copia_de_efirma para que lance si alguna
    vez se llega a invocar - prueba el "nunca se ejecuta", no solo que el
    resultado final coincida por casualidad."""
    def _fallar_si_se_llama(emisor, efirma):
        raise AssertionError("_csd_es_copia_de_efirma no debia llamarse sin e.firma registrada")
    monkeypatch.setattr(main, "_csd_es_copia_de_efirma", _fallar_si_se_llama)

    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST sin efirma registrada", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        fecha_real = date.today() + timedelta(days=200)
        emisor = Emisor(
            negocio_id=negocio_id, rfc="LLLL850101LL1", razon_social="Emisor sin e.firma",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=fecha_real,
        )
        session.add(emisor)
        # Deliberadamente SIN insertar ninguna fila en Efirma para este RFC.
        await session.commit()

    try:
        _patch_facturacion_por_rfc(monkeypatch, {
            "LLLL850101LL1": _FakeHttpResp(json_data={"facturas_mes": 5, "canceladas_mes": 0}),
        })
        async with AsyncSessionLocal() as db:
            out = await obtener_emisores_resumen(negocio_id=negocio_id, db=db, x_negocio_id=str(negocio_id), x_usuario_rfc=None)
        assert len(out) == 1
        item = out[0]
        assert item.vigencia_csd_hasta == fecha_real  # intacta, nunca anulada
        assert item.dias_restantes == 200
        assert item.vigencia_efirma_hasta is None
        assert item.dias_restantes_efirma is None
        assert item.csd_es_efirma_duplicada is False
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
            await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
            await session.commit()


# ─── Orden: emisor del propio usuario siempre primero (commits         ──
# ─── 299438131a81.../7974dd66945e..., ahora tambien en emisores-resumen) ─

async def test_emisores_resumen_ordena_el_emisor_propio_primero(monkeypatch):
    """3 emisores Activos (ninguno Inactivo - el desempate por estado no
    puede ser lo que decida el orden aqui) en el mismo negocio. El emisor
    del propio usuario autenticado NO es ni el mas reciente (eso lo es
    OOOO...) ni el unico Activo (los 3 lo son) - si el test pasara "por
    casualidad" con el orden natural de Postgres, este caso especifico lo
    desenmascara: MMMM es el mas viejo, NNNN (el propio usuario) es el de
    en medio, OOOO es el mas nuevo. Antes de este cambio, esta query no
    tenia ORDER BY en absoluto."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST orden propio primero", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        base = datetime(2026, 1, 1, 12, 0, 0)
        emisor_viejo = Emisor(
            negocio_id=negocio_id, rfc="MMMM850101MM1", razon_social="El mas viejo",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", created_at=base,
        )
        emisor_propio = Emisor(
            negocio_id=negocio_id, rfc="NNNN850101NN1", razon_social="El del usuario logueado",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", created_at=base + timedelta(days=10),  # ni el mas viejo ni el mas nuevo
        )
        emisor_nuevo = Emisor(
            negocio_id=negocio_id, rfc="OOOO850101OO1", razon_social="El mas nuevo",
            regimen_fiscal="601", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", created_at=base + timedelta(days=20),
        )
        session.add_all([emisor_viejo, emisor_propio, emisor_nuevo])
        await session.commit()

    try:
        _patch_facturacion_por_rfc(monkeypatch, {
            "MMMM850101MM1": _FakeHttpResp(json_data={"facturas_mes": 1, "canceladas_mes": 0}),
            "NNNN850101NN1": _FakeHttpResp(json_data={"facturas_mes": 1, "canceladas_mes": 0}),
            "OOOO850101OO1": _FakeHttpResp(json_data={"facturas_mes": 1, "canceladas_mes": 0}),
        })
        async with AsyncSessionLocal() as db:
            out = await obtener_emisores_resumen(
                negocio_id=negocio_id, db=db, x_negocio_id=str(negocio_id), x_usuario_rfc="NNNN850101NN1",
            )
        assert len(out) == 3
        # El propio usuario SIEMPRE primero, sin importar fecha/estado.
        assert out[0].rfc == "NNNN850101NN1"
        # Desempate por created_at desc entre los otros 2 (regla 3, sin cambios).
        assert out[1].rfc == "OOOO850101OO1"  # el mas nuevo de los que quedan
        assert out[2].rfc == "MMMM850101MM1"  # el mas viejo
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
            await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
            await session.commit()




# ─── zg7DuHM: CSD real vs e.firma (FIEL) real + cert<->key pairing ─────────
#
# Usa los 9 certificados REALES de prueba del SAT tal cual viven en
# certs_test/ (embebidos en certs_reales_sat.py, ver docstring ahi de por
# que no se leen de disco en tiempo de test) - instruccion explicita de
# zg7DuHM Cambio 4: usarlos directo, no generar nada sintetico para este
# bloque.
#
# _validar_certificado_es_csd/_validar_cert_key_pairing se prueban DIRECTO
# como funciones puras sobre los 9 certificados, sin pasar por
# crear_emisor/actualizar_emisor: 3 de los 5 RFC de CSD_REALES
# (EKU9003173C9, IIA040805DZ4, IVD920810GU2) YA tienen un Emisor real
# registrado en la BD de este entorno (datos reales de sesiones de dev
# previas - uno de ellos es justo RAHP7112093H0/Pedro, ver Cambio 5) -
# crear_emisor() valida unicidad de RFC GLOBAL (main.py, no por negocio),
# asi que insertar un emisor nuevo con esos RFC chocaria (409) con datos
# reales sin relacion con lo que este test quiere probar. Confirmado
# empiricamente (SELECT directo a la BD, 21 sep 2026) antes de escribir
# esto - no es una suposicion. Las funciones puras no tocan la BD, asi que
# cubren los 9 certificados sin este problema.
#
# La integracion end-to-end (que crear_emisor/actualizar_emisor SI llamen a
# estas funciones, con negocio/BD real) se prueba aparte, mas abajo, solo
# con los 2 RFC de CSD_REALES/FIEL_REALES que SI estan libres en este
# entorno (MISC491214B86, XIQB891116QE4) - confirmado antes de escribir
# este test que ningun Emisor real usa esos 2 RFC.

def _cert_real(cert_b64: str) -> x509.Certificate:
    return x509.load_der_x509_certificate(base64.b64decode(cert_b64))


def _real_por_rfc(lista, rfc):
    return next(r for r in lista if r[0] == rfc)


@pytest.mark.parametrize("rfc,tipo,cert_b64,key_b64", CSD_REALES, ids=[r[0] for r in CSD_REALES])
def test_validar_certificado_es_csd_acepta_los_5_csd_reales(rfc, tipo, cert_b64, key_b64):
    from main import _validar_certificado_es_csd
    _validar_certificado_es_csd(_cert_real(cert_b64))  # no debe lanzar nada


@pytest.mark.parametrize("rfc,tipo,cert_b64,key_b64", FIEL_REALES, ids=[r[0] for r in FIEL_REALES])
def test_validar_certificado_es_csd_rechaza_las_4_fiel_reales(rfc, tipo, cert_b64, key_b64):
    from main import _validar_certificado_es_csd
    with pytest.raises(HTTPException) as exc_info:
        _validar_certificado_es_csd(_cert_real(cert_b64))
    assert exc_info.value.status_code == 422
    assert "e.firma (FIEL)" in exc_info.value.detail
    assert "no a un CSD" in exc_info.value.detail


def test_validar_certificado_es_csd_sin_keyusage_no_dice_que_es_fiel():
    """Ajuste de seguimiento zg7DuHM (21 sep 2026): un certificado sin
    KeyUsage (ni ExtendedKeyUsage) NO confirma que sea una e.firma - solo
    confirma que le falta una extension basica esperada. Antes de este
    ajuste, este caso reusaba por error el mismo mensaje de "es una
    e.firma (FIEL)" que el check de ExtendedKeyUsage. _cert_sintetico_der
    (arriba, sin ninguna extension) es exactamente este caso - lo usan
    muchos otros tests de este archivo, pero ninguno pasaba antes por
    _validar_certificado_es_csd (construyen el Emisor directo en BD), asi
    que esta rama no tenia cobertura hasta este test."""
    from main import _validar_certificado_es_csd
    cert_bytes = _cert_sintetico_der(rfc="ZZZZ800101ZZ1", dias_vigencia=365)
    cert = x509.load_der_x509_certificate(cert_bytes)
    with pytest.raises(HTTPException) as exc_info:
        _validar_certificado_es_csd(cert)
    assert exc_info.value.status_code == 422
    assert "e.firma (FIEL)" not in exc_info.value.detail
    assert "falta" in exc_info.value.detail and "KeyUsage" in exc_info.value.detail


def test_validar_cert_key_pairing_acepta_par_real_correcto():
    from main import _validar_cert_key_pairing
    _rfc, _tipo, cert_b64, key_b64 = CSD_REALES[0]
    cert = _cert_real(cert_b64)
    key_bytes = base64.b64decode(key_b64)
    _validar_cert_key_pairing(cert, key_bytes, PASSWORD_CERTS_REALES)  # no debe lanzar nada


def test_validar_cert_key_pairing_rechaza_par_real_cruzado():
    """cert de un CSD real + key de OTRO CSD real (ambos individualmente
    validos, pero NO son el mismo par) - debe rechazarlo por mismatch, no
    por alguna otra razon incidental."""
    from main import _validar_cert_key_pairing
    _rfc_a, _tipo_a, cert_a_b64, _key_a_b64 = CSD_REALES[0]
    _rfc_b, _tipo_b, _cert_b_b64, key_b_b64 = CSD_REALES[1]
    cert_a = _cert_real(cert_a_b64)
    key_b_bytes = base64.b64decode(key_b_b64)
    with pytest.raises(HTTPException) as exc_info:
        _validar_cert_key_pairing(cert_a, key_b_bytes, PASSWORD_CERTS_REALES)
    assert exc_info.value.status_code == 422
    assert "no corresponde al certificado" in exc_info.value.detail


# ─── Integracion end-to-end (crear_emisor/actualizar_emisor reales) ────────
# Solo con los 2 RFC libres en este entorno (ver nota arriba) - confirma que
# el wiring dentro del endpoint real es correcto, no solo las funciones puras.

async def test_csd_real_es_aceptado_por_crear_emisor_end_to_end(negocio_temporal):
    rfc, _tipo, cert_b64, key_b64 = _real_por_rfc(CSD_REALES, "XIQB891116QE4")
    async with AsyncSessionLocal() as db:
        out = await crear_emisor(
            emisor=EmisorCreate(
                razon_social=f"TEST CSD real {rfc}", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_b64, csd_key_base64=key_b64, csd_password=PASSWORD_CERTS_REALES,
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
        )
    assert out.rfc == rfc


async def test_fiel_real_es_rechazada_por_crear_emisor_end_to_end(negocio_temporal):
    """Caso real que motivo zg7DuHM (RAHP7112093H0/Pedro subio su e.firma
    en vez de su CSD y, antes de este fix, el backend la acepto sin
    avisar) - reproducido aqui end-to-end con un RFC libre en este entorno."""
    rfc, _tipo, cert_b64, key_b64 = _real_por_rfc(FIEL_REALES, "XIQB891116QE4")
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await crear_emisor(
                emisor=EmisorCreate(
                    razon_social=f"TEST FIEL real {rfc}", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                    csd_cert_base64=cert_b64, csd_key_base64=key_b64, csd_password=PASSWORD_CERTS_REALES,
                ),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
            )
    assert exc_info.value.status_code == 422
    assert "e.firma (FIEL)" in exc_info.value.detail
    async with AsyncSessionLocal() as db:
        fila = (await db.execute(select(Emisor).where(Emisor.rfc == rfc))).scalar_one_or_none()
    assert fila is None


async def test_csd_real_es_aceptado_por_actualizar_emisor_end_to_end(negocio_temporal):
    rfc, _tipo, cert_b64, key_b64 = _real_por_rfc(CSD_REALES, "MISC491214B86")
    async with AsyncSessionLocal() as db:
        await crear_emisor(
            emisor=EmisorCreate(
                razon_social="TEST alta previa", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_b64, csd_key_base64=key_b64, csd_password=PASSWORD_CERTS_REALES,
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
        )
    async with AsyncSessionLocal() as db:
        out = await actualizar_emisor(
            rfc=rfc,
            emisor=EmisorCreate(
                razon_social="TEST rotacion CSD real", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_b64, csd_key_base64=key_b64, csd_password=PASSWORD_CERTS_REALES,
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    assert out.rfc == rfc


async def test_fiel_real_es_rechazada_por_actualizar_emisor_end_to_end(negocio_temporal):
    """Este es el endpoint EXACTO (PUT) donde ocurrio el caso real de
    zg7DuHM (Pedro/RAHP7112093H0)."""
    rfc_csd, _tipo, cert_csd_b64, key_csd_b64 = _real_por_rfc(CSD_REALES, "MISC491214B86")
    async with AsyncSessionLocal() as db:
        await crear_emisor(
            emisor=EmisorCreate(
                razon_social="TEST alta previa (CSD real)", rfc=rfc_csd, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_csd_b64, csd_key_base64=key_csd_b64, csd_password=PASSWORD_CERTS_REALES,
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
        )
    _rfc_fiel, _tipo_fiel, cert_fiel_b64, key_fiel_b64 = _real_por_rfc(FIEL_REALES, "MISC491214B86")
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await actualizar_emisor(
                rfc=rfc_csd,
                emisor=EmisorCreate(
                    razon_social="TEST rotacion con FIEL por error", rfc=rfc_csd, regimen_fiscal="601", codigo_postal="00000",
                    csd_cert_base64=cert_fiel_b64, csd_key_base64=key_fiel_b64, csd_password=PASSWORD_CERTS_REALES,
                ),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc_info.value.status_code == 422
    assert "e.firma (FIEL)" in exc_info.value.detail
    async with AsyncSessionLocal() as db:
        fila = (await db.execute(select(Emisor).where(Emisor.rfc == rfc_csd))).scalar_one()
    assert fila.csd_cert_base64 == cert_csd_b64


async def test_cert_key_cruzados_reales_es_rechazado_por_crear_emisor_end_to_end(negocio_temporal):
    """Mismatch real end-to-end: cert real de XIQB891116QE4 + llave real de
    MISC491214B86 (ambos RFC libres en este entorno)."""
    rfc_a, _tipo_a, cert_a_b64, _key_a_b64 = _real_por_rfc(CSD_REALES, "XIQB891116QE4")
    _rfc_b, _tipo_b, _cert_b_b64, key_b_b64 = _real_por_rfc(CSD_REALES, "MISC491214B86")
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await crear_emisor(
                emisor=EmisorCreate(
                    razon_social="TEST cert/key cruzados", rfc=rfc_a, regimen_fiscal="601", codigo_postal="00000",
                    csd_cert_base64=cert_a_b64, csd_key_base64=key_b_b64, csd_password=PASSWORD_CERTS_REALES,
                ),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
            )
    assert exc_info.value.status_code == 422
    assert "no corresponde al certificado" in exc_info.value.detail
    async with AsyncSessionLocal() as db:
        fila = (await db.execute(select(Emisor).where(Emisor.rfc == rfc_a))).scalar_one_or_none()
    assert fila is None
