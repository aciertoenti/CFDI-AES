"""declaraciones anuales estructuradas y tipos de ingreso

Revision ID: 0a1c7c91811f
Revises: 8fe5c70d8102
Create Date: 2026-09-23 17:42:57.994602

ESCRITA A MANO (reporte 189) - alembic revision --autogenerate SOLO
detecto el ALTER TABLE (agregar declaraciones_anuales_documentos.
declaracion_id): las 2 tablas nuevas (declaraciones_anuales,
declaracion_anual_tipos_ingreso) ya habian sido creadas OUT-OF-BAND por
create_tables() (Base.metadata.create_all, que create_all() SI corre
para tablas nuevas aunque nunca modifica una existente) durante un
reinicio del contenedor entre el edit de database.py y la primera
corrida de --autogenerate - mismo patron ya documentado en reportes
183/185 para este mismo servicio. Se dropearon esas 2 tablas
out-of-band antes de escribir esta migracion a mano, y se verifico
aplicando `alembic upgrade head` limpio contra la BD real (ver
entregable, seccion D1, salida real de \\d por tabla).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a1c7c91811f'
down_revision: Union[str, Sequence[str], None] = '8fe5c70d8102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'declaraciones_anuales',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('negocio_id', sa.Integer(), nullable=False),
        sa.Column('emisor_id', sa.Integer(), nullable=False),
        sa.Column('ejercicio', sa.Integer(), nullable=False),
        sa.Column('tipo_declaracion', sa.String(length=20), nullable=False),
        sa.Column('numero_complementaria', sa.Integer(), nullable=True),
        sa.Column('numero_operacion', sa.String(length=50), nullable=True),
        sa.Column('fecha_presentacion', sa.DateTime(), nullable=True),
        sa.Column('saldo_a_favor', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('cantidad_a_cargo', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('cantidad_a_pagar', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('origen', sa.String(length=20), nullable=False),
        sa.Column('creado_por', sa.String(length=20), nullable=True),
        sa.Column('creado_en', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "(tipo_declaracion = 'normal' AND numero_complementaria IS NULL) OR "
            "(tipo_declaracion = 'complementaria' AND numero_complementaria >= 1)",
            name='ck_declaracion_anual_numero_complementaria',
        ),
        sa.CheckConstraint("tipo_declaracion IN ('normal', 'complementaria')", name='ck_declaracion_anual_tipo_declaracion'),
        sa.CheckConstraint("origen IN ('extraido', 'manual')", name='ck_declaracion_anual_origen'),
        sa.ForeignKeyConstraint(['emisor_id'], ['emisores.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # UNIQUE con NULL: Postgres NUNCA considera 2 NULL iguales en una
        # constraint UNIQUE - varias filas con numero_operacion=NULL
        # (origen='manual') conviven sin chocar, sin necesitar un indice
        # parcial con WHERE (a diferencia de ix_efirmas_rfc_titular_activo_unico,
        # que SI necesita WHERE porque ahi la unicidad es sobre un
        # subconjunto de VALOR, no sobre NULL).
        sa.UniqueConstraint('negocio_id', 'emisor_id', 'numero_operacion', name='uq_declaracion_anual_negocio_emisor_num_operacion'),
    )
    op.create_index(op.f('ix_declaraciones_anuales_emisor_id'), 'declaraciones_anuales', ['emisor_id'], unique=False)
    op.create_index(op.f('ix_declaraciones_anuales_ejercicio'), 'declaraciones_anuales', ['ejercicio'], unique=False)
    op.create_index(op.f('ix_declaraciones_anuales_negocio_id'), 'declaraciones_anuales', ['negocio_id'], unique=False)

    op.create_table(
        'declaracion_anual_tipos_ingreso',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('declaracion_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['declaracion_id'], ['declaraciones_anuales.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_declaracion_anual_tipos_ingreso_declaracion_id'), 'declaracion_anual_tipos_ingreso', ['declaracion_id'], unique=False)

    # ### comandos SI detectados por autogenerate (el ALTER a la tabla ya
    # existente) - unica parte real generada automaticamente ###
    op.add_column('declaraciones_anuales_documentos', sa.Column('declaracion_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_declaraciones_anuales_documentos_declaracion_id'), 'declaraciones_anuales_documentos', ['declaracion_id'], unique=False)
    op.create_foreign_key(
        'fk_declaraciones_anuales_documentos_declaracion_id',
        'declaraciones_anuales_documentos', 'declaraciones_anuales',
        ['declaracion_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_declaraciones_anuales_documentos_declaracion_id', 'declaraciones_anuales_documentos', type_='foreignkey')
    op.drop_index(op.f('ix_declaraciones_anuales_documentos_declaracion_id'), table_name='declaraciones_anuales_documentos')
    op.drop_column('declaraciones_anuales_documentos', 'declaracion_id')

    op.drop_index(op.f('ix_declaracion_anual_tipos_ingreso_declaracion_id'), table_name='declaracion_anual_tipos_ingreso')
    op.drop_table('declaracion_anual_tipos_ingreso')

    op.drop_index(op.f('ix_declaraciones_anuales_negocio_id'), table_name='declaraciones_anuales')
    op.drop_index(op.f('ix_declaraciones_anuales_ejercicio'), table_name='declaraciones_anuales')
    op.drop_index(op.f('ix_declaraciones_anuales_emisor_id'), table_name='declaraciones_anuales')
    op.drop_table('declaraciones_anuales')
