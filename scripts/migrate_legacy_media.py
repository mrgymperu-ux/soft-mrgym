"""Migra medios del contenedor activo a columnas binarias persistentes."""

import argparse
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.main import _validar_y_optimizar_foto


def _descargar(base_url: str, ruta: str) -> tuple[bytes, str]:
    if not ruta.startswith("/uploads/"):
        raise ValueError("Solo se migran rutas antiguas bajo /uploads/")
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", ruta.lstrip("/"))
    request = urllib.request.Request(url, headers={"User-Agent": "Soft-Gym-Media-Migration/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        contenido = response.read(10 * 1024 * 1024 + 1)
        tipo = (response.headers.get_content_type() or "").lower()
    return _validar_y_optimizar_foto(contenido, tipo, optimizar=True)


def migrar(database_url: str, base_url: str, aplicar: bool) -> dict:
    db = sessionmaker(bind=create_engine(database_url))()
    resultado = {"logos_detectados": 0, "ejercicios_detectados": 0, "migrados": 0, "errores": []}
    try:
        for gym in db.query(models.Gimnasio).all():
            for modo, campo_url, campo_datos, campo_tipo in (
                ("claro", "logo_url", "logo_datos", "logo_tipo"),
                ("oscuro", "logo_oscuro_url", "logo_oscuro_datos", "logo_oscuro_tipo"),
            ):
                ruta = getattr(gym, campo_url)
                if ruta and ruta.startswith("/uploads/") and not getattr(gym, campo_datos):
                    resultado["logos_detectados"] += 1
                    if aplicar:
                        try:
                            datos, tipo = _descargar(base_url, ruta)
                            setattr(gym, campo_datos, datos); setattr(gym, campo_tipo, tipo)
                            setattr(gym, campo_url, f"/gym/{gym.slug}/logo/{modo}")
                            resultado["migrados"] += 1
                        except Exception as exc:
                            resultado["errores"].append(f"gimnasio {gym.id} {modo}: {exc}")
        for ejercicio in db.query(models.TipoEjercicio).filter(models.TipoEjercicio.imagen_url.like("/uploads/%")).all():
            if ejercicio.imagen_datos:
                continue
            resultado["ejercicios_detectados"] += 1
            if aplicar:
                try:
                    datos, tipo = _descargar(base_url, ejercicio.imagen_url)
                    ejercicio.imagen_datos, ejercicio.imagen_tipo = datos, tipo
                    ejercicio.imagen_url = f"/tipos-ejercicio/{ejercicio.id}/imagen-publica"
                    resultado["migrados"] += 1
                except Exception as exc:
                    resultado["errores"].append(f"ejercicio {ejercicio.id}: {exc}")
        if aplicar and not resultado["errores"]:
            db.commit()
        elif aplicar:
            db.rollback()
            resultado["migrados"] = 0
    finally:
        db.close()
    return resultado


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Define DATABASE_URL")
    if args.apply and args.confirm != "MIGRATE_MEDIA":
        raise RuntimeError("Para escribir usa --apply --confirm MIGRATE_MEDIA")
    print(migrar(url, args.base_url, args.apply))


if __name__ == "__main__":
    main()
