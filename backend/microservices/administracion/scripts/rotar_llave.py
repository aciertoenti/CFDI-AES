"""
Script de rotacion de llaves maestras (CSD/EFIRMA/DECLARACIONES) sin
perdida de datos - reporte 186 (EFIRMA_MASTER_KEY se expuso en una
salida de herramienta durante el reporte 185, motivo real de esta
tarea).

Uso (dentro del contenedor de administracion):
    python scripts/rotar_llave.py --llave EFIRMA
    python scripts/rotar_llave.py --llave CSD
    python scripts/rotar_llave.py --llave DECLARACIONES

Requiere que <LLAVE>_MASTER_KEY_ANTERIOR (la llave VIEJA) y
<LLAVE>_MASTER_KEY (la llave NUEVA, actual) esten AMBAS en el entorno -
ver _construir_fernet en database.py. Si _ANTERIOR no esta configurada,
el script sigue funcionando (re-cifra con la unica llave disponible,
inofensivo) pero no tiene sentido correrlo sin una rotacion en curso.

Trabaja con SQL crudo (mismo patron ya establecido en
migrar_csd_a_cifrado.py), NO con el ORM: asi se lee/escribe el valor
CIFRADO directamente, sin pasar por el descifrado/cifrado transparente
de CifradoFernet/CifradoFernetBinario (emisores, declaraciones) -
uniforme para las 3 llaves sin importar si su tabla usa un
TypeDecorator o cifrado explicito en los endpoints (caso de EFIRMA,
ver comentario en database.py).

MultiFernet.rotate(token) descifra el token con CUALQUIERA de las 2
llaves configuradas (actual o anterior, en ese orden) y lo re-cifra
SIEMPRE con la actual (la primera de la lista) - asi una fila ya
migrada (cifrada con la actual) y una fila aun sin migrar (cifrada con
la anterior) se procesan identico, sin necesitar saber de antemano cual
es cual. Fernet (sin MultiFernet, cuando no hay _ANTERIOR) tambien
expone .rotate() con la misma firma.

UNA sola transaccion (engine.begin(), mismo patron que
migrar_csd_a_cifrado.py): si CUALQUIER fila falla (ninguna de las 2
llaves la descifra, o cualquier otro error), la transaccion completa se
revierte via rollback automatico de engine.begin() al propagar la
excepcion - no queda ninguna fila a medio re-cifrar.

Idempotente: correrlo de nuevo sobre filas YA re-cifradas con la llave
actual sigue funcionando sin dañar nada (rotate() vuelve a descifrar
con la actual y re-cifra con la actual otra vez - produce un token
nuevo, distinto byte a byte del anterior por el IV/timestamp propios de
Fernet, pero funcionalmente identico: mismo texto plano al descifrar).

Nunca imprime valores cifrados ni descifrados, llaves, ni contraseñas -
solo conteos (filas_procesadas / total_filas).
"""
import argparse
import asyncio
import os
import sys

from database import _construir_fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# tabla, columnas de TEXTO (str, token Fernet como string) y columnas
# BINARIAS (bytes, token Fernet como bytes) cifradas con cada llave -
# ver database.py (CifradoFernet vs CifradoFernetBinario) y el
# comentario de EFIRMA_MASTER_KEY sobre cifrado explicito en los
# endpoints (efirmas.key_base64_cifrado/password_cifrado son Text
# planas, NO pasan por un TypeDecorator).
_CONFIG = {
    "CSD": {
        "tabla": "emisores",
        "columnas_texto": ["csd_cert_base64", "csd_key_base64", "csd_password"],
        "columnas_binarias": [],
    },
    "EFIRMA": {
        "tabla": "efirmas",
        "columnas_texto": ["key_base64_cifrado", "password_cifrado"],
        "columnas_binarias": [],
    },
    "DECLARACIONES": {
        "tabla": "declaraciones_anuales_documentos",
        "columnas_texto": [],
        "columnas_binarias": ["contenido_cifrado"],
    },
}


async def rotar(
    nombre_llave: str,
    database_url: str | None = None,
    config: dict | None = None,
) -> tuple[int, int]:
    """Re-cifra todas las filas de la tabla asociada a <nombre_llave> en
    UNA sola transaccion. Devuelve (filas_procesadas, total_filas).

    database_url y config son opcionales, SOLO para los tests (ver
    tests/test_rotar_llave.py): database_url apunta a una BD de prueba
    en vez de os.environ["DATABASE_URL"], y config sustituye la entrada
    de _CONFIG por una tabla de prueba desechable (nunca las 3 tablas
    reales) - asi el script se prueba de verdad contra Postgres (SQL,
    transaccion, rollback) sin tocar efirmas/emisores/
    declaraciones_anuales_documentos ni con datos sinteticos. nombre_llave
    sigue siendo el nombre real de la variable de entorno que arma la
    llave Fernet/MultiFernet (via _construir_fernet) en ambos casos."""
    cfg = config if config is not None else _CONFIG.get(nombre_llave)
    if cfg is None:
        raise ValueError(f"Llave desconocida: {nombre_llave!r} (validas: {sorted(_CONFIG)})")

    fernet = _construir_fernet(f"{nombre_llave}_MASTER_KEY")
    columnas = cfg["columnas_texto"] + cfg["columnas_binarias"]
    tabla = cfg["tabla"]

    engine = create_async_engine(database_url or os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            filas = (
                await conn.execute(text(f"SELECT id, {', '.join(columnas)} FROM {tabla}"))
            ).mappings().all()
            total = len(filas)
            procesadas = 0

            for fila in filas:
                cambios = {}
                for col in cfg["columnas_texto"]:
                    cambios[col] = fernet.rotate(fila[col].encode()).decode()
                for col in cfg["columnas_binarias"]:
                    cambios[col] = fernet.rotate(bytes(fila[col]))

                set_clause = ", ".join(f"{c} = :{c}" for c in cambios)
                await conn.execute(
                    text(f"UPDATE {tabla} SET {set_clause} WHERE id = :id"),
                    {**cambios, "id": fila["id"]},
                )
                procesadas += 1

            # Si algo de arriba lanza (InvalidToken de una fila que no
            # descifra con ninguna llave, error de conexion, etc.), esta
            # linea nunca se alcanza - engine.begin() revierte todo al
            # propagarse la excepcion, no queda ninguna fila a medias.
            return procesadas, total
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rota una llave maestra sin perdida de datos (reporte 186).")
    parser.add_argument("--llave", required=True, choices=sorted(_CONFIG), help="CSD | EFIRMA | DECLARACIONES")
    args = parser.parse_args()

    procesadas, total = asyncio.run(rotar(args.llave))
    print(f"filas_procesadas={procesadas} total_filas={total}")
    if procesadas != total:
        print("ADVERTENCIA: procesadas != total", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
