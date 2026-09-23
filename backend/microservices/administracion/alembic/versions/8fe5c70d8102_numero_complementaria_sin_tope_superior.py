"""numero_complementaria sin tope superior

Revision ID: 8fe5c70d8102
Revises: e99c6581cc3d
Create Date: 2026-09-23 06:03:10.606024

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8fe5c70d8102'
down_revision: Union[str, Sequence[str], None] = 'e99c6581cc3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Escrita a mano (reporte 185/C3, 22 sep 2026): Alembic autogenerate NO
# detecta cambios de CHECK constraint por defecto (limitacion conocida,
# confirmado aqui mismo - el autogenerate corrido para esta revision
# genero un archivo vacio, "pass"/"pass", pese a que el modelo real SI
# cambio). Reemplaza el CHECK original (numero_complementaria BETWEEN 1
# AND 3) por uno sin tope superior (numero_complementaria >= 1) - el
# limite de 3 (regla general de Art. 32 CFF) tiene excepciones legales
# reales que un numero_complementaria=4+ debe poder representar.

def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        'ck_declaracion_doc_numero_complementaria',
        'declaraciones_anuales_documentos',
        type_='check',
    )
    op.create_check_constraint(
        'ck_declaracion_doc_numero_complementaria',
        'declaraciones_anuales_documentos',
        "(tipo_declaracion = 'normal' AND numero_complementaria IS NULL) OR "
        "(tipo_declaracion = 'complementaria' AND numero_complementaria >= 1)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'ck_declaracion_doc_numero_complementaria',
        'declaraciones_anuales_documentos',
        type_='check',
    )
    op.create_check_constraint(
        'ck_declaracion_doc_numero_complementaria',
        'declaraciones_anuales_documentos',
        "(tipo_declaracion = 'normal' AND numero_complementaria IS NULL) OR "
        "(tipo_declaracion = 'complementaria' AND numero_complementaria BETWEEN 1 AND 3)",
    )
