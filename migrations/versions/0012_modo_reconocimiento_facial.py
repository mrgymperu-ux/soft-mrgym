"""Modo configurable para reconocimiento facial.

Revision ID: 0012_modo_reconocimiento_facial
Revises: 0011_horario_semanal_staff
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_modo_reconocimiento_facial"
down_revision = "0011_horario_staff"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "gimnasios",
        sa.Column("reconocimiento_facial_modo", sa.String(length=20), nullable=False, server_default="desactivado"),
    )


def downgrade():
    op.drop_column("gimnasios", "reconocimiento_facial_modo")
