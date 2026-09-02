"""sincronizar enum estadoconversacion con el modelo

Revision ID: 2aeca69f603d
Revises: d572b9264060
Create Date: 2026-09-02 01:25:17.650340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2aeca69f603d'
down_revision: Union[str, None] = 'd572b9264060'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # El tipo nativo estadoconversacion quedo 2 etiquetas atras del enum de
    # Python (models/schemas.py:EstadoConversacion):
    #   - IDENTIFICANDO_TICKETS: drift preexistente, nunca migrado.
    #   - CAPTURA_MONTO: agregado en 4f0bfba (captura del monto real en el flujo).
    # ADD VALUE es aditivo e idempotente (PG 12+); permitido dentro de una
    # transaccion desde PG 12 - la BD del bot es postgres:16.
    op.execute("ALTER TYPE estadoconversacion ADD VALUE IF NOT EXISTS 'IDENTIFICANDO_TICKETS'")
    op.execute("ALTER TYPE estadoconversacion ADD VALUE IF NOT EXISTS 'CAPTURA_MONTO'")


def downgrade() -> None:
    # PostgreSQL no permite quitar un valor de un ENUM sin recrear el tipo
    # (y reescribir toda columna que lo use). El cambio es aditivo e
    # inofensivo, no se revierte.
    pass
