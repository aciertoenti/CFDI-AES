"""
Migracion de datos (#15) - crea el Negocio por defecto y asigna a el los
emisores existentes que quedaron sin negocio_id (creados antes de que el
modelo de tenants existiera). No es una migracion de Alembic: transforma
datos que ya viven en las filas, no el esquema.

Idempotente: si ya existe un Negocio con el nombre por defecto, lo reusa en
vez de crear uno nuevo; solo toca filas de emisores con negocio_id IS NULL.

Uso (dentro del contenedor de administracion):
    python scripts/backfill_negocio.py
"""
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]

NOMBRE_NEGOCIO_DEFAULT = "Negocio por defecto (pre-tenants)"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        existente = (await conn.execute(
            text("SELECT id FROM negocios WHERE nombre = :nombre"),
            {"nombre": NOMBRE_NEGOCIO_DEFAULT},
        )).scalar_one_or_none()

        if existente is not None:
            negocio_id = existente
            print(f"Negocio por defecto ya existia: id={negocio_id}")
        else:
            negocio_id = (await conn.execute(
                text(
                    "INSERT INTO negocios (nombre, plan, estado) "
                    "VALUES (:nombre, 'basico', 'Activo') RETURNING id"
                ),
                {"nombre": NOMBRE_NEGOCIO_DEFAULT},
            )).scalar_one()
            print(f"Negocio por defecto creado: id={negocio_id}")

        antes = (await conn.execute(
            text("SELECT id, rfc, negocio_id FROM emisores WHERE negocio_id IS NULL")
        )).mappings().all()

        if not antes:
            print("No hay emisores sin negocio_id - nada que rellenar.")
        else:
            print(f"\nEmisores a rellenar ({len(antes)}):")
            for fila in antes:
                print(f"  ANTES: id={fila['id']} rfc={fila['rfc']} negocio_id={fila['negocio_id']}")

            await conn.execute(
                text("UPDATE emisores SET negocio_id = :negocio_id WHERE negocio_id IS NULL"),
                {"negocio_id": negocio_id},
            )

            despues = (await conn.execute(
                text("SELECT id, rfc, negocio_id FROM emisores WHERE id = ANY(:ids)"),
                {"ids": [f["id"] for f in antes]},
            )).mappings().all()
            print(f"\nEmisores actualizados:")
            for fila in despues:
                print(f"  DESPUES: id={fila['id']} rfc={fila['rfc']} negocio_id={fila['negocio_id']}")

    await engine.dispose()
    print(f"\nNEGOCIO_ID_DEFAULT={negocio_id}")


if __name__ == "__main__":
    asyncio.run(main())
