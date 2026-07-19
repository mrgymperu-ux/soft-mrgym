"""Elimina la configuracion global duplicada; cada gimnasio es su unica fuente."""

from alembic import op
import sqlalchemy as sa

revision = "0009_simplificacion_sistema"
down_revision = "0008_control_documental"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "configuracion" in sa.inspect(bind).get_table_names():
        op.drop_table("configuracion")


def downgrade():
    # No se recrea una fuente global que mezcle gimnasios. Los valores vigentes
    # permanecen en gimnasios y no se pierde configuracion operativa.
    pass
