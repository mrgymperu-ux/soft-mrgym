"""Plantillas faciales cifradas y aisladas por gimnasio."""

from alembic import op
import sqlalchemy as sa

revision = "0010_biometria_facial"
down_revision = "0009_simplificacion_sistema"
branch_labels = None
depends_on = None


def upgrade():
    from backend import models

    bind = op.get_bind()
    models.BiometriaFacial.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    # Los datos biometricos son sensibles: no se eliminan automaticamente.
    pass
