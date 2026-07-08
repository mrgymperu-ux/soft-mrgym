"""
reset_admin.py
Restablece la contraseña del usuario administrador SIN borrar datos.

Uso (desde la raiz del proyecto D:\\Soft-MrGym):
    py -3.12 -m backend.reset_admin

O simplemente doble clic en: reset-admin.bat

Que hace:
  1. Busca el usuario 'admin' (o el primer usuario STAFF si no
     existe uno llamado 'admin').
  2. Te pide la nueva contraseña por consola (si presionas Enter
     sin escribir nada, usa 'admin1234').
  3. Actualiza el hash en la base de datos y reactiva la cuenta.
  4. Si no existe ningun usuario, crea el admin desde cero.
"""

from . import models, auth
from .database import SessionLocal, engine


def reset_admin():
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        usuario = (
            db.query(models.Usuario)
            .filter(models.Usuario.username == "admin")
            .first()
        )
        if not usuario:
            usuario = (
                db.query(models.Usuario)
                .filter(models.Usuario.rol == models.RolUsuario.STAFF)
                .first()
            )

        nueva = input("Nueva contraseña para el admin (Enter = admin1234): ").strip()
        if not nueva:
            nueva = "admin1234"

        if usuario:
            usuario.password_hash = auth.hash_password(nueva)
            usuario.activo = True
            usuario.es_administrador = True
            db.commit()
            print(f"[reset_admin] Listo. Usuario: '{usuario.username}'  Nueva contraseña aplicada.")
        else:
            usuario = models.Usuario(
                nombre_completo="Administrador",
                username="admin",
                password_hash=auth.hash_password(nueva),
                rol=models.RolUsuario.STAFF,
                es_administrador=True,
                puede_eliminar=True,
                activo=True,
            )
            db.add(usuario)
            db.commit()
            print("[reset_admin] No existia ningun usuario. Se creo 'admin' con la nueva contraseña.")

        print("[reset_admin] Ya puedes iniciar sesion en el sistema.")
    finally:
        db.close()


if __name__ == "__main__":
    reset_admin()
