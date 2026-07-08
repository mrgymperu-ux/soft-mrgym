"""
init_db.py
Script que inicializa la base de datos: crea todas las tablas y
carga datos iniciales minimos para poder usar el sistema desde el
primer arranque (sin esto, no habria forma de loguearse).

Se ejecuta como modulo desde la raiz del proyecto:
    py -3.12 -m backend.init_db

Que hace:
  1. Crea todas las tablas definidas en models.py (si no existen).
  2. Crea la fila de Configuracion por defecto (id=1) si no existe.
  3. Crea un usuario STAFF administrador inicial, SOLO si todavia
     no existe ningun usuario en la base de datos. Las credenciales
     se pueden definir por variable de entorno; si no se definen,
     se usan valores por defecto que se deben cambiar de inmediato.

IMPORTANTE: cambiar la contraseña del admin inicial (o las
variables de entorno ADMIN_USERNAME / ADMIN_PASSWORD) antes de
usar el sistema en produccion real.
"""

import os
from dotenv import load_dotenv

from . import models, auth
from .database import SessionLocal, engine

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")
ADMIN_NOMBRE = os.getenv("ADMIN_NOMBRE", "Administrador")


def init_db():
    models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # --- Configuracion por defecto ---
        config = db.query(models.Configuracion).filter(models.Configuracion.id == 1).first()
        if not config:
            config = models.Configuracion(id=1)
            db.add(config)
            db.commit()
            print("[init_db] Configuracion por defecto creada.")

        # --- Usuario admin inicial ---
        existe_algun_usuario = db.query(models.Usuario).count() > 0
        if not existe_algun_usuario:
            admin = models.Usuario(
                nombre_completo=ADMIN_NOMBRE,
                username=ADMIN_USERNAME,
                password_hash=auth.hash_password(ADMIN_PASSWORD),
                rol=models.RolUsuario.STAFF,
            )
            db.add(admin)
            db.commit()
            print(f"[init_db] Usuario admin creado -> username: '{ADMIN_USERNAME}'")
            print("[init_db] IMPORTANTE: cambia esta contraseña antes de usar en produccion.")
        else:
            print("[init_db] Ya existen usuarios, no se crea admin por defecto.")

    finally:
        db.close()


if __name__ == "__main__":
    init_db()
