"""declaraciones_documentos_tipo_documento_acuse

Reporte 189d, R1 - MIGRACION DE DATOS (no de esquema): antes de este
reporte, los documentos que el analizador clasificaba como ACUSE_ANUAL
(origen='extraido' en declaraciones_anuales) se guardaban con
tipo_documento='declaracion' - un residuo del formulario viejo del
reporte 188, cuyo valor por defecto era ese, y que el reporte 189 nunca
corrigio porque en ese momento tipo_documento seguia siendo un campo que
el usuario elegia a mano. Desde 189d (R1), el backend siempre guarda
tipo_documento='acuse' para estos casos (ver main.py,
subir_documento_declaracion_anual) - esta migracion corrige los datos
YA EXISTENTES para que coincidan con la nueva realidad.

Alcance deliberadamente ACOTADO (pedido explicito): solo toca documentos
CON declaracion_id apuntando a una DeclaracionAnual con origen='extraido'
Y tipo_documento='declaracion' actual - las declaraciones con
origen='manual' (si las hay) NUNCA se tocan aqui, sin importar que
tipo_documento tengan.

Reversible: el downgrade revierte exactamente el mismo conjunto (mismo
filtro, tipo_documento invertido). Advertencia real (documentada, no un
bug): si esta migracion se hace downgrade DESPUES de que la aplicacion ya
haya creado documentos NUEVOS con tipo_documento='acuse' via el flujo
normal (main.py, ya no solo datos legacy), el downgrade tambien los
revertiria a 'declaracion' - el downgrade esta pensado para deshacer ESTE
cambio de datos poco despues de aplicarlo, no como un boton reversible en
cualquier momento futuro arbitrario (mismo criterio de cualquier
migracion de datos, no es particular de esta).

Revision ID: 4db101a508ca
Revises: 0a1c7c91811f
Create Date: 2026-09-23 23:51:37.846138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4db101a508ca'
down_revision: Union[str, Sequence[str], None] = '0a1c7c91811f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FILTRO_UPGRADE = """
    d.declaracion_id IN (SELECT id FROM declaraciones_anuales WHERE origen = 'extraido')
    AND d.tipo_documento = 'declaracion'
"""
_FILTRO_DOWNGRADE = """
    d.declaracion_id IN (SELECT id FROM declaraciones_anuales WHERE origen = 'extraido')
    AND d.tipo_documento = 'acuse'
"""


def upgrade() -> None:
    """declaracion -> acuse, SOLO para documentos de declaraciones con
    origen='extraido' (nunca 'manual'). Conteo antes/despues impreso a
    stdout (visible en `alembic upgrade head`) para verificacion real,
    no solo asumida."""
    conn = op.get_bind()

    antes = conn.execute(sa.text(
        f"SELECT count(*) FROM declaraciones_anuales_documentos d WHERE {_FILTRO_UPGRADE}"
    )).scalar()
    print(f"[4db101a508ca] documentos a corregir (declaracion->acuse, origen=extraido): {antes}")

    conn.execute(sa.text(
        f"UPDATE declaraciones_anuales_documentos d SET tipo_documento = 'acuse' WHERE {_FILTRO_UPGRADE}"
    ))

    despues = conn.execute(sa.text(
        f"SELECT count(*) FROM declaraciones_anuales_documentos d WHERE {_FILTRO_UPGRADE}"
    )).scalar()
    print(f"[4db101a508ca] documentos restantes con tipo_documento='declaracion' (origen=extraido) tras la corrección: {despues}")


def downgrade() -> None:
    """Revierte exactamente el mismo conjunto (ver advertencia arriba
    sobre datos nuevos creados despues de esta migracion)."""
    conn = op.get_bind()

    antes = conn.execute(sa.text(
        f"SELECT count(*) FROM declaraciones_anuales_documentos d WHERE {_FILTRO_DOWNGRADE}"
    )).scalar()
    print(f"[4db101a508ca] documentos a revertir (acuse->declaracion, origen=extraido): {antes}")

    conn.execute(sa.text(
        f"UPDATE declaraciones_anuales_documentos d SET tipo_documento = 'declaracion' WHERE {_FILTRO_DOWNGRADE}"
    ))

    despues = conn.execute(sa.text(
        f"SELECT count(*) FROM declaraciones_anuales_documentos d WHERE {_FILTRO_DOWNGRADE}"
    )).scalar()
    print(f"[4db101a508ca] documentos restantes con tipo_documento='acuse' (origen=extraido) tras revertir: {despues}")
