"""Expedientes contables, correlativos y datos fiscales del gimnasio."""

from alembic import op
import sqlalchemy as sa

revision = "0008_control_documental"
down_revision = "0007_precision_y_periodos"
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
    _add("gimnasios", sa.Column("ruc", sa.String(length=11), nullable=True))
    _add("gimnasios", sa.Column("razon_social", sa.String(length=200), nullable=True))
    _add("gimnasios", sa.Column("regimen_tributario", sa.String(length=60), nullable=True))
    models.CorrelativoDocumento.__table__.create(bind=bind, checkfirst=True)
    models.DocumentoFinanciero.__table__.create(bind=bind, checkfirst=True)
    models.DocumentoArchivo.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    # Los documentos y sus archivos son evidencia; no se eliminan automaticamente.
    pass
