"""
Tests de declaraciones_storage.py (validaciones puras) y de los 4
endpoints de documentos de declaraciones anuales (subir/listar/descargar/
borrar) - Parte B, 22 sep 2026.

Alcance de la funcionalidad probada: SOLO archivo. No hay captura de
montos ni parseo de PDF en esta Parte B (eso es diseño de la Parte A,
sin implementar).

Mismo patron ya establecido en este archivo de tests (test_config_marca.py,
test_emisores_resumen.py): Postgres real para la integracion (lo
interesante es que persista de verdad, incluido el cifrado), llamadas
DIRECTAS a las funciones de endpoint (no HTTP), UploadFile construido a
mano con bytes reales (no un mock de "esto es un PDF").
"""
import hashlib
import io
from datetime import datetime, timezone

import declaraciones_storage
import main
import pytest
import pytest_asyncio
from cryptography.fernet import InvalidToken
from database import AsyncSessionLocal, DeclaracionAnualDocumento, Emisor, Negocio, engine
from database import _fernet as _fernet_csd  # solo para el test de C1 (llave separada)
from database import _fernet_declaraciones
from fastapi import HTTPException, UploadFile
from sqlalchemy import select


@pytest_asyncio.fixture(autouse=True)
async def _pool_por_test():
    # Mismo bug/fix ya documentado en test_listar_emisores_orden.py.
    await engine.dispose()
    yield


# ─── C1 (reporte 185): llave de cifrado SEPARADA, no CSD_MASTER_KEY ────────

def test_contenido_cifrado_con_declaraciones_key_no_descifra_con_csd_key():
    """Confirma la separacion real de llaves (no solo de nombre) - un
    token generado con _fernet_declaraciones (DECLARACIONES_MASTER_KEY)
    debe fallar al intentar descifrarlo con _fernet_csd (CSD_MASTER_KEY).
    Si esto NO lanzara InvalidToken, las 2 variables de entorno tendrian
    el mismo valor real (fail de configuracion) o CifradoFernetBinario
    seguiria usando la llave vieja por error."""
    token = _fernet_declaraciones.encrypt(b"contenido de prueba C1")
    with pytest.raises(InvalidToken):
        _fernet_csd.decrypt(token)
    # Y en la direccion correcta SI descifra - confirma que no es un
    # error generico, es especificamente el cruce de llaves lo que falla.
    assert _fernet_declaraciones.decrypt(token) == b"contenido de prueba C1"


# ─── PDF minimo real (no un mock) - firma %PDF- + estructura suficiente ────
# No necesita ser un PDF renderizable de verdad: validar_pdf() solo checa
# la firma (mismo criterio que validar_logo con magic bytes) y el resto de
# esta funcionalidad nunca abre/parsea el archivo (prohibido explicito).

def _pdf_minimo(relleno: bytes = b"") -> bytes:
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\n" + relleno + b"\n%%EOF"


def _upload_file(contenido: bytes, filename: str = "declaracion.pdf") -> UploadFile:
    return UploadFile(file=io.BytesIO(contenido), filename=filename)


# ─── declaraciones_storage.py - validaciones puras ─────────────────────────

def test_validar_pdf_acepta_firma_real():
    declaraciones_storage.validar_pdf(_pdf_minimo())  # no debe lanzar nada


def test_validar_pdf_rechaza_sin_firma():
    with pytest.raises(ValueError, match="no es un PDF"):
        declaraciones_storage.validar_pdf(b"esto no es un PDF, solo texto plano")


def test_validar_pdf_rechaza_vacio():
    with pytest.raises(ValueError, match="vacio"):
        declaraciones_storage.validar_pdf(b"")


def test_validar_pdf_rechaza_sobre_el_limite():
    contenido = b"%PDF-1.4\n" + b"\x00" * (declaraciones_storage.MAX_DECLARACION_PDF_BYTES + 1)
    with pytest.raises(ValueError, match="MB"):
        declaraciones_storage.validar_pdf(contenido)


def test_validar_ejercicio_2013_es_aceptado():
    # CORREGIDO 22 sep 2026 (reporte 185/C2): documentos reales del
    # titular confirman acuses desde 2013 - EJERCICIO_MINIMO bajo de
    # 2014 a 2000, 2013 ya no se rechaza. No debe lanzar nada.
    declaraciones_storage.validar_ejercicio(2013)


def test_validar_ejercicio_rechaza_antes_del_minimo():
    with pytest.raises(ValueError, match="2000"):
        declaraciones_storage.validar_ejercicio(1999)


def test_validar_ejercicio_rechaza_el_actual_o_futuro():
    # año actual - 1 es el maximo (calculado, no hardcodeado en el test
    # tampoco - usa la misma funcion que el modulo real).
    maximo = declaraciones_storage.ejercicio_maximo_valido()
    with pytest.raises(ValueError):
        declaraciones_storage.validar_ejercicio(maximo + 1)


def test_validar_ejercicio_acepta_el_maximo_valido():
    maximo = declaraciones_storage.ejercicio_maximo_valido()
    declaraciones_storage.validar_ejercicio(maximo)  # no debe lanzar nada


def test_validar_tipo_declaracion_normal_con_numero_es_invalido():
    with pytest.raises(ValueError, match="nulo"):
        declaraciones_storage.validar_tipo_declaracion("normal", 1)


def test_validar_tipo_declaracion_complementaria_sin_numero_es_invalido():
    with pytest.raises(ValueError, match="obligatorio"):
        declaraciones_storage.validar_tipo_declaracion("complementaria", None)


def test_validar_tipo_declaracion_complementaria_numero_4_es_valido():
    # CORREGIDO 22 sep 2026 (reporte 185/C3): el tope de 3 (regla general
    # de Art. 32 CFF) tiene excepciones legales reales - un numero_
    # complementaria=4 ya NO se rechaza. No debe lanzar nada.
    declaraciones_storage.validar_tipo_declaracion("complementaria", 4)


def test_validar_tipo_declaracion_complementaria_numero_0_es_invalido():
    # 0 sigue siendo invalido - el minimo real sigue siendo 1.
    with pytest.raises(ValueError, match="obligatorio"):
        declaraciones_storage.validar_tipo_declaracion("complementaria", 0)


def test_sanitizar_nombre_archivo_quita_caracteres_peligrosos():
    assert declaraciones_storage.sanitizar_nombre_archivo("../../etc/passwd") == ".._.._etc_passwd"
    assert declaraciones_storage.sanitizar_nombre_archivo("declaración 2024\r\nX-Evil: 1") == "declaraci_n 2024__X-Evil_ 1"


# ─── Integracion contra Postgres real ──────────────────────────────────────

@pytest.fixture
async def negocio_temporal():
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST declaraciones anuales", plan="basico")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(DeclaracionAnualDocumento.__table__.delete().where(DeclaracionAnualDocumento.negocio_id == negocio_id))
        await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
        await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
        await session.commit()


@pytest.fixture
async def otro_negocio_temporal():
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST otro negocio (aislamiento)", plan="basico")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(Emisor.__table__.delete().where(Emisor.negocio_id == negocio_id))
        await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
        await session.commit()


async def _crear_emisor_pf(negocio_id: int, rfc: str = "TEST850101AB1") -> int:
    async with AsyncSessionLocal() as session:
        emisor = Emisor(
            negocio_id=negocio_id, rfc=rfc, razon_social="TEST Persona Fisica",
            regimen_fiscal="612", codigo_postal="00000",
            csd_cert_base64="dummy", csd_key_base64="dummy", csd_password="dummy",
            estado="Activo",
        )
        session.add(emisor)
        await session.commit()
        await session.refresh(emisor)
        return emisor.id


@pytest.fixture
async def emisor_temporal(negocio_temporal):
    return await _crear_emisor_pf(negocio_temporal)


async def test_happy_path_sube_y_aparece_en_la_lista(negocio_temporal, emisor_temporal):
    contenido = _pdf_minimo(b"contenido real de prueba")
    async with AsyncSessionLocal() as db:
        out = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="declaracion",
            archivo=_upload_file(contenido, "Declaracion 2024.pdf"),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    assert out.ejercicio == 2024
    assert out.tamano_bytes == len(contenido)
    assert out.sha256 == hashlib.sha256(contenido).hexdigest()

    async with AsyncSessionLocal() as db:
        lista = await main.listar_documentos_declaracion_anual(
            emisor_id=emisor_temporal, db=db, x_negocio_id=str(negocio_temporal),
        )
    assert len(lista) == 1
    assert lista[0].id == out.id
    # La lista NUNCA debe traer el contenido - DeclaracionDocumentoResponse
    # no tiene ese campo, confirmar que no existe en absoluto.
    assert not hasattr(lista[0], "contenido_cifrado")


async def test_archivo_no_pdf_con_extension_pdf_se_rechaza(negocio_temporal, emisor_temporal):
    """El caso pedido explicitamente: extension .pdf pero NO es un PDF real
    - debe rechazarse por magic bytes, no por la extension del nombre."""
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(b"esto no es un PDF real", "declaracion.pdf"),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 422


async def test_archivo_sobre_el_limite_se_rechaza(negocio_temporal, emisor_temporal):
    contenido = b"%PDF-1.4\n" + b"\x00" * (declaraciones_storage.MAX_DECLARACION_PDF_BYTES + 1)
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(contenido),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 422


async def test_ejercicio_fuera_de_rango_se_rechaza(negocio_temporal, emisor_temporal):
    # 1999, no 2013 (CORREGIDO 22 sep 2026, reporte 185/C2): EJERCICIO_MINIMO
    # bajo a 2000 - 2013 ya es un ejercicio valido, ya no sirve para este caso.
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=1999, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(_pdf_minimo()),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 422


async def test_ejercicio_2013_es_aceptado_end_to_end(negocio_temporal, emisor_temporal):
    """Caso real pedido explicitamente (reporte 185/C2, C0): documentos
    reales del titular confirman acuses desde 2013 - debe subir sin
    problema a traves del endpoint completo, no solo la validacion pura."""
    async with AsyncSessionLocal() as db:
        out = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2013, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_pdf_minimo(b"acuse 2013")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    assert out.ejercicio == 2013


async def test_complementaria_sin_numero_se_rechaza(negocio_temporal, emisor_temporal):
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="complementaria",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(_pdf_minimo()),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 422


async def test_duplicado_mismo_sha256_da_409(negocio_temporal, emisor_temporal):
    contenido = _pdf_minimo(b"contenido identico")
    async with AsyncSessionLocal() as db:
        await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="declaracion",
            archivo=_upload_file(contenido, "primera.pdf"),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(contenido, "copia_con_otro_nombre.pdf"),  # mismo contenido, distinto nombre
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 409


async def test_emisor_de_otro_negocio_se_rechaza_sin_revelar_existencia(
    negocio_temporal, emisor_temporal, otro_negocio_temporal,
):
    """emisor_temporal pertenece a negocio_temporal - llamar con
    otro_negocio_temporal en el header debe dar 404 (nunca 403, mismo
    criterio IDOR que actualizar_emisor)."""
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(_pdf_minimo()),
                db=db, x_negocio_id=str(otro_negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 404


async def test_descarga_devuelve_bytes_identicos_con_headers_correctos(negocio_temporal, emisor_temporal):
    contenido = _pdf_minimo(b"contenido para descarga")
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="declaracion",
            archivo=_upload_file(contenido, "Declaración 2024 (final).pdf"),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    async with AsyncSessionLocal() as db:
        resp = await main.descargar_documento_declaracion_anual(
            emisor_id=emisor_temporal, documento_id=subido.id,
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert hashlib.sha256(resp.body).hexdigest() == hashlib.sha256(contenido).hexdigest()
    assert resp.body == contenido
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in resp.headers["content-disposition"]


async def test_contenido_en_bd_esta_cifrado(negocio_temporal, emisor_temporal):
    """Confirma que lo que vive en la columna NO es el PDF en claro -
    lee la fila via SQL crudo (no el ORM, que descifraria transparente)."""
    contenido = _pdf_minimo(b"para verificar cifrado")
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="declaracion",
            archivo=_upload_file(contenido),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    async with engine.connect() as conn:
        from sqlalchemy import text
        crudo = (await conn.execute(
            text("SELECT contenido_cifrado FROM declaraciones_anuales_documentos WHERE id = :id"),
            {"id": subido.id},
        )).scalar_one()
    assert bytes(crudo)[:5] != b"%PDF-"
    assert bytes(crudo) != contenido


async def test_delete_aislado_por_negocio(negocio_temporal, emisor_temporal, otro_negocio_temporal):
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="declaracion",
            archivo=_upload_file(_pdf_minimo()),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    # Intento desde OTRO negocio - 404, nada se borra.
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.borrar_documento_declaracion_anual(
                emisor_id=emisor_temporal, documento_id=subido.id,
                db=db, x_negocio_id=str(otro_negocio_temporal),
            )
    assert exc.value.status_code == 404
    async with AsyncSessionLocal() as db:
        sigue = await db.get(DeclaracionAnualDocumento, subido.id)
    assert sigue is not None

    # Delete real desde el negocio correcto - 204, ya no aparece.
    async with AsyncSessionLocal() as db:
        resp = await main.borrar_documento_declaracion_anual(
            emisor_id=emisor_temporal, documento_id=subido.id,
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resp.status_code == 204
    async with AsyncSessionLocal() as db:
        ya_no = await db.get(DeclaracionAnualDocumento, subido.id)
    assert ya_no is None
