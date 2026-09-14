"""
Tests de white-label del portal publico (zg2mOhE):
  - validar_logo() (logo_storage.py) - unit puro, sin DB/HTTP. Valida por
    magic bytes REALES, no por Content-Type declarado - un cliente API
    directo puede saltarse cualquier validacion que solo confiara en el
    navegador, asi que esto se prueba con bytes crudos, no con un mock de
    un objeto UploadFile.
  - GET/PUT /admin/config y GET /admin/negocios/{id}/branding - integracion
    contra Postgres real (mismo patron que test_listar_emisores_orden.py):
    lo interesante es que persista de verdad (antes era un mock puro) y
    que el negocio ajeno/sin configurar caiga limpio al fallback.
"""
import base64
from datetime import datetime

import main
import pytest
import pytest_asyncio
from database import AsyncSessionLocal, Negocio, engine
from fastapi import HTTPException
from logo_storage import MAX_LOGO_BYTES, validar_logo


@pytest_asyncio.fixture(autouse=True)
async def _pool_por_test():
    # Mismo bug/fix ya documentado en test_listar_emisores_orden.py.
    await engine.dispose()
    yield


# ─── validar_logo() - por magic bytes reales, no por Content-Type ──────────

# PNG 1x1 real (mismo que se subio de verdad a MinIO en la verificacion
# manual de esta tarjeta, via curl -F) - no un hex escrito a mano.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100
SVG_SIMPLE = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
SVG_SIN_PROLOG = b'<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg>'


def test_png_real_se_acepta():
    assert validar_logo(PNG_1X1) == "image/png"


def test_jpeg_real_se_acepta():
    assert validar_logo(JPEG_HEADER) == "image/jpeg"


def test_svg_con_prolog_xml_se_acepta():
    assert validar_logo(SVG_SIMPLE) == "image/svg+xml"


def test_svg_sin_prolog_se_acepta():
    assert validar_logo(SVG_SIN_PROLOG) == "image/svg+xml"


def test_vacio_se_rechaza():
    with pytest.raises(ValueError, match="vacio"):
        validar_logo(b"")


def test_texto_plano_disfrazado_se_rechaza():
    """El caso pedido explicitamente: un cliente API directo declara
    Content-Type: image/png pero manda cualquier otra cosa - validar_logo
    ni siquiera recibe ese header, solo bytes, asi que no hay forma de
    mentirle."""
    with pytest.raises(ValueError, match="Formato no soportado"):
        validar_logo(b"esto no es una imagen, solo texto plano")


def test_pdf_se_rechaza():
    # Otro formato binario real, pero no de los 3 permitidos.
    with pytest.raises(ValueError, match="Formato no soportado"):
        validar_logo(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")


def test_excede_2mb_se_rechaza():
    contenido = PNG_1X1[:8] + b"\x00" * (MAX_LOGO_BYTES + 1)
    with pytest.raises(ValueError, match="2MB"):
        validar_logo(contenido)


def test_justo_en_el_limite_no_rechaza_por_tamano():
    # Exactamente MAX_LOGO_BYTES, con magic bytes de PNG validos al inicio -
    # no debe lanzar por tamano (aunque el resto del contenido sea basura,
    # eso es aceptable: validar_logo no decodifica la imagen completa).
    contenido = PNG_1X1[:8] + b"\x00" * (MAX_LOGO_BYTES - 8)
    assert len(contenido) == MAX_LOGO_BYTES
    assert validar_logo(contenido) == "image/png"


# ─── PUT/GET /admin/config - integracion contra Postgres real ─────────────

@pytest.fixture
async def negocio_temporal():
    async with AsyncSessionLocal() as session:
        negocio = Negocio(nombre="TEST config marca", plan="basico")
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        negocio_id = negocio.id
    yield negocio_id
    async with AsyncSessionLocal() as session:
        await session.execute(Negocio.__table__.delete().where(Negocio.id == negocio_id))
        await session.commit()


async def test_get_config_sin_configurar_trae_null(negocio_temporal):
    async with AsyncSessionLocal() as session:
        out = await main.obtener_config(db=session, x_negocio_id=str(negocio_temporal))
    assert out.logo_url is None
    assert out.color_primario is None
    # pac_url/storage_bucket: hallazgo documentado, siguen siendo el mismo
    # valor mock de siempre - no forman parte de este alcance.
    assert out.pac_url == "https://ws.finkok.com/servicios/soap/stamp.wsdl"


async def test_put_config_persiste_de_verdad(negocio_temporal):
    async with AsyncSessionLocal() as session:
        out = await main.actualizar_config(
            config=main.ConfiguracionUpdate(logo_url="https://ejemplo.mx/logo.png", color_primario="#123ABC"),
            db=session, x_negocio_id=str(negocio_temporal),
        )
    assert out.logo_url == "https://ejemplo.mx/logo.png"
    assert out.color_primario == "#123ABC"

    # Verificacion independiente: releer directo de la BD, no confiar solo
    # en lo que el propio endpoint devolvio.
    async with AsyncSessionLocal() as session:
        result = await session.get(Negocio, negocio_temporal)
        assert result.logo_url == "https://ejemplo.mx/logo.png"
        assert result.color_primario == "#123ABC"


async def test_put_config_color_invalido_es_422(negocio_temporal):
    async with AsyncSessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            await main.actualizar_config(
                config=main.ConfiguracionUpdate(color_primario="rojo"),
                db=session, x_negocio_id=str(negocio_temporal),
            )
    assert exc.value.status_code == 422


async def test_put_config_pac_url_sigue_sin_persistir(negocio_temporal):
    """Hallazgo documentado: pac_url/pac_usuario/pac_password/storage_bucket
    siguen fuera de alcance - se aceptan en el body pero NO deben aparecer
    en ningun lado persistidos (no hay columna para ellos en Negocio)."""
    async with AsyncSessionLocal() as session:
        out = await main.actualizar_config(
            config=main.ConfiguracionUpdate(pac_url="https://otro-pac.example/wsdl", color_primario="#00C896"),
            db=session, x_negocio_id=str(negocio_temporal),
        )
    # La respuesta sigue trayendo el valor mock de siempre, no el que se mando.
    assert out.pac_url == "https://ws.finkok.com/servicios/soap/stamp.wsdl"


# ─── GET /admin/negocios/{id}/branding - sin self-only, con fallback ──────

async def test_branding_de_negocio_configurado(negocio_temporal):
    async with AsyncSessionLocal() as session:
        await main.actualizar_config(
            config=main.ConfiguracionUpdate(logo_url="https://ejemplo.mx/logo.png", color_primario="#00C896"),
            db=session, x_negocio_id=str(negocio_temporal),
        )
    async with AsyncSessionLocal() as session:
        out = await main.obtener_branding_negocio(negocio_id=negocio_temporal, db=session)
    assert out.logo_url == "https://ejemplo.mx/logo.png"
    assert out.color_primario == "#00C896"


async def test_branding_de_negocio_sin_configurar_es_null(negocio_temporal):
    async with AsyncSessionLocal() as session:
        out = await main.obtener_branding_negocio(negocio_id=negocio_temporal, db=session)
    assert out.logo_url is None
    assert out.color_primario is None


async def test_branding_de_negocio_inexistente_no_truena():
    """Portal publico con un negocio_id que no existe (dato corrupto,
    negocio borrado, etc.) - debe caer al fallback, NUNCA 404/500."""
    async with AsyncSessionLocal() as session:
        out = await main.obtener_branding_negocio(negocio_id=999999999, db=session)
    assert out.logo_url is None
    assert out.color_primario is None
