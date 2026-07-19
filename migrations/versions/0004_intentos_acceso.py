"""Bloqueo persistente de intentos de acceso."""

from alembic import op

revision = "0004_intentos_acceso"
down_revision = "0003_anulaciones"
branch_labels = None
depends_on = None


def upgrade():
    from backend import models
    models.IntentoAcceso.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    # Se conserva la evidencia de seguridad deliberadamente.
    pass
