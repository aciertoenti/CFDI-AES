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
    cert_b64 = _cert_sintetico_base64(rfc=rfc, dias_vigencia=365)
    body = EmisorCreate(
        razon_social="TEST alta con vigencia",
        rfc=rfc,
        regimen_fiscal="601",
        codigo_postal="00000",
        csd_cert_base64=cert_b64,
        csd_key_base64="dummy-no-se-valida-la-key-en-crear-emisor",
        csd_password="dummy",
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
    cert_viejo = _cert_sintetico_base64(rfc=rfc, dias_vigencia=10)
    async with AsyncSessionLocal() as db:
        await crear_emisor(
            emisor=EmisorCreate(
                razon_social="TEST reemplazo", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_viejo, csd_key_base64="dummy", csd_password="dummy",
            ),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc=None,
        )

    cert_nuevo = _cert_sintetico_base64(rfc=rfc, dias_vigencia=800)
    async with AsyncSessionLocal() as db:
        out = await actualizar_emisor(
            rfc=rfc,
            emisor=EmisorCreate(
                razon_social="TEST reemplazo", rfc=rfc, regimen_fiscal="601", codigo_postal="00000",
                csd_cert_base64=cert_nuevo, csd_key_base64="dummy", csd_password="dummy",
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
