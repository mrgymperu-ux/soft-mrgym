"""
auth.py
Autenticacion y autorizacion.

Dos flujos de login completamente distintos, como define el plan
de arquitectura:

  1. Staff / Profesores (tabla Usuario): login con username +
     password, devuelve un JWT. Las rutas protegidas para staff o
     profesores leen ese JWT y verifican el rol adentro.

  2. Alumnos (tabla Cliente): login con DNI + codigo_acceso corto
     (sin password tradicional, pensado para que sea rapido de
     usar desde el celular). Tambien devuelve un JWT, pero de tipo
     distinto ("alumno"), que solo da acceso a sus propios datos.

MULTI-TENANT:
  Cada JWT incluye 'gimnasio_id'. La dependencia get_usuario_actual
  expone ese ID a todos los endpoints via el objeto Usuario.
  El helper get_gimnasio_id(usuario) lo extrae para usarlo en queries.
  Los endpoints filtran SIEMPRE por gimnasio_id — nunca se mezclan
  datos de distintos gimnasios.

IMPORTANTE - variable de entorno SECRET_KEY:
  En desarrollo, si no se define, se genera una por defecto (NO
  usar esa por defecto en produccion). Definir SECRET_KEY en el
  archivo .env o en las variables de entorno del hosting antes de
  desplegar de verdad.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .database import get_db

load_dotenv()

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "cambiar-esta-clave-en-produccion-no-usar-en-real",
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 horas, pensado para un turno de trabajo largo

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl es solo informativo para la doc de Swagger; el login real
# de staff/profesor vive en /auth/login (ver main.py)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


# ==================================================================
# PASSWORDS
# ==================================================================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verificar_password(password_plano: str, password_hash: str) -> bool:
    return pwd_context.verify(password_plano, password_hash)


# ==================================================================
# CODIGO DE ACCESO DE ALUMNOS
# ==================================================================

def verificar_codigo_acceso(codigo_ingresado: str, codigo_guardado: Optional[str]) -> bool:
    """
    Comparacion simple del codigo de acceso del alumno. Se guarda
    en texto plano por decision explicita (no es informacion
    sensible tipo bancaria, y prioriza velocidad/simplicidad).
    """
    if not codigo_guardado:
        return False
    return codigo_ingresado.strip() == codigo_guardado.strip()


# ==================================================================
# JWT
# ==================================================================

def crear_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decodificar_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ==================================================================
# HELPER MULTI-TENANT
# ==================================================================

def get_gimnasio_id(usuario: models.Usuario) -> Optional[int]:
    """
    Extrae el gimnasio_id del usuario autenticado.
    Retorna None si es superadmin de plataforma (sin gimnasio asignado).
    Uso en endpoints:
        gid = auth.get_gimnasio_id(usuario)
        db.query(models.Cliente).filter(models.Cliente.gimnasio_id == gid)
    """
    return usuario.gimnasio_id


# ==================================================================
# DEPENDENCIES - STAFF / PROFESOR
# ==================================================================

def get_usuario_actual(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Usuario:
    """
    Dependency para rutas que requieren un Usuario (staff o
    profesor) autenticado. Lanza 401 si no hay token o es invalido.
    El usuario devuelto tiene gimnasio_id cargado.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decodificar_token(token)

    if payload.get("tipo") != "usuario":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no valido para este recurso",
        )

    usuario_id = payload.get("sub")
    usuario = db.query(models.Usuario).filter(models.Usuario.id == int(usuario_id)).first()

    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
        )

    return usuario


def requiere_staff(usuario: models.Usuario = Depends(get_usuario_actual)) -> models.Usuario:
    """Dependency para rutas exclusivas de staff (admin/recepcion)."""
    if usuario.rol != models.RolUsuario.STAFF:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere rol de staff")
    return usuario


def requiere_staff_o_profesor(usuario: models.Usuario = Depends(get_usuario_actual)) -> models.Usuario:
    """Dependency para rutas accesibles tanto por staff como por profesores."""
    if usuario.rol not in (models.RolUsuario.STAFF, models.RolUsuario.PROFESOR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    return usuario


# ==================================================================
# PERMISOS FINOS (administrador, eliminar, zonas)
# ==================================================================

ZONAS_DISPONIBLES = [
    "clientes", "membresias", "productos", "ventas", "venta_rapida",
    "asistencias", "progreso", "agenda", "entrenamientos", "nutricion",
    "retos", "planilla", "pagos", "usuarios", "configuracion", "metas",
]


def requiere_administrador(usuario: models.Usuario = Depends(requiere_staff)) -> models.Usuario:
    """
    Para zonas exclusivas del administrador: Metas de ventas,
    tramos de comision, y gestion de Usuarios/permisos.
    """
    if not usuario.es_administrador:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere permisos de administrador",
        )
    return usuario


def requiere_superadmin(usuario: models.Usuario = Depends(get_usuario_actual)) -> models.Usuario:
    """Solo superadmin de plataforma SaaS (acceso cross-gimnasio)."""
    if not getattr(usuario, 'es_superadmin', False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere permisos de superadmin de plataforma",
        )
    return usuario


def requiere_permiso_eliminar(usuario: models.Usuario = Depends(requiere_staff)) -> models.Usuario:
    """Para acciones de borrado/desactivacion, ademas de ser staff."""
    if not usuario.es_administrador and not usuario.puede_eliminar:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar registros",
        )
    return usuario


def requiere_permiso_exportar(usuario: models.Usuario = Depends(requiere_staff)) -> models.Usuario:
    """
    Para exportar/importar datos en bloque (CSV con todos los campos,
    incluye info personal de clientes).
    """
    if not usuario.es_administrador and not usuario.puede_exportar:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para exportar/importar datos",
        )
    return usuario


def requiere_zona(zona: str):
    """
    Factory de dependency: exige que el staff tenga esa zona en su
    lista de zonas_permitidas (los administradores siempre pasan).
    Uso: _=Depends(auth.requiere_zona("planilla"))
    """
    def dependencia(usuario: models.Usuario = Depends(requiere_staff)) -> models.Usuario:
        if usuario.es_administrador:
            return usuario
        permitidas = [z.strip() for z in (usuario.zonas_permitidas or "").split(",") if z.strip()]
        if zona not in permitidas:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes acceso a la zona '{zona}'",
            )
        return usuario
    return dependencia


# ==================================================================
# DEPENDENCIES - ALUMNO
# ==================================================================

def get_cliente_actual(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Cliente:
    """
    Dependency para rutas del portal del alumno. Lanza 401 si no
    hay token, es invalido, o no corresponde a un cliente.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decodificar_token(token)

    if payload.get("tipo") != "alumno":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no valido para este recurso",
        )

    cliente_id = payload.get("sub")
    cliente = db.query(models.Cliente).filter(models.Cliente.id == int(cliente_id)).first()

    if cliente is None or not cliente.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Alumno no encontrado o inactivo",
        )

    return cliente


def get_profesor_actual(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Empleado:
    """
    Dependency para la Zona de Profesores (portal separado del
    software de staff).
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decodificar_token(token)

    if payload.get("tipo") != "profesor":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no valido para este recurso",
        )

    profesor_id = payload.get("sub")
    profesor = db.query(models.Empleado).filter(models.Empleado.id == int(profesor_id)).first()

    if profesor is None or not profesor.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Profesor no encontrado o inactivo",
        )

    return profesor


# ==================================================================
# FUNCIONES DE LOGIN (usadas por los endpoints en main.py)
# ==================================================================

def autenticar_usuario(db: Session, username: str, password: str) -> Optional[models.Usuario]:
    usuario = db.query(models.Usuario).filter(models.Usuario.username == username).first()
    if not usuario or not usuario.activo:
        return None
    if not verificar_password(password, usuario.password_hash):
        return None
    return usuario


def autenticar_alumno(db: Session, dni: str, codigo_acceso: str, gimnasio_id: int = None) -> Optional[models.Cliente]:
    query = db.query(models.Cliente).filter(models.Cliente.dni == dni)
    if gimnasio_id:
        query = query.filter(models.Cliente.gimnasio_id == gimnasio_id)
    cliente = query.first()
    if not cliente or not cliente.activo:
        return None
    if not verificar_codigo_acceso(codigo_acceso, cliente.codigo_acceso):
        return None
    return cliente


def autenticar_profesor(db: Session, dni: str, codigo_acceso: str, gimnasio_id: int = None) -> Optional[models.Empleado]:
    """
    Login de profesores de sala a su 'Zona de Profesores':
    DNI + codigo corto, igual de simple que el login de alumnos.
    """
    query = (
        db.query(models.Empleado)
        .filter(
            models.Empleado.dni == dni,
            models.Empleado.tipo == models.TipoEmpleado.PROFESOR_DE_SALA,
        )
    )
    if gimnasio_id:
        query = query.filter(models.Empleado.gimnasio_id == gimnasio_id)
    profesor = query.first()
    if not profesor or not profesor.activo:
        return None
    if not verificar_codigo_acceso(codigo_acceso, profesor.codigo_acceso):
        return None
    return profesor
