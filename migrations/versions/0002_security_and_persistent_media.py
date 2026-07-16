"""Seguridad, sesiones, auditoría y medios persistentes."""

from alembic import op
import sqlalchemy as sa

revision = "0002_security_media"
down_revision = "0001_baseline"
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
    for table in (models.TokenAutenticacion.__table__, models.InvitacionUsuario.__table__, models.SesionUsuario.__table__, models.EventoAuditoria.__table__):
        table.create(bind=bind, checkfirst=True)
    _add("usuarios", sa.Column("email", sa.String(), nullable=True))
    _add("usuarios", sa.Column("email_verificado", sa.Boolean(), server_default=sa.false(), nullable=True))
    _add("usuarios", sa.Column("sesion_version", sa.Integer(), server_default="1", nullable=True))
    _add("gimnasios", sa.Column("logo_datos", sa.LargeBinary(), nullable=True))
    _add("gimnasios", sa.Column("logo_tipo", sa.String(), nullable=True))
    _add("gimnasios", sa.Column("logo_oscuro_datos", sa.LargeBinary(), nullable=True))
    _add("gimnasios", sa.Column("logo_oscuro_tipo", sa.String(), nullable=True))
    _add("tipos_ejercicio", sa.Column("imagen_datos", sa.LargeBinary(), nullable=True))
    _add("tipos_ejercicio", sa.Column("imagen_tipo", sa.String(), nullable=True))


def downgrade():
    # No se eliminan datos de seguridad ni imágenes automáticamente.
    pass
