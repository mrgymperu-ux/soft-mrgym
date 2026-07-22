"""Ventas al personal descontadas de su saldo de planilla.

Revision ID: 0015_venta_cuenta_saldo
Revises: 0014_beneficio_invitado
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_venta_cuenta_saldo"
down_revision = "0014_beneficio_invitado"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE metodopago ADD VALUE IF NOT EXISTS 'CUENTA_SALDO'")

    with op.batch_alter_table("ventas") as batch_op:
        batch_op.add_column(sa.Column("empleado_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pago_planilla_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_ventas_empleado", "empleados", ["empleado_id"], ["id"])
        batch_op.create_foreign_key("fk_ventas_pago_planilla", "pagos_planilla", ["pago_planilla_id"], ["id"])
        batch_op.create_index("ix_ventas_empleado_id", ["empleado_id"])
        batch_op.create_unique_constraint("uq_ventas_pago_planilla_id", ["pago_planilla_id"])


def downgrade():
    with op.batch_alter_table("ventas") as batch_op:
        batch_op.drop_constraint("uq_ventas_pago_planilla_id", type_="unique")
        batch_op.drop_index("ix_ventas_empleado_id")
        batch_op.drop_constraint("fk_ventas_pago_planilla", type_="foreignkey")
        batch_op.drop_constraint("fk_ventas_empleado", type_="foreignkey")
        batch_op.drop_column("pago_planilla_id")
        batch_op.drop_column("empleado_id")
    # PostgreSQL no permite quitar de forma segura un valor ENUM en uso.
