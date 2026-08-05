"""
Migracion de datos (#34) - cifra en el sitio el CSD que ya existia en texto
plano antes de adoptar cifrado Fernet en el modelo Emisor.

No es una migracion de Alembic: no cambia esquema, transforma valores que
ya viven en las filas. Se corre una sola vez, a mano, ANTES de desplegar el
modelo con cifrado transparente (database.py) - si se corre despues, el
modelo ya intentaria descifrar valores que siguen en texto plano y fallaria
al leerlos.

Idempotente: por cada columna, intenta descifrar el valor actual con
CSD_MASTER_KEY primero. Si el descifrado funciona, la fila ya esta migrada
y se salta. Si falla (InvalidToken), se asume texto plano y se cifra.

Uso (dentro del contenedor de administracion):
    python scripts/migrar_csd_a_cifrado.py
"""
import asyncio
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ["DATABASE_URL"]
CSD_MASTER_KEY = os.environ["CSD_MASTER_KEY"]

fernet = Fernet(CSD_MASTER_KEY.encode())

CAMPOS = ["csd_cert_base64", "csd_key_base64", "csd_password"]


def cifrar_si_hace_falta(valor: str) -> tuple[str, bool]:
    """Devuelve (valor_final, se_modifico)."""
    try:
        fernet.decrypt(valor.encode())
        return valor, False  # ya estaba cifrado
    except InvalidToken:
        return fernet.encrypt(valor.encode()).decode(), True


async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        filas = (await conn.execute(text("SELECT id, rfc, csd_cert_base64, csd_key_base64, csd_password FROM emisores"))).mappings().all()

        if not filas:
            print("No hay emisores en la tabla - nada que migrar.")
            return

        for fila in filas:
            print(f"\n=== Emisor {fila['rfc']} (id={fila['id']}) ===")
            cambios = {}
            for campo in CAMPOS:
                original = fila[campo]
                nuevo, modificado = cifrar_si_hace_falta(original)
                estado = "CIFRADO (nuevo)" if modificado else "ya estaba cifrado, sin cambio"
                print(f"  {campo}: {estado}")
                print(f"    antes: {original[:60]}{'...' if len(original) > 60 else ''} (len={len(original)})")
                print(f"    despues: {nuevo[:60]}...  (len={len(nuevo)})")
                if modificado:
                    cambios[campo] = nuevo

            if cambios:
                set_clause = ", ".join(f"{c} = :{c}" for c in cambios)
                await conn.execute(
                    text(f"UPDATE emisores SET {set_clause} WHERE id = :id"),
                    {**cambios, "id": fila["id"]},
                )
                print(f"  -> fila actualizada en Postgres.")
            else:
                print(f"  -> sin cambios (ya estaba migrada).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
