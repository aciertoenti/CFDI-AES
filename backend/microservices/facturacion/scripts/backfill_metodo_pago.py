"""
Backfill de datos (#40) - rellena metodo_pago para facturas timbradas antes
de agregar esa columna, parseando el atributo MetodoPago del XML ya
guardado en cada fila. No es una migracion de Alembic: no cambia esquema,
transforma valores que ya viven en las filas.

Idempotente: solo toca filas con metodo_pago IS NULL.

Uso (dentro del contenedor de facturacion):
    python scripts/backfill_metodo_pago.py
"""
import asyncio
import os
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]

_METODO_PAGO_RE = re.compile(r'MetodoPago="([A-Z]{3})"')


def extraer_metodo_pago(xml: str) -> str | None:
    m = _METODO_PAGO_RE.search(xml)
    return m.group(1) if m else None


async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        filas = (await conn.execute(
            text("SELECT id, folio, xml FROM facturas WHERE metodo_pago IS NULL")
        )).mappings().all()

        if not filas:
            print("No hay facturas sin metodo_pago - nada que rellenar.")
            return

        print(f"Rellenando {len(filas)} facturas...")
        sin_match = []
        for fila in filas:
            metodo = extraer_metodo_pago(fila["xml"])
            if metodo is None:
                sin_match.append(fila["folio"])
                continue
            await conn.execute(
                text("UPDATE facturas SET metodo_pago = :metodo WHERE id = :id"),
                {"metodo": metodo, "id": fila["id"]},
            )
            print(f"  {fila['folio']}: metodo_pago = {metodo}")

        if sin_match:
            print(f"\nADVERTENCIA - no se pudo extraer MetodoPago del XML en: {sin_match}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
