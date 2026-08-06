"""Intentos de pago de suscripcion SaaS via Izipay (checkout incrustado).

Revision ID: 0019_intento_pago_izipay
Revises: 0018_icono_gimnasio
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_intento_pago_izipay"
down_revision = "0018_icono_gimnasio"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intentos_pago_izipay",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("orden_id", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("gimnasio_id", sa.Integer(), sa.ForeignKey("gimnasios.id"), nullable=False, index=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("planes_saas.id"), nullable=False),
        sa.Column("meses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("moneda", sa.String(), nullable=False, server_default="PEN"),
        sa.Column("estado", sa.String(), nullable=False, server_default="pendiente"),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("confirmado_en", sa.DateTime(), nullable=True),
        sa.Column("pago_id", sa.Integer(), sa.ForeignKey("pagos_saas.id"), nullable=True),
    )


def downgrade():
    op.drop_table("intentos_pago_izipay")
