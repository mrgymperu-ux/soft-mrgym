"""Anulacion auditable de membresias asignadas y cargos de servicio."""

from alembic import op
import sqlalchemy as sa

revision = "0006_documentos_financieros"
down_revision = "0005_caja_conciliacion"
branch_labels = None
depends_on = None


def _add(table, column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table in inspector.get_table_names() and column.name not in {c["name"] for c in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade():
    for table in ("cliente_membresias", "cargos_servicio"):
        _add(table, sa.Column("anulada", sa.Boolean(), nullable=False, server_default=sa.false()))
        _add(table, sa.Column("anulada_en", sa.DateTime(), nullable=True))
        _add(table, sa.Column("anulada_por_id", sa.Integer(), nullable=True))
        _add(table, sa.Column("motivo_anulacion", sa.Text(), nullable=True))


def downgrade():
    pass
