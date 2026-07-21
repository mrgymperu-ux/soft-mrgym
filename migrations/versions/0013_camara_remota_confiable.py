"""Camara remota confiable.

Revision ID: 0013_camara_remota
Revises: 0012_modo_reconocimiento_facial
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_camara_remota"
down_revision = "0012_modo_reconocimiento_facial"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("gimnasios", sa.Column("camara_remota_token_hash", sa.String(length=64), nullable=True))

def downgrade():
    op.drop_column("gimnasios", "camara_remota_token_hash")
