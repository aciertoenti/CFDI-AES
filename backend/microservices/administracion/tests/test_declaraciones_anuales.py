"""
Tests de declaraciones_storage.py + declaraciones_pdf.py (analisis de
contenido) + los endpoints de declaraciones anuales (analizar/subir/
listar/descargar/borrar) - Parte B (22 sep 2026) + reporte 189
(validacion por CONTENIDO del PDF, 23 sep 2026).

Reporte 189 - motivo real: antes se guardaba el ejercicio/tipo que el
usuario elegia A MANO, sin leer el PDF - una prueba real guardo un acuse
de 2013 como si fuera 2025, y una opinion de cumplimiento como si fuera
una declaracion. Estos tests cubren la extraccion de contenido para los
2 formatos conocidos (reciente y 2013), el rechazo de opiniones de
cumplimiento/RFC ajeno/numero de operacion duplicado, y los limites
duros de lectura (paginas, timeout, PDF corrupto) - todo con PDFs
SINTETICOS con capa de texto REAL (reportlab), nunca documentos reales.

reportlab NO esta en requirements.txt (mismo criterio ya establecido
para pytest en este archivo: dependencia de TEST, se instala ad-hoc
antes de correr la suite, nunca en la imagen de produccion).

Mismo patron ya establecido en este archivo de tests (test_config_marca.py,
test_emisores_resumen.py): Postgres real para la integracion (lo
interesante es que persista de verdad, incluido el cifrado), llamadas
DIRECTAS a las funciones de endpoint (no HTTP), UploadFile construido a
mano con bytes reales (no un mock de "esto es un PDF").
"""
import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal

import declaraciones_pdf
import declaraciones_storage
import main
import pytest
import pytest_asyncio
from cryptography.fernet import InvalidToken
from database import AsyncSessionLocal, DeclaracionAnual, DeclaracionAnualDocumento, DeclaracionAnualTipoIngreso, Emisor, Negocio, engine
from database import _fernet as _fernet_csd  # solo para el test de C1 (llave separada)
from database import _fernet_declaraciones
from fastapi import HTTPException, UploadFile
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import func, select


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


# ─── PDFs sinteticos ────────────────────────────────────────────────────────

def _pdf_minimo(relleno: bytes = b"") -> bytes:
    """PDF sin capa de texto REAL parseable (solo firma %PDF-) - usado
    para los casos que no dependen del analisis de contenido (validacion
    de tamano/firma pura). analizar_pdf() sobre esto cae en NO_RECONOCIDO
    (pypdf no logra abrirlo como PDF valido - mismo comportamiento que
    "PDF corrupto")."""
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\n" + relleno + b"\n%%EOF"


def _pdf_con_texto(lineas: list, paginas: int = 1) -> bytes:
    """PDF sintetico con capa de texto REAL (reportlab) - cada linea de
    `lineas` se reparte en la primera pagina; si `paginas` > 1, se agregan
    paginas adicionales de relleno simple (para el caso "mas de 10
    paginas")."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 780
    for linea in lineas:
        c.drawString(50, y, linea)
        y -= 18
    c.showPage()
    for i in range(paginas - 1):
        c.drawString(50, 780, f"Pagina de relleno {i}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _acuse_reciente(rfc: str = "TEST850101AB1", ejercicio: int = 2024, numero_operacion: str = "12345678901234") -> bytes:
    return _pdf_con_texto([
        "ACUSE DE RECIBO",
        f"DECLARACION DEL EJERCICIO {ejercicio}",
        f"RFC: {rfc}",
        f"Numero de operacion: {numero_operacion}",
        "Fecha y hora de presentacion: 15/04/2025 23:45:10",
        "Saldo a favor: $0.00",
        "Cantidad a cargo: $1,234.56",
        "Cantidad a pagar: $1,234.56",
        "INGRESOS QUE DECLARA",
        "Sueldos, salarios y asimilados",
        "Intereses",
        "ANEXOS QUE PRESENTA",
        "Anexo 1",
    ])


def _acuse_2013(rfc: str = "TEST850101AB1", numero_operacion: str = "98765432109876") -> bytes:
    return _pdf_con_texto([
        "ACUSE DE RECIBO",
        "DECLARACION DEL EJERCICIO 2013",
        f"R.F.C. : {rfc}",
        f"Numero de Operacion: {numero_operacion}",
        "Fecha de presentacion: 10/04/2014",
        "IMPUESTOS QUE DECLARA",
        "ISR personas fisicas",
        "ANEXOS QUE PRESENTA",
        "Anexo 2",
    ])


def _acuse_formato_desglose_por_concepto(rfc: str = "TEST850101AB1", ejercicio: int = 2024, numero_operacion: str = "55566677788899") -> bytes:
    """Reproduce el formato EXACTO encontrado en los 6 acuses reales de
    RAHP7112093H0 (reporte 189b, F2) - hallazgo real, no hipotetico: pypdf
    extrae los montos como ENTEROS sin decimales cuando son cero
    ("CANTIDAD A CARGO: 0", no "0.00"), con separador de miles solo si el
    monto lo amerita ("A FAVOR: 12,345", sin ".00"), y la etiqueta del
    saldo a favor es la palabra desnuda "A FAVOR:" (SIN "SALDO" antes) en
    el desglose por concepto de pago - a diferencia de la etiqueta
    "Saldo a favor:" que sí usa _acuse_reciente() arriba (ambas formas
    reales, el regex debe aceptar las dos)."""
    return _pdf_con_texto([
        "ACUSE DE RECIBO",
        f"DECLARACION DEL EJERCICIO {ejercicio}",
        f"RFC: {rfc}",
        f"Numero de operacion: {numero_operacion}",
        "Fecha y hora de presentacion: 20/04/2025 10:00:00",
        "IMPUESTOS QUE DECLARA:",
        "CONCEPTO DE PAGO (1): ISR PERSONAS FISICAS",
        "A FAVOR: 12,345",
        "CANTIDAD A CARGO: 0",
        "CANTIDAD A PAGAR: 0",
        "INGRESOS QUE DECLARA",
        "Sueldos, salarios y asimilados",
        "ANEXOS QUE PRESENTA",
    ])


def _opinion_cumplimiento(rfc: str = "TEST850101AB1") -> bytes:
    return _pdf_con_texto([
        "Opinion del cumplimiento de obligaciones fiscales",
        f"RFC: {rfc}",
        "Sentido: Positivo",
    ])


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


# ─── declaraciones_pdf.py - analisis de contenido (reporte 189) ───────────

def test_acuse_formato_reciente_extrae_todos_los_campos():
    r = declaraciones_pdf.analizar_pdf(_acuse_reciente(rfc="TEST850101AB1", ejercicio=2024, numero_operacion="12345678901234"))
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.ACUSE_ANUAL
    d = r.datos
    assert d.rfc == "TEST850101AB1"
    assert d.ejercicio == 2024
    assert d.tipo_declaracion == "normal"
    assert d.numero_operacion == "12345678901234"
    assert d.fecha_presentacion == datetime(2025, 4, 15, 23, 45, 10)
    # Decimal, no float (declaraciones_pdf.py guarda Decimal a proposito -
    # numeric(14,2) en BD - comparar contra Decimal(str(...)), nunca un
    # literal float, que no representa 1234.56 exacto en binario).
    assert d.saldo_a_favor == Decimal("0")
    assert d.cantidad_a_cargo == Decimal("1234.56")
    assert d.cantidad_a_pagar == Decimal("1234.56")
    assert d.ingresos_que_declara == ["Sueldos, salarios y asimilados", "Intereses"]


def test_acuse_formato_2013_extrae_los_campos_de_ese_formato():
    """Formato 2013: R.F.C. (con puntos), Numero de Operacion (con
    mayuscula distinta), IMPUESTOS QUE DECLARA (no INGRESOS)."""
    r = declaraciones_pdf.analizar_pdf(_acuse_2013(rfc="TEST850101AB1", numero_operacion="98765432109876"))
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.ACUSE_ANUAL
    d = r.datos
    assert d.rfc == "TEST850101AB1"
    assert d.ejercicio == 2013
    assert d.numero_operacion == "98765432109876"
    assert d.ingresos_que_declara == ["ISR personas fisicas"]


def test_acuse_formato_desglose_por_concepto_montos_sin_decimales():
    """Reporte 189b F2 - BUG REAL encontrado con los 6 acuses reales de
    RAHP7112093H0: el regex anterior exigia ".NN" (2 decimales) siempre y
    "SALDO A FAVOR" como frase fija - ambos rechazaban el formato real
    (montos enteros sin decimales, etiqueta "A FAVOR:" sin "SALDO").
    Corregido en declaraciones_pdf.py (_RE_MONTO con decimales opcionales,
    "SALDO" opcional en _RE_SALDO_FAVOR)."""
    r = declaraciones_pdf.analizar_pdf(_acuse_formato_desglose_por_concepto())
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.ACUSE_ANUAL
    d = r.datos
    assert d.saldo_a_favor == Decimal("12345")
    assert d.cantidad_a_cargo == Decimal("0")
    assert d.cantidad_a_pagar == Decimal("0")


def test_opinion_cumplimiento_se_rechaza():
    r = declaraciones_pdf.analizar_pdf(_opinion_cumplimiento())
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.OPINION_CUMPLIMIENTO


def test_pdf_sin_texto_reconocible_es_no_reconocido():
    r = declaraciones_pdf.analizar_pdf(_pdf_con_texto(["Un documento cualquiera", "sin relacion con el SAT"]))
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.NO_RECONOCIDO
    assert r.error_lectura is None  # se leyo bien, solo no se reconocio


def test_pdf_corrupto_da_error_controlado_nunca_lanza():
    r = declaraciones_pdf.analizar_pdf(b"%PDF-1.4\nesto no es un PDF valido en absoluto")
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.NO_RECONOCIDO
    assert r.error_lectura == "No se pudo leer el documento"


def test_mas_de_10_paginas_da_error_controlado():
    contenido = _pdf_con_texto(["ACUSE DE RECIBO", "DECLARACION DEL EJERCICIO 2024"], paginas=declaraciones_pdf.MAX_PAGINAS_PDF + 3)
    r = declaraciones_pdf.analizar_pdf(contenido)
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.NO_RECONOCIDO
    assert r.error_lectura == "No se pudo leer el documento"


def test_tiempo_excedido_da_error_controlado(monkeypatch):
    """Deterministico (no un PDF realmente lento) - se baja el limite a
    un valor imposible de cumplir para forzar el timeout siempre, sin
    depender de la velocidad real de la maquina."""
    monkeypatch.setattr(declaraciones_pdf, "TIEMPO_MAX_LECTURA_SEGUNDOS", 0.0001)
    r = declaraciones_pdf.analizar_pdf(_acuse_reciente())
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.NO_RECONOCIDO
    assert r.error_lectura == "No se pudo leer el documento"


def test_clasificacion_es_tolerante_a_mayusculas_y_acentos():
    contenido = _pdf_con_texto(["acuse de recibo", "declaración del ejercicio 2024", "rfc: TEST850101AB1"])
    r = declaraciones_pdf.analizar_pdf(contenido)
    assert r.tipo_detectado == declaraciones_pdf.TipoDocumentoDetectado.ACUSE_ANUAL


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
        # Orden FK-safe: documentos -> tipos_ingreso (via declaracion) ->
        # declaraciones -> emisores -> negocio.
        ids_declaraciones = (await session.execute(
            select(DeclaracionAnual.id).where(DeclaracionAnual.negocio_id == negocio_id)
        )).scalars().all()
        await session.execute(DeclaracionAnualDocumento.__table__.delete().where(DeclaracionAnualDocumento.negocio_id == negocio_id))
        if ids_declaraciones:
            await session.execute(DeclaracionAnualTipoIngreso.__table__.delete().where(DeclaracionAnualTipoIngreso.declaracion_id.in_(ids_declaraciones)))
        await session.execute(DeclaracionAnual.__table__.delete().where(DeclaracionAnual.negocio_id == negocio_id))
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


def _primer_documento(lista):
    """La lista ahora es por DECLARACION (reporte 189) - helper para los
    tests que solo suben 1 archivo y quieren el documento anidado."""
    assert len(lista) == 1
    assert len(lista[0].documentos) == 1
    return lista[0].documentos[0]


async def test_happy_path_sube_y_aparece_en_la_lista(negocio_temporal, emisor_temporal):
    """PDF sin texto reconocible (_pdf_minimo) -> NO_RECONOCIDO ->
    origen='manual' -> se usan ejercicio/tipo del FORMULARIO tal cual
    (comportamiento sin cambios para este caso, ya cubierto por
    test_ejercicio_del_documento_prevalece_sobre_el_cliente para el caso
    ACUSE_ANUAL)."""
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
    assert out.declaracion_id is not None

    async with AsyncSessionLocal() as db:
        lista = await main.listar_documentos_declaracion_anual(
            emisor_id=emisor_temporal, db=db, x_negocio_id=str(negocio_temporal),
        )
    doc = _primer_documento(lista)
    assert doc.id == out.id
    assert lista[0].origen == "manual"
    # La lista NUNCA debe traer el contenido - DeclaracionDocumentoResponse
    # no tiene ese campo, confirmar que no existe en absoluto.
    assert not hasattr(doc, "contenido_cifrado")


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
    # PDF sin texto (NO_RECONOCIDO/manual) para que el ejercicio del
    # FORMULARIO sea el que se valide (1999).
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
    problema a traves del endpoint completo. Ahora usa un acuse SINTETICO
    real de formato 2013 (reporte 189) en vez de un PDF sin texto, para
    probar el camino ACUSE_ANUAL con ejercicio extraido."""
    async with AsyncSessionLocal() as db:
        out = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2020, tipo_declaracion="normal",  # el cliente manda OTRO ejercicio a proposito
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_acuse_2013(rfc="TEST850101AB1")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    assert out.ejercicio == 2013  # el del DOCUMENTO, no el 2020 que mando el cliente


async def test_ejercicio_del_documento_prevalece_sobre_el_cliente(negocio_temporal, emisor_temporal):
    """Pedido explicito del reporte 189: si el PDF se reconoce como
    ACUSE_ANUAL, el ejercicio/tipo_declaracion EXTRAIDOS reemplazan lo
    que mande el formulario, sin importar que el cliente mande otra
    cosa."""
    async with AsyncSessionLocal() as db:
        out = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=1900, tipo_declaracion="complementaria", numero_complementaria=9,
            tipo_documento="acuse",
            archivo=_upload_file(_acuse_reciente(rfc="TEST850101AB1", ejercicio=2022, numero_operacion="11111111111111")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    assert out.ejercicio == 2022
    assert out.tipo_declaracion == "normal"
    assert out.numero_complementaria is None

    async with AsyncSessionLocal() as db:
        decl = await db.get(DeclaracionAnual, out.declaracion_id)
    assert decl.ejercicio == 2022
    assert decl.origen == "extraido"
    assert decl.numero_operacion == "11111111111111"


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


async def test_rfc_ajeno_se_rechaza_al_guardar(negocio_temporal, emisor_temporal):
    """emisor_temporal tiene rfc=TEST850101AB1 - un acuse con OTRO RFC
    debe rechazarse (reporte 189, validacion dura de D2)."""
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="acuse",
                archivo=_upload_file(_acuse_reciente(rfc="OTRO900101XY2")),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 422
    assert "otro RFC" in exc.value.detail


async def test_rfc_ajeno_se_rechaza_al_analizar(negocio_temporal, emisor_temporal):
    """Mismo criterio en /analizar (solo lectura, sin guardar nada) -
    pedido explicito de D4: el usuario ve el rechazo ANTES de intentar
    guardar."""
    async with AsyncSessionLocal() as db:
        resultado = await main.analizar_documento_declaracion_anual(
            emisor_id=emisor_temporal,
            archivo=_upload_file(_acuse_reciente(rfc="OTRO900101XY2")),
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resultado.tipo_detectado == "ACUSE_ANUAL"
    assert resultado.puede_guardar is False
    assert resultado.rfc_coincide is False
    assert "otro RFC" in resultado.mensaje


async def test_analizar_no_guarda_nada(negocio_temporal, emisor_temporal):
    """/analizar es SOLO LECTURA (pedido explicito D3) - correrlo no debe
    dejar ninguna fila en declaraciones_anuales ni en
    declaraciones_anuales_documentos."""
    async with AsyncSessionLocal() as db:
        resultado = await main.analizar_documento_declaracion_anual(
            emisor_id=emisor_temporal,
            archivo=_upload_file(_acuse_reciente()),
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resultado.tipo_detectado == "ACUSE_ANUAL"
    assert resultado.puede_guardar is True
    assert resultado.extraido.ejercicio == 2024

    async with AsyncSessionLocal() as db:
        n_declaraciones = await db.scalar(select(func.count()).select_from(DeclaracionAnual).where(DeclaracionAnual.emisor_id == emisor_temporal))
        n_documentos = await db.scalar(select(func.count()).select_from(DeclaracionAnualDocumento).where(DeclaracionAnualDocumento.emisor_id == emisor_temporal))
    assert n_declaraciones == 0
    assert n_documentos == 0


async def test_numero_operacion_duplicado_se_rechaza(negocio_temporal, emisor_temporal):
    """2 acuses DISTINTOS (contenido/sha256 distinto - textos de relleno
    diferentes) pero con el MISMO numero_operacion - el segundo debe
    rechazarse por duplicado (reporte 189, D2)."""
    async with AsyncSessionLocal() as db:
        await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_acuse_reciente(numero_operacion="22222222222222")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    otro_acuse = _pdf_con_texto([
        "ACUSE DE RECIBO", "DECLARACION DEL EJERCICIO 2024",
        "RFC: TEST850101AB1", "Numero de operacion: 22222222222222",
        "texto de relleno distinto para que el sha256 no coincida",
    ])
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="acuse",
                archivo=_upload_file(otro_acuse),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 409


async def test_opinion_cumplimiento_se_rechaza_al_guardar(negocio_temporal, emisor_temporal):
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="declaracion",
                archivo=_upload_file(_opinion_cumplimiento(rfc="TEST850101AB1")),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
    assert exc.value.status_code == 422
    assert "opinión de cumplimiento" in exc.value.detail.lower()


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


async def test_aislamiento_por_negocio_id_en_numero_operacion(negocio_temporal, emisor_temporal, otro_negocio_temporal):
    """El UNIQUE de numero_operacion es POR NEGOCIO (negocio_id, emisor_id,
    numero_operacion) - el mismo numero_operacion en un emisor de OTRO
    negocio no debe chocar. Se crea un 2do emisor con el MISMO rfc en el
    otro negocio (rfc es UNIQUE global en emisores - se usa un rfc
    distinto para no chocar con esa constraint, que es un concepto
    aparte del aislamiento que se prueba aqui)."""
    otro_emisor_id = await _crear_emisor_pf(otro_negocio_temporal, rfc="OTRO900101XY2")
    try:
        async with AsyncSessionLocal() as db:
            await main.subir_documento_declaracion_anual(
                emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="acuse",
                archivo=_upload_file(_acuse_reciente(rfc="TEST850101AB1", numero_operacion="33333333333333")),
                db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
            )
        # Mismo numero_operacion, OTRO negocio/emisor - no debe chocar.
        async with AsyncSessionLocal() as db:
            out2 = await main.subir_documento_declaracion_anual(
                emisor_id=otro_emisor_id, ejercicio=2024, tipo_declaracion="normal",
                numero_complementaria=None, tipo_documento="acuse",
                archivo=_upload_file(_acuse_reciente(rfc="OTRO900101XY2", numero_operacion="33333333333333")),
                db=db, x_negocio_id=str(otro_negocio_temporal), x_usuario_rfc="TESTER",
            )
        assert out2.ejercicio == 2024
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(DeclaracionAnualDocumento.__table__.delete().where(DeclaracionAnualDocumento.emisor_id == otro_emisor_id))
            ids = (await db.execute(select(DeclaracionAnual.id).where(DeclaracionAnual.emisor_id == otro_emisor_id))).scalars().all()
            if ids:
                await db.execute(DeclaracionAnualTipoIngreso.__table__.delete().where(DeclaracionAnualTipoIngreso.declaracion_id.in_(ids)))
            await db.execute(DeclaracionAnual.__table__.delete().where(DeclaracionAnual.emisor_id == otro_emisor_id))
            await db.commit()


# ─── Borrado de declaraciones (reporte 189b, F3) ───────────────────────────

async def test_borrar_ultimo_documento_borra_tambien_la_declaracion(negocio_temporal, emisor_temporal):
    """Al borrar el ÚNICO documento de una declaración, la declaración y
    sus tipos de ingreso deben desaparecer en la MISMA operación - ya no
    debe quedar huérfana (hallazgo real del reporte 189, corregido aquí)."""
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_acuse_reciente(rfc="TEST850101AB1", numero_operacion="44455566677788")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    declaracion_id = subido.declaracion_id
    assert declaracion_id is not None

    async with AsyncSessionLocal() as db:
        resp = await main.borrar_documento_declaracion_anual(
            emisor_id=emisor_temporal, documento_id=subido.id,
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        assert await db.get(DeclaracionAnual, declaracion_id) is None
        tipos = (await db.execute(
            select(DeclaracionAnualTipoIngreso).where(DeclaracionAnualTipoIngreso.declaracion_id == declaracion_id)
        )).scalars().all()
    assert tipos == []


async def test_borrar_un_documento_no_borra_la_declaracion_si_quedan_otros(negocio_temporal, emisor_temporal):
    """Caso contrario al anterior: si a la declaración le queda AL MENOS
    un documento ligado, la declaración NO se borra. El flujo real de
    subida hoy rechaza un 2do documento con el mismo numero_operacion
    (ver reporte 189, D3) - para probar el caso "quedan mas documentos"
    se liga un 2do documento a la MISMA declaración directamente en BD
    (simula el escenario que el DELETE debe manejar correctamente aunque
    el flujo de subida actual no lo produzca todavia)."""
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_acuse_reciente(rfc="TEST850101AB1", numero_operacion="99988877766655")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    declaracion_id = subido.declaracion_id

    segundo_contenido = _pdf_minimo(b"segundo documento de la misma declaracion")
    async with AsyncSessionLocal() as db:
        segundo = DeclaracionAnualDocumento(
            negocio_id=negocio_temporal, emisor_id=emisor_temporal, declaracion_id=declaracion_id,
            ejercicio=2024, tipo_declaracion="normal", numero_complementaria=None,
            tipo_documento="comprobante_pago", nombre_archivo_original="pago.pdf",
            tamano_bytes=len(segundo_contenido), sha256=hashlib.sha256(segundo_contenido).hexdigest(),
            contenido_cifrado=segundo_contenido, creado_por="TESTER",
        )
        db.add(segundo)
        await db.commit()
        await db.refresh(segundo)

    async with AsyncSessionLocal() as db:
        resp = await main.borrar_documento_declaracion_anual(
            emisor_id=emisor_temporal, documento_id=subido.id,
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        # La declaracion SIGUE existiendo - todavia tiene el 2do documento.
        assert await db.get(DeclaracionAnual, declaracion_id) is not None
        assert await db.get(DeclaracionAnualDocumento, segundo.id) is not None


async def test_borrar_declaracion_completa_borra_documentos_y_tipos_ingreso(negocio_temporal, emisor_temporal):
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2023, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_acuse_reciente(rfc="TEST850101AB1", ejercicio=2023, numero_operacion="12312312312399")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    declaracion_id = subido.declaracion_id

    async with AsyncSessionLocal() as db:
        tipos_antes = (await db.execute(
            select(DeclaracionAnualTipoIngreso).where(DeclaracionAnualTipoIngreso.declaracion_id == declaracion_id)
        )).scalars().all()
    assert len(tipos_antes) > 0  # el acuse sintetico trae "INGRESOS QUE DECLARA"

    async with AsyncSessionLocal() as db:
        resp = await main.borrar_declaracion_anual(
            emisor_id=emisor_temporal, declaracion_id=declaracion_id,
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resp.status_code == 204

    async with AsyncSessionLocal() as db:
        assert await db.get(DeclaracionAnual, declaracion_id) is None
        assert await db.get(DeclaracionAnualDocumento, subido.id) is None
        tipos_despues = (await db.execute(
            select(DeclaracionAnualTipoIngreso).where(DeclaracionAnualTipoIngreso.declaracion_id == declaracion_id)
        )).scalars().all()
    assert tipos_despues == []


async def test_borrar_declaracion_aislada_por_negocio_id(negocio_temporal, emisor_temporal, otro_negocio_temporal):
    async with AsyncSessionLocal() as db:
        subido = await main.subir_documento_declaracion_anual(
            emisor_id=emisor_temporal, ejercicio=2024, tipo_declaracion="normal",
            numero_complementaria=None, tipo_documento="acuse",
            archivo=_upload_file(_acuse_reciente(rfc="TEST850101AB1", numero_operacion="77788899900011")),
            db=db, x_negocio_id=str(negocio_temporal), x_usuario_rfc="TESTER",
        )
    declaracion_id = subido.declaracion_id

    # Intento desde OTRO negocio - 404, nada se borra.
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.borrar_declaracion_anual(
                emisor_id=emisor_temporal, declaracion_id=declaracion_id,
                db=db, x_negocio_id=str(otro_negocio_temporal),
            )
    assert exc.value.status_code == 404
    async with AsyncSessionLocal() as db:
        assert await db.get(DeclaracionAnual, declaracion_id) is not None

    # declaracion_id inexistente/no numerico razonable - tambien 404.
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await main.borrar_declaracion_anual(
                emisor_id=emisor_temporal, declaracion_id=99999999,
                db=db, x_negocio_id=str(negocio_temporal),
            )
    assert exc.value.status_code == 404

    # Delete real desde el negocio correcto - 204.
    async with AsyncSessionLocal() as db:
        resp = await main.borrar_declaracion_anual(
            emisor_id=emisor_temporal, declaracion_id=declaracion_id,
            db=db, x_negocio_id=str(negocio_temporal),
        )
    assert resp.status_code == 204
