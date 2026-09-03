"""relajar email de clientes a nullable

Revision ID: c176eed5fc42
Revises: 264eee14da7c
Create Date: 2026-09-03 16:25:51.562291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c176eed5fc42'
down_revision: Union[str, Sequence[str], None] = '264eee14da7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('clientes', 'email', existing_type=sa.String(254), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # No-op seguro: convertir NOT NULL de vuelta seria inseguro si ya
    # existen filas con email NULL para entonces (mismo criterio que
    # 1fca290, migracion del enum de WhatsApp Bot). Si se necesita
    # revertir, backfill manual primero:
    #   UPDATE clientes SET email = '' WHERE email IS NULL;
    #   ALTER TABLE clientes ALTER COLUMN email SET NOT NULL;
    pass
