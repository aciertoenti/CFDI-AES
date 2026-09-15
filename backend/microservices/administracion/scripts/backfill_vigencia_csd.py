"""
Backfill (one-off) del dashboard multi-emisor (vigencia CSD) - puebla
Emisor.vigencia_csd_hasta para los emisores dados de alta ANTES de que
crear_emisor/actualizar_emisor empezaran a poblarlo al vuelo.

No es una migracion de Alembic: transforma datos que ya viven en las filas,
no el esquema (la columna ya existe, ver migracion
72d545d1cbfe_agregar_vigencia_csd_hasta_a_emisores.py, que debe estar
aplicada ANTES de correr esto).

Idempotente: si un emisor ya tiene vigencia_csd_hasta, se salta (no
reparsea el certificado). Tolera certificados corruptos POR EMISOR - ya
hay un caso real conocido (GWT010101AA1, "error parsing asn1 value:
ShortData") - deja vigencia_csd_hasta en NULL para ese emisor y continua
con los demas; nunca se detiene a medio camino por una fila mala.

Uso (dentro del contenedor de administracion):
    python scripts/backfill_vigencia_csd.py
"""
import asyncio
import base64
import sys

# Permite correr el script desde /app (WORKDIR del contenedor) - mismo
# criterio que el resto de scripts/ de este servicio.
sys.path.insert(0, ".")

from csd_rfc import extraer_vigencia_hasta_de_certificado  # noqa: E402
from database import AsyncSessionLocal, Emisor  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        emisores = (await db.execute(select(Emisor))).scalars().all()
        if not emisores:
            print("No hay emisores en la tabla - nada que hacer.")
            return

        poblados = []
        fallidos = []
        ya_tenian = []

        for e in emisores:
            if e.vigencia_csd_hasta is not None:
                ya_tenian.append(e.rfc)
                continue
            try:
                cert_bytes = base64.b64decode(e.csd_cert_base64)
                vigencia = extraer_vigencia_hasta_de_certificado(cert_bytes)
            except Exception as ex:
                # Deliberadamente amplio (no solo ValueError): un backfill
                # nunca debe tronar a medio camino por un dato existente
                # inesperado (base64 corrupto, certificado truncado, etc.)
                fallidos.append((e.rfc, type(ex).__name__, str(ex)[:150]))
                continue
            e.vigencia_csd_hasta = vigencia
            poblados.append((e.rfc, vigencia.isoformat()))

        if poblados:
            await db.commit()

        print("\n=== Backfill vigencia_csd_hasta ===")
        print(f"Total emisores en la tabla: {len(emisores)}")
        print(f"Ya tenian vigencia (saltados, sin re-parsear): {len(ya_tenian)}")
        print(f"Poblados correctamente en esta corrida: {len(poblados)}")
        for rfc, v in poblados:
            print(f"  OK    {rfc} -> {v}")
        print(f"Fallidos (certificado no parseable, vigencia_csd_hasta queda NULL): {len(fallidos)}")
        for rfc, tipo, msg in fallidos:
            print(f"  FALLO {rfc}: {tipo}: {msg}")


if __name__ == "__main__":
    asyncio.run(main())
