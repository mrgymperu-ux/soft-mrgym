"""Horario semanal compacto para el staff."""

from alembic import op
import sqlalchemy as sa

revision = "0011_horario_staff"
down_revision = "0010_biometria_facial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columnas = {columna["name"] for columna in inspector.get_columns("empleados")}
    if "horario_semanal" not in columnas:
        with op.batch_alter_table("empleados") as batch_op:
            batch_op.add_column(sa.Column("horario_semanal", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    # Se conserva el horario para no perder configuracion del personal.
    pass
