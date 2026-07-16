"""Crea y verifica un respaldo completo portable de la base de datos."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import create_engine

from migrate_gym_to_production import backup_database, reflect


def verificar(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload.get("tables"), dict) or not payload["tables"]:
        raise RuntimeError("El respaldo no contiene tablas")
    total = sum(len(rows) for rows in payload["tables"].values())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"archivo": path.name, "sha256": digest, "tablas": len(payload["tables"]), "filas": total}
    path.with_suffix(path.suffix + ".sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verificar(args.verify), indent=2))
        return
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Define DATABASE_URL para respaldar la base correcta")
    engine = create_engine(url)
    path = backup_database(engine, reflect(engine), args.output_dir)
    print(json.dumps(verificar(path), indent=2))


if __name__ == "__main__":
    main()
