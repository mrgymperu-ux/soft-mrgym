"""Caja conciliable, idempotencia y anulacion de egresos."""

from alembic import op
import sqlalchemy as sa

revision = "0005_caja_conciliacion"
down_revision = "0004_intentos_acceso"
branch_labels = None
depends_on = None


def _add(table, column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table in inspector.get_table_names() and column.name not in {c["name"] for c in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade():
    from backend import models
    bind = op.get_bind()
    models.OperacionIdempotente.__table__.create(bind=bind, checkfirst=True)
    models.TurnoCaja.__table__.create(bind=bind, checkfirst=True)
    for table in ("otros_ingresos", "gastos", "pagos_planilla", "pagos_servicio"):
        _add(table, sa.Column("anulada", sa.Boolean(), nullable=False, server_default=sa.false()))
        _add(table, sa.Column("anulada_en", sa.DateTime(), nullable=True))
        _add(table, sa.Column("anulada_por_id", sa.Integer(), nullable=True))
        _add(table, sa.Column("motivo_anulacion", sa.Text(), nullable=True))


def downgrade():
    # La evidencia financiera no se elimina automaticamente.
    pass
