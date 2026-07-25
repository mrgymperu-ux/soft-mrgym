"""Icono separado del logo, para instalar el portal como app (PWA).

Revision ID: 0018_icono_gimnasio
Revises: 0017_invitaciones_multiples
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_icono_gimnasio"
down_revision = "0017_invitaciones_multiples"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gimnasios", sa.Column("icono_url", sa.String(), nullable=True))
    op.add_column("gimnasios", sa.Column("icono_datos", sa.LargeBinary(), nullable=True))
    op.add_column("gimnasios", sa.Column("icono_tipo", sa.String(), nullable=True))


def downgrade():
    op.drop_column("gimnasios", "icono_tipo")
    op.drop_column("gimnasios", "icono_datos")
    op.drop_column("gimnasios", "icono_url")
