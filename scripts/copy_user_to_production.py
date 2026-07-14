"""Copia de forma segura un usuario local hacia un gimnasio de produccion."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import MetaData, create_engine, insert, select

from migrate_gym_to_production import _read_url, backup_database, reflect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", default="sql_app.db")
    parser.add_argument("--username", required=True)
    parser.add_argument("--target-gym-id", type=int, required=True)
    parser.add_argument("--target-url-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source_db).resolve()
    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(_read_url(args.target_url_file), pool_pre_ping=True)
    source_meta = reflect(source_engine)
    target_meta = reflect(target_engine)
    source_users = source_meta.tables["usuarios"]
    target_users = target_meta.tables["usuarios"]
    target_gyms = target_meta.tables["gimnasios"]

    with source_engine.connect() as conn:
        source_user = conn.execute(
            select(source_users).where(source_users.c.username == args.username)
        ).mappings().one_or_none()
    if source_user is None:
        raise RuntimeError("El usuario no existe en la base local")

    with target_engine.connect() as conn:
        gym_exists = conn.scalar(
            select(target_gyms.c.id).where(target_gyms.c.id == args.target_gym_id)
        )
        duplicate = conn.scalar(
            select(target_users.c.id).where(target_users.c.username == args.username)
        )
    if not gym_exists:
        raise RuntimeError("El gimnasio destino no existe")
    if duplicate:
        raise RuntimeError("El usuario ya existe en produccion")

    backup_path = backup_database(target_engine, target_meta, args.backup_dir)
    common_columns = set(source_users.c.keys()) & set(target_users.c.keys())
    values = {
        key: value for key, value in source_user.items()
        if key in common_columns and key != "id"
    }
    values["gimnasio_id"] = args.target_gym_id
    values["empleado_id"] = None
    values["es_superadmin"] = False

    with target_engine.begin() as conn:
        new_id = conn.execute(
            insert(target_users).values(**values).returning(target_users.c.id)
        ).scalar_one()
    print(f"RESPALDO_OK={backup_path.resolve()}")
    print(f"USUARIO_COPIADO_OK id={new_id} gimnasio_id={args.target_gym_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
