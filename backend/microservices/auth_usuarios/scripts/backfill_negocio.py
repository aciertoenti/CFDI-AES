"""
Migracion de datos (#15) - asigna negocio_id a los usuarios existentes que
quedaron sin el (creados antes de que el modelo de tenants existiera).
No es una migracion de Alembic: transforma datos que ya viven en las
filas, no el esquema.

A diferencia del backfill de administracion, este servicio NO es dueno de
la tabla negocios (vive en otra base de datos, cfdi_admin) - el id del
Negocio por defecto se recibe como argumento, no se genera aqui.

Idempotente: solo toca filas con negocio_id IS NULL.

Uso (dentro del contenedor de auth):
    python scripts/backfill_negocio.py <negocio_id>
"""
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]


async def main(negocio_id: int) -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        antes = (await conn.execute(
            text("SELECT id, email, negocio_id FROM usuarios WHERE negocio_id IS NULL")
        )).mappings().all()

        if not antes:
            print("No hay usuarios sin negocio_id - nada que rellenar.")
            await engine.dispose()
            return

        print(f"Usuarios a rellenar ({len(antes)}):")
        for fila in antes:
            print(f"  ANTES: id={fila['id']} email={fila['email']} negocio_id={fila['negocio_id']}")

        await conn.execute(
            text("UPDATE usuarios SET negocio_id = :negocio_id WHERE negocio_id IS NULL"),
            {"negocio_id": negocio_id},
        )

        despues = (await conn.execute(
            text("SELECT id, email, negocio_id FROM usuarios WHERE id = ANY(:ids)"),
            {"ids": [f["id"] for f in antes]},
        )).mappings().all()
        print(f"\nUsuarios actualizados:")
        for fila in despues:
            print(f"  DESPUES: id={fila['id']} email={fila['email']} negocio_id={fila['negocio_id']}")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python scripts/backfill_negocio.py <negocio_id>")
        sys.exit(1)
    asyncio.run(main(int(sys.argv[1])))
