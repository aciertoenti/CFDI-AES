"""
Tests de scripts/rotar_llave.py contra una tabla de PRUEBA desechable
("rotacion_test_tabla"), creada y borrada por estos mismos tests -
NUNCA toca efirmas/emisores/declaraciones_anuales_documentos reales.
Llaves SINTETICAS generadas aqui (Fernet.generate_key()), nunca las
llaves reales del .env. Reporte 186.

Se usa el mismo Postgres que el resto de los tests de administracion
(os.environ["DATABASE_URL"], real, no un mock) precisamente porque R3
pide probar el script CONTRA UNA BD real (SQL crudo, transaccion,
rollback) - el aislamiento viene de la tabla desechable, no de una BD
separada.
"""
import os

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet, InvalidToken
from rotar_llave import rotar
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

NOMBRE_LLAVE = "TEST_ROTACION_SCRIPT"
TABLA = "rotacion_test_tabla"
CONFIG = {
    "tabla": TABLA,
    "columnas_texto": ["col_texto"],
    "columnas_binarias": ["col_binaria"],
}


@pytest_asyncio.fixture
async def tabla_prueba():
    """Crea la tabla desechable antes del test, la borra despues -
    aislada por completo de las tablas reales (nombre distinto, nunca
    coincide con efirmas/emisores/declaraciones_anuales_documentos)."""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {TABLA} (id SERIAL PRIMARY KEY, col_texto TEXT NOT NULL, col_binaria BYTEA NOT NULL)"
        ))
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLA}"))
    await engine.dispose()


async def _insertar_fila(engine, fernet_para_insertar, texto: bytes, binario: bytes):
    async with engine.begin() as conn:
        await conn.execute(
            text(f"INSERT INTO {TABLA} (col_texto, col_binaria) VALUES (:t, :b)"),
            {
                "t": fernet_para_insertar.encrypt(texto).decode(),
                "b": fernet_para_insertar.encrypt(binario),
            },
        )


async def _leer_filas(engine):
    async with engine.begin() as conn:
        return (await conn.execute(text(f"SELECT id, col_texto, col_binaria FROM {TABLA} ORDER BY id"))).mappings().all()


@pytest.mark.asyncio
async def test_happy_path_rota_texto_y_binario(tabla_prueba, monkeypatch):
    engine = tabla_prueba
    llave_vieja = Fernet.generate_key()
    llave_nueva = Fernet.generate_key()
    fernet_vieja = Fernet(llave_vieja)

    # 3 filas, todas cifradas con la llave VIEJA (simula el estado antes
    # de la rotacion).
    for i in range(3):
        await _insertar_fila(engine, fernet_vieja, f"texto plano {i}".encode(), f"binario {i}".encode())

    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY", llave_nueva.decode())
    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY_ANTERIOR", llave_vieja.decode())

    procesadas, total = await rotar(NOMBRE_LLAVE, database_url=os.environ["DATABASE_URL"], config=CONFIG)
    assert (procesadas, total) == (3, 3)

    filas = await _leer_filas(engine)
    assert len(filas) == 3
    fernet_nueva_sola = Fernet(llave_nueva)
    for i, fila in enumerate(filas):
        # Descifra con la NUEVA sola - confirma que quedo re-cifrada con
        # la actual, no con la vieja.
        assert fernet_nueva_sola.decrypt(fila["col_texto"].encode()) == f"texto plano {i}".encode()
        assert fernet_nueva_sola.decrypt(bytes(fila["col_binaria"])) == f"binario {i}".encode()
        # Y la VIEJA sola ya NO la descifra - la rotacion realmente
        # cambio la llave con la que quedo cifrada, no fue un no-op.
        with pytest.raises(InvalidToken):
            fernet_vieja.decrypt(fila["col_texto"].encode())


@pytest.mark.asyncio
async def test_idempotente_correrlo_dos_veces_no_dana_nada(tabla_prueba, monkeypatch):
    engine = tabla_prueba
    llave_vieja = Fernet.generate_key()
    llave_nueva = Fernet.generate_key()
    await _insertar_fila(engine, Fernet(llave_vieja), b"texto idempotente", b"binario idempotente")

    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY", llave_nueva.decode())
    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY_ANTERIOR", llave_vieja.decode())

    primera = await rotar(NOMBRE_LLAVE, database_url=os.environ["DATABASE_URL"], config=CONFIG)
    segunda = await rotar(NOMBRE_LLAVE, database_url=os.environ["DATABASE_URL"], config=CONFIG)
    assert primera == (1, 1)
    assert segunda == (1, 1)

    filas = await _leer_filas(engine)
    fernet_nueva_sola = Fernet(llave_nueva)
    assert fernet_nueva_sola.decrypt(filas[0]["col_texto"].encode()) == b"texto idempotente"
    assert fernet_nueva_sola.decrypt(bytes(filas[0]["col_binaria"])) == b"binario idempotente"


@pytest.mark.asyncio
async def test_una_fila_ilegible_revierte_la_transaccion_completa(tabla_prueba, monkeypatch):
    """Si UNA fila esta cifrada con una llave que ni la actual ni la
    anterior pueden descifrar (dato corrupto/ajeno), rotar() debe
    fallar y NINGUNA fila debe quedar modificada - ni siquiera las que
    si se hubieran podido procesar antes de llegar a la mala."""
    engine = tabla_prueba
    llave_vieja = Fernet.generate_key()
    llave_nueva = Fernet.generate_key()
    llave_ajena = Fernet.generate_key()

    await _insertar_fila(engine, Fernet(llave_vieja), b"fila buena 1", b"bin buena 1")
    await _insertar_fila(engine, Fernet(llave_ajena), b"fila ilegible", b"bin ilegible")  # ni actual ni anterior la descifran
    await _insertar_fila(engine, Fernet(llave_vieja), b"fila buena 2", b"bin buena 2")

    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY", llave_nueva.decode())
    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY_ANTERIOR", llave_vieja.decode())

    filas_antes = await _leer_filas(engine)

    with pytest.raises(InvalidToken):
        await rotar(NOMBRE_LLAVE, database_url=os.environ["DATABASE_URL"], config=CONFIG)

    filas_despues = await _leer_filas(engine)
    # Ni una sola fila cambio - rollback completo, incluida la fila 1
    # (buena) que se proceso ANTES de llegar a la fila ilegible.
    assert filas_antes == filas_despues


@pytest.mark.asyncio
async def test_tabla_vacia_no_falla(tabla_prueba, monkeypatch):
    llave = Fernet.generate_key()
    monkeypatch.setenv(f"{NOMBRE_LLAVE}_MASTER_KEY", llave.decode())
    monkeypatch.delenv(f"{NOMBRE_LLAVE}_MASTER_KEY_ANTERIOR", raising=False)

    procesadas, total = await rotar(NOMBRE_LLAVE, database_url=os.environ["DATABASE_URL"], config=CONFIG)
    assert (procesadas, total) == (0, 0)


def test_llave_config_desconocida_lanza_valueerror():
    """Sin `config` explicito y con un nombre de llave que no esta en
    _CONFIG, debe fallar rapido con un mensaje claro (no un KeyError
    critico ni un intento de tocar una tabla inexistente)."""
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(rotar("LLAVE_QUE_NO_EXISTE"))
