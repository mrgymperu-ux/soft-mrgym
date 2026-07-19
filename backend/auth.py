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
import re
import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from . import models
from .time_utils import ahora_lima, hoy_lima
from .database import get_db

load_dotenv()

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "cambiar-esta-clave-en-produccion-no-usar-en-real",
)
if os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"} and SECRET_KEY == "cambiar-esta-clave-en-produccion-no-usar-en-real":
    raise RuntimeError("SECRET_KEY debe configurarse con un valor seguro en produccion")
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


def validar_password_segura(password: str) -> None:
    """Regla comun para propietarios y cuentas de staff."""
    if len(password) < 10:
        raise ValueError("La contrasena debe tener al menos 10 caracteres")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("La contrasena debe combinar letras y numeros")


CODIGO_HASH_PREFIX = "$2"


def hash_codigo_acceso(codigo: str) -> str:
    return pwd_context.hash(codigo.strip())


# ==================================================================
# CODIGO DE ACCESO DE ALUMNOS
# ==================================================================

def verificar_codigo_acceso(codigo_ingresado: str, codigo_guardado: Optional[str]) -> bool:
    """
    Acepta hashes bcrypt y, temporalmente, valores antiguos en texto
    plano para permitir una migracion gradual sin bloquear usuarios.
    """
    if not codigo_guardado:
        return False
    codigo = codigo_ingresado.strip()
    guardado = codigo_guardado.strip()
    if guardado.startswith(CODIGO_HASH_PREFIX):
        try:
            return pwd_context.verify(codigo, guardado)
        except (ValueError, TypeError):
            return False
    return codigo == guardado


def codigo_necesita_rehash(codigo_guardado: Optional[str]) -> bool:
    return bool(codigo_guardado and not codigo_guardado.strip().startswith(CODIGO_HASH_PREFIX))


class LoginRateLimiter:
    """Limitador local por IP+identificador, sin guardar contrasenas."""
    def __init__(self, max_intentos: int = 5, ventana_segundos: int = 15 * 60):
        self.max_intentos = max_intentos
        self.ventana_segundos = ventana_segundos
        self._intentos = defaultdict(deque)
        self._lock = threading.Lock()

    def comprobar(self, clave: str) -> Optional[int]:
        ahora = time.monotonic()
        with self._lock:
            intentos = self._intentos[clave]
            while intentos and ahora - intentos[0] >= self.ventana_segundos:
                intentos.popleft()
            if len(intentos) >= self.max_intentos:
                return max(1, int(self.ventana_segundos - (ahora - intentos[0])))
        return None

    def registrar_fallo(self, clave: str) -> None:
        with self._lock:
            self._intentos[clave].append(time.monotonic())

    def limpiar(self, clave: str) -> None:
        with self._lock:
            self._intentos.pop(clave, None)


login_rate_limiter = LoginRateLimiter()


def clave_rate_limit(request: Request, tipo: str, identificador: str, slug: Optional[str] = None) -> str:
    ip = request.client.host if request.client else "desconocida"
    return f"{tipo}:{ip}:{(slug or '').lower()}:{identificador.strip().lower()}"


def _hash_clave_rate_limit(clave: str) -> str:
    """Evita persistir IP, DNI, correo o nombre de usuario en texto legible."""
    return hmac.new(SECRET_KEY.encode("utf-8"), clave.encode("utf-8"), hashlib.sha256).hexdigest()


def _registro_intentos(db: Session, clave: str) -> Optional[models.IntentoAcceso]:
    return db.query(models.IntentoAcceso).filter(
        models.IntentoAcceso.clave_hash == _hash_clave_rate_limit(clave)
    ).with_for_update().first()


def _espera_persistente(db: Session, clave: str) -> Optional[int]:
    registro = _registro_intentos(db, clave)
    if not registro:
        return None
    ahora = ahora_lima()
    if registro.bloqueado_hasta and registro.bloqueado_hasta > ahora:
        return max(1, int((registro.bloqueado_hasta - ahora).total_seconds()))
    if (ahora - registro.ventana_inicio).total_seconds() >= login_rate_limiter.ventana_segundos:
        db.delete(registro)
        db.commit()
    return None


def exigir_intentos_disponibles(clave: str, db: Optional[Session] = None) -> None:
    espera = login_rate_limiter.comprobar(clave)
    if espera is None and db is not None:
        espera = _espera_persistente(db, clave)
    if espera is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera antes de volver a probar.",
            headers={"Retry-After": str(espera)},
        )


def registrar_fallo_login(db: Session, clave: str) -> None:
    """Registra el fallo en memoria y BD para que sobreviva reinicios del servidor."""
    login_rate_limiter.registrar_fallo(clave)
    ahora = ahora_lima()
    registro = _registro_intentos(db, clave)
    if not registro:
        registro = models.IntentoAcceso(
            clave_hash=_hash_clave_rate_limit(clave),
            fallos=0,
            ventana_inicio=ahora,
            actualizado_en=ahora,
        )
        db.add(registro)
    elif (ahora - registro.ventana_inicio).total_seconds() >= login_rate_limiter.ventana_segundos:
        registro.fallos = 0
        registro.ventana_inicio = ahora
        registro.bloqueado_hasta = None
    registro.fallos += 1
    registro.actualizado_en = ahora
    if registro.fallos >= login_rate_limiter.max_intentos:
        registro.bloqueado_hasta = ahora + timedelta(seconds=login_rate_limiter.ventana_segundos)
    try:
        db.commit()
    except IntegrityError:
        # Dos solicitudes simultaneas pudieron intentar crear la misma clave.
        db.rollback()
        registro = _registro_intentos(db, clave)
        if not registro:
            raise
        registro.fallos += 1
        registro.actualizado_en = ahora
        if registro.fallos >= login_rate_limiter.max_intentos:
            registro.bloqueado_hasta = ahora + timedelta(seconds=login_rate_limiter.ventana_segundos)
        db.commit()


def limpiar_fallos_login(db: Session, clave: str) -> None:
    login_rate_limiter.limpiar(clave)
    registro = _registro_intentos(db, clave)
    if registro:
        db.delete(registro)
        db.commit()


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


def _suscripcion_permite_acceso(db: Session, gimnasio_id: Optional[int]) -> bool:
    """Compatibilidad: tenants sin registro SaaS siguen activos hasta configurarlos."""
    if not gimnasio_id:
        return True
    suscripcion = db.query(models.SuscripcionSaas).filter(
        models.SuscripcionSaas.gimnasio_id == gimnasio_id
    ).first()
    if not suscripcion:
        return True
    if suscripcion.estado in {"suspendida", "cancelada"}:
        return False
    hoy = hoy_lima()
    if hoy <= suscripcion.fecha_fin_periodo:
        return True
    return bool(suscripcion.fecha_fin_gracia and hoy <= suscripcion.fecha_fin_gracia)


def _exigir_suscripcion_activa(db: Session, gimnasio_id: Optional[int]):
    if not _suscripcion_permite_acceso(db, gimnasio_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="La suscripcion de Soft-Gym esta vencida o suspendida. Contacta al administrador de la plataforma.",
        )


# ==================================================================
# DEPENDENCIES - STAFF / PROFESOR
# ==================================================================

def get_usuario_actual(
    request: Request,
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
    try:
        usuario_id = int(usuario_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()

    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
        )
    if int(payload.get("sv", 0)) != int(usuario.sesion_version or 1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesion fue cerrada. Ingresa nuevamente")
    jti = payload.get("jti")
    sesion = db.query(models.SesionUsuario).filter(
        models.SesionUsuario.usuario_id == usuario.id,
        models.SesionUsuario.jti == jti,
        models.SesionUsuario.revocada_en.is_(None),
    ).first() if jti else None
    if not sesion:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesion ya no esta activa")
    ahora = ahora_lima()
    if not sesion.ultima_actividad or (ahora - sesion.ultima_actividad).total_seconds() >= 300:
        sesion.ultima_actividad = ahora
        db.commit()

    # Un tenant suspendido no puede seguir usando tokens existentes.
    # El superadmin de plataforma queda exento para poder administrarlo.
    if usuario.gimnasio_id and not getattr(usuario, "es_superadmin", False):
        gimnasio_activo = db.query(models.Gimnasio.id).filter(
            models.Gimnasio.id == usuario.gimnasio_id,
            models.Gimnasio.activo == True,
        ).first()
        if not gimnasio_activo:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gimnasio suspendido")
        # El dueño debe poder entrar a Configuración para consultar su
        # deuda/plan aun cuando el resto del sistema esté bloqueado.
        rutas_autoservicio = ("/suscripcion/mi-plan", "/configuracion", "/gym-actual")
        if not request.url.path.startswith(rutas_autoservicio):
            _exigir_suscripcion_activa(db, usuario.gimnasio_id)

    return usuario


_ZONA_POR_PREFIJO = {
    "clientes": "clientes", "clientes-historicos": "clientes",
    "membresias": "membresias", "cliente-membresias": "membresias",
    "productos": "productos", "compras": "productos",
    "ventas": "ventas", "asistencias": "asistencias", "asistencias-empleado": "asistencias",
    "progreso": "progreso", "medidas": "progreso",
    "tipos-ejercicio": "entrenamientos", "rutinas": "entrenamientos", "paquetes-rutina": "entrenamientos",
    "equipamiento-gimnasio": "entrenamientos",
    "rutina-dias": "entrenamientos", "rutina-ejercicios": "entrenamientos",
    "nutricion": "nutricion", "alimentos": "nutricion", "paquetes-nutricion": "nutricion",
    "retos": "retos", "agenda": "agenda", "clases": "agenda", "reservas-sala": "agenda", "salas": "agenda",
    "planilla": "planilla", "pagos-planilla": "planilla",
    "servicios": "pagos", "cargos-servicio": "pagos", "pagos-servicio": "pagos",
    "dashboard": "sistema", "reportes": "sistema",
    "ingresos": "sistema", "egresos": "sistema", "gastos": "sistema",
    "conceptos-ingreso": "sistema", "otros-ingresos": "sistema",
    "usuarios": "usuarios", "empleados": "usuarios", "puestos": "usuarios",
    "configuracion": "configuracion", "gym-actual": "configuracion",
    "metas": "metas", "comisiones": "metas",
}


def _validar_zona_de_ruta(request: Request, usuario: models.Usuario):
    """Aplica zonas_permitidas tambien en API, no solo en el menu."""
    if usuario.es_administrador:
        return
    prefijo = request.url.path.strip("/").split("/", 1)[0]
    # Los modulos necesitan leer moneda, marca y preferencias generales.
    # La zona Configuracion protege las modificaciones, no esta lectura comun.
    if request.method.upper() == "GET" and prefijo in {"configuracion", "gym-actual"}:
        return
    zona = _ZONA_POR_PREFIJO.get(prefijo)
    if not zona:
        return
    permitidas = {z.strip() for z in (usuario.zonas_permitidas or "").split(",") if z.strip()}
    if zona not in permitidas:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes acceso a la zona '{zona}'")


def requiere_staff(request: Request, usuario: models.Usuario = Depends(get_usuario_actual)) -> models.Usuario:
    """Dependency para rutas exclusivas de staff (admin/recepcion)."""
    if usuario.rol != models.RolUsuario.STAFF:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere rol de staff")
    _validar_zona_de_ruta(request, usuario)
    return usuario


def requiere_staff_o_profesor(request: Request, usuario: models.Usuario = Depends(get_usuario_actual)) -> models.Usuario:
    """Dependency para rutas accesibles tanto por staff como por profesores."""
    if usuario.rol not in (models.RolUsuario.STAFF, models.RolUsuario.PROFESOR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    if usuario.rol == models.RolUsuario.STAFF:
        _validar_zona_de_ruta(request, usuario)
    return usuario


# ==================================================================
# PERMISOS FINOS (administrador, eliminar, zonas)
# ==================================================================

ZONAS_DISPONIBLES = [
    "clientes", "membresias", "productos", "ventas", "venta_rapida",
    "asistencias", "agenda", "entrenamientos", "nutricion",
    "retos", "planilla", "pagos", "sistema", "usuarios", "configuracion", "metas",
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
    try:
        cliente_id = int(cliente_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()

    if cliente is None or not cliente.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Alumno no encontrado o inactivo",
        )

    gimnasio_activo = db.query(models.Gimnasio.id).filter(
        models.Gimnasio.id == cliente.gimnasio_id,
        models.Gimnasio.activo == True,
    ).first()
    if not gimnasio_activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gimnasio suspendido")
    _exigir_suscripcion_activa(db, cliente.gimnasio_id)

    return cliente


def get_cliente_para_configurar_password(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Cliente:
    """Acepta solamente el token corto de primer acceso/reset de clave."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    payload = decodificar_token(token)
    if payload.get("tipo") != "alumno_configuracion":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token no valido para configurar la contrasena")
    try:
        cliente_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.activo == True).first()
    if not cliente or (cliente.codigo_acceso and cliente.codigo_acceso.strip()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La configuracion inicial ya no esta disponible")
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
    try:
        profesor_id = int(profesor_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")
    profesor = db.query(models.Empleado).filter(models.Empleado.id == profesor_id).first()

    if profesor is None or not profesor.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Profesor no encontrado o inactivo",
        )

    gimnasio_activo = db.query(models.Gimnasio.id).filter(
        models.Gimnasio.id == profesor.gimnasio_id,
        models.Gimnasio.activo == True,
    ).first()
    if not gimnasio_activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gimnasio suspendido")
    _exigir_suscripcion_activa(db, profesor.gimnasio_id)

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
    if usuario.gimnasio_id and not getattr(usuario, "es_superadmin", False):
        gimnasio = db.query(models.Gimnasio).filter(
            models.Gimnasio.id == usuario.gimnasio_id,
            models.Gimnasio.activo == True,
        ).first()
        if not gimnasio:
            return None
    return usuario


def autenticar_alumno(db: Session, dni: str, codigo_acceso: str, gimnasio_id: int = None) -> Optional[models.Cliente]:
    query = db.query(models.Cliente).filter(models.Cliente.dni == dni)
    if gimnasio_id:
        query = query.filter(models.Cliente.gimnasio_id == gimnasio_id)
    cliente = query.first()
    if not cliente or not cliente.activo:
        return None
    if not _suscripcion_permite_acceso(db, cliente.gimnasio_id):
        return None
    if not verificar_codigo_acceso(codigo_acceso, cliente.codigo_acceso):
        return None
    if codigo_necesita_rehash(cliente.codigo_acceso):
        cliente.codigo_acceso = hash_codigo_acceso(codigo_acceso)
        db.commit()
    return cliente


def obtener_alumno_para_inicio(db: Session, dni: str, gimnasio_id: int = None) -> Optional[models.Cliente]:
    """Busca un alumno activo para decidir si debe crear o ingresar su contraseña."""
    query = db.query(models.Cliente).filter(models.Cliente.dni == dni)
    if gimnasio_id:
        query = query.filter(models.Cliente.gimnasio_id == gimnasio_id)
    cliente = query.first()
    if not cliente or not cliente.activo:
        return None
    if not _suscripcion_permite_acceso(db, cliente.gimnasio_id):
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
    if not _suscripcion_permite_acceso(db, profesor.gimnasio_id):
        return None
    if not verificar_codigo_acceso(codigo_acceso, profesor.codigo_acceso):
        return None
    if codigo_necesita_rehash(profesor.codigo_acceso):
        profesor.codigo_acceso = hash_codigo_acceso(codigo_acceso)
        db.commit()
    return profesor
