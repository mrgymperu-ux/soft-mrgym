"""Invitación única vinculada a una matrícula titular.

Revision ID: 0016_invitados_membresia
Revises: 0015_venta_cuenta_saldo
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_invitados_membresia"
down_revision = "0015_venta_cuenta_saldo"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("cliente_membresias") as batch_op:
        batch_op.add_column(sa.Column("invitado_por_cm_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_cliente_membresias_invitado_titular",
            "cliente_membresias",
            ["invitado_por_cm_id"],
            ["id"],
        )
        batch_op.create_index("ix_cliente_membresias_invitado_por_cm_id", ["invitado_por_cm_id"], unique=True)


def downgrade():
    with op.batch_alter_table("cliente_membresias") as batch_op:
        batch_op.drop_index("ix_cliente_membresias_invitado_por_cm_id")
        batch_op.drop_constraint("fk_cliente_membresias_invitado_titular", type_="foreignkey")
        batch_op.drop_column("invitado_por_cm_id")
