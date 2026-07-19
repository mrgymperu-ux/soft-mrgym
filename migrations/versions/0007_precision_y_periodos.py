"""Importes exactos y ajustes para periodos conciliados."""

from alembic import op
import sqlalchemy as sa

revision = "0007_precision_y_periodos"
down_revision = "0006_documentos_financieros"
branch_labels = None
depends_on = None


MONETARY_COLUMNS = {
    "planes_saas": ("precio_mensual",),
    "pagos_saas": ("monto",),
    "membresias": ("precio", "monto_inicial", "penalizacion", "monto_mensual"),
    "cliente_membresias": ("monto_pagado",),
    "pagos_membresia": ("monto",),
    "productos": ("precio_compra", "precio_venta"),
    "ventas": ("total", "costo_comision_gym"),
    "detalle_ventas": ("precio_unitario", "subtotal"),
    "compras": ("costo_unitario", "costo_total"),
    "empleados": ("sueldo_fijo_mensual", "tarifa_por_clase", "tarifa_reducida"),
    "clases_dictadas": ("monto_pagado",),
    "pagos_planilla": ("monto_sueldo_fijo", "monto_comision_membresias", "monto_comision_productos", "monto_clases", "monto_total"),
    "cargos_servicio": ("monto_total",),
    "pagos_servicio": ("monto",),
    "conceptos_otro_ingreso": ("monto_sugerido",),
    "otros_ingresos": ("monto",),
    "gastos": ("monto",),
    "metas_mensuales": ("meta_membresias", "meta_productos"),
}


def upgrade():
    from backend import models

    bind = op.get_bind()
    models.AjusteCaja.__table__.create(bind=bind, checkfirst=True)

    # SQLite ya preserva estos valores sin un tipo rigido y recrear todas las
    # tablas seria un riesgo innecesario. PostgreSQL si obtiene NUMERIC exacto.
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, columns in MONETARY_COLUMNS.items():
        if table not in tables:
            continue
        existing = {column["name"]: column["type"] for column in inspector.get_columns(table)}
        for column in columns:
            if column not in existing:
                continue
            op.alter_column(
                table,
                column,
                existing_type=existing[column],
                type_=sa.Numeric(12, 2),
                postgresql_using=f"ROUND({column}::numeric, 2)",
            )


def downgrade():
    # No se vuelve a tipos aproximados ni se elimina evidencia financiera.
    pass
