"""Permite varios pases de invitado por membresia titular.

Revision ID: 0017_invitaciones_multiples
Revises: 0016_invitados_membresia
"""

from alembic import op


revision = "0017_invitaciones_multiples"
down_revision = "0016_invitados_membresia"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("cliente_membresias") as batch_op:
        batch_op.drop_index("ix_cliente_membresias_invitado_por_cm_id")
        batch_op.create_index(
            "ix_cliente_membresias_invitado_por_cm_id",
            ["invitado_por_cm_id"],
            unique=False,
        )
    # Las invitaciones creadas con la regla anterior podían durar varios
    # días. Desde esta versión cada registro equivale a un solo ingreso.
    op.execute(
        """
        UPDATE cliente_membresias
        SET fecha_fin = fecha_inicio
        WHERE invitado_por_cm_id IS NOT NULL
          AND (fecha_fin IS NULL OR fecha_fin <> fecha_inicio)
        """
    )


def downgrade():
    with op.batch_alter_table("cliente_membresias") as batch_op:
        batch_op.drop_index("ix_cliente_membresias_invitado_por_cm_id")
        batch_op.create_index(
            "ix_cliente_membresias_invitado_por_cm_id",
            ["invitado_por_cm_id"],
            unique=True,
        )
