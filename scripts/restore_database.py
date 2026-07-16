"""Restaura un respaldo portable únicamente sobre una base vacía."""

import argparse
import base64
import gzip
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, select, text

from backend.database import Base
from backend import models  # noqa: F401


def _valor(value):
    if not isinstance(value, dict) or "__type__" not in value:
        return value
    tipo, raw = value["__type__"], value.get("value")
    if tipo == "datetime":
        return datetime.fromisoformat(raw)
    if tipo == "decimal":
        return Decimal(raw)
    if tipo == "bytes":
        return base64.b64decode(raw)
    if tipo == "enum":
        return raw
    return raw


def restaurar(path: Path, database_url: str, confirmacion: str) -> dict:
    if confirmacion != "RESTORE_EMPTY_DATABASE":
        raise RuntimeError("Falta --confirm RESTORE_EMPTY_DATABASE")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name == "alembic_version":
                continue
            if conn.execute(select(table).limit(1)).first() is not None:
                raise RuntimeError(f"La base destino no está vacía: {table.name}")
    insertadas = 0
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in Base.metadata.sorted_tables:
            rows = payload.get("tables", {}).get(table.name, [])
            if not rows:
                continue
            columnas = {c.name for c in table.columns}
            preparados = [{k: _valor(v) for k, v in row.items() if k in columnas} for row in rows]
            conn.execute(table.insert(), preparados)
            insertadas += len(preparados)
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=ON"))
    return {"tablas_respaldo": len(payload.get("tables", {})), "filas_restauradas": insertadas}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    url = os.getenv("RESTORE_DATABASE_URL")
    if not url:
        raise RuntimeError("Define RESTORE_DATABASE_URL; DATABASE_URL no se usa para evitar accidentes")
    print(json.dumps(restaurar(args.backup, url, args.confirm), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
