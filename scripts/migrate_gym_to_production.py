"""Migracion transaccional de un gimnasio SQLite hacia PostgreSQL.

La herramienta nunca borra datos del destino. Antes de ejecutar crea un
respaldo JSON comprimido de todas las tablas de produccion. Los IDs se
reasignan y todas las llaves foraneas se traducen dentro de una transaccion.

Ejemplos:
    python scripts/migrate_gym_to_production.py --target-url-file URL --audit
    python scripts/migrate_gym_to_production.py --target-url-file URL --execute
"""

from __future__ import annotations

import argparse
import base64
import enum
import gzip
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.schema import Table


TABLE_ORDER = [
    "puestos",
    "empleados",
    "usuarios",
    "suscripciones_saas",
    "clientes",
    "clientes_historicos",
    "membresias",
    "cliente_membresias",
    "pagos_membresia",
    "productos",
    "ventas",
    "detalle_ventas",
    "compras",
    "asistencias",
    "progresos",
    "tipos_ejercicio",
    "rutinas",
    "rutina_dias",
    "rutina_ejercicios",
    "paquetes_rutina",
    "paquete_rutina_dias",
    "paquete_rutina_ejercicios",
    "alimentos",
    "planes_nutricion",
    "comidas_plan",
    "paquetes_nutricion",
    "paquete_alimentos",
    "retos",
    "asistencias_empleado",
    "clases_dictadas",
    "conceptos_otro_ingreso",
    "reservas_sala",
    "otros_ingresos",
    "pagos_planilla",
    "servicios",
    "cargos_servicio",
    "pagos_servicio",
    "gastos",
    "metas_mensuales",
    "tramos_comision",
    "medidas",
    "pagos_saas",
]

# Tablas sin gimnasio_id que pertenecen al gimnasio por medio de su padre.
CHILD_SCOPE = {
    "cliente_membresias": ("clientes", "cliente_id"),
    "pagos_membresia": ("cliente_membresias", "cliente_membresia_id"),
    "detalle_ventas": ("ventas", "venta_id"),
    "rutina_dias": ("rutinas", "rutina_id"),
    "rutina_ejercicios": ("rutina_dias", "dia_id"),
    "paquete_rutina_dias": ("paquetes_rutina", "paquete_id"),
    "paquete_rutina_ejercicios": ("paquete_rutina_dias", "dia_id"),
    "comidas_plan": ("planes_nutricion", "plan_id"),
    "paquete_alimentos": ("paquetes_nutricion", "paquete_id"),
    "asistencias_empleado": ("empleados", "empleado_id"),
    "pagos_servicio": ("cargos_servicio", "cargo_id"),
}

GLOBAL_TABLES = {"planes_saas", "configuracion"}

OPERATIONAL_TABLES = {
    "usuarios", "clientes", "clientes_historicos", "cliente_membresias",
    "pagos_membresia", "ventas", "detalle_ventas", "compras", "asistencias",
    "progresos", "rutinas", "rutina_dias", "rutina_ejercicios",
    "empleados", "asistencias_empleado",
    "clases_dictadas", "reservas_sala", "otros_ingresos", "pagos_planilla",
    "cargos_servicio", "pagos_servicio", "gastos", "medidas", "pagos_saas",
}


def _read_url(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value.removeprefix("postgres://")
    if not value.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise RuntimeError("El archivo temporal no contiene una URL PostgreSQL valida")
    return value


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, enum.Enum):
        return {"__type__": "enum", "value": value.value}
    if isinstance(value, bytes):
        return {"__type__": "bytes", "value": base64.b64encode(value).decode("ascii")}
    return {"__type__": type(value).__name__, "value": str(value)}


def backup_database(engine: Engine, metadata: MetaData, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = backup_dir / f"supabase-antes-mrgym-{stamp}.json.gz"
    payload: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "purpose": "Respaldo previo a migracion de MrGym",
        "tables": {},
    }
    with engine.connect() as conn:
        for table_name in sorted(metadata.tables):
            table = metadata.tables[table_name]
            rows = conn.execute(select(table)).mappings().all()
            payload["tables"][table_name] = [
                {key: _json_value(value) for key, value in row.items()} for row in rows
            ]
    with gzip.open(output, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    return output


def reflect(engine: Engine) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata


def select_source_gym(conn: Connection, table: Table, gym_id: int | None) -> dict[str, Any]:
    stmt = select(table)
    if gym_id is not None:
        stmt = stmt.where(table.c.id == gym_id)
    else:
        stmt = stmt.order_by(table.c.id)
    rows = conn.execute(stmt).mappings().all()
    if gym_id is None and len(rows) != 1:
        choices = ", ".join(f"{row['id']}:{row['nombre']}" for row in rows)
        raise RuntimeError(f"Indica --source-gym-id. Gimnasios locales: {choices}")
    if not rows:
        raise RuntimeError("No existe el gimnasio local solicitado")
    return dict(rows[0])


def build_plan_map(
    source_conn: Connection,
    target_conn: Connection,
    source_meta: MetaData,
    target_meta: MetaData,
) -> dict[int, int]:
    if "planes_saas" not in source_meta.tables or "planes_saas" not in target_meta.tables:
        return {}
    source_table = source_meta.tables["planes_saas"]
    target_table = target_meta.tables["planes_saas"]
    source_rows = source_conn.execute(select(source_table)).mappings().all()
    target_rows = target_conn.execute(select(target_table)).mappings().all()
    target_by_name = {str(row["nombre"]).strip().casefold(): row["id"] for row in target_rows}
    mapping: dict[int, int] = {}
    for row in source_rows:
        name = str(row["nombre"]).strip().casefold()
        if name in target_by_name:
            mapping[row["id"]] = target_by_name[name]
    return mapping


def collect_source_rows(
    conn: Connection,
    metadata: MetaData,
    gym_id: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, set[int]]]:
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    ids_by_table: dict[str, set[int]] = {}
    for table_name in TABLE_ORDER:
        if table_name not in metadata.tables:
            continue
        table = metadata.tables[table_name]
        if "gimnasio_id" in table.c:
            stmt = select(table).where(table.c.gimnasio_id == gym_id)
        elif table_name in CHILD_SCOPE:
            parent_name, fk_column = CHILD_SCOPE[table_name]
            parent_ids = ids_by_table.get(parent_name, set())
            if not parent_ids:
                rows: list[dict[str, Any]] = []
                rows_by_table[table_name] = rows
                ids_by_table[table_name] = set()
                continue
            stmt = select(table).where(table.c[fk_column].in_(parent_ids))
        else:
            continue
        rows = [dict(row) for row in conn.execute(stmt).mappings().all()]
        rows_by_table[table_name] = rows
        if "id" in table.c:
            ids_by_table[table_name] = {int(row["id"]) for row in rows}
    return rows_by_table, ids_by_table


def find_unhandled_gym_tables(metadata: MetaData) -> list[str]:
    handled = set(TABLE_ORDER) | {"gimnasios"} | GLOBAL_TABLES
    return sorted(
        name for name, table in metadata.tables.items()
        if "gimnasio_id" in table.c and name not in handled
    )


def source_target_summary(
    source_conn: Connection,
    target_conn: Connection,
    source_meta: MetaData,
    target_meta: MetaData,
    source_gym: dict[str, Any],
    source_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    target_gyms = target_conn.execute(select(target_meta.tables["gimnasios"])).mappings().all()
    target_users = target_conn.execute(select(target_meta.tables["usuarios"])).mappings().all()
    source_users = source_rows.get("usuarios", [])
    target_usernames = {str(row["username"]).casefold() for row in target_users}
    collisions = sorted(
        str(row["username"]) for row in source_users
        if str(row["username"]).casefold() in target_usernames
    )
    slug_collision = any(row["slug"] == source_gym["slug"] for row in target_gyms)
    target_counts: dict[str, dict[str, int]] = {}
    for gym in target_gyms:
        gym_counts: dict[str, int] = {}
        for table_name in TABLE_ORDER:
            table = target_meta.tables.get(table_name)
            if table is None or "gimnasio_id" not in table.c:
                continue
            count = int(target_conn.scalar(
                select(func.count()).select_from(table).where(table.c.gimnasio_id == gym["id"])
            ) or 0)
            if count:
                gym_counts[table_name] = count
        target_counts[str(gym["id"])] = gym_counts
    return {
        "source_gym": {
            "id": source_gym["id"],
            "nombre": source_gym["nombre"],
            "slug": source_gym["slug"],
        },
        "target_gyms": [
            {"id": row["id"], "nombre": row["nombre"], "slug": row["slug"]}
            for row in target_gyms
        ],
        "counts": {name: len(rows) for name, rows in source_rows.items() if rows},
        "target_counts": target_counts,
        "username_collisions": collisions,
        "slug_collision": slug_collision,
    }


def insert_batch(
    conn: Connection,
    table: Table,
    values: list[dict[str, Any]],
    old_ids: list[int],
    batch_size: int = 250,
) -> dict[int, int]:
    if not values:
        return {}
    mapping: dict[int, int] = {}
    pk = table.c.id
    statement = insert(table).returning(pk, sort_by_parameter_order=True)
    for offset in range(0, len(values), batch_size):
        batch = values[offset:offset + batch_size]
        batch_old_ids = old_ids[offset:offset + batch_size]
        new_ids = list(conn.execute(statement, batch).scalars())
        if len(new_ids) != len(batch_old_ids):
            raise RuntimeError(f"No se pudieron correlacionar IDs de {table.name}")
        mapping.update(zip(batch_old_ids, map(int, new_ids)))
    return mapping


def clear_seed_only_target_gym(
    conn: Connection,
    metadata: MetaData,
    gym_id: int,
) -> dict[str, int]:
    rows_by_table, ids_by_table = collect_source_rows(conn, metadata, gym_id)
    populated = {
        name: len(rows_by_table.get(name, []))
        for name in OPERATIONAL_TABLES
        if rows_by_table.get(name)
    }
    if populated:
        detail = ", ".join(f"{name}={count}" for name, count in sorted(populated.items()))
        raise RuntimeError(
            "El gimnasio destino contiene datos operativos y no se reemplazara: " + detail
        )
    deleted: dict[str, int] = {}
    for table_name in reversed(TABLE_ORDER):
        table = metadata.tables.get(table_name)
        ids = ids_by_table.get(table_name, set())
        if table is None or not ids:
            continue
        result = conn.execute(delete(table).where(table.c.id.in_(ids)))
        deleted[table_name] = int(result.rowcount or 0)
    return deleted


def migrate(
    target_conn: Connection,
    source_meta: MetaData,
    target_meta: MetaData,
    source_gym: dict[str, Any],
    source_rows: dict[str, list[dict[str, Any]]],
    plan_map: dict[int, int],
    existing_target_gym_id: int | None = None,
    target_name: str | None = None,
) -> tuple[int, dict[str, dict[int, int]]]:
    source_gym_table = source_meta.tables["gimnasios"]
    target_gym_table = target_meta.tables["gimnasios"]
    common_gym_columns = set(source_gym_table.c.keys()) & set(target_gym_table.c.keys())
    gym_values = {
        key: value for key, value in source_gym.items()
        if key in common_gym_columns and key != "id"
    }
    if gym_values.get("plan_id") is not None:
        old_plan_id = int(gym_values["plan_id"])
        if old_plan_id not in plan_map:
            raise RuntimeError("El plan SaaS del gimnasio no existe en produccion")
        gym_values["plan_id"] = plan_map[old_plan_id]
    if target_name is not None:
        gym_values["nombre"] = target_name
    if existing_target_gym_id is None:
        target_gym_id = int(target_conn.execute(
            insert(target_gym_table).values(**gym_values).returning(target_gym_table.c.id)
        ).scalar_one())
    else:
        target_gym_id = existing_target_gym_id
        target_conn.execute(
            update(target_gym_table)
            .where(target_gym_table.c.id == target_gym_id)
            .values(**gym_values)
        )

    id_maps: dict[str, dict[int, int]] = {
        "gimnasios": {int(source_gym["id"]): target_gym_id},
        "planes_saas": plan_map,
    }

    for table_name in TABLE_ORDER:
        rows = source_rows.get(table_name, [])
        if not rows or table_name not in target_meta.tables:
            id_maps.setdefault(table_name, {})
            continue
        source_table = source_meta.tables[table_name]
        target_table = target_meta.tables[table_name]
        common_columns = set(source_table.c.keys()) & set(target_table.c.keys())
        fk_by_column = {fk.parent.name: fk for fk in target_table.foreign_keys}
        prepared: list[dict[str, Any]] = []
        old_ids: list[int] = []
        for row in rows:
            old_ids.append(int(row["id"]))
            values = {
                key: value for key, value in row.items()
                if key in common_columns and key != "id"
            }
            for key, value in list(values.items()):
                enum_values = getattr(target_table.c[key].type, "enums", None)
                if value is None or not enum_values or not isinstance(value, str):
                    continue
                if value not in enum_values:
                    matches = {
                        str(candidate).casefold(): candidate for candidate in enum_values
                    }
                    if value.casefold() in matches:
                        values[key] = matches[value.casefold()]
            if "gimnasio_id" in values:
                values["gimnasio_id"] = target_gym_id
            for column_name, fk in fk_by_column.items():
                if column_name not in values or values[column_name] is None:
                    continue
                referenced_table = fk.column.table.name
                old_value = int(values[column_name])
                if referenced_table == "gimnasios":
                    values[column_name] = target_gym_id
                    continue
                mapping = id_maps.get(referenced_table, {})
                if old_value not in mapping:
                    raise RuntimeError(
                        f"Referencia fuera del gimnasio: {table_name}.{column_name}="
                        f"{old_value} -> {referenced_table}"
                    )
                values[column_name] = mapping[old_value]
            prepared.append(values)
        id_maps[table_name] = insert_batch(target_conn, target_table, prepared, old_ids)
    return target_gym_id, id_maps


def validate_target(
    conn: Connection,
    metadata: MetaData,
    target_gym_id: int,
    source_rows: dict[str, list[dict[str, Any]]],
    id_maps: dict[str, dict[int, int]],
) -> dict[str, int]:
    validated: dict[str, int] = {}
    for table_name, source_table_rows in source_rows.items():
        if not source_table_rows or table_name not in metadata.tables:
            continue
        table = metadata.tables[table_name]
        if "gimnasio_id" in table.c:
            count = int(conn.scalar(
                select(func.count()).select_from(table).where(table.c.gimnasio_id == target_gym_id)
            ) or 0)
        else:
            new_ids = list(id_maps.get(table_name, {}).values())
            count = int(conn.scalar(
                select(func.count()).select_from(table).where(table.c.id.in_(new_ids))
            ) or 0) if new_ids else 0
        expected = len(source_table_rows)
        if count != expected:
            raise RuntimeError(f"Validacion fallo en {table_name}: {count} != {expected}")
        validated[table_name] = count
    return validated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrar un gimnasio local a Supabase")
    parser.add_argument("--source-db", default="sql_app.db")
    parser.add_argument("--source-gym-id", type=int, default=1)
    parser.add_argument("--target-url-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"))
    parser.add_argument("--target-gym-id", type=int)
    parser.add_argument("--target-name")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source_db).resolve()
    if not source_path.exists():
        raise RuntimeError(f"No existe la base local: {source_path}")
    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(_read_url(args.target_url_file), pool_pre_ping=True)
    source_meta = reflect(source_engine)
    target_meta = reflect(target_engine)
    for required in ("gimnasios", "usuarios"):
        if required not in source_meta.tables or required not in target_meta.tables:
            raise RuntimeError(f"Falta la tabla requerida: {required}")
    unhandled = find_unhandled_gym_tables(source_meta)
    if unhandled:
        raise RuntimeError("Tablas multi-tenant no contempladas: " + ", ".join(unhandled))

    with source_engine.connect() as source_conn, target_engine.connect() as target_conn:
        source_gym = select_source_gym(
            source_conn, source_meta.tables["gimnasios"], args.source_gym_id
        )
        source_rows, _ = collect_source_rows(source_conn, source_meta, int(source_gym["id"]))
        summary = source_target_summary(
            source_conn, target_conn, source_meta, target_meta, source_gym, source_rows
        )
        plan_map = build_plan_map(source_conn, target_conn, source_meta, target_meta)

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.audit:
        print("AUDITORIA_OK")
        return 0
    target_gym_ids = {int(row["id"]) for row in summary["target_gyms"]}
    if args.target_gym_id is not None and args.target_gym_id not in target_gym_ids:
        raise RuntimeError("No existe el gimnasio destino solicitado")
    if summary["slug_collision"] and args.target_gym_id is None:
        raise RuntimeError("Ya existe en produccion un gimnasio con el mismo slug")
    if summary["username_collisions"]:
        names = ", ".join(summary["username_collisions"])
        raise RuntimeError(f"Usuarios ya existentes en produccion: {names}")

    backup_path = backup_database(target_engine, target_meta, args.backup_dir)
    print(f"RESPALDO_OK={backup_path.resolve()}")
    with target_engine.begin() as target_conn:
        cleared: dict[str, int] = {}
        if args.target_gym_id is not None:
            cleared = clear_seed_only_target_gym(target_conn, target_meta, args.target_gym_id)
        target_gym_id, id_maps = migrate(
            target_conn,
            source_meta,
            target_meta,
            source_gym,
            source_rows,
            plan_map,
            existing_target_gym_id=args.target_gym_id,
            target_name=args.target_name,
        )
        validated = validate_target(
            target_conn, target_meta, target_gym_id, source_rows, id_maps
        )
    print(json.dumps({
        "MIGRACION_OK": True,
        "target_gym_id": target_gym_id,
        "cleared_seed_counts": cleared,
        "validated_counts": validated,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
