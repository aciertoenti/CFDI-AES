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
    import base64
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
            negocio_id=negocio_con_2_emisores, db=db, x_negocio_id=str(negocio_con_2_emisores),
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

    d2 = por_rfc["EEEE850101EE1"]
    assert d2.facturas_mes == 3
    assert d2.vigencia_csd_hasta is None
    assert d2.dias_restantes is None  # nunca inventado a partir de vigencia None
    # Sin ninguna e.firma registrada para este RFC - None, no error.
    assert d2.vigencia_efirma_hasta is None
    assert d2.dias_restantes_efirma is None


async def test_emisores_resumen_alerta_csd_y_efirma_con_la_misma_vigencia(monkeypatch):
    """Caso real (RAHP7112093H0, 15-sep-2026): un usuario subio su e.firma
    en el formulario de CSD por error - ambas vigencias quedan IDENTICAS.
    El endpoint no bloquea nada (fuera de alcance de esta tarjeta), pero
    debe exponer ambos valores tal cual para que la señal sea visible."""
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST alerta CSD=FIEL", plan="despacho")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id

        misma_fecha = date(2028, 5, 2)
        emisor = Emisor(
            negocio_id=negocio_id, rfc="GGGG850101GG1", razon_social="Emisor confundido",
            regimen_fiscal="625", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo", vigencia_csd_hasta=misma_fecha,
        )
        session.add(emisor)
        session.add(_efirma_dummy(rfc_titular="GGGG850101GG1", negocio_id=negocio_id, vigencia_hasta=misma_fecha))
        await session.commit()

    try:
        async with AsyncSessionLocal() as db:
            out = await obtener_emisores_resumen(negocio_id=negocio_id, db=db, x_negocio_id=str(negocio_id))
        assert len(out) == 1
        item = out[0]
        assert item.vigencia_csd_hasta == misma_fecha
        assert item.vigencia_efirma_hasta == misma_fecha
        assert item.vigencia_csd_hasta == item.vigencia_efirma_hasta  # la señal de alerta en si
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
            negocio_id=negocio_con_2_emisores, db=db, x_negocio_id=str(negocio_con_2_emisores),
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
                negocio_id=negocio_con_2_emisores, db=db, x_negocio_id="999999",
            )
    assert exc.value.status_code == 404
