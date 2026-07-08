"""
database.py
Conexion a la base de datos (Engine y SessionLocal).

Por defecto usa SQLite local (sql_app.db) para desarrollo, sin
necesitar ninguna cuenta externa. En produccion, se define la
variable de entorno DATABASE_URL apuntando a Postgres (Supabase,
Neon, etc.) y el sistema usa esa conexion automaticamente, sin
cambiar ni una linea de codigo.

Ejemplo de DATABASE_URL para Postgres (Supabase/Neon):
    postgresql://usuario:password@host:5432/nombre_db

Como definir la variable de entorno:
    - En desarrollo local: crear un archivo .env en backend/ con
      DATABASE_URL=postgresql://...
      (requiere python-dotenv, ya esta en requirements.txt)
    - En produccion (Fly.io, Render, etc.): configurarla en el
      panel de variables de entorno del servicio de hosting.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Carga variables desde un archivo .env si existe (no falla si no existe)
load_dotenv()

# Si no hay DATABASE_URL definida (o esta vacia), cae a SQLite local
# automaticamente. os.getenv() solo usa el default cuando la variable
# NO EXISTE; si existe pero vacia (caso de un .env con DATABASE_URL=
# sin valor), hay que revisarlo aparte con "or".
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./sql_app.db"

# SQLite necesita este argumento extra para funcionar con FastAPI
# (que puede usar la conexion desde distintos threads). Postgres no
# lo necesita, asi que se agrega condicionalmente.
connect_args = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependency de FastAPI: abre una sesion de base de datos por
    request y la cierra siempre al terminar, incluso si hay error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()