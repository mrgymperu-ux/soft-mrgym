"""
main.py
Punto de entrada FastAPI. Rutas agrupadas por modulo, en el mismo
orden que models.py / schemas.py.

Convencion de permisos:
  - /auth/*                 publico (login)
  - /staff/...               requiere rol STAFF
  - /portal-alumno/...       requiere token de alumno (Cliente)
  - el resto de rutas de gestion (clientes, productos, ventas,
    etc.) requiere STAFF o PROFESOR segun el caso, ver cada ruta
"""

from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
import base64
import calendar
import math
import os
import uuid
import csv
import io
import asyncio
import time
import logging
import json
import secrets
import hashlib
import urllib.request
import unicodedata
from urllib.parse import parse_qs, urlparse
from PIL import Image, ImageOps, UnidentifiedImageError
from cryptography.fernet import Fernet, InvalidToken

from fastapi import FastAPI, Depends, HTTPException, Query, Path, UploadFile, File, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, Response, JSONResponse
from sqlalchemy import func, text, or_
from sqlalchemy.orm import Session

from . import models, schemas, auth, pdf_generator, email_service
from .database import get_db, engine, SessionLocal, SQLALCHEMY_DATABASE_URL
from .time_utils import ahora_lima, hoy_lima

logger = logging.getLogger("soft-mrgym")

app = FastAPI(title="Soft-Gym API")

PASSWORD_LEGACY_ALUMNO = "1234"


def _crear_sesion_usuario(db: Session, usuario: models.Usuario, request: Request) -> models.SesionUsuario:
    sesion = models.SesionUsuario(
        usuario_id=usuario.id,
        jti=uuid.uuid4().hex,
        ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    return sesion


def _evento_auditoria(db: Session, accion: str, request: Request, usuario: Optional[models.Usuario] = None, detalles: Optional[str] = None):
    db.add(models.EventoAuditoria(
        gimnasio_id=usuario.gimnasio_id if usuario else None,
        usuario_id=usuario.id if usuario else None,
        accion=accion,
        metodo=request.method,
        ruta=request.url.path,
        estado_http=200,
        ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        detalles=detalles[:1000] if detalles else None,
    ))
    db.commit()

# ==================================================================
# KEEP-ALIVE INTELIGENTE (anti-sleep Render free tier)
# - Solo se auto-pinga si NO hubo trafico en los ultimos 14 min
# - Lun-Sab 6:00 AM-11:00 PM; domingo 6:00 AM-3:00 PM (Lima)
# - Fuera de ese horario deja dormir al contenedor (ahorra horas)
# ==================================================================
_ultimo_request_ts = time.time()
_sync_version = int(time.time() * 1000)
_INTERVALO_CHECK_SEG = 30           # evita superar los 15 min por desfase del contador
_UMBRAL_INACTIVIDAD_SEG = 14 * 60   # Render duerme tras 15 min sin trafico
_HORA_INICIO = 6    # 6 AM Lima
_HORA_FIN = 23       # 11 PM Lima
def _hora_lima_actual() -> tuple:
    """Retorna (hora, dia_semana) en Lima. dia_semana: 0=lunes, 6=domingo."""
    lima_now = ahora_lima()
    return lima_now.hour, lima_now.weekday()


def _en_horario_activo() -> bool:
    """True si estamos en horario donde el keep-alive debe funcionar.
    Lun-Sab: 6am - 11pm | Dom: 6am - 3pm"""
    hora, dia = _hora_lima_actual()
    if dia == 6:  # domingo
        return _HORA_INICIO <= hora < 15
    return _HORA_INICIO <= hora < _HORA_FIN


async def _keep_alive_loop():
    """Background task: si no hubo trafico reciente y estamos en horario,
    hace un GET a la URL externa para que Render no duerma el contenedor."""
    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not external_url:
        logger.info("[keep-alive] No RENDER_EXTERNAL_URL, keep-alive desactivado (dev local)")
        return
    ping_url = f"{external_url}/ping"
    logger.info(f"[keep-alive] Activo -> {ping_url} (horario {_HORA_INICIO}:00-{_HORA_FIN}:00 Lima)")
    while True:
        await asyncio.sleep(_INTERVALO_CHECK_SEG)
        try:
            if not _en_horario_activo():
                continue  # fuera de horario, dejar dormir
            inactividad = time.time() - _ultimo_request_ts
            if inactividad < _UMBRAL_INACTIVIDAD_SEG:
                continue  # hubo trafico reciente, no hace falta
            # Self-ping a traves de la URL externa (Render lo cuenta como trafico)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(ping_url, timeout=10).read()
            )
            logger.info(f"[keep-alive] Ping enviado (inactivo {inactividad:.0f}s)")
        except Exception as e:
            logger.warning(f"[keep-alive] Error: {e}")


@app.middleware("http")
async def track_last_request(request: Request, call_next):
    """Registra actividad y publica una version liviana de cambios de datos."""
    global _ultimo_request_ts, _sync_version
    _ultimo_request_ts = time.time()
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
        _sync_version += 1
    response.headers["X-Sync-Version"] = str(_sync_version)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path not in {"/docs", "/redoc", "/openapi.json"}:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "img-src 'self' data: blob:; font-src 'self' https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'"
        )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    es_mutacion = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    es_exportacion = "attachment" in (response.headers.get("content-disposition") or "").lower()
    if es_mutacion or es_exportacion:
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        payload = {}
        if token:
            try:
                payload = auth.decodificar_token(token)
            except HTTPException:
                payload = {}
        db_auditoria = SessionLocal()
        try:
            db_auditoria.add(models.EventoAuditoria(
                gimnasio_id=payload.get("gimnasio_id"),
                usuario_id=int(payload["sub"]) if payload.get("tipo") == "usuario" and str(payload.get("sub", "")).isdigit() else None,
                accion="EXPORTAR" if es_exportacion else request.method,
                metodo=request.method,
                ruta=request.url.path[:500],
                estado_http=response.status_code,
                ip=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "")[:500] or None,
            ))
            db_auditoria.commit()
        except Exception:
            db_auditoria.rollback()
            logger.exception("No se pudo registrar auditoria para %s", request.url.path)
        finally:
            db_auditoria.close()
    return response


# ==================================================================
# HELPER MULTI-TENANT
# Uso: gid = get_gid(usuario)  →  db.query(Model).filter(Model.gimnasio_id == gid)
# ==================================================================

def get_gid(usuario: models.Usuario) -> Optional[int]:
    """Extrae el gimnasio_id del usuario autenticado."""
    return usuario.gimnasio_id


def q(db: Session, Model, usuario: models.Usuario):
    """
    Shorthand para queries filtradas por gimnasio.
    Uso: q(db, models.Cliente, usuario).filter(...).all()
    Equivale a: db.query(Model).filter(Model.gimnasio_id == get_gid(usuario))
    """
    gid = get_gid(usuario)
    return db.query(Model).filter(Model.gimnasio_id == gid)


def _cifrador_biometrico() -> Fernet:
    """Deriva una clave exclusiva para biometria sin guardar otra clave en la BD."""
    secreto = os.getenv("BIOMETRIC_ENCRYPTION_KEY") or auth.SECRET_KEY
    material = hashlib.sha256(f"soft-gym-biometria:{secreto}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _cifrar_descriptor_facial(descriptor: List[float]) -> str:
    payload = json.dumps(descriptor, separators=(",", ":")).encode("utf-8")
    return _cifrador_biometrico().encrypt(payload).decode("ascii")


def _descifrar_descriptor_facial(valor: str) -> List[float]:
    try:
        payload = _cifrador_biometrico().decrypt(valor.encode("ascii"))
        descriptor = json.loads(payload)
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("La plantilla facial no se puede descifrar") from exc
    if not isinstance(descriptor, list) or len(descriptor) != 1024:
        raise ValueError("La plantilla facial tiene un formato incompatible")
    return [float(valor) for valor in descriptor]


def _buscar_idempotente(db: Session, usuario: models.Usuario, endpoint: str, clave: Optional[str], payload: dict, Modelo):
    """Devuelve el recurso ya creado si el navegador reenvia la misma operacion."""
    if not isinstance(clave, str) or not clave:
        return None
    if len(clave) < 16 or len(clave) > 100:
        raise HTTPException(status_code=400, detail="Clave de operacion invalida")
    gid = get_gid(usuario)
    # Serializa las operaciones financieras del gimnasio y evita carreras entre reintentos.
    db.query(models.Gimnasio).filter(models.Gimnasio.id == gid).with_for_update().first()
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    registro = db.query(models.OperacionIdempotente).filter(
        models.OperacionIdempotente.gimnasio_id == gid,
        models.OperacionIdempotente.endpoint == endpoint,
        models.OperacionIdempotente.clave == clave,
    ).first()
    if not registro:
        return None
    if registro.payload_hash != payload_hash:
        raise HTTPException(status_code=409, detail="La clave de operacion ya fue usada con datos diferentes")
    recurso = db.query(Modelo).filter(Modelo.id == registro.recurso_id).first()
    if not recurso:
        raise HTTPException(status_code=409, detail="La operacion ya fue procesada, pero su registro no esta disponible")
    return recurso


def _guardar_idempotencia(db: Session, usuario: models.Usuario, endpoint: str, clave: Optional[str], payload: dict, recurso_tipo: str, recurso_id: int):
    if not isinstance(clave, str) or not clave:
        return
    db.add(models.OperacionIdempotente(
        gimnasio_id=get_gid(usuario), endpoint=endpoint, clave=clave,
        payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
        recurso_tipo=recurso_tipo, recurso_id=recurso_id,
    ))


def _del_gym(db: Session, Model, entidad_id: int, usuario: models.Usuario):
    """Obtiene una entidad raiz por id, siempre limitada al tenant actual."""
    return q(db, Model, usuario).filter(Model.id == entidad_id).first()


def _cliente_membresia_del_gym(db: Session, cm_id: int, usuario: models.Usuario):
    """Resuelve una membresia asignada a traves del gimnasio de su cliente."""
    return (
        db.query(models.ClienteMembresia)
        .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
        .filter(
            models.ClienteMembresia.id == cm_id,
            models.Cliente.gimnasio_id == get_gid(usuario),
        )
        .first()
    )


def _pago_membresia_del_gym(db: Session, pago_id: int, usuario: models.Usuario):
    return (
        db.query(models.PagoMembresia)
        .join(models.ClienteMembresia, models.ClienteMembresia.id == models.PagoMembresia.cliente_membresia_id)
        .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
        .filter(models.PagoMembresia.id == pago_id, models.Cliente.gimnasio_id == get_gid(usuario))
        .first()
    )


def _rutina_dia_del_gym(db: Session, dia_id: int, usuario: models.Usuario):
    return (
        db.query(models.RutinaDia)
        .join(models.Rutina, models.Rutina.id == models.RutinaDia.rutina_id)
        .filter(models.RutinaDia.id == dia_id, models.Rutina.gimnasio_id == get_gid(usuario))
        .first()
    )


def _rutina_ejercicio_del_gym(db: Session, ejercicio_id: int, usuario: models.Usuario):
    return (
        db.query(models.RutinaEjercicio)
        .join(models.RutinaDia, models.RutinaDia.id == models.RutinaEjercicio.dia_id)
        .join(models.Rutina, models.Rutina.id == models.RutinaDia.rutina_id)
        .filter(models.RutinaEjercicio.id == ejercicio_id, models.Rutina.gimnasio_id == get_gid(usuario))
        .first()
    )


def _pago_servicio_del_gym(db: Session, pago_id: int, usuario: models.Usuario):
    return (
        db.query(models.PagoServicio)
        .join(models.CargoServicio, models.CargoServicio.id == models.PagoServicio.cargo_id)
        .filter(models.PagoServicio.id == pago_id, models.CargoServicio.gimnasio_id == get_gid(usuario))
        .first()
    )


def _configuracion_del_gym(db: Session, usuario: models.Usuario) -> models.Gimnasio:
    """Fuente unica de configuracion operativa para el tenant autenticado."""
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == get_gid(usuario)).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    return gimnasio


def _sumar_meses(fecha: date, meses: int) -> date:
    """Suma meses conservando el dia cuando existe en el mes destino."""
    indice = fecha.month - 1 + meses
    anio = fecha.year + indice // 12
    mes = indice % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _estado_suscripcion(suscripcion: Optional[models.SuscripcionSaas]) -> str:
    if not suscripcion:
        return "sin_configurar"
    if suscripcion.estado in {"suspendida", "cancelada"}:
        return suscripcion.estado
    hoy = hoy_lima()
    if hoy <= suscripcion.fecha_fin_periodo:
        return "prueba" if suscripcion.estado == "prueba" else "activa"
    if suscripcion.fecha_fin_gracia and hoy <= suscripcion.fecha_fin_gracia:
        return "gracia"
    return "vencida"


def _crear_prueba_saas(db: Session, gimnasio: models.Gimnasio, dias: int = 14):
    """Crea la prueba inicial; no se usa para tenants legacy ya existentes."""
    hoy = hoy_lima()
    suscripcion = models.SuscripcionSaas(
        gimnasio_id=gimnasio.id,
        plan_id=gimnasio.plan_id,
        estado="prueba",
        fecha_inicio=hoy,
        fecha_fin_periodo=hoy + timedelta(days=dias - 1),
        fecha_fin_gracia=hoy + timedelta(days=dias + 4),
        dias_gracia=5,
    )
    db.add(suscripcion)
    return suscripcion


def _serializar_suscripcion(gimnasio: models.Gimnasio, incluir_pagos: bool = True) -> dict:
    suscripcion = gimnasio.suscripcion_saas
    if not suscripcion:
        return {
            "id": None, "gimnasio_id": gimnasio.id, "plan_id": gimnasio.plan_id,
            "nombre_plan": gimnasio.plan.nombre if gimnasio.plan else None,
            "estado": "sin_configurar", "dias_gracia": 0,
            "dias_restantes": None, "auto_renovacion": False, "pagos": [],
        }
    estado = _estado_suscripcion(suscripcion)
    limite = suscripcion.fecha_fin_gracia or suscripcion.fecha_fin_periodo
    dias_restantes = (limite - hoy_lima()).days
    return {
        "id": suscripcion.id,
        "gimnasio_id": gimnasio.id,
        "plan_id": suscripcion.plan_id,
        "nombre_plan": suscripcion.plan.nombre if suscripcion.plan else None,
        "estado": estado,
        "fecha_inicio": suscripcion.fecha_inicio,
        "fecha_fin_periodo": suscripcion.fecha_fin_periodo,
        "fecha_fin_gracia": suscripcion.fecha_fin_gracia,
        "dias_gracia": suscripcion.dias_gracia,
        "dias_restantes": max(dias_restantes, 0),
        "auto_renovacion": suscripcion.auto_renovacion,
        "notas": suscripcion.notas,
        "pagos": sorted(suscripcion.pagos, key=lambda p: p.fecha_pago, reverse=True) if incluir_pagos else [],
    }


def _validar_limite_plan(db: Session, usuario: models.Usuario, recurso: str):
    """
    Valida que el gimnasio no haya alcanzado el limite de su plan SaaS
    para el recurso indicado. Lanza HTTPException 403 si se excede.
    recurso: 'clientes' | 'productos' | 'rutinas' | 'usuarios_staff'
    Un limite de 0 en el plan significa ilimitado.
    """
    gid = get_gid(usuario)
    if not gid:
        return  # sin gimnasio, no hay limite
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gid).first()
    if not gimnasio or not gimnasio.plan_id:
        return
    plan = db.query(models.PlanSaas).filter(models.PlanSaas.id == gimnasio.plan_id).first()
    if not plan:
        return
    if not plan.activo:
        raise HTTPException(status_code=403, detail="El plan del gimnasio esta inactivo")

    mapa = {
        "clientes": (plan.max_clientes, models.Cliente, models.Cliente.activo == True),
        "productos": (plan.max_productos, models.Producto, models.Producto.activo == True),
        "rutinas": (plan.max_rutinas, models.Rutina, models.Rutina.activo == True),
        "usuarios_staff": (plan.max_usuarios_staff, models.Usuario, models.Usuario.activo == True),
    }
    if recurso not in mapa:
        return

    limite, modelo, filtro_extra = mapa[recurso]
    if limite == 0:  # 0 = ilimitado
        return

    query_actual = db.query(func.count(modelo.id)).filter(modelo.gimnasio_id == gid, filtro_extra)
    if recurso == "usuarios_staff":
        query_actual = query_actual.filter(models.Usuario.rol == models.RolUsuario.STAFF)
    actual = query_actual.scalar() or 0

    if actual >= limite:
        nombres = {"clientes": "clientes", "productos": "productos", "rutinas": "rutinas", "usuarios_staff": "usuarios de staff"}
        raise HTTPException(
            status_code=403,
            detail=f"Tu plan ({plan.nombre}) permite maximo {limite} {nombres[recurso]}. "
                   f"Actualmente tienes {actual}. Actualiza tu plan para agregar mas.",
        )


def _validar_nutricion_habilitada(db: Session, usuario: models.Usuario):
    """Lanza 403 si el plan del gimnasio no tiene nutricion habilitada."""
    gid = get_gid(usuario)
    if not gid:
        return
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gid).first()
    if not gimnasio or not gimnasio.plan_id:
        return
    plan = db.query(models.PlanSaas).filter(models.PlanSaas.id == gimnasio.plan_id).first()
    if not plan:
        return
    if not plan.activo:
        raise HTTPException(status_code=403, detail="El plan del gimnasio esta inactivo")
    if not plan.nutricion_habilitada:
        raise HTTPException(
            status_code=403,
            detail=f"Tu plan ({plan.nombre}) no incluye el modulo de nutricion. Actualiza tu plan para acceder a esta funcionalidad.",
        )


def _detectar_delimitador(primera_linea: str) -> str:
    """
    Detecta el separador de un CSV/TSV subido. Excel en espanol
    (Peru y la mayoria de LatAm) exporta CSV con punto y coma (;)
    por defecto, no coma - si no se detecta, ninguna columna hace
    match y TODAS las filas se leen vacias (se ven como si todo
    fuera invalido/duplicado sin ningun error claro). Se prioriza
    tab > punto y coma > coma, contando ocurrencias reales en vez
    de solo verificar presencia, para no confundirse con texto
    libre que traiga una coma suelta.
    """
    if "\t" in primera_linea:
        return "\t"
    conteo_pyc = primera_linea.count(";")
    conteo_coma = primera_linea.count(",")
    if conteo_pyc > conteo_coma:
        return ";"
    return ","

# ========================================================
# ARCHIVOS SUBIDOS (fotos de clientes, productos, etc.)
# ========================================================
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
FOTOS_CLIENTES_DIR = os.path.join(UPLOADS_DIR, "clientes")
FOTOS_PRODUCTOS_DIR = os.path.join(UPLOADS_DIR, "productos")
os.makedirs(FOTOS_CLIENTES_DIR, exist_ok=True)
os.makedirs(FOTOS_PRODUCTOS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

EXTENSIONES_IMAGEN_PERMITIDAS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
TAMANO_MAXIMO_FOTO_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 25_000_000


def _validar_y_optimizar_foto(contenido: bytes, content_type: str, optimizar: bool = False):
    if content_type not in EXTENSIONES_IMAGEN_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Formato no soportado. Usa JPEG, PNG o WEBP")
    if len(contenido) > TAMANO_MAXIMO_FOTO_BYTES:
        raise HTTPException(status_code=400, detail="La imagen supera el tamano maximo de 10MB")
    formatos_por_mime = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    try:
        inspeccion = Image.open(io.BytesIO(contenido))
        if inspeccion.format != formatos_por_mime[content_type]:
            raise HTTPException(status_code=400, detail="El contenido no coincide con el formato declarado")
        inspeccion.verify()
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
        if optimizar:
            imagen = ImageOps.exif_transpose(imagen)
            imagen.thumbnail((960, 960), Image.Resampling.LANCZOS)
            # PNG y WEBP pueden traer transparencia en RGBA, LA o mediante
            # una paleta. WEBP admite canal alfa, por lo que no debemos
            # aplanarlo sobre blanco (especialmente importante para logos).
            tiene_transparencia = "A" in imagen.getbands() or "transparency" in imagen.info
            imagen = imagen.convert("RGBA" if tiene_transparencia else "RGB")
            salida = io.BytesIO()
            imagen.save(salida, format="WEBP", quality=76, method=6, optimize=True)
            contenido = salida.getvalue()
            content_type = "image/webp"
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="La foto no es una imagen valida o es demasiado grande")
    return contenido, content_type


def _validar_y_guardar_foto(contenido: bytes, content_type: str, directorio: str, optimizar: bool = False) -> str:
    contenido, content_type = _validar_y_optimizar_foto(contenido, content_type, optimizar)
    extension = EXTENSIONES_IMAGEN_PERMITIDAS[content_type]
    nombre_archivo = f"{uuid.uuid4().hex}{extension}"
    ruta_destino = os.path.join(directorio, nombre_archivo)
    with open(ruta_destino, "wb") as f:
        f.write(contenido)
    carpeta = os.path.basename(directorio)
    return f"/uploads/{carpeta}/{nombre_archivo}"


def _version_contenido_imagen(contenido: Optional[bytes]) -> Optional[str]:
    """Token corto para invalidar la cache cuando se reemplaza una imagen."""
    return hashlib.sha256(contenido).hexdigest()[:12] if contenido else None


def _eliminar_foto_anterior(foto_url: Optional[str]):
    if not foto_url:
        return
    ruta = os.path.join(os.path.dirname(__file__), foto_url.lstrip("/"))
    if os.path.isfile(ruta):
        try:
            os.remove(ruta)
        except OSError:
            pass

# ========================================================
# CORS - permite que los frontends (staff y alumno) se conecten
# ========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://localhost:3002,"
        "http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002",
    ).split(",") if o.strip()],
    # La autenticacion usa Bearer JWT, no cookies cross-origin.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Sync-Version"],
)


def _migrar_columnas_nuevas():
    """
    SQLAlchemy's create_all no altera tablas existentes, asi que en
    una base de datos ya creada agregamos aqui, de forma
    idempotente, las columnas nuevas que se fueron sumando al
    modelo (evita tener que borrar la BD en cada despliegue).
    Soporta SQLite (PRAGMA) y PostgreSQL (information_schema).
    """
    from sqlalchemy import text, inspect as sa_inspect

    es_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

    def _columnas_existentes(conn, tabla):
        if es_sqlite:
            return {fila[1] for fila in conn.execute(text(f"PRAGMA table_info({tabla})"))}
        else:
            filas = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{tabla}'"
            ))
            return {fila[0] for fila in filas}

    def _tipo_pg(definicion_sql):
        """Convierte tipos SQLite a PostgreSQL."""
        d = definicion_sql.upper()
        if "BOOLEAN" in d:
            default = "DEFAULT FALSE" if "DEFAULT 0" in d else ("DEFAULT TRUE" if "DEFAULT 1" in d else "")
            return f"BOOLEAN {default}".strip()
        if "FLOAT" in d:
            val = definicion_sql.split("DEFAULT")[-1].strip() if "DEFAULT" in definicion_sql else ""
            return f"DOUBLE PRECISION DEFAULT {val}" if val else "DOUBLE PRECISION"
        if "INTEGER" in d:
            val = definicion_sql.split("DEFAULT")[-1].strip() if "DEFAULT" in definicion_sql else ""
            return f"INTEGER DEFAULT {val}" if val else "INTEGER"
        if "VARCHAR" in d or "TEXT" in d:
            val = definicion_sql.split("DEFAULT")[-1].strip() if "DEFAULT" in definicion_sql else ""
            tipo_base = "TEXT" if "TEXT" in d else "VARCHAR"
            return f"{tipo_base} DEFAULT {val}" if val else tipo_base
        if "DATE" in d:
            return "DATE"
        if "BLOB" in d:
            return "BYTEA"
        return definicion_sql

    columnas_esperadas = {
        "gimnasios": [
            ("logo_oscuro_url", "VARCHAR"),
            ("latitud", "FLOAT"),
            ("longitud", "FLOAT"),
            ("radio_asistencia_metros", "FLOAT DEFAULT 150.0"),
            ("equipamiento_disponible", "TEXT"),
            ("equipamiento_personalizado", "TEXT"),
            ("logo_datos", "BLOB"),
            ("logo_tipo", "VARCHAR"),
            ("logo_oscuro_datos", "BLOB"),
            ("logo_oscuro_tipo", "VARCHAR"),
        ],
        "cliente_membresias": [("monto_pagado", "FLOAT DEFAULT 0.0"), ("vendido_por_id", "INTEGER"), ("fecha_pago_saldo", "DATE"), ("metodo_pago", "VARCHAR DEFAULT 'efectivo'")],
        "clientes": [
            ("foto_url", "VARCHAR"),
            ("foto_datos", "BLOB"),
            ("foto_tipo", "VARCHAR"),
            ("genero", "VARCHAR"),
            ("fecha_renovacion", "DATE"),
            ("fecha_vencimiento", "DATE"),
            ("membresia_texto", "VARCHAR"),
            ("asistencias_legado", "INTEGER DEFAULT 0"),
            ("gimnasio_id", "INTEGER"),
        ],
        "productos": [("foto_url", "VARCHAR"), ("foto_datos", "BLOB"), ("foto_tipo", "VARCHAR"), ("gimnasio_id", "INTEGER")],
        "pagos_membresia": [("fecha_proximo_pago", "DATE")],
        "planes_nutricion": [("origen", "VARCHAR DEFAULT 'membresia'"), ("gimnasio_id", "INTEGER")],
        "ventas": [("usuario_id", "INTEGER"), ("costo_comision_gym", "FLOAT DEFAULT 0.0"), ("gimnasio_id", "INTEGER")],
        "empleados": [
            ("dni", "VARCHAR"),
            ("fecha_nacimiento", "DATE"),
            ("puesto", "VARCHAR"),
            ("codigo_acceso", "VARCHAR"),
            ("gimnasio_id", "INTEGER"),
            ("horario_semanal", "TEXT DEFAULT '[]'"),
        ],
        "usuarios": [
            ("es_administrador", "BOOLEAN DEFAULT 1"),
            ("es_superadmin", "BOOLEAN DEFAULT 0"),
            ("puede_eliminar", "BOOLEAN DEFAULT 1"),
            ("puede_exportar", "BOOLEAN DEFAULT 0"),
            ("zonas_permitidas", "VARCHAR"),
            ("gimnasio_id", "INTEGER"),
            ("email", "VARCHAR"),
            ("email_verificado", "BOOLEAN DEFAULT 0"),
            ("sesion_version", "INTEGER DEFAULT 1"),
            ("pin_counter_hash", "VARCHAR"),
        ],
        "membresias": [
            ("duracion_meses", "INTEGER"),
            ("duracion_dias_extra", "INTEGER"),
            ("monto_inicial", "FLOAT"),
            ("fracciones_pago_deuda", "INTEGER"),
            ("penalizacion", "FLOAT"),
            ("dias_gracia_pago", "INTEGER"),
            ("monto_mensual", "FLOAT"),
            ("dias_congelamiento", "INTEGER"),
            ("permite_congelamiento", "BOOLEAN DEFAULT 1"),
            ("dias_acceso_periodo", "INTEGER"),
            ("hora_inicio_acceso", "VARCHAR DEFAULT '00:00'"),
            ("hora_fin_acceso", "VARCHAR DEFAULT '24:00'"),
            ("dias_semana_acceso", "VARCHAR DEFAULT 'dom,lun,mar,mie,jue,vie,sab'"),
            ("password_tarifa", "VARCHAR"),
            ("congelado_no_aparece_pagos", "BOOLEAN DEFAULT 0"),
            ("no_aparecer_reporte_cruce_medidas", "BOOLEAN DEFAULT 0"),
            ("incluye_nutricion", "BOOLEAN DEFAULT 0"),
            ("incluye_retos", "BOOLEAN DEFAULT 0"),
            ("gimnasio_id", "INTEGER"),
        ],
        "clases_dictadas": [
            ("serie_id", "VARCHAR"),
            ("profesor_reemplazo_id", "INTEGER"),
            ("agenda_nombre", "VARCHAR DEFAULT 'Clases'"),
            ("permite_registro", "BOOLEAN DEFAULT 0"),
            ("gimnasio_id", "INTEGER"),
        ],
        "pagos_planilla": [
            ("desde", "DATE"),
            ("hasta", "DATE"),
            ("gimnasio_id", "INTEGER"),
            ("metodo_pago", "VARCHAR"),
        ],
        # clientes_extra: ya fusionado arriba en la entrada "clientes"
        "rutina_ejercicios": [("tipo_ejercicio_id", "INTEGER")],
        "comidas_plan": [("alimento_id", "INTEGER"), ("cantidad_gramos", "FLOAT"), ("porcion_cliente", "VARCHAR")],
        "pagos_servicio": [("metodo_pago", "VARCHAR")],
        "cargos_servicio": [
            ("recurrente_tipo", "VARCHAR"),
            ("recurrente_dias_semana", "VARCHAR"),
            ("serie_id", "VARCHAR"),
            ("gimnasio_id", "INTEGER"),
        ],
        "tipos_ejercicio": [
            ("categoria", "VARCHAR"),
            ("equipamiento", "VARCHAR"),
            ("nivel", "VARCHAR"),
            ("genero_recomendado", "VARCHAR DEFAULT 'todos'"),
            ("objetivo", "VARCHAR"),
            ("imagen_url_2", "VARCHAR"),
            ("imagen_url_3", "VARCHAR"),
            ("imagen_datos", "BLOB"),
            ("imagen_tipo", "VARCHAR"),
            ("gimnasio_id", "INTEGER"),
        ],
        "alimentos": [
            ("porcion_casera", "VARCHAR"),
            ("gimnasio_id", "INTEGER"),
        ],
        "clientes_historicos": [("gimnasio_id", "INTEGER")],
        "compras": [("gimnasio_id", "INTEGER"), ("metodo_pago", "VARCHAR")],
        "asistencias": [("gimnasio_id", "INTEGER")],
        "progresos": [("gimnasio_id", "INTEGER")],
        "rutinas": [("gimnasio_id", "INTEGER")],
        "paquetes_rutina": [("equipamiento_origen", "VARCHAR")],
        "paquetes_nutricion": [("gimnasio_id", "INTEGER")],
        "paquete_alimentos": [("porcion_cliente", "VARCHAR")],
        "retos": [("gimnasio_id", "INTEGER")],
        "puestos": [("gimnasio_id", "INTEGER")],
        "servicios": [("gimnasio_id", "INTEGER")],
        "gastos": [("gimnasio_id", "INTEGER"), ("metodo_pago", "VARCHAR")],
        "metas_mensuales": [("gimnasio_id", "INTEGER")],
        "tramos_comision": [("gimnasio_id", "INTEGER")],
        "medidas": [("gimnasio_id", "INTEGER")],
    }
    with engine.connect() as conn:
        for tabla, columnas in columnas_esperadas.items():
            try:
                existentes = _columnas_existentes(conn, tabla)
            except Exception:
                continue  # tabla puede no existir aún
            for nombre_columna, definicion_sql in columnas:
                if nombre_columna not in existentes:
                    tipo = definicion_sql if es_sqlite else _tipo_pg(definicion_sql)
                    try:
                        conn.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {nombre_columna} {tipo}"))
                    except Exception:
                        pass  # columna ya existe o tipo incompatible

        # En PostgreSQL el DNI debe ser unico dentro de cada gimnasio,
        # no en toda la plataforma. Bases nuevas reciben la restriccion
        # desde models.py; esta conversion cubre despliegues existentes.
        if not es_sqlite:
            restricciones = sa_inspect(conn).get_unique_constraints("clientes")
            for restriccion in restricciones:
                if restriccion.get("column_names") == ["dni"] and restriccion.get("name"):
                    nombre = restriccion["name"].replace('"', '""')
                    conn.execute(text(f'ALTER TABLE clientes DROP CONSTRAINT "{nombre}"'))
            restricciones = sa_inspect(conn).get_unique_constraints("clientes")
            if not any(r.get("column_names") == ["gimnasio_id", "dni"] for r in restricciones):
                conn.execute(text(
                    "ALTER TABLE clientes ADD CONSTRAINT uq_clientes_gimnasio_dni "
                    "UNIQUE (gimnasio_id, dni)"
                ))
        conn.commit()


def _sembrar_gimnasio_default():
    """
    Garantiza que exista un Gimnasio con id=1 (el 'default' para la
    instalacion actual). Tambien asigna gimnasio_id=1 a todos los
    registros existentes que aun tengan gimnasio_id=NULL, de forma
    idempotente. Esto permite que la base de datos ya existente
    funcione correctamente despues de la migracion multi-tenant.
    """
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # 1. Crear el plan Free si no existe
        plan = db.query(models.PlanSaas).filter_by(nombre="Free").first()
        if not plan:
            plan = models.PlanSaas(
                nombre="Free",
                precio_mensual=0.0,
                max_clientes=50,
                max_productos=20,
                max_rutinas=10,
                max_usuarios_staff=1,
                nutricion_habilitada=False,
                reportes_avanzados=False,
                dominio_propio=False,
            )
            db.add(plan)
            db.flush()

        plan_pro = db.query(models.PlanSaas).filter_by(nombre="Pro").first()
        if not plan_pro:
            plan_pro = models.PlanSaas(
                nombre="Pro",
                precio_mensual=49.0,
                max_clientes=0,
                max_productos=0,
                max_rutinas=0,
                max_usuarios_staff=0,
                nutricion_habilitada=True,
                reportes_avanzados=True,
                dominio_propio=True,
            )
            db.add(plan_pro)
            db.flush()

        # 2. Crear el gimnasio default si no existe
        gimnasio = db.query(models.Gimnasio).filter_by(id=1).first()
        if not gimnasio:
            gimnasio = db.query(models.Gimnasio).filter_by(slug="mi-gimnasio").first()
        if not gimnasio:
            # Leer configuracion existente para no perder datos
            try:
                cfg = db.execute(text("SELECT * FROM configuracion LIMIT 1")).fetchone()
            except Exception:
                cfg = None
            gimnasio = models.Gimnasio(
                nombre="Mi Gimnasio",
                slug="mi-gimnasio",
                plan_id=plan_pro.id,  # tu instalacion actual va en Pro
                activo=True,
                moneda=cfg.moneda if cfg and hasattr(cfg, 'moneda') else "S/",
                comision_tarjeta=cfg.comision_tarjeta if cfg and hasattr(cfg, 'comision_tarjeta') else 3.5,
                comision_qr=cfg.comision_qr if cfg and hasattr(cfg, 'comision_qr') else 2.0,
                dias_aviso_vencimiento=cfg.dias_aviso_vencimiento if cfg and hasattr(cfg, 'dias_aviso_vencimiento') else 7,
                comision_producto_porcentaje=cfg.comision_producto_porcentaje if cfg and hasattr(cfg, 'comision_producto_porcentaje') else 0.0,
                tema=cfg.tema if cfg and hasattr(cfg, 'tema') else "lavanda",
                modo_tema=cfg.modo_tema if cfg and hasattr(cfg, 'modo_tema') else "claro",
                clausulas_contrato=cfg.clausulas_contrato if cfg and hasattr(cfg, 'clausulas_contrato') else None,
                medidas_campos_visibles=cfg.medidas_campos_visibles if cfg and hasattr(cfg, 'medidas_campos_visibles') else None,
                medidas_valores_visibles=cfg.medidas_valores_visibles if cfg and hasattr(cfg, 'medidas_valores_visibles') else None,
            )
            db.add(gimnasio)
            db.flush()
        db.commit()

        # 3. Asignar gimnasio_id al gimnasio default a todos los registros NULL (idempotente)
        gid_default = gimnasio.id  # puede no ser 1 en PostgreSQL
        tablas_raiz = [
            "usuarios", "clientes", "clientes_historicos", "membresias",
            "productos", "ventas", "compras", "asistencias", "progresos",
            "tipos_ejercicio", "rutinas", "planes_nutricion", "alimentos",
            "paquetes_nutricion", "retos", "puestos", "empleados",
            "clases_dictadas", "pagos_planilla", "servicios", "cargos_servicio",
            "gastos", "metas_mensuales", "tramos_comision", "medidas",
        ]
        with engine.connect() as conn:
            for tabla in tablas_raiz:
                try:
                    conn.execute(text(
                        f"UPDATE {tabla} SET gimnasio_id = {gid_default} WHERE gimnasio_id IS NULL"
                    ))
                except Exception:
                    pass  # tabla puede no existir aun en una BD nueva
            # El flujo anterior asignaba una clave comun. Los alumnos que aun
            # la conservan pasan al nuevo flujo seguro de crear su propia clave.
            conn.execute(text(
                "UPDATE clientes SET codigo_acceso = NULL WHERE codigo_acceso = :password_legacy"
            ), {"password_legacy": PASSWORD_LEGACY_ALUMNO})
            conn.commit()

        # 4. Marcar al primer admin como superadmin (idempotente)
        primer_admin = db.query(models.Usuario).filter(
            models.Usuario.gimnasio_id == gid_default,
            models.Usuario.es_administrador == True,
        ).first()
        if primer_admin:
            primer_admin.es_superadmin = True
            db.commit()
    finally:
        db.close()


# ==================================================================
# ENDPOINT DE SALUD (usado por el keep-alive y monitoreo)
# ==================================================================
@app.get("/ping", tags=["Sistema"])
def ping():
    """Health check liviano. Usado por el keep-alive interno."""
    hora, dia = _hora_lima_actual()
    return {"status": "ok", "hora_lima": hora, "dia": dia, "keep_alive_activo": _en_horario_activo()}


@app.get("/health/ready", include_in_schema=False)
def readiness(db: Session = Depends(get_db)):
    """Comprueba que la aplicación puede consultar la base de datos."""
    try:
        db.execute(text("SELECT 1"))
        version = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        return {"status": "ready", "database": "ok", "migration": version}
    except Exception:
        logger.exception("Fallo la comprobacion de disponibilidad")
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "error"})


@app.get("/sistema/preparacion-produccion", tags=["Sistema"])
def preparacion_produccion(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """Diagnostico sin exponer secretos para activar controles de produccion."""
    entorno_produccion = os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
    secreto_seguro = auth.SECRET_KEY != "cambiar-esta-clave-en-produccion-no-usar-en-real"
    postgres = SQLALCHEMY_DATABASE_URL.startswith(("postgresql://", "postgresql+"))
    app_base = os.getenv("APP_BASE_URL", "").strip()
    url_https = app_base.startswith("https://")
    correo_configurado = email_service.esta_configurado()
    verificacion_activa = os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"
    cuentas_pendientes = db.query(func.count(models.Usuario.id)).filter(
        models.Usuario.gimnasio_id == usuario.gimnasio_id,
        models.Usuario.activo == True,
        or_(models.Usuario.email.is_(None), models.Usuario.email_verificado != True),
    ).scalar() or 0
    try:
        migracion = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        db.execute(text("SELECT COUNT(*) FROM intentos_acceso")).scalar()
        bloqueo_persistente = True
    except Exception:
        db.rollback()
        migracion = None
        bloqueo_persistente = False

    correo_puede_activarse = correo_configurado and url_https and cuentas_pendientes == 0
    comprobaciones = [
        {"nombre": "Entorno de produccion", "ok": entorno_produccion, "detalle": "Activo" if entorno_produccion else "Modo de desarrollo"},
        {"nombre": "Clave de seguridad", "ok": secreto_seguro, "detalle": "Configurada" if secreto_seguro else "Falta configurar"},
        {"nombre": "Base PostgreSQL", "ok": postgres, "detalle": "Conectada" if postgres else "Base local"},
        {"nombre": "Bloqueo de accesos persistente", "ok": bloqueo_persistente, "detalle": "Activo" if bloqueo_persistente else "Migracion pendiente"},
        {"nombre": "URL publica segura", "ok": url_https, "detalle": "HTTPS activo" if url_https else "Falta APP_BASE_URL con HTTPS"},
        {"nombre": "Proveedor de correo", "ok": correo_configurado, "detalle": "Configurado" if correo_configurado else "Faltan credenciales de correo"},
        {"nombre": "Cuentas con correo verificado", "ok": cuentas_pendientes == 0, "detalle": "Todas listas" if cuentas_pendientes == 0 else f"{cuentas_pendientes} cuenta(s) pendiente(s)"},
        {"nombre": "Verificacion de correo", "ok": verificacion_activa, "detalle": "Obligatoria" if verificacion_activa else "Aun no obligatoria"},
    ]
    return {
        "estado": "listo" if all(item["ok"] for item in comprobaciones[:5]) else "requiere_atencion",
        "migracion": migracion,
        "correo_puede_activarse": correo_puede_activarse,
        "correo_configurado": correo_configurado and url_https,
        "verificacion_correo_activa": verificacion_activa,
        "comprobaciones": comprobaciones,
        "respaldo": "Revisar en GitHub que el respaldo diario tenga una ejecucion exitosa",
    }


@app.post("/sistema/probar-correo", tags=["Sistema"])
def probar_correo_produccion(
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    if not email_service.esta_configurado():
        raise HTTPException(status_code=503, detail="El proveedor de correo aun no esta configurado")
    if not usuario.email:
        raise HTTPException(status_code=400, detail="Tu usuario administrador no tiene correo registrado")
    try:
        email_service.enviar(
            usuario.email,
            "Prueba de correo de Soft-Gym",
            email_service.plantilla_accion(
                "Correo configurado correctamente",
                "Soft-Gym pudo enviar este mensaje desde el entorno de produccion.",
                "Abrir Soft-Gym",
                os.getenv("APP_BASE_URL", "https://soft-mrgym.onrender.com"),
            ),
        )
    except Exception as exc:
        logger.exception("Fallo la prueba de correo de produccion")
        raise HTTPException(status_code=502, detail="El proveedor no pudo entregar el correo de prueba") from exc
    return {"message": "Correo de prueba enviado al administrador"}


@app.get("/sync-version", tags=["Sistema"])
def sync_version():
    """Version minima para que los clientes consulten cambios sin descargar todos los datos."""
    return {"version": _sync_version}


@app.on_event("startup")
def startup_event():
    # Lanzar keep-alive como tarea de fondo
    asyncio.get_event_loop().create_task(_keep_alive_loop())
    # En PostgreSQL, crear ENUMs puede fallar si ya existen (race condition
    # entre workers de gunicorn, o deploy anterior parcial). Se maneja
    # creando las tablas en un solo intento robusto.
    from sqlalchemy import text
    with engine.connect() as conn:
        # Pre-crear los ENUMs si no existen (evita el error de create_all)
        for enum_name, enum_values in [
            ("rolusuario", "'staff', 'profesor'"),
            ("metodopago", "'efectivo', 'tarjeta', 'qr'"),
            ("tipocomida", "'desayuno', 'comida', 'cena', 'aperitivo'"),
            ("tipoempleado", "'staff_fijo', 'profesor_de_sala'"),
            ("categoriaalimento", "'proteina', 'carbohidrato', 'grasa', 'vegetal', 'fruta', 'lacteo', 'legumbre', 'otro'"),
            ("propositonutricion", "'bajar_peso', 'ganar_masa', 'mantenimiento', 'definicion'"),
            ("categoriagasto", "'compra_producto', 'pago_staff', 'pago_profesor', 'pago_servicio', 'otros'"),
        ]:
            try:
                conn.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({enum_values})"))
            except Exception:
                pass  # ya existe
        conn.commit()

    try:
        models.Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        print(f"[WARN] create_all: {e}")
    _migrar_columnas_nuevas()
    _sembrar_gimnasio_default()  # garantiza que exista el gimnasio 1 y asigna data existente
    _sembrar_puestos_iniciales()
    _sembrar_ejercicios_catalogo()
    _normalizar_equipamiento_ejercicios()
    _sembrar_paquetes_rutina_iniciales()
    _sembrar_alimentos_iniciales()
    _sembrar_alimentos_expansion_lima()
    _sembrar_alimentos_expansion_lima_2()
    _sembrar_paquetes_nutricion_iniciales()
    _sembrar_paquetes_nutricion_variantes()
    _sembrar_servicios_iniciales()
    _sembrar_porciones_caseras()
    _normalizar_porciones_cliente()
    _sincronizar_nombres_ejercicios_catalogo()
    _rotar_tokens_fotos_clientes()


def _sembrar_ejercicios_catalogo():
    """Precarga el catalogo de ejercicios con categoria, equipamiento, nivel, genero y objetivo para sugerencia automatica."""
    db = SessionLocal()
    try:
        _EJERCICIOS = [
            # CALENTAMIENTO
            ("Saltos de tijera", "Cuerpo completo", "calentamiento", "sin_equipo", "principiante", "todos", "bajar_peso"),
            ("Saltar cuerda basico", "Cuerpo completo", "calentamiento", "cuerda", "principiante", "todos", "bajar_peso"),
            ("Saltar cuerda doble", "Cuerpo completo", "calentamiento", "cuerda", "intermedio", "todos", "bajar_peso"),
            ("Saltar cuerda cruzada", "Cuerpo completo", "calentamiento", "cuerda", "avanzado", "todos", "tonificar"),
            ("Trote en el sitio", "Piernas", "calentamiento", "sin_equipo", "principiante", "todos", "bajar_peso"),
            ("Step basico subir y bajar", "Piernas", "calentamiento", "step", "principiante", "todos", "bajar_peso"),
            ("Step lateral", "Piernas", "calentamiento", "step", "principiante", "todos", "tonificar"),
            ("Step con rodillazo", "Piernas", "calentamiento", "step", "intermedio", "todos", "tonificar"),
            ("Step con patada", "Piernas", "calentamiento", "step", "intermedio", "femenino", "tonificar"),
            ("Circulos de cadera con pelota", "Core", "calentamiento", "pelota", "principiante", "femenino", "flexibilidad"),
            ("Pase de pelota alrededor del cuerpo", "Core", "calentamiento", "pelota", "principiante", "todos", "flexibilidad"),
            ("Pelota overhead squat", "Cuerpo completo", "calentamiento", "pelota", "intermedio", "todos", "tonificar"),
            ("Rotacion de tronco con pelota", "Core", "calentamiento", "pelota", "principiante", "todos", "flexibilidad"),
            # CARDIO
            ("Burpees", "Cuerpo completo", "cardio", "sin_equipo", "intermedio", "todos", "bajar_peso"),
            ("Mountain climbers", "Core", "cardio", "sin_equipo", "intermedio", "todos", "bajar_peso"),
            ("Sentadilla con salto", "Piernas", "cardio", "sin_equipo", "intermedio", "todos", "bajar_peso"),
            ("Rodillazos altos", "Core", "cardio", "sin_equipo", "principiante", "todos", "bajar_peso"),
            ("Patinadores laterales", "Piernas", "cardio", "sin_equipo", "intermedio", "todos", "tonificar"),
            ("Box jump (step alto)", "Piernas", "cardio", "step", "avanzado", "todos", "ganar_masa"),
            ("Step up con mancuerna", "Piernas", "cardio", "step", "intermedio", "todos", "tonificar"),
            # FUERZA - TREN SUPERIOR
            ("Press de banca con barra", "Pecho", "fuerza", "barra", "intermedio", "masculino", "ganar_masa"),
            ("Press inclinado con mancuernas", "Pecho", "fuerza", "mancuernas", "intermedio", "todos", "ganar_masa"),
            ("Aperturas con mancuernas", "Pecho", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Flexiones de pecho", "Pecho", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Flexiones diamante", "Triceps", "fuerza", "sin_equipo", "avanzado", "masculino", "ganar_masa"),
            ("Remo con barra", "Espalda", "fuerza", "barra", "intermedio", "todos", "ganar_masa"),
            ("Remo con mancuerna", "Espalda", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Jalon al pecho (maquina)", "Espalda", "fuerza", "maquina", "principiante", "todos", "tonificar"),
            ("Dominadas", "Espalda", "fuerza", "barra", "avanzado", "masculino", "ganar_masa"),
            ("Press militar con mancuernas", "Hombros", "fuerza", "mancuernas", "intermedio", "todos", "ganar_masa"),
            ("Elevaciones laterales", "Hombros", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Elevaciones frontales", "Hombros", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Curl de biceps con mancuernas", "Biceps", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Curl con barra", "Biceps", "fuerza", "barra", "intermedio", "masculino", "ganar_masa"),
            ("Extension de triceps con mancuerna", "Triceps", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Fondos en paralelas", "Triceps", "fuerza", "sin_equipo", "avanzado", "masculino", "ganar_masa"),
            ("Press en maquina de pecho", "Pecho", "fuerza", "maquina", "principiante", "femenino", "tonificar"),
            ("Remo en maquina", "Espalda", "fuerza", "maquina", "principiante", "femenino", "tonificar"),
            # Variantes corporales y con maquina por grupo. Permiten que
            # una plantilla se adapte sin perder el objetivo muscular.
            ("Remo isometrico con autocarga", "Espalda", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Flexiones pica para hombros", "Hombros", "fuerza", "sin_equipo", "intermedio", "todos", "ganar_masa"),
            ("Curl de biceps con autorresistencia", "Biceps", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Extension de triceps con autorresistencia", "Triceps", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Press de hombros en maquina", "Hombros", "fuerza", "press_hombros_maquina", "principiante", "todos", "tonificar"),
            ("Curl de biceps en maquina", "Biceps", "fuerza", "biceps_maquina", "principiante", "todos", "tonificar"),
            ("Extension de triceps en maquina", "Triceps", "fuerza", "triceps_maquina", "principiante", "todos", "tonificar"),
            # FUERZA - TREN INFERIOR
            ("Sentadilla con barra", "Piernas", "fuerza", "barra", "intermedio", "todos", "ganar_masa"),
            ("Sentadilla copa con mancuerna", "Piernas", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Prensa de piernas (maquina)", "Piernas", "fuerza", "maquina", "principiante", "todos", "ganar_masa"),
            ("Extension de cuadriceps (maquina)", "Piernas", "fuerza", "maquina", "principiante", "todos", "tonificar"),
            ("Curl de femoral (maquina)", "Piernas", "fuerza", "maquina", "principiante", "todos", "tonificar"),
            ("Peso muerto rumano con barra", "Piernas", "fuerza", "barra", "intermedio", "todos", "ganar_masa"),
            ("Peso muerto rumano con mancuernas", "Piernas", "fuerza", "mancuernas", "principiante", "femenino", "tonificar"),
            ("Zancadas con mancuernas", "Piernas", "fuerza", "mancuernas", "principiante", "todos", "tonificar"),
            ("Hip thrust con barra", "Gluteos", "fuerza", "barra", "intermedio", "femenino", "ganar_masa"),
            ("Hip thrust en maquina", "Gluteos", "fuerza", "maquina", "principiante", "femenino", "tonificar"),
            ("Abduccion de cadera (maquina)", "Gluteos", "fuerza", "maquina", "principiante", "femenino", "tonificar"),
            ("Elevacion de talones (pantorrilla)", "Piernas", "fuerza", "maquina", "principiante", "todos", "tonificar"),
            ("Sentadilla bulgara", "Piernas", "fuerza", "mancuernas", "avanzado", "todos", "ganar_masa"),
            ("Patada de gluteo en polea", "Gluteos", "fuerza", "maquina", "principiante", "femenino", "tonificar"),
            ("Sentadilla con peso corporal", "Piernas", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Zancadas alternas sin peso", "Piernas", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Puente de gluteos", "Gluteos", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Patada de gluteo sin equipo", "Gluteos", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            # CORE
            ("Plancha frontal", "Core", "fuerza", "colchoneta", "principiante", "todos", "tonificar"),
            ("Plancha lateral", "Core", "fuerza", "colchoneta", "intermedio", "todos", "tonificar"),
            ("Crunch abdominal", "Core", "fuerza", "colchoneta", "principiante", "todos", "tonificar"),
            ("Crunch con pelota", "Core", "fuerza", "pelota", "principiante", "todos", "tonificar"),
            ("Russian twist", "Core", "fuerza", "colchoneta", "intermedio", "todos", "tonificar"),
            ("Russian twist con pelota", "Core", "fuerza", "pelota", "intermedio", "todos", "tonificar"),
            ("Elevacion de piernas", "Core", "fuerza", "colchoneta", "intermedio", "todos", "tonificar"),
            ("Bicicleta abdominal", "Core", "fuerza", "colchoneta", "principiante", "todos", "bajar_peso"),
            ("Pelota entre rodillas squeeze", "Core", "fuerza", "pelota", "principiante", "femenino", "tonificar"),
            ("Plancha frontal sin equipo", "Core", "fuerza", "sin_equipo", "principiante", "todos", "tonificar"),
            ("Crunch abdominal en maquina", "Core", "fuerza", "abdominal_maquina", "principiante", "todos", "tonificar"),
            # FUNCIONAL
            ("Kettlebell swing", "Cuerpo completo", "funcional", "mancuernas", "intermedio", "todos", "bajar_peso"),
            ("Thruster con mancuernas", "Cuerpo completo", "funcional", "mancuernas", "intermedio", "todos", "ganar_masa"),
            ("Clean and press con mancuerna", "Cuerpo completo", "funcional", "mancuernas", "avanzado", "todos", "ganar_masa"),
            ("Circuito corporal completo", "Cuerpo completo", "funcional", "sin_equipo", "principiante", "todos", "bajar_peso"),
            ("Circuito en multiestacion", "Cuerpo completo", "funcional", "multiestacion", "principiante", "todos", "ganar_masa"),
            ("Battle ropes", "Cuerpo completo", "funcional", "cuerda", "intermedio", "todos", "bajar_peso"),
            ("Wall ball con pelota", "Cuerpo completo", "funcional", "pelota", "intermedio", "todos", "tonificar"),
            ("Sentadilla con banda elastica", "Piernas", "funcional", "banda", "principiante", "femenino", "tonificar"),
            ("Caminata lateral con banda", "Gluteos", "funcional", "banda", "principiante", "femenino", "tonificar"),
            ("Pull apart con banda", "Espalda", "funcional", "banda", "principiante", "todos", "tonificar"),
            ("Remo en TRX", "Espalda", "funcional", "trx", "principiante", "todos", "tonificar"),
            ("Sentadilla asistida en TRX", "Piernas", "funcional", "trx", "principiante", "todos", "tonificar"),
            ("Caminata en caminadora", "Piernas", "cardio", "caminadora", "principiante", "todos", "bajar_peso"),
            ("Intervalos en caminadora", "Piernas", "cardio", "caminadora", "intermedio", "todos", "bajar_peso"),
            ("Bicicleta estatica", "Piernas", "cardio", "bicicleta_estatica", "principiante", "todos", "bajar_peso"),
            ("Eliptica", "Cuerpo completo", "cardio", "eliptica", "principiante", "todos", "bajar_peso"),
            ("Escaladora", "Piernas", "cardio", "escaladora", "intermedio", "todos", "tonificar"),
            ("Remo ergometro", "Cuerpo completo", "cardio", "remo_cardio", "intermedio", "todos", "rendimiento"),
            ("Golpes rectos al saco", "Cuerpo completo", "cardio", "saco_boxeo", "principiante", "todos", "bajar_peso"),
            ("Combinaciones al saco", "Cuerpo completo", "cardio", "saco_boxeo", "intermedio", "todos", "rendimiento"),
            ("Trabajo de pera de boxeo", "Hombros", "cardio", "pera_boxeo", "intermedio", "todos", "rendimiento"),
            ("Sombra de boxeo", "Cuerpo completo", "cardio", "sin_equipo", "principiante", "todos", "bajar_peso"),
            # ESTIRAMIENTO
            ("Estiramiento de cuadriceps de pie", "Piernas", "estiramiento", "sin_equipo", "principiante", "todos", "flexibilidad"),
            ("Estiramiento de isquiotibiales", "Piernas", "estiramiento", "colchoneta", "principiante", "todos", "flexibilidad"),
            ("Estiramiento de pecho en pared", "Pecho", "estiramiento", "sin_equipo", "principiante", "todos", "flexibilidad"),
            ("Estiramiento de espalda (gato-vaca)", "Espalda", "estiramiento", "colchoneta", "principiante", "todos", "flexibilidad"),
            ("Estiramiento de hombros", "Hombros", "estiramiento", "sin_equipo", "principiante", "todos", "flexibilidad"),
            ("Pelota de estabilidad estiramiento de espalda", "Espalda", "estiramiento", "pelota", "principiante", "todos", "flexibilidad"),
            ("Estiramiento de cadera con pelota", "Piernas", "estiramiento", "pelota", "principiante", "femenino", "flexibilidad"),
            ("Estiramiento de pantorrilla en step", "Piernas", "estiramiento", "step", "principiante", "todos", "flexibilidad"),
        ]
        nuevos = 0
        for gimnasio in db.query(models.Gimnasio).filter(models.Gimnasio.activo == True).all():
            nombres_existentes = {t.nombre for t in db.query(models.TipoEjercicio).filter(models.TipoEjercicio.gimnasio_id == gimnasio.id).all()}
            for nombre, grupo, cat, equip, nivel, genero, obj in _EJERCICIOS:
                if nombre in nombres_existentes:
                    continue
                db.add(models.TipoEjercicio(
                    nombre=nombre, grupo_muscular=grupo, categoria=cat,
                    equipamiento=equip, nivel=nivel, genero_recomendado=genero, objetivo=obj,
                    gimnasio_id=gimnasio.id,
                ))
                nuevos += 1
        if nuevos:
            db.commit()
    finally:
        db.close()


def _normalizar_equipamiento_ejercicios():
    """Convierte etiquetas antiguas y genericas en equipos seleccionables."""
    db = SessionLocal()
    try:
        for ejercicio in db.query(models.TipoEjercicio).all():
            nombre = (ejercicio.nombre or "").lower()
            equipo = ejercicio.equipamiento or "sin_equipo"
            if equipo == "barra":
                equipo = "barra_dominadas" if "dominada" in nombre else "barra_discos"
            elif equipo == "banda": equipo = "bandas_elasticas"
            elif equipo == "pelota": equipo = "balon_medicinal" if "wall ball" in nombre else "fitball"
            elif equipo == "cuerda": equipo = "cuerda_batida" if "battle" in nombre else "cuerda_saltar"
            elif equipo == "mancuernas" and "kettlebell" in nombre: equipo = "kettlebell"
            elif equipo == "maquina":
                if "jalon" in nombre or "polea" in nombre: equipo = "poleas"
                elif "press" in nombre and "pecho" in nombre: equipo = "press_pecho_maquina"
                elif "remo" in nombre: equipo = "remo_maquina"
                elif "prensa" in nombre: equipo = "prensa_piernas"
                elif "extension de cuadriceps" in nombre: equipo = "extension_cuadriceps"
                elif "curl de femoral" in nombre: equipo = "curl_femoral"
                elif "hip thrust" in nombre: equipo = "hip_thrust_maquina"
                elif "abduccion" in nombre or "aduccion" in nombre: equipo = "abductores_aductores"
                elif "pantorrilla" in nombre or "talones" in nombre: equipo = "pantorrilla_maquina"
                else: equipo = "multiestacion"
            ejercicio.equipamiento = equipo
        db.commit()
    finally:
        db.close()


def _sembrar_paquetes_rutina_iniciales():
    """Crea paquetes editables por objetivo, genero y nivel para cada gimnasio."""
    plantillas = {
        "adaptacion_a": [
            ("Step basico subir y bajar", "12"), ("Sentadilla copa con mancuerna", "12"),
            ("Remo en maquina", "12"), ("Press en maquina de pecho", "12"), ("Plancha frontal", "25 s"),
        ],
        "adaptacion_b": [
            ("Trote en el sitio", "45 s"), ("Prensa de piernas (maquina)", "12"),
            ("Jalon al pecho (maquina)", "12"), ("Elevaciones laterales", "12"), ("Crunch abdominal", "15"),
        ],
        "movilidad": [
            ("Estiramiento de cuadriceps de pie", "30 s"), ("Estiramiento de isquiotibiales", "30 s"),
            ("Estiramiento de pecho en pared", "30 s"), ("Estiramiento de espalda (gato-vaca)", "10"),
            ("Estiramiento de hombros", "30 s"),
        ],
        "quema_full": [
            ("Saltos de tijera", "40 s"), ("Sentadilla copa con mancuerna", "15"),
            ("Remo con mancuerna", "12"), ("Rodillazos altos", "40 s"), ("Bicicleta abdominal", "20"),
        ],
        "quema_piernas": [
            ("Step con rodillazo", "16"), ("Zancadas con mancuernas", "12 por lado"),
            ("Patinadores laterales", "40 s"), ("Sentadilla con salto", "12"), ("Plancha lateral", "30 s por lado"),
        ],
        "hiit": [
            ("Burpees", "12"), ("Mountain climbers", "40 s"), ("Kettlebell swing", "15"),
            ("Battle ropes", "30 s"), ("Rodillazos altos", "45 s"),
        ],
        "empuje": [
            ("Press de banca con barra", "8-10"), ("Press inclinado con mancuernas", "10"),
            ("Press militar con mancuernas", "10"), ("Elevaciones laterales", "12"),
            ("Extension de triceps con mancuerna", "12"),
        ],
        "jale": [
            ("Remo con barra", "8-10"), ("Jalon al pecho (maquina)", "10-12"),
            ("Remo con mancuerna", "10 por lado"), ("Curl con barra", "10"),
            ("Curl de biceps con mancuernas", "12"),
        ],
        "piernas_masa": [
            ("Sentadilla con barra", "8-10"), ("Prensa de piernas (maquina)", "10-12"),
            ("Peso muerto rumano con barra", "10"), ("Curl de femoral (maquina)", "12"),
            ("Elevacion de talones (pantorrilla)", "15"),
        ],
        "gluteos_base": [
            ("Sentadilla copa con mancuerna", "12"), ("Hip thrust en maquina", "12"),
            ("Peso muerto rumano con mancuernas", "12"), ("Abduccion de cadera (maquina)", "15"),
            ("Caminata lateral con banda", "16 pasos"),
        ],
        "gluteos_avanzado": [
            ("Hip thrust con barra", "8-10"), ("Sentadilla bulgara", "10 por lado"),
            ("Peso muerto rumano con barra", "10"), ("Patada de gluteo en polea", "12 por lado"),
            ("Abduccion de cadera (maquina)", "15"),
        ],
        "superior_tono": [
            ("Press inclinado con mancuernas", "12"), ("Remo con mancuerna", "12"),
            ("Elevaciones laterales", "15"), ("Curl de biceps con mancuernas", "12"),
            ("Extension de triceps con mancuerna", "12"),
        ],
        "core": [
            ("Plancha frontal", "40 s"), ("Plancha lateral", "30 s por lado"),
            ("Russian twist", "20"), ("Elevacion de piernas", "12"), ("Bicicleta abdominal", "20"),
        ],
        "funcional": [
            ("Kettlebell swing", "15"), ("Thruster con mancuernas", "12"),
            ("Wall ball con pelota", "15"), ("Step up con mancuerna", "12 por lado"),
            ("Mountain climbers", "40 s"),
        ],
        "potencia": [
            ("Clean and press con mancuerna", "8 por lado"), ("Box jump (step alto)", "10"),
            ("Thruster con mancuernas", "10"), ("Battle ropes", "30 s"), ("Burpees", "12"),
        ],
    }

    # nombre, nivel, objetivo, etapa, genero, semanas, descripcion, dias
    recetas = [
        ("Inicio · Adaptacion general", "basico", "inicio", "adaptacion", "todos", 4,
         "Para personas sin experiencia. Tres dias, tecnica controlada y descanso de 60 a 90 segundos.",
         [("Dia 1 · Cuerpo completo", "adaptacion_a"), ("Dia 2 · Fuerza inicial", "adaptacion_b"), ("Dia 3 · Movilidad", "movilidad")]),
        ("Bajar peso · Principiante mixto", "basico", "bajar_peso", "inicio", "todos", 6,
         "Circuito inicial de bajo impacto. Mantener un ritmo conversacional y priorizar la tecnica.",
         [("Dia 1 · Circuito", "quema_full"), ("Dia 2 · Fuerza base", "adaptacion_b"), ("Dia 3 · Circuito y core", "quema_piernas")]),
        ("Bajar peso · Intermedio femenino", "intermedio", "bajar_peso", "desarrollo", "femenino", 6,
         "Combina fuerza de tren inferior, circuito metabolico y core. Descanso de 45 a 60 segundos.",
         [("Dia 1 · Gluteos", "gluteos_base"), ("Dia 2 · Metabolico", "quema_full"), ("Dia 3 · Superior", "superior_tono"), ("Dia 4 · HIIT", "hiit")]),
        ("Bajar peso · Avanzado masculino", "avanzado", "bajar_peso", "desarrollo", "masculino", 8,
         "Cinco dias con fuerza y acondicionamiento. Requiere dominio tecnico y recuperacion adecuada.",
         [("Dia 1 · Empuje", "empuje"), ("Dia 2 · HIIT", "hiit"), ("Dia 3 · Piernas", "piernas_masa"), ("Dia 4 · Jale", "jale"), ("Dia 5 · Funcional", "funcional")]),
        ("Ganar masa · Principiante masculino", "basico", "ganar_masa", "adaptacion", "masculino", 6,
         "Tres dias de cuerpo completo para aprender patrones y progresar cargas sin llegar al fallo.",
         [("Dia 1 · Base", "adaptacion_a"), ("Dia 2 · Tren superior", "superior_tono"), ("Dia 3 · Piernas", "piernas_masa")]),
        ("Ganar masa · Intermedio masculino", "intermedio", "ganar_masa", "desarrollo", "masculino", 8,
         "Division de cuatro dias con sobrecarga progresiva. Descansos de 90 a 120 segundos en compuestos.",
         [("Dia 1 · Empuje", "empuje"), ("Dia 2 · Jale", "jale"), ("Dia 3 · Piernas", "piernas_masa"), ("Dia 4 · Superior", "superior_tono")]),
        ("Ganar masa · Avanzado masculino", "avanzado", "ganar_masa", "desarrollo", "masculino", 10,
         "Cinco dias de hipertrofia para alumnos experimentados, con control de carga y recuperacion.",
         [("Dia 1 · Pecho y hombro", "empuje"), ("Dia 2 · Espalda", "jale"), ("Dia 3 · Piernas", "piernas_masa"), ("Dia 4 · Superior", "superior_tono"), ("Dia 5 · Piernas 2", "piernas_masa")]),
        ("Ganar masa · Principiante femenino", "basico", "ganar_masa", "adaptacion", "femenino", 6,
         "Base de tres dias con enfasis en gluteos y piernas, sin descuidar tren superior y core.",
         [("Dia 1 · Gluteos", "gluteos_base"), ("Dia 2 · Superior", "superior_tono"), ("Dia 3 · Piernas y core", "adaptacion_b")]),
        ("Ganar masa · Intermedio femenino", "intermedio", "ganar_masa", "desarrollo", "femenino", 8,
         "Cuatro dias con dos estimulos de tren inferior y progresion de cargas.",
         [("Dia 1 · Gluteos", "gluteos_avanzado"), ("Dia 2 · Superior", "superior_tono"), ("Dia 3 · Piernas", "piernas_masa"), ("Dia 4 · Gluteos y core", "gluteos_base")]),
        ("Ganar masa · Avanzado femenino", "avanzado", "ganar_masa", "desarrollo", "femenino", 10,
         "Cinco dias para alumnas avanzadas, con tres estimulos inferiores y dos superiores/funcionales.",
         [("Dia 1 · Gluteos fuerza", "gluteos_avanzado"), ("Dia 2 · Superior", "superior_tono"), ("Dia 3 · Piernas", "piernas_masa"), ("Dia 4 · Funcional", "funcional"), ("Dia 5 · Gluteos volumen", "gluteos_base")]),
        ("Tonificacion · Principiante femenino", "basico", "tonificacion", "inicio", "femenino", 6,
         "Tres dias equilibrados con cargas moderadas, repeticiones controladas y trabajo de postura.",
         [("Dia 1 · Inferior", "gluteos_base"), ("Dia 2 · Superior", "superior_tono"), ("Dia 3 · Cuerpo completo", "quema_full")]),
        ("Tonificacion · Intermedio mixto", "intermedio", "tonificacion", "desarrollo", "todos", 8,
         "Cuatro dias que combinan fuerza, core y acondicionamiento para mejorar composicion corporal.",
         [("Dia 1 · Superior", "superior_tono"), ("Dia 2 · Piernas", "gluteos_base"), ("Dia 3 · Funcional", "funcional"), ("Dia 4 · Core y cardio", "quema_piernas")]),
        ("Tonificacion · Avanzado femenino", "avanzado", "tonificacion", "definicion", "femenino", 8,
         "Cinco dias con enfasis inferior, circuitos y densidad de trabajo para alumnas experimentadas.",
         [("Dia 1 · Gluteos", "gluteos_avanzado"), ("Dia 2 · Superior", "superior_tono"), ("Dia 3 · HIIT", "hiit"), ("Dia 4 · Piernas", "piernas_masa"), ("Dia 5 · Funcional", "funcional")]),
        ("Definicion · Intermedio masculino", "intermedio", "definicion", "definicion", "masculino", 8,
         "Mantiene fuerza y masa muscular mientras aumenta el gasto mediante dos sesiones metabolicas.",
         [("Dia 1 · Empuje", "empuje"), ("Dia 2 · Piernas", "piernas_masa"), ("Dia 3 · Jale", "jale"), ("Dia 4 · HIIT", "hiit")]),
        ("Definicion · Intermedio femenino", "intermedio", "definicion", "definicion", "femenino", 8,
         "Fuerza de cuerpo completo con enfasis en gluteos, core y acondicionamiento.",
         [("Dia 1 · Gluteos", "gluteos_avanzado"), ("Dia 2 · Superior", "superior_tono"), ("Dia 3 · Funcional", "funcional"), ("Dia 4 · Core y cardio", "quema_piernas")]),
        ("Definicion · Avanzado mixto", "avanzado", "definicion", "definicion", "todos", 10,
         "Cinco dias de alta densidad. Supervisar recuperacion y conservar cargas en ejercicios principales.",
         [("Dia 1 · Empuje", "empuje"), ("Dia 2 · Piernas", "piernas_masa"), ("Dia 3 · Jale", "jale"), ("Dia 4 · HIIT", "hiit"), ("Dia 5 · Funcional", "funcional")]),
        ("Rendimiento · Intermedio mixto", "intermedio", "rendimiento", "desarrollo", "todos", 8,
         "Mejora fuerza general, potencia y capacidad de trabajo con cuatro sesiones semanales.",
         [("Dia 1 · Fuerza superior", "empuje"), ("Dia 2 · Fuerza inferior", "piernas_masa"), ("Dia 3 · Funcional", "funcional"), ("Dia 4 · Acondicionamiento", "hiit")]),
        ("Rendimiento · Avanzado mixto", "avanzado", "rendimiento", "competencia", "todos", 10,
         "Cinco dias para atletas avanzados. Exige tecnica consolidada y control de fatiga.",
         [("Dia 1 · Potencia", "potencia"), ("Dia 2 · Fuerza superior", "empuje"), ("Dia 3 · Fuerza inferior", "piernas_masa"), ("Dia 4 · Jale", "jale"), ("Dia 5 · Acondicionamiento", "hiit")]),
    ]

    series_por_nivel = {"basico": 3, "intermedio": 4, "avanzado": 4, "competencia": 5}
    db = SessionLocal()
    try:
        gimnasios = db.query(models.Gimnasio).filter(models.Gimnasio.activo == True).all()
        for gimnasio in gimnasios:
            catalogo = {
                ejercicio.nombre: ejercicio
                for ejercicio in db.query(models.TipoEjercicio).filter(
                    models.TipoEjercicio.gimnasio_id == gimnasio.id,
                    models.TipoEjercicio.activo == True,
                ).all()
            }
            existentes = {
                nombre for (nombre,) in db.query(models.PaqueteRutina.nombre).filter(
                    models.PaqueteRutina.gimnasio_id == gimnasio.id
                ).all()
            }
            for nombre, nivel, objetivo, etapa, genero, semanas, descripcion, dias_receta in recetas:
                if nombre in existentes:
                    continue
                nombres_requeridos = {
                    nombre_ejercicio
                    for _, clave in dias_receta
                    for nombre_ejercicio, _ in plantillas[clave]
                }
                if not nombres_requeridos.issubset(catalogo):
                    continue
                dias = []
                for orden, (nombre_dia, clave) in enumerate(dias_receta, start=1):
                    ejercicios = [models.PaqueteRutinaEjercicio(
                        tipo_ejercicio_id=catalogo[nombre_ejercicio].id,
                        nombre=nombre_ejercicio,
                        series=series_por_nivel[nivel],
                        repeticiones=repeticiones,
                        notas="Carga que permita completar la tecnica sin dolor.",
                    ) for nombre_ejercicio, repeticiones in plantillas[clave]]
                    dias.append(models.PaqueteRutinaDia(nombre=nombre_dia, orden=orden, ejercicios=ejercicios))
                db.add(models.PaqueteRutina(
                    gimnasio_id=gimnasio.id,
                    nombre=nombre,
                    descripcion=descripcion,
                    nivel=nivel,
                    objetivo=objetivo,
                    etapa=etapa,
                    genero_recomendado=genero,
                    duracion_semanas=semanas,
                    dias=dias,
                ))
                existentes.add(nombre)
        db.commit()
    finally:
        db.close()


def _sembrar_alimentos_iniciales():
    """La primera vez (tabla alimentos vacia), precarga un catalogo base de alimentos peruanos comunes con su valor nutricional aproximado por 100g, editable despues desde Nutricion."""
    db = SessionLocal()
    try:
        if db.query(models.Alimento).first():
            return
        # (nombre, categoria, calorias, proteinas_g, carbohidratos_g, grasas_g, fibra_g) por 100g
        iniciales = [
            ("Pechuga de pollo a la plancha", models.CategoriaAlimento.PROTEINA, 165, 31.0, 0.0, 3.6, 0.0),
            ("Filete de pescado (bonito)", models.CategoriaAlimento.PROTEINA, 140, 26.0, 0.0, 4.0, 0.0),
            ("Huevo", models.CategoriaAlimento.PROTEINA, 155, 13.0, 1.1, 11.0, 0.0),
            ("Lomo de res", models.CategoriaAlimento.PROTEINA, 250, 26.0, 0.0, 17.0, 0.0),
            ("Atun en agua", models.CategoriaAlimento.PROTEINA, 116, 26.0, 0.0, 1.0, 0.0),
            ("Queso fresco", models.CategoriaAlimento.LACTEO, 264, 18.0, 3.4, 21.0, 0.0),
            ("Leche descremada", models.CategoriaAlimento.LACTEO, 35, 3.4, 5.0, 0.1, 0.0),
            ("Yogurt natural", models.CategoriaAlimento.LACTEO, 61, 3.5, 4.7, 3.3, 0.0),
            ("Arroz blanco cocido", models.CategoriaAlimento.CARBOHIDRATO, 130, 2.7, 28.0, 0.3, 0.4),
            ("Papa sancochada", models.CategoriaAlimento.CARBOHIDRATO, 87, 1.9, 20.0, 0.1, 1.8),
            ("Camote", models.CategoriaAlimento.CARBOHIDRATO, 86, 1.6, 20.0, 0.1, 3.0),
            ("Quinua cocida", models.CategoriaAlimento.CARBOHIDRATO, 120, 4.4, 21.3, 1.9, 2.8),
            ("Avena cocida", models.CategoriaAlimento.CARBOHIDRATO, 68, 2.4, 12.0, 1.4, 1.7),
            ("Pan integral", models.CategoriaAlimento.CARBOHIDRATO, 247, 13.0, 41.0, 4.2, 7.0),
            ("Choclo (maiz)", models.CategoriaAlimento.CARBOHIDRATO, 96, 3.4, 21.0, 1.5, 2.4),
            ("Yuca sancochada", models.CategoriaAlimento.CARBOHIDRATO, 160, 1.4, 38.0, 0.3, 1.8),
            ("Lentejas cocidas", models.CategoriaAlimento.LEGUMBRE, 116, 9.0, 20.0, 0.4, 7.9),
            ("Frijol canario cocido", models.CategoriaAlimento.LEGUMBRE, 127, 8.7, 22.8, 0.5, 6.4),
            ("Garbanzo cocido", models.CategoriaAlimento.LEGUMBRE, 164, 8.9, 27.4, 2.6, 7.6),
            ("Palta (aguacate)", models.CategoriaAlimento.GRASA, 160, 2.0, 8.5, 14.7, 6.7),
            ("Aceite de oliva", models.CategoriaAlimento.GRASA, 884, 0.0, 0.0, 100.0, 0.0),
            ("Mani", models.CategoriaAlimento.GRASA, 567, 25.8, 16.1, 49.2, 8.5),
            ("Platano de seda", models.CategoriaAlimento.FRUTA, 89, 1.1, 23.0, 0.3, 2.6),
            ("Manzana", models.CategoriaAlimento.FRUTA, 52, 0.3, 14.0, 0.2, 2.4),
            ("Papaya", models.CategoriaAlimento.FRUTA, 43, 0.5, 11.0, 0.3, 1.7),
            ("Naranja", models.CategoriaAlimento.FRUTA, 47, 0.9, 12.0, 0.1, 2.4),
            ("Ensalada de vegetales frescos", models.CategoriaAlimento.VEGETAL, 20, 1.2, 4.0, 0.2, 1.8),
            ("Brocoli cocido", models.CategoriaAlimento.VEGETAL, 35, 2.4, 7.0, 0.4, 3.3),
            ("Espinaca cocida", models.CategoriaAlimento.VEGETAL, 23, 2.9, 3.6, 0.4, 2.2),
            ("Zanahoria", models.CategoriaAlimento.VEGETAL, 41, 0.9, 10.0, 0.2, 2.8),
        ]
        for nombre, categoria, cal, prot, carb, gras, fibra in iniciales:
            db.add(models.Alimento(
                nombre=nombre, categoria=categoria, porcion_gramos=100.0,
                calorias=cal, proteinas_g=prot, carbohidratos_g=carb, grasas_g=gras, fibra_g=fibra,
            ))
        db.commit()
    finally:
        db.close()


def _sembrar_paquetes_nutricion_iniciales():
    """
    La primera vez (tabla paquetes_nutricion vacia), precarga un
    catalogo amplio de paquetes de desayuno/almuerzo/cena para cada
    proposito (bajar de peso, ganar masa, mantenimiento, definicion),
    cada uno en 3 tamanos de porcion (reducida/estandar/amplia).

    No se duplican paquetes por genero/edad de forma explicita: el
    algoritmo de /nutricion/generar-automatico calcula el gasto
    calorico real del cliente (que ya varia solo por sexo, edad,
    peso y estatura via la formula de Mifflin-St Jeor) y elige, de
    estas 3 porciones, la que mas se acerque a lo que ese cliente
    necesita - cubriendo asi todo el espectro de hombres y mujeres
    de distintas edades y contexturas con un catalogo manejable.
    """
    db = SessionLocal()
    try:
        if db.query(models.PaqueteNutricion).first():
            return

        alimentos = {a.nombre: a for a in db.query(models.Alimento).all()}

        def _crear_paquete(nombre, tipo_comida, proposito, notas, receta_base, factor):
            items = []
            for nombre_alimento, gramos in receta_base:
                alimento = alimentos.get(nombre_alimento)
                if not alimento:
                    continue
                items.append(models.PaqueteAlimento(alimento_id=alimento.id, cantidad_gramos=round(gramos * factor, 1)))
            if not items:
                return
            db.add(models.PaqueteNutricion(nombre=nombre, tipo_comida=tipo_comida, proposito=proposito, notas=notas, items=items))

        PROP = models.PropositoNutricion
        TC = models.TipoComida

        # (tipo_comida, proposito, etiqueta, notas, receta base en gramos @ porcion "estandar")
        RECETAS = [
            (TC.DESAYUNO, PROP.BAJAR_PESO, "Desayuno ligero proteico",
             "Bajo en carbohidratos, alto en proteina y fibra para saciar con pocas calorias.",
             [("Huevo", 100), ("Espinaca cocida", 80), ("Papaya", 150)]),
            (TC.DESAYUNO, PROP.GANAR_MASA, "Desayuno energetico",
             "Alto en carbohidratos y calorias para sumar al superavit calorico del dia.",
             [("Avena cocida", 250), ("Platano de seda", 120), ("Mani", 30), ("Leche descremada", 200)]),
            (TC.DESAYUNO, PROP.MANTENIMIENTO, "Desayuno balanceado",
             "Combinacion equilibrada de carbohidratos, proteina y grasas saludables.",
             [("Pan integral", 60), ("Palta (aguacate)", 50), ("Huevo", 50), ("Naranja", 130)]),
            (TC.DESAYUNO, PROP.DEFINICION, "Desayuno alto en proteina",
             "Proteina alta y carbohidratos moderados para conservar masa muscular en deficit leve.",
             [("Huevo", 150), ("Avena cocida", 120), ("Manzana", 130), ("Yogurt natural", 100)]),

            (TC.COMIDA, PROP.BAJAR_PESO, "Almuerzo ligero",
             "Proteina magra con vegetales y una porcion controlada de carbohidrato.",
             [("Pechuga de pollo a la plancha", 150), ("Ensalada de vegetales frescos", 200), ("Camote", 100)]),
            (TC.COMIDA, PROP.GANAR_MASA, "Almuerzo completo",
             "Alto aporte calorico con proteina, carbohidratos y grasas para ganar masa.",
             [("Lomo de res", 180), ("Arroz blanco cocido", 250), ("Frijol canario cocido", 150), ("Palta (aguacate)", 50)]),
            (TC.COMIDA, PROP.MANTENIMIENTO, "Almuerzo balanceado",
             "Pescado, quinua y vegetales en porciones equilibradas.",
             [("Filete de pescado (bonito)", 150), ("Quinua cocida", 150), ("Brocoli cocido", 150)]),
            (TC.COMIDA, PROP.DEFINICION, "Almuerzo alto en proteina",
             "Proteina alta, carbohidrato moderado y vegetales para definicion muscular.",
             [("Pechuga de pollo a la plancha", 180), ("Choclo (maiz)", 100), ("Ensalada de vegetales frescos", 200)]),

            (TC.CENA, PROP.BAJAR_PESO, "Cena ligera",
             "Cena baja en calorias, alta en proteina y vegetales.",
             [("Filete de pescado (bonito)", 130), ("Espinaca cocida", 150), ("Zanahoria", 100)]),
            (TC.CENA, PROP.GANAR_MASA, "Cena reforzada",
             "Cena con buen aporte calorico para sostener el superavit diario.",
             [("Atun en agua", 150), ("Camote", 200), ("Palta (aguacate)", 60), ("Ensalada de vegetales frescos", 100)]),
            (TC.CENA, PROP.MANTENIMIENTO, "Cena balanceada",
             "Combinacion moderada de proteina, carbohidrato y vegetales.",
             [("Huevo", 100), ("Yuca sancochada", 120), ("Brocoli cocido", 120)]),
            (TC.CENA, PROP.DEFINICION, "Cena alta en proteina",
             "Proteina alta y carbohidrato bajo, ideal para la noche en definicion.",
             [("Atun en agua", 150), ("Espinaca cocida", 150), ("Garbanzo cocido", 100)]),
        ]

        NIVELES = [("porcion reducida", 0.75), ("porcion estandar", 1.0), ("porcion amplia", 1.35), ("porcion extra amplia", 1.85)]

        for tipo_comida, proposito, etiqueta, notas, receta in RECETAS:
            for sufijo, factor in NIVELES:
                _crear_paquete(f"{etiqueta} ({sufijo})", tipo_comida, proposito, notas, receta, factor)

        db.commit()
    finally:
        db.close()


def _sembrar_paquetes_nutricion_variantes():
    """
    Segunda tanda de recetas (una mas por cada combinacion tipo de
    comida x proposito), usando ingredientes distintos a los de la
    primera tanda para dar mas variedad real (pescados variados,
    mas verduras, mas fuentes de carbohidrato) y evitar que el
    cliente coma siempre lo mismo. Idempotente por nombre de paquete
    (revisa si ya existe antes de crear), para poder correr sin
    duplicar aunque el catalogo de paquetes ya tenga datos.
    """
    db = SessionLocal()
    try:
        alimentos = {a.nombre: a for a in db.query(models.Alimento).all()}
        existentes = {p.nombre for p in db.query(models.PaqueteNutricion).all()}

        def _crear_si_no_existe(nombre, tipo_comida, proposito, notas, receta_base, factor):
            if nombre in existentes:
                return
            items = []
            for nombre_alimento, gramos in receta_base:
                alimento = alimentos.get(nombre_alimento)
                if not alimento:
                    continue
                items.append(models.PaqueteAlimento(alimento_id=alimento.id, cantidad_gramos=round(gramos * factor, 1)))
            if not items:
                return
            db.add(models.PaqueteNutricion(nombre=nombre, tipo_comida=tipo_comida, proposito=proposito, notas=notas, items=items))
            existentes.add(nombre)

        PROP = models.PropositoNutricion
        TC = models.TipoComida

        RECETAS_V2 = [
            (TC.DESAYUNO, PROP.BAJAR_PESO, "Desayuno frutal proteico",
             "Yogur griego (mas proteina, menos calorias que el yogurt normal) con fruta y semillas de chia.",
             [("Yogur griego sin azucar", 150), ("Fresa", 100), ("Semillas de chia", 15)]),
            (TC.DESAYUNO, PROP.GANAR_MASA, "Desayuno fuerza",
             "Avena con frutos secos y leche entera para un desayuno alto en calorias.",
             [("Avena cocida", 200), ("Almendras", 30), ("Leche entera", 200)]),
            (TC.DESAYUNO, PROP.MANTENIMIENTO, "Desayuno tradicional",
             "Huevo con camote y naranja, combinacion sencilla y balanceada.",
             [("Huevo", 100), ("Camote", 150), ("Naranja", 130)]),
            (TC.DESAYUNO, PROP.DEFINICION, "Desayuno proteico ligero",
             "Yogur griego con avena y linaza: alta proteina, grasas saludables, carbohidrato controlado.",
             [("Yogur griego sin azucar", 200), ("Avena cocida", 80), ("Linaza", 15)]),

            (TC.COMIDA, PROP.BAJAR_PESO, "Almuerzo de pescado",
             "Merluza (pescado muy magro) con esparragos y zapallito italiano.",
             [("Merluza", 150), ("Esparragos", 150), ("Zapallito italiano", 100)]),
            (TC.COMIDA, PROP.GANAR_MASA, "Almuerzo andino",
             "Caballa, quinua y habas: buena densidad calorica con proteina y carbohidrato de calidad.",
             [("Caballa", 180), ("Quinua cocida", 200), ("Habas cocidas", 150), ("Palta (aguacate)", 50)]),
            (TC.COMIDA, PROP.MANTENIMIENTO, "Almuerzo mixto",
             "Jurel con arroz integral y esparragos, opcion balanceada con otro tipo de pescado.",
             [("Jurel", 150), ("Arroz integral cocido", 150), ("Esparragos", 150)]),
            (TC.COMIDA, PROP.DEFINICION, "Almuerzo magro",
             "Merluza con menestra de lentejas y ensalada, proteina alta y grasa baja.",
             [("Merluza", 180), ("Lentejas cocidas", 120), ("Ensalada de vegetales frescos", 200)]),

            (TC.CENA, PROP.BAJAR_PESO, "Cena de mar",
             "Caballa con lechuga y tomate, cena ligera con otro tipo de pescado azul.",
             [("Caballa", 130), ("Lechuga", 100), ("Tomate", 100)]),
            (TC.CENA, PROP.GANAR_MASA, "Cena energetica",
             "Pejerrey con papa sancochada y palta para sumar calorias en la noche.",
             [("Pejerrey", 180), ("Papa sancochada", 200), ("Palta (aguacate)", 60)]),
            (TC.CENA, PROP.MANTENIMIENTO, "Cena sencilla",
             "Pavo con coliflor y zanahoria, opcion liviana y balanceada.",
             [("Pavo (pechuga sin piel)", 150), ("Coliflor cocida", 150), ("Zanahoria", 100)]),
            (TC.CENA, PROP.DEFINICION, "Cena proteica vegetal",
             "Merluza con brocoli y esparragos: proteina alta, carbohidrato minimo.",
             [("Merluza", 150), ("Brocoli cocido", 150), ("Esparragos", 100)]),
        ]

        NIVELES = [("porcion reducida", 0.75), ("porcion estandar", 1.0), ("porcion amplia", 1.35), ("porcion extra amplia", 1.85)]

        for tipo_comida, proposito, etiqueta, notas, receta in RECETAS_V2:
            for sufijo, factor in NIVELES:
                _crear_si_no_existe(f"{etiqueta} ({sufijo})", tipo_comida, proposito, notas, receta, factor)

        db.commit()
    finally:
        db.close()


def _sembrar_servicios_iniciales():
    """La primera vez (tabla servicios vacia), precarga los conceptos de servicios/deudas mas comunes de un gimnasio, editable despues desde Pagos > Servicios."""
    db = SessionLocal()
    try:
        if db.query(models.Servicio).first():
            return
        for nombre in ["Personal de Limpieza", "Internet", "Agua", "Luz", "Mantenimiento", "Alquiler", "Deudas"]:
            db.add(models.Servicio(nombre=nombre, activo=True))
        db.commit()
    finally:
        db.close()


def _sembrar_porciones_caseras():
    """Actualiza porciones caseras de los alimentos existentes (solo los que no la tienen todavia)."""
    _PORCIONES = {
        # Proteinas
        "Pollo (pechuga)": "1 filete mediano", "Pollo pechuga a la plancha": "1 filete mediano",
        "Pollo muslo": "1 muslo", "Res (bistec)": "1 bistec mediano", "Lomo de res": "1 filete",
        "Pescado (tilapia)": "1 filete", "Pescado tilapia al vapor": "1 filete",
        "Bonito": "1 filete", "Jurel": "1 filete", "Trucha": "1 trucha entera",
        "Atun en lata": "1 lata escurrida", "Huevo cocido": "1.5 unidades",
        "Huevo": "2 unidades", "Huevos revueltos (2)": "2 unidades",
        "Tofu": "1 bloque chico",
        # Lacteos
        "Leche descremada": "1 vaso", "Leche entera": "1 vaso", "Leche": "1 vaso",
        "Yogur natural": "1 vasito", "Yogur griego": "1 vasito",
        "Queso fresco": "2 tajadas", "Queso fresco serrano": "2 tajadas",
        # Carbohidratos
        "Arroz cocido": "1/2 taza", "Arroz integral cocido": "1/2 taza",
        "Quinua cocida": "1/2 taza", "Avena cocida": "1/2 vaso", "Avena": "3 cucharadas",
        "Papa sancochada": "1 papa mediana", "Papa": "1 papa mediana",
        "Camote sancochado": "1 camote mediano", "Camote": "1 camote chico",
        "Yuca sancochada": "1 trozo mediano", "Pan integral": "2 rebanadas",
        "Pan ciabatta integral": "1 pan", "Pan frances": "1 pan",
        "Fideos cocidos": "1 taza", "Lentejas cocidas": "1/2 taza",
        "Frejoles cocidos": "1/2 taza", "Frijoles cocidos": "1/2 taza",
        "Garbanzos cocidos": "1/2 taza", "Pallares cocidos": "1/2 taza",
        "Choclo desgranado": "1/2 taza", "Choclo": "1 mazorca chica",
        "Mote cocido": "1/2 taza", "Trigo cocido": "1/2 taza",
        "Cebada cocida": "1/2 taza", "Kiwicha cocida": "1/2 taza",
        "Chuño cocido": "3 unidades",
        # Frutas
        "Platano (isla)": "1 unidad", "Platano de isla": "1 unidad",
        "Platano de seda": "1 unidad", "Manzana": "1 unidad mediana",
        "Naranja": "1 unidad", "Mandarina": "2 unidades",
        "Papaya": "1 tajada", "Pina": "1 rodaja", "Piña": "1 rodaja",
        "Mango": "1/2 mango", "Sandia": "1 tajada", "Melon": "1 tajada",
        "Uvas": "1 racimo chico", "Fresa": "8 fresas", "Pera": "1 unidad",
        "Durazno": "1 unidad", "Granadilla": "2 unidades",
        "Lucuma": "1/2 unidad", "Chirimoya": "1/2 unidad",
        "Maracuya (pulpa)": "2 unidades", "Tuna": "1 unidad",
        "Aguaymanto": "1 puñado",
        # Vegetales
        "Brocoli": "1 taza", "Espinaca": "2 tazas (cruda)",
        "Lechuga": "3 hojas grandes", "Tomate": "1 unidad",
        "Zanahoria": "1 unidad mediana", "Pepino": "1/2 pepino",
        "Palta (aguacate)": "1/4 palta", "Palta": "1/4 palta",
        "Zapallo": "1 tajada", "Vainitas": "1 taza",
        "Cebolla": "1/2 unidad", "Choclo desgranado": "1/2 taza",
        "Betarraga": "1 unidad chica", "Alcachofa": "1 unidad",
        # Grasas
        "Aceite de oliva": "1 cucharada", "Mani": "1 puñado (20 unid)",
        "Almendras": "10 unidades", "Nueces": "5 mitades",
        "Pecanas": "5 unidades", "Aceitunas": "6 unidades",
        "Linaza": "1 cucharada", "Chia": "1 cucharada",
        "Sacha inchi": "1 puñado", "Cancha serrana": "1/4 taza",
        # Otros
        "Miel de abeja": "1 cucharada", "Mermelada": "1 cucharada",
    }
    db = SessionLocal()
    try:
        sin_porcion = db.query(models.Alimento).filter(
            models.Alimento.porcion_casera.is_(None)
        ).all()
        actualizados = 0
        for alimento in sin_porcion:
            casera = _PORCIONES.get(alimento.nombre)
            if casera:
                alimento.porcion_casera = casera
                actualizados += 1
        if actualizados:
            db.commit()
    finally:
        db.close()


def _sembrar_alimentos_expansion_lima():
    """
    Amplia el catalogo base con mas alimentos comunes en Lima/Peru
    (mas proteinas, frutas, vegetales, lacteos, grasas y legumbres).
    A diferencia de _sembrar_alimentos_iniciales (que solo corre si
    la tabla esta completamente vacia), esta funcion revisa alimento
    por alimento por nombre para poder ampliar un catalogo que ya
    tiene datos, sin duplicar los que ya existan.
    """
    db = SessionLocal()
    try:
        existentes = {fila[0] for fila in db.query(models.Alimento.nombre).all()}
        CA = models.CategoriaAlimento
        # (nombre, categoria, calorias, proteinas_g, carbohidratos_g, grasas_g, fibra_g) por 100g
        nuevos = [
            ("Pavo (pechuga sin piel)", CA.PROTEINA, 135, 30.0, 0.0, 1.0, 0.0),
            ("Carne de cerdo (lomo)", CA.PROTEINA, 242, 27.0, 0.0, 14.0, 0.0),
            ("Higado de pollo", CA.PROTEINA, 119, 17.0, 0.9, 4.8, 0.0),
            ("Camarones", CA.PROTEINA, 99, 24.0, 0.2, 0.3, 0.0),
            ("Calamar", CA.PROTEINA, 92, 15.6, 3.1, 1.4, 0.0),
            ("Jurel", CA.PROTEINA, 158, 20.0, 0.0, 8.0, 0.0),
            ("Pejerrey", CA.PROTEINA, 105, 18.0, 0.0, 3.5, 0.0),
            ("Leche entera", CA.LACTEO, 61, 3.2, 4.8, 3.3, 0.0),
            ("Queso edam", CA.LACTEO, 357, 25.0, 1.4, 28.0, 0.0),
            ("Mantequilla", CA.GRASA, 717, 0.9, 0.1, 81.0, 0.0),
            ("Nueces", CA.GRASA, 654, 15.0, 14.0, 65.0, 6.7),
            ("Pan frances", CA.CARBOHIDRATO, 274, 9.0, 55.0, 1.4, 2.2),
            ("Tallarines cocidos", CA.CARBOHIDRATO, 158, 5.8, 31.0, 0.9, 1.8),
            ("Mote (maiz mote cocido)", CA.CARBOHIDRATO, 123, 3.2, 25.0, 1.2, 3.0),
            ("Kiwicha cocida", CA.CARBOHIDRATO, 122, 4.5, 21.0, 2.0, 3.0),
            ("Oca sancochada", CA.CARBOHIDRATO, 71, 1.0, 16.8, 0.1, 1.2),
            ("Pina", CA.FRUTA, 50, 0.5, 13.0, 0.1, 1.4),
            ("Mango", CA.FRUTA, 60, 0.8, 15.0, 0.4, 1.6),
            ("Fresa", CA.FRUTA, 32, 0.7, 7.7, 0.3, 2.0),
            ("Mandarina", CA.FRUTA, 53, 0.8, 13.3, 0.3, 1.8),
            ("Sandia", CA.FRUTA, 30, 0.6, 7.6, 0.2, 0.4),
            ("Uva", CA.FRUTA, 69, 0.7, 18.0, 0.2, 0.9),
            ("Aguaymanto", CA.FRUTA, 53, 1.9, 11.0, 0.7, 4.9),
            ("Chirimoya", CA.FRUTA, 75, 1.6, 17.7, 0.7, 3.0),
            ("Maracuya", CA.FRUTA, 68, 2.2, 15.0, 0.7, 3.0),
            ("Tomate", CA.VEGETAL, 18, 0.9, 3.9, 0.2, 1.2),
            ("Pepino", CA.VEGETAL, 15, 0.7, 3.6, 0.1, 0.5),
            ("Pimiento (aji)", CA.VEGETAL, 20, 0.9, 4.6, 0.2, 1.7),
            ("Cebolla", CA.VEGETAL, 40, 1.1, 9.3, 0.1, 1.7),
            ("Apio", CA.VEGETAL, 16, 0.7, 3.0, 0.2, 1.6),
            ("Rabanito", CA.VEGETAL, 16, 0.7, 3.4, 0.1, 1.6),
            ("Vainita (ejote)", CA.VEGETAL, 31, 1.8, 7.0, 0.1, 3.4),
            ("Coliflor cocida", CA.VEGETAL, 25, 1.9, 5.0, 0.3, 2.0),
            ("Habas cocidas", CA.LEGUMBRE, 110, 7.9, 19.7, 0.7, 5.4),
            ("Pallares cocidos", CA.LEGUMBRE, 113, 7.4, 20.0, 0.5, 6.5),
            ("Arveja verde cocida", CA.LEGUMBRE, 84, 5.4, 14.5, 0.4, 5.1),
            ("Cafe solo (sin azucar)", CA.OTRO, 2, 0.1, 0.0, 0.0, 0.0),
        ]
        agregados = 0
        for nombre, categoria, cal, prot, carb, gras, fibra in nuevos:
            if nombre in existentes:
                continue
            db.add(models.Alimento(
                nombre=nombre, categoria=categoria, porcion_gramos=100.0,
                calorias=cal, proteinas_g=prot, carbohidratos_g=carb, grasas_g=gras, fibra_g=fibra,
            ))
            agregados += 1
        if agregados:
            db.commit()
    finally:
        db.close()


def _sembrar_alimentos_expansion_lima_2():
    """
    Segunda tanda de expansion del catalogo, a partir de la lista de
    alimentos peruanos comunes para dietas saludables que paso el
    gimnasio (proteinas magras, verduras, frutas, carbohidratos,
    grasas saludables y bebidas/infusiones). Mismo patron idempotente
    que _sembrar_alimentos_expansion_lima: revisa por nombre exacto
    para no duplicar lo que ya existe en el catalogo.
    """
    db = SessionLocal()
    try:
        existentes = {fila[0] for fila in db.query(models.Alimento.nombre).all()}
        CA = models.CategoriaAlimento
        nuevos = [
            ("Caballa", CA.PROTEINA, 205, 19.0, 0.0, 13.9, 0.0),
            ("Merluza", CA.PROTEINA, 86, 17.2, 0.0, 1.3, 0.0),
            ("Queso fresco light (bajo en grasa)", CA.LACTEO, 150, 17.0, 3.0, 7.0, 0.0),
            ("Yogur griego sin azucar", CA.LACTEO, 59, 10.0, 3.6, 0.4, 0.0),
            ("Lechuga", CA.VEGETAL, 15, 1.4, 2.9, 0.2, 1.3),
            ("Zapallito italiano", CA.VEGETAL, 17, 1.2, 3.1, 0.3, 1.0),
            ("Esparragos", CA.VEGETAL, 20, 2.2, 3.9, 0.1, 2.1),
            ("Melon", CA.FRUTA, 34, 0.8, 8.6, 0.2, 0.9),
            ("Arroz integral cocido", CA.CARBOHIDRATO, 112, 2.6, 23.5, 0.9, 1.8),
            ("Almendras", CA.GRASA, 579, 21.0, 22.0, 50.0, 12.5),
            ("Semillas de chia", CA.GRASA, 486, 17.0, 42.0, 31.0, 34.0),
            ("Linaza", CA.GRASA, 534, 18.0, 29.0, 42.0, 27.0),
            ("Agua", CA.OTRO, 0, 0.0, 0.0, 0.0, 0.0),
            ("Te (infusion)", CA.OTRO, 1, 0.0, 0.3, 0.0, 0.0),
            ("Infusion de hierbas (anis, manzanilla, hierba luisa)", CA.OTRO, 1, 0.0, 0.3, 0.0, 0.0),
        ]
        agregados = 0
        for nombre, categoria, cal, prot, carb, gras, fibra in nuevos:
            if nombre in existentes:
                continue
            db.add(models.Alimento(
                nombre=nombre, categoria=categoria, porcion_gramos=100.0,
                calorias=cal, proteinas_g=prot, carbohidratos_g=carb, grasas_g=gras, fibra_g=fibra,
            ))
            agregados += 1
        if agregados:
            db.commit()
    finally:
        db.close()


def _sembrar_puestos_iniciales():
    """La primera vez (tabla puestos vacia), precarga los puestos/especialidades que antes estaban fijos en el frontend, para no perder las opciones existentes al migrar al catalogo editable."""
    db = SessionLocal()
    try:
        if db.query(models.Puesto).first():
            return
        iniciales = [
            ("Counter", models.TipoEmpleado.STAFF_FIJO), ("Counter suplente", models.TipoEmpleado.STAFF_FIJO),
            ("Entrenador", models.TipoEmpleado.STAFF_FIJO), ("Personal Trainer", models.TipoEmpleado.STAFF_FIJO),
            ("Baile", models.TipoEmpleado.PROFESOR_DE_SALA), ("Cardio", models.TipoEmpleado.PROFESOR_DE_SALA),
            ("Marinera", models.TipoEmpleado.PROFESOR_DE_SALA), ("Salsa", models.TipoEmpleado.PROFESOR_DE_SALA),
            ("Top Figther", models.TipoEmpleado.PROFESOR_DE_SALA), ("Circuitos", models.TipoEmpleado.PROFESOR_DE_SALA),
            ("Full Body", models.TipoEmpleado.PROFESOR_DE_SALA), ("Yoga", models.TipoEmpleado.PROFESOR_DE_SALA),
        ]
        for nombre, tipo in iniciales:
            db.add(models.Puesto(nombre=nombre, tipo=tipo, activo=True))
        db.commit()
    finally:
        db.close()


# ==================================================================
# AUTENTICACION (publico)
# ==================================================================

def _resolver_gimnasio_id_por_slug(db: Session, slug: Optional[str]) -> Optional[int]:
    """Convierte un slug a gimnasio_id; es obligatorio en portales multi-tenant."""
    if not slug:
        raise HTTPException(status_code=400, detail="Debes indicar el gimnasio")
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug, models.Gimnasio.activo == True).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail=f"Gimnasio '{slug}' no encontrado")
    return gimnasio.id


@app.get("/gym/{slug}", tags=["Auth"])
def info_publica_gimnasio(slug: str, db: Session = Depends(get_db)):
    """Info publica de un gimnasio (para personalizar login, PWA, etc). No requiere auth."""
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug, models.Gimnasio.activo == True).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail=f"Gimnasio '{slug}' no encontrado")
    return {
        "id": gimnasio.id,
        "nombre": gimnasio.nombre,
        "slug": gimnasio.slug,
        "logo_url": gimnasio.logo_url,
        "logo_oscuro_url": gimnasio.logo_oscuro_url,
        "logo_version": _version_contenido_imagen(gimnasio.logo_datos),
        "logo_oscuro_version": _version_contenido_imagen(gimnasio.logo_oscuro_datos),
        "tema": gimnasio.tema,
        "modo_tema": gimnasio.modo_tema,
    }


@app.post("/gym-actual/logo", tags=["Auth"])
async def subir_logo_gimnasio(
    logo: UploadFile = File(...),
    modo: str = Query("claro", pattern="^(claro|oscuro)$"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """Sube o reemplaza el logo del gimnasio. Solo admin."""
    gid = get_gid(usuario)
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gid).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    contenido, tipo = _validar_y_optimizar_foto(await logo.read(), logo.content_type, optimizar=True)
    if modo == "oscuro":
        gimnasio.logo_oscuro_datos, gimnasio.logo_oscuro_tipo = contenido, tipo
        gimnasio.logo_oscuro_url = f"/gym/{gimnasio.slug}/logo/oscuro"
        campo_logo = "logo_oscuro_url"
    else:
        gimnasio.logo_datos, gimnasio.logo_tipo = contenido, tipo
        gimnasio.logo_url = f"/gym/{gimnasio.slug}/logo/claro"
        campo_logo = "logo_url"
    db.commit()
    return {"logo_url": getattr(gimnasio, campo_logo), "modo": modo, "version": _version_contenido_imagen(contenido)}


@app.get("/gym/{slug}/logo/{modo}", tags=["PWA"])
def obtener_logo_gimnasio(slug: str, modo: str, db: Session = Depends(get_db)):
    if modo not in {"claro", "oscuro"}:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug, models.Gimnasio.activo == True).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    contenido = gimnasio.logo_oscuro_datos if modo == "oscuro" else gimnasio.logo_datos
    tipo = gimnasio.logo_oscuro_tipo if modo == "oscuro" else gimnasio.logo_tipo
    if not contenido:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    return Response(content=contenido, media_type=tipo or "image/webp", headers={"Cache-Control": "public, no-cache"})


@app.get("/gym-actual/", tags=["Auth"])
def info_gimnasio_actual(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.get_usuario_actual)):
    """Info del gimnasio del usuario autenticado. Para que el frontend obtenga el slug sin tenerlo en sessionStorage."""
    gid = get_gid(usuario)
    if not gid:
        raise HTTPException(status_code=404, detail="Sin gimnasio asignado")
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gid).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    return {
        "id": gimnasio.id,
        "nombre": gimnasio.nombre,
        "slug": gimnasio.slug,
        "logo_url": gimnasio.logo_url,
        "logo_oscuro_url": gimnasio.logo_oscuro_url,
        "logo_version": _version_contenido_imagen(gimnasio.logo_datos),
        "logo_oscuro_version": _version_contenido_imagen(gimnasio.logo_oscuro_datos),
        "tema": gimnasio.tema,
        "modo_tema": gimnasio.modo_tema,
    }


# --- Colores por tema (para PWA manifest y meta tags) ---
_COLORES_TEMA = {
    "lavanda": {"bg": "#667eea", "fg": "#ffffff"},
    "oceano": {"bg": "#0077b6", "fg": "#ffffff"},
    "bosque": {"bg": "#2d6a4f", "fg": "#ffffff"},
    "atardecer": {"bg": "#e85d04", "fg": "#ffffff"},
    "noche": {"bg": "#1a1a2e", "fg": "#e0e0e0"},
    "cereza": {"bg": "#d90429", "fg": "#ffffff"},
    "dorado": {"bg": "#c9a227", "fg": "#1a1a1a"},
}


@app.get("/gym/{slug}/manifest.json", tags=["PWA"])
def manifest_gimnasio(slug: str, portal: str = "alumno", db: Session = Depends(get_db)):
    """
    Genera un Web App Manifest dinamico para cada gimnasio.
    portal: 'alumno' | 'profesor' | 'staff' - determina start_url y scope.
    """
    from fastapi.responses import JSONResponse
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug, models.Gimnasio.activo == True).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")

    colores = _COLORES_TEMA.get(gimnasio.tema or "lavanda", _COLORES_TEMA["lavanda"])

    portales = {
        "alumno": {"start": f"/alumno/mi-perfil.html?gym={slug}", "scope": "/alumno/", "sufijo": ""},
        "profesor": {"start": f"/profesor/agenda.html?gym={slug}", "scope": "/profesor/", "sufijo": " - Profesores"},
        "staff": {"start": f"/principal.html", "scope": "/", "sufijo": " - Admin"},
    }
    p = portales.get(portal, portales["alumno"])

    icono_url = gimnasio.logo_url or f"/gym/{slug}/icon.svg"

    manifest = {
        "name": gimnasio.nombre + p["sufijo"],
        "short_name": gimnasio.nombre[:12],
        "description": f"App de {gimnasio.nombre}",
        "start_url": p["start"],
        "scope": p["scope"],
        "display": "standalone",
        "orientation": "portrait",
        "theme_color": colores["bg"],
        "background_color": colores["bg"],
        "icons": [
            {"src": icono_url, "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"},
            {"src": icono_url, "sizes": "192x192", "type": "image/svg+xml"},
            {"src": icono_url, "sizes": "512x512", "type": "image/svg+xml"},
        ],
    }
    return JSONResponse(content=manifest, media_type="application/manifest+json")


@app.get("/gym/{slug}/icon.svg", tags=["PWA"])
def icono_gimnasio(slug: str, db: Session = Depends(get_db)):
    """
    Genera un icono SVG con la inicial del gimnasio y el color
    de su tema. Se usa como fallback si el gym no tiene logo_url.
    """
    from fastapi.responses import Response
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug, models.Gimnasio.activo == True).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")

    colores = _COLORES_TEMA.get(gimnasio.tema or "lavanda", _COLORES_TEMA["lavanda"])
    inicial = (gimnasio.nombre or "G")[0].upper()

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="80" fill="{colores['bg']}"/>
  <text x="256" y="280" text-anchor="middle" dominant-baseline="central"
        font-family="Arial,sans-serif" font-weight="bold" font-size="280"
        fill="{colores['fg']}">{inicial}</text>
  <text x="256" y="420" text-anchor="middle" font-family="Arial,sans-serif"
        font-size="60" fill="{colores['fg']}" opacity="0.7">GYM</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/gym/{slug}/sw.js", tags=["PWA"])
def service_worker_gimnasio(slug: str):
    """
    Service Worker minimo: solo hace que la app sea 'instalable'
    como PWA. No cachea nada (la app necesita conexion para funcionar).
    """
    from fastapi.responses import Response
    sw = """// Service Worker - Soft-Gym PWA
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));
"""
    return Response(content=sw, media_type="application/javascript")


@app.get("/gym/{slug}/qr.svg", tags=["PWA"])
def qr_portal_alumno(slug: str, portal: str = "alumno", db: Session = Depends(get_db)):
    """
    Genera un codigo QR como SVG para compartir el portal del alumno
    (o profesor) de un gimnasio. El dueño puede imprimirlo, ponerlo
    en la recepcion, o compartirlo por WhatsApp.
    """
    from fastapi.responses import Response
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug, models.Gimnasio.activo == True).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")

    # Construir la URL que el QR codifica
    # En produccion RENDER_EXTERNAL_URL estara definido; en dev usamos localhost
    base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:3001")
    rutas = {"alumno": "alumno/login.html", "profesor": "profesor/login.html"}
    ruta = rutas.get(portal, rutas["alumno"])
    url_completa = f"{base}/{ruta}?gym={slug}"

    # Generar QR con la libreria qrcode (pure python, sin deps C)
    # Si no esta instalada, retornar un SVG con la URL en texto
    try:
        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr.add_data(url_completa)
        qr.make(fit=True)
        img = qr.make_image(image_factory=factory)
        buf = io.BytesIO()
        img.save(buf)
        svg_content = buf.getvalue().decode("utf-8")
    except ImportError:
        # Fallback: SVG simple con la URL como texto
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100">
  <rect width="300" height="100" fill="#f0f0f0" rx="10"/>
  <text x="150" y="40" text-anchor="middle" font-family="Arial" font-size="12">Escanea o visita:</text>
  <text x="150" y="70" text-anchor="middle" font-family="Arial" font-size="10" fill="#0077b6">{url_completa}</text>
</svg>"""

    return Response(content=svg_content, media_type="image/svg+xml")


@app.post("/auth/login", response_model=schemas.TokenResponse, tags=["Auth"])
def login_staff_profesor(datos: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Login de staff y profesores con username + password."""
    clave = auth.clave_rate_limit(request, "staff", datos.username)
    auth.exigir_intentos_disponibles(clave, db)
    usuario = auth.autenticar_usuario(db, datos.username, datos.password)
    if not usuario:
        auth.registrar_fallo_login(db, clave)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    auth.limpiar_fallos_login(db, clave)
    if os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true" and (not usuario.email or not usuario.email_verificado):
        raise HTTPException(status_code=403, detail="Debes verificar tu correo antes de ingresar")

    # Obtener slug del gimnasio para el frontend
    gym_slug = None
    if usuario.gimnasio_id:
        gym = db.query(models.Gimnasio).filter(models.Gimnasio.id == usuario.gimnasio_id).first()
        if gym:
            gym_slug = gym.slug

    sesion = _crear_sesion_usuario(db, usuario, request)
    _evento_auditoria(db, "INICIO_SESION", request, usuario)
    token = auth.crear_access_token({
        "sub": str(usuario.id),
        "tipo": "usuario",
        "rol": usuario.rol.value,
        "gimnasio_id": usuario.gimnasio_id,
        "sv": usuario.sesion_version or 1,
        "jti": sesion.jti,
    })
    return schemas.TokenResponse(
        access_token=token,
        rol=usuario.rol.value,
        nombre=usuario.nombre_completo,
        es_administrador=usuario.es_administrador,
        es_superadmin=getattr(usuario, 'es_superadmin', False),
        puede_eliminar=usuario.puede_eliminar,
        puede_exportar=usuario.puede_exportar,
        zonas_permitidas=usuario.zonas_permitidas,
        gimnasio_id=usuario.gimnasio_id,
        gimnasio_slug=gym_slug,
    )


def _buscar_dispositivo_counter(db: Session, token: str):
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return db.query(models.DispositivoCounter).filter(
        models.DispositivoCounter.token_hash == token_hash,
        models.DispositivoCounter.revocado_en.is_(None),
    ).first()


@app.post("/counter/dispositivos", response_model=schemas.CounterVincularResponse, tags=["Counter"])
def vincular_dispositivo_counter(
    datos: schemas.CounterVincularRequest,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(auth.requiere_administrador),
):
    import hashlib
    import secrets
    token = secrets.token_urlsafe(48)
    dispositivo = models.DispositivoCounter(
        gimnasio_id=admin.gimnasio_id,
        nombre=datos.nombre.strip(),
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        creado_por_id=admin.id,
    )
    db.add(dispositivo)
    db.commit()
    db.refresh(dispositivo)
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == admin.gimnasio_id).first()
    return schemas.CounterVincularResponse(
        dispositivo_token=token,
        dispositivo_id=dispositivo.id,
        gimnasio_nombre=gimnasio.nombre,
    )


@app.delete("/counter/dispositivos/{dispositivo_id}", tags=["Counter"])
def revocar_dispositivo_counter(
    dispositivo_id: int,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(auth.requiere_administrador),
):
    dispositivo = db.query(models.DispositivoCounter).filter(
        models.DispositivoCounter.id == dispositivo_id,
        models.DispositivoCounter.gimnasio_id == admin.gimnasio_id,
    ).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    dispositivo.revocado_en = ahora_lima()
    db.commit()
    return {"message": "Dispositivo revocado"}


@app.put("/usuarios/{usuario_id}/pin-counter", tags=["Counter"])
def configurar_pin_counter(
    usuario_id: int,
    datos: schemas.CounterPinRequest,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(auth.requiere_administrador),
):
    usuario = db.query(models.Usuario).filter(
        models.Usuario.id == usuario_id,
        models.Usuario.gimnasio_id == admin.gimnasio_id,
        models.Usuario.activo == True,
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    usuario.pin_counter_hash = auth.hash_codigo_acceso(datos.pin)
    db.commit()
    return {"message": "PIN de Counter actualizado"}


@app.get("/counter/usuarios", response_model=List[schemas.CounterUsuarioOut], tags=["Counter"])
def listar_usuarios_counter(dispositivo_token: str, db: Session = Depends(get_db)):
    dispositivo = _buscar_dispositivo_counter(db, dispositivo_token)
    if not dispositivo:
        raise HTTPException(status_code=401, detail="Dispositivo no vinculado o revocado")
    usuarios = db.query(models.Usuario).filter(
        models.Usuario.gimnasio_id == dispositivo.gimnasio_id,
        models.Usuario.activo == True,
        models.Usuario.pin_counter_hash.isnot(None),
    ).order_by(models.Usuario.nombre_completo).all()
    return [schemas.CounterUsuarioOut(id=u.id, nombre=u.nombre_completo, rol=u.rol.value) for u in usuarios]


@app.post("/counter/login", response_model=schemas.TokenResponse, tags=["Counter"])
def login_counter(datos: schemas.CounterLoginRequest, request: Request, db: Session = Depends(get_db)):
    dispositivo = _buscar_dispositivo_counter(db, datos.dispositivo_token)
    if not dispositivo:
        raise HTTPException(status_code=401, detail="Dispositivo no vinculado o revocado")
    clave = auth.clave_rate_limit(request, "counter", str(datos.usuario_id), str(dispositivo.id))
    auth.exigir_intentos_disponibles(clave, db)
    usuario = db.query(models.Usuario).filter(
        models.Usuario.id == datos.usuario_id,
        models.Usuario.gimnasio_id == dispositivo.gimnasio_id,
        models.Usuario.activo == True,
    ).first()
    if not usuario or not auth.verificar_codigo_acceso(datos.pin, usuario.pin_counter_hash):
        auth.registrar_fallo_login(db, clave)
        raise HTTPException(status_code=401, detail="Trabajador o PIN incorrecto")
    auth.limpiar_fallos_login(db, clave)
    if os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true" and (not usuario.email or not usuario.email_verificado):
        raise HTTPException(status_code=403, detail="Debes verificar tu correo antes de ingresar")
    dispositivo.ultimo_uso_en = ahora_lima()
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == usuario.gimnasio_id).first()
    sesion = _crear_sesion_usuario(db, usuario, request)
    _evento_auditoria(db, "INICIO_SESION_COUNTER", request, usuario, f"dispositivo_id={dispositivo.id}")
    token = auth.crear_access_token({
        "sub": str(usuario.id), "tipo": "usuario", "rol": usuario.rol.value,
        "gimnasio_id": usuario.gimnasio_id, "sv": usuario.sesion_version or 1, "jti": sesion.jti,
    })
    return schemas.TokenResponse(
        access_token=token, rol=usuario.rol.value, nombre=usuario.nombre_completo,
        es_administrador=usuario.es_administrador,
        es_superadmin=getattr(usuario, "es_superadmin", False),
        puede_eliminar=usuario.puede_eliminar, puede_exportar=usuario.puede_exportar,
        zonas_permitidas=usuario.zonas_permitidas, gimnasio_id=usuario.gimnasio_id,
        gimnasio_slug=gimnasio.slug if gimnasio else None,
    )


def _crear_token_un_solo_uso(db: Session, usuario_id: int, proposito: str, minutos: int) -> str:
    import hashlib
    import secrets
    token = secrets.token_urlsafe(48)
    db.add(models.TokenAutenticacion(
        usuario_id=usuario_id,
        proposito=proposito,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expira_en=ahora_lima() + timedelta(minutes=minutos),
    ))
    db.commit()
    return token


def _consumir_token_un_solo_uso(db: Session, token: str, proposito: str) -> models.TokenAutenticacion:
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    registro = db.query(models.TokenAutenticacion).filter(
        models.TokenAutenticacion.token_hash == token_hash,
        models.TokenAutenticacion.proposito == proposito,
        models.TokenAutenticacion.usado_en.is_(None),
    ).first()
    if not registro or registro.expira_en < ahora_lima():
        raise HTTPException(status_code=400, detail="El enlace es invalido o ya vencio")
    registro.usado_en = ahora_lima()
    return registro


@app.post("/auth/solicitar-recuperacion", tags=["Auth"])
def solicitar_recuperacion(datos: schemas.SolicitarRecuperacionRequest, db: Session = Depends(get_db)):
    """Respuesta deliberadamente generica para no revelar si un correo existe."""
    usuario = db.query(models.Usuario).filter(
        func.lower(models.Usuario.email) == datos.email.lower(),
        models.Usuario.activo == True,
    ).first()
    if usuario and email_service.esta_configurado():
        token = _crear_token_un_solo_uso(db, usuario.id, "recuperar_password", 30)
        base = os.getenv("APP_BASE_URL", "http://localhost:3001").rstrip("/")
        url = f"{base}/restablecer.html?token={token}"
        email_service.enviar(
            usuario.email,
            "Restablece tu contraseña de Soft-Gym",
            email_service.plantilla_accion("Restablecer contraseña", "Este enlace vence en 30 minutos.", "Crear nueva contraseña", url),
        )
    return {"message": "Si el correo corresponde a una cuenta, enviaremos las instrucciones."}


@app.post("/auth/restablecer-password", tags=["Auth"])
def restablecer_password(datos: schemas.RestablecerPasswordRequest, db: Session = Depends(get_db)):
    try:
        auth.validar_password_segura(datos.nueva_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    registro = _consumir_token_un_solo_uso(db, datos.token, "recuperar_password")
    usuario = db.query(models.Usuario).filter(models.Usuario.id == registro.usuario_id, models.Usuario.activo == True).first()
    if not usuario:
        raise HTTPException(status_code=400, detail="La cuenta ya no esta disponible")
    usuario.password_hash = auth.hash_password(datos.nueva_password)
    usuario.sesion_version = int(usuario.sesion_version or 1) + 1
    db.commit()
    return {"message": "Contraseña actualizada. Ya puedes iniciar sesión."}


@app.post("/auth/verificar-email", tags=["Auth"])
def verificar_email(datos: schemas.VerificarEmailRequest, db: Session = Depends(get_db)):
    registro = _consumir_token_un_solo_uso(db, datos.token, "verificar_email")
    usuario = db.query(models.Usuario).filter(models.Usuario.id == registro.usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=400, detail="La cuenta ya no esta disponible")
    usuario.email_verificado = True
    db.commit()
    return {"message": "Correo verificado correctamente"}


@app.post("/auth/reenviar-verificacion", tags=["Auth"])
def reenviar_verificacion_email(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.get_usuario_actual),
):
    if usuario.email_verificado:
        return {"message": "Tu correo ya esta verificado", "enviado": False}
    if not usuario.email:
        raise HTTPException(status_code=400, detail="Tu cuenta no tiene un correo registrado")
    if not email_service.esta_configurado():
        raise HTTPException(status_code=503, detail="El proveedor de correo aun no esta configurado")
    token_email = _crear_token_un_solo_uso(db, usuario.id, "verificar_email", 24 * 60)
    base = os.getenv("APP_BASE_URL", "http://localhost:3000").rstrip("/")
    try:
        email_service.enviar(
            usuario.email,
            "Verifica tu correo de Soft-Gym",
            email_service.plantilla_accion(
                "Verifica tu correo",
                "Confirma que este correo pertenece a tu cuenta de Soft-Gym.",
                "Verificar correo",
                f"{base}/verificar-email.html?token={token_email}",
            ),
        )
    except Exception as exc:
        logger.exception("Fallo el reenvio de verificacion para usuario %s", usuario.id)
        raise HTTPException(status_code=502, detail="El proveedor no pudo entregar el correo") from exc
    return {"message": "Correo de verificacion enviado", "enviado": True}


@app.post("/auth/cerrar-otras-sesiones", tags=["Auth"])
def cerrar_otras_sesiones(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.get_usuario_actual)):
    db.query(models.SesionUsuario).filter(
        models.SesionUsuario.usuario_id == usuario.id,
        models.SesionUsuario.revocada_en.is_(None),
    ).update({"revocada_en": ahora_lima()}, synchronize_session=False)
    usuario.sesion_version = int(usuario.sesion_version or 1) + 1
    db.commit()
    return {"message": "Todas las sesiones fueron cerradas. Ingresa nuevamente."}


@app.get("/auditoria", tags=["Auditoria"])
def consultar_auditoria(
    accion: Optional[str] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(auth.requiere_administrador),
):
    consulta = db.query(models.EventoAuditoria).filter(models.EventoAuditoria.gimnasio_id == get_gid(admin))
    if accion:
        consulta = consulta.filter(models.EventoAuditoria.accion == accion.upper())
    if desde:
        consulta = consulta.filter(models.EventoAuditoria.creado_en >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        consulta = consulta.filter(models.EventoAuditoria.creado_en <= datetime.combine(hasta, datetime.max.time()))
    eventos = consulta.order_by(models.EventoAuditoria.creado_en.desc()).offset(skip).limit(limit).all()
    usuarios = {u.id: u.nombre_completo for u in db.query(models.Usuario).filter(models.Usuario.gimnasio_id == get_gid(admin)).all()}
    return [{
        "id": e.id, "accion": e.accion, "metodo": e.metodo, "ruta": e.ruta,
        "estado_http": e.estado_http, "usuario_id": e.usuario_id,
        "usuario": usuarios.get(e.usuario_id, "Sistema"), "ip": e.ip,
        "dispositivo": e.user_agent, "detalles": e.detalles, "creado_en": e.creado_en,
    } for e in eventos]


@app.get("/auth/sesiones", tags=["Auth"])
def listar_sesiones(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.get_usuario_actual)):
    sesiones = db.query(models.SesionUsuario).filter(
        models.SesionUsuario.usuario_id == usuario.id,
    ).order_by(models.SesionUsuario.ultima_actividad.desc()).limit(30).all()
    return [{
        "id": s.id, "ip": s.ip, "dispositivo": s.user_agent,
        "creada_en": s.creada_en, "ultima_actividad": s.ultima_actividad,
        "activa": s.revocada_en is None, "revocada_en": s.revocada_en,
    } for s in sesiones]


@app.delete("/auth/sesiones/{sesion_id}", tags=["Auth"])
def cerrar_sesion(sesion_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.get_usuario_actual)):
    sesion = db.query(models.SesionUsuario).filter(
        models.SesionUsuario.id == sesion_id,
        models.SesionUsuario.usuario_id == usuario.id,
    ).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    sesion.revocada_en = ahora_lima()
    db.commit()
    return {"message": "Sesión cerrada"}


@app.get("/usuarios/invitaciones", tags=["Usuarios"])
def listar_invitaciones(db: Session = Depends(get_db), admin: models.Usuario = Depends(auth.requiere_administrador)):
    invitaciones = db.query(models.InvitacionUsuario).filter(
        models.InvitacionUsuario.gimnasio_id == get_gid(admin),
    ).order_by(models.InvitacionUsuario.creado_en.desc()).all()
    return [{
        "id": i.id, "email": i.email, "rol": i.rol.value,
        "expira_en": i.expira_en, "aceptada_en": i.aceptada_en,
        "revocada_en": i.revocada_en, "creado_en": i.creado_en,
    } for i in invitaciones]


@app.post("/usuarios/invitaciones", tags=["Usuarios"])
def crear_invitacion(
    datos: schemas.InvitacionUsuarioCreate,
    db: Session = Depends(get_db),
    admin: models.Usuario = Depends(auth.requiere_administrador),
):
    import hashlib
    import secrets
    email = str(datos.email).strip().lower()
    if db.query(models.Usuario).filter(func.lower(models.Usuario.email) == email, models.Usuario.activo == True).first():
        raise HTTPException(status_code=400, detail="Ese correo ya pertenece a una cuenta activa")
    if datos.empleado_id:
        empleado = q(db, models.Empleado, admin).filter(models.Empleado.id == datos.empleado_id).first()
        if not empleado:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")

    ahora = ahora_lima()
    anteriores = db.query(models.InvitacionUsuario).filter(
        models.InvitacionUsuario.gimnasio_id == get_gid(admin),
        func.lower(models.InvitacionUsuario.email) == email,
        models.InvitacionUsuario.aceptada_en.is_(None),
        models.InvitacionUsuario.revocada_en.is_(None),
    ).all()
    for anterior in anteriores:
        anterior.revocada_en = ahora

    token = secrets.token_urlsafe(48)
    invitacion = models.InvitacionUsuario(
        gimnasio_id=get_gid(admin), email=email, rol=datos.rol,
        empleado_id=datos.empleado_id, es_administrador=datos.es_administrador,
        puede_eliminar=datos.puede_eliminar, puede_exportar=datos.puede_exportar,
        zonas_permitidas=datos.zonas_permitidas,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expira_en=ahora + timedelta(hours=72), invitado_por_id=admin.id,
    )
    db.add(invitacion)
    db.commit()
    db.refresh(invitacion)
    base = os.getenv("APP_BASE_URL", "http://localhost:3001").rstrip("/")
    url = f"{base}/aceptar-invitacion.html?token={token}"
    enviado = False
    if email_service.esta_configurado():
        try:
            email_service.enviar(email, "Invitación a Soft-Gym", email_service.plantilla_accion(
                "Te invitaron a Soft-Gym", "Crea tu cuenta personal. Este enlace vence en 72 horas.", "Aceptar invitación", url))
            enviado = True
        except Exception:
            logger.exception("No se pudo enviar la invitacion %s", invitacion.id)
    return {"id": invitacion.id, "email": email, "expira_en": invitacion.expira_en, "enviado": enviado, "enlace": url}


@app.delete("/usuarios/invitaciones/{invitacion_id}", tags=["Usuarios"])
def revocar_invitacion(invitacion_id: int, db: Session = Depends(get_db), admin: models.Usuario = Depends(auth.requiere_administrador)):
    invitacion = db.query(models.InvitacionUsuario).filter(
        models.InvitacionUsuario.id == invitacion_id,
        models.InvitacionUsuario.gimnasio_id == get_gid(admin),
    ).first()
    if not invitacion:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitacion.aceptada_en:
        raise HTTPException(status_code=400, detail="La invitación ya fue aceptada")
    invitacion.revocada_en = ahora_lima()
    db.commit()
    return {"message": "Invitación revocada"}


@app.post("/auth/aceptar-invitacion", tags=["Auth"])
def aceptar_invitacion(datos: schemas.InvitacionUsuarioAceptar, db: Session = Depends(get_db)):
    import hashlib
    try:
        auth.validar_password_segura(datos.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token_hash = hashlib.sha256(datos.token.encode("utf-8")).hexdigest()
    invitacion = db.query(models.InvitacionUsuario).filter(
        models.InvitacionUsuario.token_hash == token_hash,
        models.InvitacionUsuario.aceptada_en.is_(None),
        models.InvitacionUsuario.revocada_en.is_(None),
    ).first()
    if not invitacion or invitacion.expira_en < ahora_lima():
        raise HTTPException(status_code=400, detail="La invitación es inválida o ya venció")
    username = datos.username.strip()
    if db.query(models.Usuario).filter(models.Usuario.username == username).first():
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya está en uso")
    usuario = models.Usuario(
        gimnasio_id=invitacion.gimnasio_id, nombre_completo=datos.nombre_completo.strip(),
        username=username, email=invitacion.email, email_verificado=True,
        password_hash=auth.hash_password(datos.password), rol=invitacion.rol,
        empleado_id=invitacion.empleado_id, es_administrador=invitacion.es_administrador,
        puede_eliminar=invitacion.puede_eliminar, puede_exportar=invitacion.puede_exportar,
        zonas_permitidas=invitacion.zonas_permitidas,
    )
    db.add(usuario)
    invitacion.aceptada_en = ahora_lima()
    db.commit()
    return {"message": "Cuenta creada correctamente. Ya puedes iniciar sesión."}


@app.post("/auth/login-alumno", response_model=schemas.TokenResponse, tags=["Auth"])
def login_alumno(datos: schemas.LoginAlumnoRequest, request: Request, db: Session = Depends(get_db)):
    """Login de alumnos con DNI + codigo de acceso corto."""
    clave = auth.clave_rate_limit(request, "alumno", datos.dni, datos.slug)
    auth.exigir_intentos_disponibles(clave, db)
    gid = _resolver_gimnasio_id_por_slug(db, datos.slug)
    cliente = auth.autenticar_alumno(db, datos.dni, datos.codigo_acceso, gimnasio_id=gid)
    if not cliente:
        auth.registrar_fallo_login(db, clave)
        raise HTTPException(status_code=401, detail="DNI o codigo de acceso incorrectos")

    auth.limpiar_fallos_login(db, clave)
    token = auth.crear_access_token({"sub": str(cliente.id), "tipo": "alumno", "gimnasio_id": cliente.gimnasio_id})
    return schemas.TokenResponse(
        access_token=token,
        rol="alumno",
        nombre=cliente.nombre,
        gimnasio_id=cliente.gimnasio_id,
        debe_cambiar_password=False,
    )


@app.post("/auth/iniciar-alumno", tags=["Auth"])
def iniciar_login_alumno(datos: schemas.InicioLoginAlumnoRequest, db: Session = Depends(get_db)):
    """Indica si pide contraseña o permite crearla en el primer ingreso."""
    gid = _resolver_gimnasio_id_por_slug(db, datos.slug)
    cliente = auth.obtener_alumno_para_inicio(db, datos.dni.strip(), gimnasio_id=gid)
    if not cliente:
        raise HTTPException(status_code=401, detail="No encontramos un alumno activo con ese DNI")
    if cliente.codigo_acceso and cliente.codigo_acceso.strip():
        return {"requiere_password": True, "debe_crear_password": False}

    token = auth.crear_access_token(
        {"sub": str(cliente.id), "tipo": "alumno_configuracion", "gimnasio_id": cliente.gimnasio_id},
        expires_delta=timedelta(minutes=15),
    )
    return {
        "requiere_password": False,
        "debe_crear_password": True,
        "access_token": token,
        "token_type": "bearer",
        "rol": "alumno",
        "nombre": cliente.nombre,
        "gimnasio_id": cliente.gimnasio_id,
        "debe_cambiar_password": True,
    }


@app.post("/auth/login-profesor", response_model=schemas.TokenResponse, tags=["Auth"])
def login_profesor(datos: schemas.LoginAlumnoRequest, request: Request, db: Session = Depends(get_db)):
    """
    Login de profesores de sala a su Zona de Profesores (portal
    aparte, sin acceso al software de staff): DNI + codigo corto.
    """
    gid = _resolver_gimnasio_id_por_slug(db, datos.slug)
    clave = auth.clave_rate_limit(request, "profesor", datos.dni, datos.slug)
    auth.exigir_intentos_disponibles(clave, db)
    profesor = auth.autenticar_profesor(db, datos.dni, datos.codigo_acceso, gimnasio_id=gid)
    if not profesor:
        auth.registrar_fallo_login(db, clave)
        raise HTTPException(status_code=401, detail="DNI o codigo de acceso incorrectos")

    auth.limpiar_fallos_login(db, clave)
    token = auth.crear_access_token({"sub": str(profesor.id), "tipo": "profesor", "gimnasio_id": profesor.gimnasio_id})
    return schemas.TokenResponse(access_token=token, rol="profesor_sala", nombre=profesor.nombre_completo, gimnasio_id=profesor.gimnasio_id)


# ==================================================================
# GESTION DE USUARIOS (staff / profesores) - solo STAFF administra
# ==================================================================

@app.get("/usuarios/", response_model=List[schemas.Usuario], tags=["Usuarios"])
def listar_usuarios(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    return q(db, models.Usuario, usuario).order_by(models.Usuario.nombre_completo).all()


@app.post("/usuarios/", response_model=schemas.Usuario, tags=["Usuarios"])
def crear_usuario(datos: schemas.UsuarioCreate, db: Session = Depends(get_db), usuario_admin: models.Usuario = Depends(auth.requiere_administrador)):
    """
    Crea una cuenta de acceso para staff o profesor. Si se asocia
    a un empleado_id, ese Empleado debe existir y, para un usuario
    con rol PROFESOR, debe ser de tipo PROFESOR_DE_SALA.
    """
    import secrets
    password_interna = datos.password or secrets.token_urlsafe(32)
    if datos.password:
        try:
            auth.validar_password_segura(datos.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if datos.rol == models.RolUsuario.STAFF:
        _validar_limite_plan(db, usuario_admin, "usuarios_staff")
    existente = db.query(models.Usuario).filter(models.Usuario.username == datos.username).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya esta en uso")

    if datos.empleado_id:
        empleado = _del_gym(db, models.Empleado, datos.empleado_id, usuario_admin)
        if not empleado:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
        if datos.rol == models.RolUsuario.PROFESOR and empleado.tipo != models.TipoEmpleado.PROFESOR_DE_SALA:
            raise HTTPException(status_code=400, detail="El empleado asociado no es un profesor de sala")
        ya_ligado = q(db, models.Usuario, usuario_admin).filter(
            models.Usuario.empleado_id == datos.empleado_id,
            models.Usuario.activo == True,
        ).first()
        if ya_ligado:
            raise HTTPException(status_code=400, detail=f"Ese empleado ya tiene una cuenta de acceso activa ('{ya_ligado.username}')")

    db_usuario = models.Usuario(
        nombre_completo=datos.nombre_completo,
        username=datos.username,
        password_hash=auth.hash_password(password_interna),
        rol=datos.rol,
        empleado_id=datos.empleado_id,
        es_administrador=datos.es_administrador,
        puede_eliminar=datos.puede_eliminar,
        puede_exportar=datos.puede_exportar,
        zonas_permitidas=datos.zonas_permitidas,
        gimnasio_id=get_gid(usuario_admin),
    )
    db.add(db_usuario)
    db.commit()
    db.refresh(db_usuario)
    return db_usuario


@app.put("/usuarios/{usuario_id}", response_model=schemas.Usuario, tags=["Usuarios"])
def actualizar_usuario(
    usuario_id: int,
    datos: schemas.UsuarioUpdate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Cualquier staff puede cambiar su propia contraseña (usuario_id
    igual al suyo). Cualquier otro cambio (a otra cuenta, o a
    permisos/zonas/estado propios) requiere ser administrador.
    """
    es_uno_mismo = usuario_id == usuario_actual.id
    datos_dict = datos.model_dump(exclude_unset=True)
    campos_autoservicio = {"password"}

    if not usuario_actual.es_administrador:
        if not es_uno_mismo:
            raise HTTPException(status_code=403, detail="Requiere permisos de administrador")
        if set(datos_dict.keys()) - campos_autoservicio:
            raise HTTPException(status_code=403, detail="Solo puedes cambiar tu propia contraseña")

    usuario = q(db, models.Usuario, usuario_actual).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if "password" in datos_dict:
        nueva_password = datos_dict.pop("password")
        if nueva_password:
            try:
                auth.validar_password_segura(nueva_password)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            usuario.password_hash = auth.hash_password(nueva_password)

    for campo, valor in datos_dict.items():
        setattr(usuario, campo, valor)

    db.commit()
    db.refresh(usuario)
    return usuario


@app.delete("/usuarios/{usuario_id}", tags=["Usuarios"])
def desactivar_usuario(usuario_id: int, db: Session = Depends(get_db), usuario_actual=Depends(auth.requiere_administrador)):
    if usuario_id == usuario_actual.id:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta")

    usuario = q(db, models.Usuario, usuario_actual).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    usuario.activo = False
    db.commit()
    return {"message": "Usuario desactivado correctamente"}


@app.get("/usuarios/me", response_model=schemas.Usuario, tags=["Usuarios"])
def mi_cuenta(usuario: models.Usuario = Depends(auth.get_usuario_actual)):
    """Devuelve los datos del usuario (staff o profesor) actualmente logueado."""
    return usuario


# ==================================================================
# DASHBOARD (staff)
# ==================================================================

# ==================================================================
# INGRESOS / EGRESOS (vistas agregadas filtrables para el panel)
# ==================================================================

@app.get("/conceptos-ingreso/", response_model=List[schemas.ConceptoOtroIngreso], tags=["Finanzas"])
def listar_conceptos_ingreso(
    solo_activos: bool = True,
    para_agenda: bool = False,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff),
):
    query = q(db, models.ConceptoOtroIngreso, usuario)
    if solo_activos:
        query = query.filter(models.ConceptoOtroIngreso.activo == True)
    if para_agenda:
        query = query.filter(models.ConceptoOtroIngreso.mostrar_agenda == True)
    return query.order_by(models.ConceptoOtroIngreso.nombre).all()


@app.post("/conceptos-ingreso/", response_model=schemas.ConceptoOtroIngreso, tags=["Finanzas"])
def crear_concepto_ingreso(datos: schemas.ConceptoOtroIngresoCreate, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    if not datos.nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre del concepto es obligatorio")
    valores = datos.model_dump()
    valores["nombre"] = datos.nombre.strip()
    concepto = models.ConceptoOtroIngreso(**valores, gimnasio_id=get_gid(usuario))
    db.add(concepto); db.commit(); db.refresh(concepto)
    return concepto


@app.put("/conceptos-ingreso/{concepto_id}", response_model=schemas.ConceptoOtroIngreso, tags=["Finanzas"])
def actualizar_concepto_ingreso(concepto_id: int, datos: schemas.ConceptoOtroIngresoUpdate, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    concepto = _del_gym(db, models.ConceptoOtroIngreso, concepto_id, usuario)
    if not concepto:
        raise HTTPException(status_code=404, detail="Concepto no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(concepto, campo, valor.strip() if campo == "nombre" and valor else valor)
    db.commit(); db.refresh(concepto)
    return concepto


@app.delete("/conceptos-ingreso/{concepto_id}", tags=["Finanzas"])
def desactivar_concepto_ingreso(concepto_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_administrador)):
    concepto = _del_gym(db, models.ConceptoOtroIngreso, concepto_id, usuario)
    if not concepto:
        raise HTTPException(status_code=404, detail="Concepto no encontrado")
    concepto.activo = False; db.commit()
    return {"ok": True}


@app.get("/otros-ingresos/", response_model=List[schemas.OtroIngreso], tags=["Finanzas"])
def listar_otros_ingresos(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    limit: int = 100,
    incluir_anulados: bool = False,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff),
):
    query = q(db, models.OtroIngreso, usuario)
    if not incluir_anulados:
        query = query.filter(models.OtroIngreso.anulada == False)
    if desde:
        query = query.filter(models.OtroIngreso.fecha >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        query = query.filter(models.OtroIngreso.fecha <= datetime.combine(hasta, datetime.max.time()))
    return query.order_by(models.OtroIngreso.fecha.desc()).limit(min(limit, 500)).all()


@app.post("/otros-ingresos/", response_model=schemas.OtroIngreso, tags=["Finanzas"])
def registrar_otro_ingreso(datos: schemas.OtroIngresoCreate, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario, "otros-ingresos", idempotency_key, payload, models.OtroIngreso)
    if previo:
        return previo
    concepto = _del_gym(db, models.ConceptoOtroIngreso, datos.concepto_id, usuario)
    if not concepto or not concepto.activo:
        raise HTTPException(status_code=404, detail="Concepto de ingreso no encontrado")
    valores = datos.model_dump()
    valores["fecha"] = datos.fecha or ahora_lima()
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), valores["fecha"])
    ingreso = models.OtroIngreso(**valores, gimnasio_id=get_gid(usuario), usuario_id=usuario.id)
    db.add(ingreso); db.flush()
    _guardar_idempotencia(db, usuario, "otros-ingresos", idempotency_key, payload, "OtroIngreso", ingreso.id)
    db.commit(); db.refresh(ingreso)
    return ingreso


@app.delete("/otros-ingresos/{ingreso_id}", tags=["Finanzas"])
def eliminar_otro_ingreso(ingreso_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario=Depends(auth.requiere_administrador)):
    ingreso = _del_gym(db, models.OtroIngreso, ingreso_id, usuario)
    if not ingreso:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    if ingreso.anulada:
        raise HTTPException(status_code=409, detail="El ingreso ya fue anulado")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), ingreso.fecha)
    ingreso.anulada = True; ingreso.anulada_en = ahora_lima(); ingreso.anulada_por_id = usuario.id; ingreso.motivo_anulacion = datos.motivo.strip()
    db.commit()
    return {"message": "Ingreso anulado"}

@app.get("/ingresos/", tags=["Finanzas"])
def listar_ingresos(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    solo_hoy: bool = False,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    hoy = hoy_lima()
    if solo_hoy:
        desde = hasta = hoy
    if not desde:
        desde = hoy.replace(day=1)
    if not hasta:
        import calendar as _cal
        hasta = hoy.replace(day=_cal.monthrange(hoy.year, hoy.month)[1])
    desde_dt = datetime.combine(desde, datetime.min.time())
    hasta_dt  = datetime.combine(hasta, datetime.max.time())
    config = _configuracion_del_gym(db, usuario)
    detalle = []

    if not tipo or tipo == "membresias":
        # Cada pago individual (inicial o a cuenta) como linea separada
        pagos_membresia = (
            db.query(models.PagoMembresia)
            .join(models.ClienteMembresia, models.ClienteMembresia.id == models.PagoMembresia.cliente_membresia_id)
            .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
            .filter(
                models.Cliente.gimnasio_id == get_gid(usuario),
                models.PagoMembresia.anulada == False,
                models.PagoMembresia.fecha_pago >= desde_dt,
                models.PagoMembresia.fecha_pago <= hasta_dt,
            )
            .all()
        )
        for pm in pagos_membresia:
            cm = db.query(models.ClienteMembresia).filter(models.ClienteMembresia.id == pm.cliente_membresia_id).first()
            cli = db.query(models.Cliente).filter(models.Cliente.id == cm.cliente_id).first() if cm else None
            plan = db.query(models.Membresia).filter(models.Membresia.id == cm.membresia_id).first() if cm else None
            metodo = pm.metodo_pago or "efectivo"
            comision_gym = 0.0
            if metodo == "tarjeta":
                comision_gym = round(pm.monto * (config.comision_tarjeta or 0.0) / 100, 2)
            elif metodo == "qr":
                comision_gym = round(pm.monto * (config.comision_qr or 0.0) / 100, 2)
            nombre_cli = (cli.nombre + ' ' + (cli.apellidos or '')).strip() if cli else '?'
            nombre_plan = plan.nombre if plan else 'Plan ?'
            nota_tipo = pm.notas or 'Pago membresía'
            detalle.append({"id": pm.id,
                "fecha": pm.fecha_pago.isoformat(),
                "categoria": "membresias",
                "descripcion": f"{nombre_plan} — {nombre_cli} ({nota_tipo})",
                "monto": pm.monto,
                "metodo_pago": metodo,
                "comision_gym": comision_gym})

    if not tipo or tipo == "productos":
        for v in db.query(models.Venta).filter(
            models.Venta.gimnasio_id == get_gid(usuario),
            models.Venta.anulada == False,
            models.Venta.fecha_venta >= desde_dt, models.Venta.fecha_venta <= hasta_dt
        ).all():
            cli  = db.query(models.Cliente).filter(models.Cliente.id == v.cliente_id).first() if v.cliente_id else None
            prod = ", ".join(f"{d.cantidad}x {d.producto.nombre}" for d in v.detalles if d.producto) or "Venta"
            detalle.append({"id": v.id, "fecha": v.fecha_venta.isoformat(), "categoria": "productos",
                "descripcion": f"{prod}{' — ' + cli.nombre if cli else ''}", "monto": v.total,
                "metodo_pago": v.metodo_pago.value if hasattr(v.metodo_pago, "value") else v.metodo_pago,
                "comision_gym": v.costo_comision_gym or 0.0})

    if not tipo or tipo in ("otros", "otros_ingresos"):
        for ingreso in db.query(models.OtroIngreso).filter(
            models.OtroIngreso.gimnasio_id == get_gid(usuario),
            models.OtroIngreso.anulada == False,
            models.OtroIngreso.fecha >= desde_dt,
            models.OtroIngreso.fecha <= hasta_dt,
        ).all():
            comision_gym = 0.0
            if ingreso.metodo_pago == "tarjeta":
                comision_gym = round(ingreso.monto * (config.comision_tarjeta or 0.0) / 100, 2)
            elif ingreso.metodo_pago == "qr":
                comision_gym = round(ingreso.monto * (config.comision_qr or 0.0) / 100, 2)
            detalle.append({
                "id": ingreso.id,
                "fecha": ingreso.fecha.isoformat(),
                "categoria": "otros_ingresos",
                "descripcion": f"{ingreso.concepto.nombre if ingreso.concepto else 'Otro ingreso'}{(' — ' + ingreso.descripcion) if ingreso.descripcion else ''}",
                "monto": ingreso.monto,
                "metodo_pago": ingreso.metodo_pago,
                "comision_gym": comision_gym,
            })

    detalle.sort(key=lambda x: x["fecha"], reverse=True)
    tot_m = sum(d["monto"] for d in detalle if d["categoria"] == "membresias")
    tot_p = sum(d["monto"] for d in detalle if d["categoria"] == "productos")
    tot_o = sum(d["monto"] for d in detalle if d["categoria"] in ("otros", "otros_ingresos"))
    return {"total": round(tot_m + tot_p + tot_o, 2), "membresias": round(tot_m, 2),
            "productos": round(tot_p, 2), "otros": round(tot_o, 2), "detalle": detalle}


def _total_pagado_membresia(db: Session, cliente_membresia_id: int) -> float:
    """Fuente única del pagado: pagos válidos, nunca el acumulado editable."""
    total = db.query(func.coalesce(func.sum(models.PagoMembresia.monto), 0.0)).filter(
        models.PagoMembresia.cliente_membresia_id == cliente_membresia_id,
        models.PagoMembresia.anulada == False,
    ).scalar()
    return round(float(total or 0.0), 2)


@app.get("/egresos/", tags=["Finanzas"])
def listar_egresos(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    solo_hoy: bool = False,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    hoy = hoy_lima()
    if solo_hoy:
        desde = hasta = hoy
    if not desde:
        desde = hoy.replace(day=1)
    if not hasta:
        import calendar as _cal
        hasta = hoy.replace(day=_cal.monthrange(hoy.year, hoy.month)[1])
    desde_dt = datetime.combine(desde, datetime.min.time())
    hasta_dt  = datetime.combine(hasta, datetime.max.time())
    config = _configuracion_del_gym(db, usuario)
    detalle = []

    if not tipo or tipo == "compra_producto":
        for c in db.query(models.Compra).filter(
            models.Compra.gimnasio_id == get_gid(usuario),
            models.Compra.anulada == False,
            models.Compra.fecha >= desde_dt, models.Compra.fecha <= hasta_dt
        ).all():
            detalle.append({"id": c.id, "fecha": c.fecha.isoformat(), "categoria": "compra_producto",
                "descripcion": f"{c.cantidad} x {c.producto.nombre if c.producto else '?'} (S/{c.costo_unitario}/u)",
                "monto": c.costo_total, "metodo_pago": c.metodo_pago})

    if not tipo or tipo == "pago_staff":
        for p in db.query(models.PagoPlanilla).filter(
            models.PagoPlanilla.gimnasio_id == get_gid(usuario),
            models.PagoPlanilla.tipo == "staff",
            models.PagoPlanilla.anulada == False,
            models.PagoPlanilla.fecha_pago >= desde_dt, models.PagoPlanilla.fecha_pago <= hasta_dt,
        ).all():
            detalle.append({"id": p.id, "fecha": p.fecha_pago.isoformat(), "categoria": "pago_staff",
                "descripcion": f"{p.empleado.nombre_completo if p.empleado else '?'} — {p.mes}/{p.anio}{' (' + p.notas + ')' if p.notas else ''}",
                "monto": p.monto_total, "metodo_pago": p.metodo_pago})

    if not tipo or tipo == "pago_profesor":
        for p in db.query(models.PagoPlanilla).filter(
            models.PagoPlanilla.gimnasio_id == get_gid(usuario),
            models.PagoPlanilla.tipo == "profesor",
            models.PagoPlanilla.anulada == False,
            models.PagoPlanilla.fecha_pago >= desde_dt, models.PagoPlanilla.fecha_pago <= hasta_dt,
        ).all():
            periodo = f"{p.desde} al {p.hasta}" if p.desde and p.hasta else f"{p.mes}/{p.anio}"
            detalle.append({"id": p.id, "fecha": p.fecha_pago.isoformat(), "categoria": "pago_profesor",
                "descripcion": f"{p.empleado.nombre_completo if p.empleado else '?'} — {periodo}",
                "monto": p.monto_total, "metodo_pago": p.metodo_pago})

    if not tipo or tipo == "pago_servicio":
        for p in db.query(models.PagoServicio).join(
            models.CargoServicio, models.CargoServicio.id == models.PagoServicio.cargo_id
        ).filter(
            models.CargoServicio.gimnasio_id == get_gid(usuario),
            models.PagoServicio.anulada == False,
            models.PagoServicio.fecha_pago >= desde_dt,
            models.PagoServicio.fecha_pago <= hasta_dt,
        ).all():
            cargo = p.cargo
            servicio_nombre = cargo.servicio.nombre if cargo and cargo.servicio else "Servicio"
            periodo = f"{cargo.mes}/{cargo.anio}" if cargo else ""
            detalle.append({"id": p.id, "fecha": p.fecha_pago.isoformat(), "categoria": "pago_servicio",
                "descripcion": f"{servicio_nombre} — {(cargo.concepto + ' ' if cargo and cargo.concepto else '')}{periodo}".strip(),
                "monto": p.monto, "metodo_pago": p.metodo_pago})

    if not tipo or tipo == "otros":
        for g in db.query(models.Gasto).filter(
            models.Gasto.gimnasio_id == get_gid(usuario),
            models.Gasto.categoria == models.CategoriaGasto.OTROS,
            models.Gasto.anulada == False,
            models.Gasto.fecha >= desde_dt, models.Gasto.fecha <= hasta_dt,
        ).all():
            detalle.append({"id": g.id, "fecha": g.fecha.isoformat(), "categoria": "otros",
                "descripcion": g.descripcion or "Gasto general", "monto": g.monto,
                "metodo_pago": g.metodo_pago})

    # ---- Comision de pasarela (tarjeta/QR): no es un registro propio
    # en la base, se deriva de las Ventas y Membresias cobradas con
    # tarjeta/QR en el rango, para que se vea como un egreso explicito
    # justo debajo del ingreso que lo genero (misma fecha). No es
    # eliminable por si sola: se borra automaticamente si se borra la
    # venta/membresia de la que viene.
    if not tipo or tipo == "comision":
        for v in db.query(models.Venta).filter(
            models.Venta.gimnasio_id == get_gid(usuario),
            models.Venta.anulada == False,
            models.Venta.fecha_venta >= desde_dt, models.Venta.fecha_venta <= hasta_dt,
            models.Venta.metodo_pago != models.MetodoPago.EFECTIVO,
        ).all():
            if (v.costo_comision_gym or 0.0) <= 0:
                continue
            metodo_txt = "Tarjeta" if v.metodo_pago == models.MetodoPago.TARJETA else "QR"
            detalle.append({"id": v.id, "fecha": v.fecha_venta.isoformat(), "categoria": "comision",
                "descripcion": f"Comisión {metodo_txt} — Venta #{v.id}", "monto": v.costo_comision_gym,
                "metodo_pago": "cuenta"})

        for pago in db.query(models.PagoMembresia).join(
            models.ClienteMembresia, models.ClienteMembresia.id == models.PagoMembresia.cliente_membresia_id
        ).join(
            models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id
        ).filter(
            models.Cliente.gimnasio_id == get_gid(usuario),
            models.PagoMembresia.anulada == False,
            models.PagoMembresia.fecha_pago >= desde_dt,
            models.PagoMembresia.fecha_pago <= hasta_dt,
        ).all():
            metodo = pago.metodo_pago or "efectivo"
            if metodo not in ("tarjeta", "qr"):
                continue
            porcentaje = config.comision_tarjeta if metodo == "tarjeta" else config.comision_qr
            comision = round((pago.monto or 0.0) * (porcentaje or 0.0) / 100, 2)
            if comision <= 0:
                continue
            cli = pago.cliente_membresia.cliente if pago.cliente_membresia else None
            metodo_txt = "Tarjeta" if metodo == "tarjeta" else "QR"
            detalle.append({"id": pago.id, "fecha": pago.fecha_pago.isoformat(),
                "categoria": "comision",
                "descripcion": f"Comisión {metodo_txt} — Membresía {(cli.nombre + ' ' + (cli.apellidos or '')).strip() if cli else '?'}",
                "monto": comision, "metodo_pago": "cuenta"})

        for ingreso in db.query(models.OtroIngreso).filter(
            models.OtroIngreso.gimnasio_id == get_gid(usuario),
            models.OtroIngreso.anulada == False,
            models.OtroIngreso.fecha >= desde_dt,
            models.OtroIngreso.fecha <= hasta_dt,
            models.OtroIngreso.metodo_pago.in_(("tarjeta", "qr")),
        ).all():
            porcentaje = config.comision_tarjeta if ingreso.metodo_pago == "tarjeta" else config.comision_qr
            comision = round((ingreso.monto or 0.0) * (porcentaje or 0.0) / 100, 2)
            if comision <= 0:
                continue
            metodo_txt = "Tarjeta" if ingreso.metodo_pago == "tarjeta" else "QR"
            detalle.append({"id": ingreso.id, "fecha": ingreso.fecha.isoformat(),
                "categoria": "comision",
                "descripcion": f"Comisión {metodo_txt} — {ingreso.concepto.nombre if ingreso.concepto else 'Otro ingreso'}",
                "monto": comision, "metodo_pago": "cuenta"})

    detalle.sort(key=lambda x: x["fecha"], reverse=True)
    tot_c = sum(d["monto"] for d in detalle if d["categoria"] == "compra_producto")
    tot_s = sum(d["monto"] for d in detalle if d["categoria"] == "pago_staff")
    tot_p = sum(d["monto"] for d in detalle if d["categoria"] == "pago_profesor")
    tot_sv = sum(d["monto"] for d in detalle if d["categoria"] == "pago_servicio")
    tot_o = sum(d["monto"] for d in detalle if d["categoria"] == "otros")
    tot_com = sum(d["monto"] for d in detalle if d["categoria"] == "comision")
    return {"total": round(tot_c + tot_s + tot_p + tot_sv + tot_o + tot_com, 2), "compras_producto": round(tot_c, 2),
            "pago_staff": round(tot_s, 2), "pago_profesor": round(tot_p, 2), "pago_servicio": round(tot_sv, 2),
            "otros": round(tot_o, 2), "comisiones": round(tot_com, 2), "detalle": detalle}


@app.post("/gastos/", tags=["Finanzas"])
def crear_gasto(
    datos: schemas.GastoCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario, "gastos", idempotency_key, payload, models.Gasto)
    if previo:
        return previo
    if datos.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    categoria = datos.categoria.value if hasattr(datos.categoria, "value") else datos.categoria
    if categoria != models.CategoriaGasto.OTROS.value:
        raise HTTPException(status_code=400, detail="Compras, planilla y servicios deben registrarse desde su modulo para evitar egresos duplicados")
    fecha_gasto = datos.fecha or ahora_lima()
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), fecha_gasto)
    g = models.Gasto(
        fecha=fecha_gasto,
        categoria=datos.categoria,
        monto=datos.monto,
        descripcion=datos.descripcion,
        referencia_id=datos.referencia_id,
        usuario_id=getattr(usuario, "id", None),
        notas=datos.notas,
        metodo_pago=datos.metodo_pago,
        gimnasio_id=get_gid(usuario),
    )
    db.add(g); db.flush()
    _guardar_idempotencia(db, usuario, "gastos", idempotency_key, payload, "Gasto", g.id)
    db.commit(); db.refresh(g)
    return g


@app.delete("/gastos/{gasto_id}", tags=["Finanzas"])
def eliminar_gasto(gasto_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario=Depends(auth.requiere_administrador)):
    g = _del_gym(db, models.Gasto, gasto_id, usuario)
    if not g:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if g.anulada:
        raise HTTPException(status_code=409, detail="El gasto ya fue anulado")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), g.fecha)
    g.anulada = True; g.anulada_en = ahora_lima(); g.anulada_por_id = usuario.id; g.motivo_anulacion = datos.motivo.strip()
    db.commit()
    return {"message": "Gasto anulado"}


def _dinero(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _turno_cerrado_de_fecha(db: Session, gimnasio_id: int, fecha: datetime):
    return db.query(models.TurnoCaja).filter(
        models.TurnoCaja.gimnasio_id == gimnasio_id,
        models.TurnoCaja.estado == "cerrada",
        models.TurnoCaja.abierta_en <= fecha,
        models.TurnoCaja.cerrada_en >= fecha,
    ).first()


def _exigir_periodo_financiero_abierto(db: Session, gimnasio_id: int, fecha: Optional[datetime]):
    """Evita reescribir un movimiento incluido en una conciliacion ya firmada."""
    if fecha and _turno_cerrado_de_fecha(db, gimnasio_id, fecha):
        raise HTTPException(
            status_code=409,
            detail="Esta operacion pertenece a una caja cerrada y no puede modificarse. Registra un ajuste en Caja.",
        )


def _movimientos_caja(db: Session, gimnasio_id: int, desde: datetime, hasta: datetime) -> dict:
    """Reconstruye el efectivo desde los documentos fuente, sin una suma editable."""
    movimientos = []
    def agregar(tipo, registro_id, fecha, descripcion, monto, direccion):
        valor = _dinero(monto)
        movimientos.append({"tipo": tipo, "id": registro_id, "fecha": fecha.isoformat(), "descripcion": descripcion,
                            "monto": float(valor), "direccion": direccion})

    pagos = db.query(models.PagoMembresia).join(models.ClienteMembresia).join(models.Cliente).filter(
        models.Cliente.gimnasio_id == gimnasio_id, or_(models.PagoMembresia.anulada == False, models.PagoMembresia.anulada_en > hasta),
        models.PagoMembresia.metodo_pago == "efectivo", models.PagoMembresia.fecha_pago >= desde, models.PagoMembresia.fecha_pago <= hasta,
    ).all()
    for p in pagos: agregar("membresia", p.id, p.fecha_pago, "Pago de membresia", p.monto, "ingreso")
    for v in db.query(models.Venta).filter(models.Venta.gimnasio_id == gimnasio_id, or_(models.Venta.anulada == False, models.Venta.anulada_en > hasta),
        models.Venta.metodo_pago == models.MetodoPago.EFECTIVO, models.Venta.fecha_venta >= desde, models.Venta.fecha_venta <= hasta).all():
        agregar("venta", v.id, v.fecha_venta, f"Venta #{v.id}", v.total, "ingreso")
    for i in db.query(models.OtroIngreso).filter(models.OtroIngreso.gimnasio_id == gimnasio_id, or_(models.OtroIngreso.anulada == False, models.OtroIngreso.anulada_en > hasta),
        models.OtroIngreso.metodo_pago == "efectivo", models.OtroIngreso.fecha >= desde, models.OtroIngreso.fecha <= hasta).all():
        agregar("otro_ingreso", i.id, i.fecha, i.descripcion or "Otro ingreso", i.monto, "ingreso")

    for c in db.query(models.Compra).filter(models.Compra.gimnasio_id == gimnasio_id, or_(models.Compra.anulada == False, models.Compra.anulada_en > hasta),
        models.Compra.metodo_pago == "efectivo", models.Compra.fecha >= desde, models.Compra.fecha <= hasta).all():
        agregar("compra", c.id, c.fecha, f"Compra #{c.id}", c.costo_total, "egreso")
    for p in db.query(models.PagoPlanilla).filter(models.PagoPlanilla.gimnasio_id == gimnasio_id, or_(models.PagoPlanilla.anulada == False, models.PagoPlanilla.anulada_en > hasta),
        models.PagoPlanilla.metodo_pago == "efectivo", models.PagoPlanilla.fecha_pago >= desde, models.PagoPlanilla.fecha_pago <= hasta).all():
        agregar("planilla", p.id, p.fecha_pago, f"Pago de planilla #{p.id}", p.monto_total, "egreso")
    for p in db.query(models.PagoServicio).join(models.CargoServicio).filter(models.CargoServicio.gimnasio_id == gimnasio_id,
        or_(models.PagoServicio.anulada == False, models.PagoServicio.anulada_en > hasta), models.PagoServicio.metodo_pago == "efectivo",
        models.PagoServicio.fecha_pago >= desde, models.PagoServicio.fecha_pago <= hasta).all():
        agregar("servicio", p.id, p.fecha_pago, f"Pago de servicio #{p.id}", p.monto, "egreso")
    for g in db.query(models.Gasto).filter(models.Gasto.gimnasio_id == gimnasio_id, or_(models.Gasto.anulada == False, models.Gasto.anulada_en > hasta),
        models.Gasto.categoria == models.CategoriaGasto.OTROS, models.Gasto.metodo_pago == "efectivo",
        models.Gasto.fecha >= desde, models.Gasto.fecha <= hasta).all():
        agregar("gasto", g.id, g.fecha, g.descripcion or "Gasto general", g.monto, "egreso")
    for a in db.query(models.AjusteCaja).filter(
        models.AjusteCaja.gimnasio_id == gimnasio_id,
        models.AjusteCaja.fecha >= desde,
        models.AjusteCaja.fecha <= hasta,
    ).all():
        referencia = f" ({a.referencia})" if a.referencia else ""
        agregar("ajuste", a.id, a.fecha, f"Ajuste: {a.motivo}{referencia}", a.monto, a.tipo)

    ingresos = sum((_dinero(m["monto"]) for m in movimientos if m["direccion"] == "ingreso"), Decimal("0"))
    egresos = sum((_dinero(m["monto"]) for m in movimientos if m["direccion"] == "egreso"), Decimal("0"))
    movimientos.sort(key=lambda m: m["fecha"], reverse=True)
    return {"ingresos_efectivo": float(ingresos), "egresos_efectivo": float(egresos), "movimientos": movimientos}


def _resumen_turno_caja(db: Session, turno: models.TurnoCaja, hasta: Optional[datetime] = None) -> dict:
    corte = hasta or turno.cerrada_en or ahora_lima()
    conciliacion = _movimientos_caja(db, turno.gimnasio_id, turno.abierta_en, corte)
    esperado = _dinero(turno.monto_apertura) + _dinero(conciliacion["ingresos_efectivo"]) - _dinero(conciliacion["egresos_efectivo"])
    if turno.estado == "cerrada":
        conciliacion["ingresos_efectivo"] = float(turno.ingresos_efectivo or 0)
        conciliacion["egresos_efectivo"] = float(turno.egresos_efectivo or 0)
    return {"id": turno.id, "estado": turno.estado, "abierta_en": turno.abierta_en.isoformat(),
            "cerrada_en": turno.cerrada_en.isoformat() if turno.cerrada_en else None,
            "monto_apertura": float(turno.monto_apertura), "monto_esperado": float(turno.monto_esperado if turno.monto_esperado is not None else esperado),
            "monto_contado": float(turno.monto_contado) if turno.monto_contado is not None else None,
            "diferencia": float(turno.diferencia) if turno.diferencia is not None else None,
            "nota_apertura": turno.nota_apertura, "nota_cierre": turno.nota_cierre, **conciliacion}


@app.get("/caja/actual", tags=["Caja"])
def caja_actual(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    turno = q(db, models.TurnoCaja, usuario).filter(models.TurnoCaja.estado == "abierta").first()
    return _resumen_turno_caja(db, turno) if turno else {"estado": "sin_apertura"}


@app.post("/caja/abrir", tags=["Caja"])
def abrir_caja(datos: schemas.AperturaCajaRequest, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario, "caja-abrir", idempotency_key, payload, models.TurnoCaja)
    if previo: return _resumen_turno_caja(db, previo)
    gid = get_gid(usuario)
    if q(db, models.TurnoCaja, usuario).filter(models.TurnoCaja.estado == "abierta").first():
        raise HTTPException(status_code=409, detail="Ya existe una caja abierta para este gimnasio")
    turno = models.TurnoCaja(gimnasio_id=gid, clave_abierta=f"gym:{gid}", abierta_por_id=usuario.id,
                             monto_apertura=_dinero(datos.monto_apertura), nota_apertura=datos.nota)
    db.add(turno); db.flush()
    _guardar_idempotencia(db, usuario, "caja-abrir", idempotency_key, payload, "TurnoCaja", turno.id)
    db.commit(); db.refresh(turno)
    return _resumen_turno_caja(db, turno)


@app.post("/caja/cerrar", tags=["Caja"])
def cerrar_caja(datos: schemas.CierreCajaRequest, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario, "caja-cerrar", idempotency_key, payload, models.TurnoCaja)
    if previo: return _resumen_turno_caja(db, previo, previo.cerrada_en)
    turno = q(db, models.TurnoCaja, usuario).filter(models.TurnoCaja.estado == "abierta").with_for_update().first()
    if not turno: raise HTTPException(status_code=409, detail="No hay una caja abierta")
    cierre = ahora_lima(); conciliacion = _movimientos_caja(db, get_gid(usuario), turno.abierta_en, cierre)
    esperado = _dinero(turno.monto_apertura) + _dinero(conciliacion["ingresos_efectivo"]) - _dinero(conciliacion["egresos_efectivo"])
    contado = _dinero(datos.monto_contado); diferencia = contado - esperado
    if abs(diferencia) > Decimal("0.01") and not (datos.nota or "").strip():
        raise HTTPException(status_code=400, detail="Explica la diferencia antes de cerrar la caja")
    turno.estado = "cerrada"; turno.clave_abierta = None; turno.cerrada_en = cierre; turno.cerrada_por_id = usuario.id
    turno.ingresos_efectivo = _dinero(conciliacion["ingresos_efectivo"]); turno.egresos_efectivo = _dinero(conciliacion["egresos_efectivo"])
    turno.monto_esperado = esperado; turno.monto_contado = contado; turno.diferencia = diferencia; turno.nota_cierre = datos.nota
    db.flush(); _guardar_idempotencia(db, usuario, "caja-cerrar", idempotency_key, payload, "TurnoCaja", turno.id)
    db.commit(); db.refresh(turno)
    return _resumen_turno_caja(db, turno, cierre)


@app.post("/caja/ajustes", tags=["Caja"])
def crear_ajuste_caja(datos: schemas.AjusteCajaCreate, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    """Registra una correccion visible en el turno actual; nunca cambia una caja cerrada."""
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario, "caja-ajuste", idempotency_key, payload, models.AjusteCaja)
    if previo:
        return {"id": previo.id, "message": "Ajuste ya registrado"}
    turno = q(db, models.TurnoCaja, usuario).filter(models.TurnoCaja.estado == "abierta").with_for_update().first()
    if not turno:
        raise HTTPException(status_code=409, detail="Abre la caja antes de registrar un ajuste")
    ajuste = models.AjusteCaja(
        gimnasio_id=get_gid(usuario), turno_id=turno.id, tipo=datos.tipo,
        monto=_dinero(datos.monto), motivo=datos.motivo.strip(),
        referencia=(datos.referencia or "").strip() or None, usuario_id=usuario.id,
    )
    db.add(ajuste); db.flush()
    _guardar_idempotencia(db, usuario, "caja-ajuste", idempotency_key, payload, "AjusteCaja", ajuste.id)
    db.commit(); db.refresh(ajuste)
    return {"id": ajuste.id, "message": "Ajuste registrado"}


@app.get("/caja/historial", tags=["Caja"])
def historial_caja(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    turnos = q(db, models.TurnoCaja, usuario).order_by(models.TurnoCaja.abierta_en.desc()).limit(limit).all()
    return [_resumen_turno_caja(db, t, t.cerrada_en) for t in turnos]


def _fuente_documento(db: Session, usuario: models.Usuario, tipo: Optional[str], fuente_id: Optional[int]):
    """Resuelve un movimiento financiero sin permitir referencias entre gimnasios."""
    if not tipo and not fuente_id:
        return None
    if not tipo or not fuente_id:
        raise HTTPException(status_code=400, detail="Indica tipo e ID del movimiento de origen")
    gid = get_gid(usuario)
    if tipo == "venta":
        item = db.query(models.Venta).filter(models.Venta.id == fuente_id, models.Venta.gimnasio_id == gid, models.Venta.anulada == False).first()
        return {"total": item.total, "fecha": item.fecha_venta.date(), "direccion": "ingreso", "descripcion": f"Venta #{item.id}"} if item else None
    if tipo == "pago_membresia":
        item = db.query(models.PagoMembresia).join(models.ClienteMembresia).join(models.Cliente).filter(
            models.PagoMembresia.id == fuente_id, models.Cliente.gimnasio_id == gid, models.PagoMembresia.anulada == False).first()
        return {"total": item.monto, "fecha": item.fecha_pago.date(), "direccion": "ingreso", "descripcion": f"Pago de membresia #{item.id}"} if item else None
    if tipo == "compra":
        item = db.query(models.Compra).filter(models.Compra.id == fuente_id, models.Compra.gimnasio_id == gid, models.Compra.anulada == False).first()
        return {"total": item.costo_total, "fecha": item.fecha.date(), "direccion": "egreso", "descripcion": f"Compra #{item.id}"} if item else None
    if tipo == "gasto":
        item = db.query(models.Gasto).filter(models.Gasto.id == fuente_id, models.Gasto.gimnasio_id == gid, models.Gasto.anulada == False).first()
        return {"total": item.monto, "fecha": item.fecha.date(), "direccion": "egreso", "descripcion": f"Gasto #{item.id}"} if item else None
    if tipo == "pago_servicio":
        item = db.query(models.PagoServicio).join(models.CargoServicio).filter(
            models.PagoServicio.id == fuente_id, models.CargoServicio.gimnasio_id == gid, models.PagoServicio.anulada == False).first()
        return {"total": item.monto, "fecha": item.fecha_pago.date(), "direccion": "egreso", "descripcion": f"Pago de servicio #{item.id}"} if item else None
    if tipo == "pago_planilla":
        item = db.query(models.PagoPlanilla).filter(models.PagoPlanilla.id == fuente_id, models.PagoPlanilla.gimnasio_id == gid, models.PagoPlanilla.anulada == False).first()
        return {"total": item.monto_total, "fecha": item.fecha_pago.date(), "direccion": "egreso", "descripcion": f"Pago de planilla #{item.id}"} if item else None
    if tipo == "otro_ingreso":
        item = db.query(models.OtroIngreso).filter(models.OtroIngreso.id == fuente_id, models.OtroIngreso.gimnasio_id == gid, models.OtroIngreso.anulada == False).first()
        return {"total": item.monto, "fecha": item.fecha.date(), "direccion": "ingreso", "descripcion": f"Otro ingreso #{item.id}"} if item else None
    return None


def _normalizar_documento(datos: dict, fuente: Optional[dict], gimnasio: models.Gimnasio) -> dict:
    if fuente:
        if datos.get("total") is not None and abs(float(datos["total"]) - float(fuente["total"])) > 0.01:
            raise HTTPException(status_code=400, detail=f"El total debe coincidir con el movimiento de origen ({float(fuente['total']):.2f})")
        datos["total"] = float(fuente["total"])
        datos["direccion"] = fuente["direccion"]
        datos["fecha_emision"] = datos.get("fecha_emision") or fuente["fecha"]
        datos["descripcion_fuente"] = fuente["descripcion"]
    if datos.get("total") is None:
        raise HTTPException(status_code=400, detail="Indica el total o vincula un movimiento de origen")
    total = _dinero(datos["total"]); igv = _dinero(datos.get("igv") or 0)
    subtotal = _dinero(datos.get("subtotal") if datos.get("subtotal") is not None else total - igv)
    if igv > total or abs((subtotal + igv) - total) > Decimal("0.01"):
        raise HTTPException(status_code=400, detail="Subtotal + IGV debe ser igual al total")
    datos["total"] = total; datos["igv"] = igv; datos["subtotal"] = subtotal
    datos["serie"] = (datos.get("serie") or "").strip().upper() or None
    for campo in ("emisor_documento", "emisor_nombre", "receptor_documento", "receptor_nombre", "notas"):
        if campo in datos:
            datos[campo] = (datos.get(campo) or "").strip() or None
    if datos["direccion"] == "ingreso":
        datos["emisor_documento"] = datos.get("emisor_documento") or gimnasio.ruc
        datos["emisor_nombre"] = datos.get("emisor_nombre") or gimnasio.razon_social or gimnasio.nombre
    else:
        datos["receptor_documento"] = datos.get("receptor_documento") or gimnasio.ruc
        datos["receptor_nombre"] = datos.get("receptor_nombre") or gimnasio.razon_social or gimnasio.nombre
    return datos


@app.get("/documentos-financieros/", response_model=List[schemas.DocumentoFinancieroOut], tags=["Documentos"])
def listar_documentos_financieros(anio: Optional[int] = None, mes: Optional[int] = Query(None, ge=1, le=12), estado: Optional[str] = None, direccion: Optional[str] = None, limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    query = q(db, models.DocumentoFinanciero, usuario)
    if anio:
        query = query.filter(func.extract("year", models.DocumentoFinanciero.fecha_emision) == anio)
    if mes:
        query = query.filter(func.extract("month", models.DocumentoFinanciero.fecha_emision) == mes)
    if estado:
        query = query.filter(models.DocumentoFinanciero.estado == estado)
    if direccion:
        query = query.filter(models.DocumentoFinanciero.direccion == direccion)
    return query.order_by(models.DocumentoFinanciero.fecha_emision.desc(), models.DocumentoFinanciero.id.desc()).limit(limit).all()


@app.post("/documentos-financieros/", response_model=schemas.DocumentoFinancieroOut, tags=["Documentos"])
def crear_documento_financiero(datos: schemas.DocumentoFinancieroCreate, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario, "documentos-crear", idempotency_key, payload, models.DocumentoFinanciero)
    if previo:
        return previo
    valores = datos.model_dump()
    fuente = _fuente_documento(db, usuario, valores.get("fuente_tipo"), valores.get("fuente_id"))
    if valores.get("fuente_tipo") and not fuente:
        raise HTTPException(status_code=404, detail="Movimiento de origen no encontrado")
    valores = _normalizar_documento(valores, fuente, _configuracion_del_gym(db, usuario))
    documento = models.DocumentoFinanciero(**valores, gimnasio_id=get_gid(usuario), creado_por_id=usuario.id, estado="borrador")
    db.add(documento); db.flush()
    _guardar_idempotencia(db, usuario, "documentos-crear", idempotency_key, payload, "DocumentoFinanciero", documento.id)
    db.commit(); db.refresh(documento)
    return documento


@app.put("/documentos-financieros/{documento_id}", response_model=schemas.DocumentoFinancieroOut, tags=["Documentos"])
def actualizar_documento_financiero(documento_id: int, datos: schemas.DocumentoFinancieroUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    documento = _del_gym(db, models.DocumentoFinanciero, documento_id, usuario)
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if documento.estado != "borrador":
        raise HTTPException(status_code=409, detail="Un documento emitido no se edita; debe anularse y registrarse nuevamente")
    valores = datos.model_dump(exclude_unset=True)
    base = {campo: getattr(documento, campo) for campo in (
        "direccion", "tipo", "serie", "numero", "fecha_emision", "emisor_documento", "emisor_nombre",
        "receptor_documento", "receptor_nombre", "subtotal", "igv", "total", "moneda", "notas")}
    base.update(valores)
    base = _normalizar_documento(base, None, _configuracion_del_gym(db, usuario))
    for campo, valor in base.items():
        setattr(documento, campo, valor)
    db.commit(); db.refresh(documento)
    return documento


_SERIES_DOCUMENTO = {"boleta": "B001", "factura": "F001", "recibo": "R001", "nota_credito": "NC01", "nota_debito": "ND01", "sustento_egreso": "E001", "otro": "D001"}


@app.post("/documentos-financieros/{documento_id}/emitir", response_model=schemas.DocumentoFinancieroOut, tags=["Documentos"])
def emitir_documento_financiero(documento_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == get_gid(usuario)).with_for_update().first()
    documento = _del_gym(db, models.DocumentoFinanciero, documento_id, usuario)
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if documento.estado == "emitido":
        return documento
    if documento.estado == "anulado":
        raise HTTPException(status_code=409, detail="Un documento anulado no puede emitirse")
    if documento.direccion == "ingreso" and documento.tipo in ("boleta", "factura") and not (gimnasio.ruc and gimnasio.razon_social):
        raise HTTPException(status_code=400, detail="Configura RUC y razon social antes de emitir boletas o facturas")
    if documento.direccion == "egreso" and (not documento.serie or documento.numero is None):
        raise HTTPException(status_code=400, detail="En documentos recibidos indica la serie y numero del proveedor")
    if documento.fuente_tipo and documento.fuente_id:
        clave = f"gym:{gimnasio.id}:{documento.fuente_tipo}:{documento.fuente_id}"
        duplicado = db.query(models.DocumentoFinanciero).filter(models.DocumentoFinanciero.clave_fuente_vigente == clave, models.DocumentoFinanciero.id != documento.id).first()
        if duplicado:
            raise HTTPException(status_code=409, detail=f"El movimiento ya tiene el documento #{duplicado.id}")
        documento.clave_fuente_vigente = clave
    documento.serie = (documento.serie or _SERIES_DOCUMENTO[documento.tipo]).upper()
    if documento.direccion == "ingreso":
        correlativo = db.query(models.CorrelativoDocumento).filter_by(gimnasio_id=gimnasio.id, tipo=documento.tipo, serie=documento.serie).with_for_update().first()
        if not correlativo:
            correlativo = models.CorrelativoDocumento(gimnasio_id=gimnasio.id, tipo=documento.tipo, serie=documento.serie, ultimo_numero=0)
            db.add(correlativo); db.flush()
        if documento.numero is None:
            correlativo.ultimo_numero += 1
            documento.numero = correlativo.ultimo_numero
        else:
            correlativo.ultimo_numero = max(correlativo.ultimo_numero, documento.numero)
    repetido = db.query(models.DocumentoFinanciero).filter(
        models.DocumentoFinanciero.gimnasio_id == gimnasio.id, models.DocumentoFinanciero.tipo == documento.tipo,
        models.DocumentoFinanciero.serie == documento.serie, models.DocumentoFinanciero.numero == documento.numero,
        models.DocumentoFinanciero.id != documento.id).first()
    if repetido:
        raise HTTPException(status_code=409, detail="La serie y numero ya estan registrados")
    documento.estado = "emitido"; documento.emitido_en = ahora_lima(); documento.emitido_por_id = usuario.id
    db.commit(); db.refresh(documento)
    return documento


@app.post("/documentos-financieros/{documento_id}/anular", response_model=schemas.DocumentoFinancieroOut, tags=["Documentos"])
def anular_documento_financiero(documento_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    documento = _del_gym(db, models.DocumentoFinanciero, documento_id, usuario)
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if documento.estado == "anulado":
        raise HTTPException(status_code=409, detail="El documento ya fue anulado")
    documento.estado = "anulado"; documento.clave_fuente_vigente = None
    documento.anulado_en = ahora_lima(); documento.anulado_por_id = usuario.id; documento.motivo_anulacion = datos.motivo.strip()
    db.commit(); db.refresh(documento)
    return documento


def _validar_archivo_documento(nombre: str, contenido: bytes) -> tuple[str, str]:
    extension = os.path.splitext(nombre)[1].lower()
    if extension == ".pdf" and contenido.startswith(b"%PDF-"):
        return "application/pdf", extension
    if extension == ".xml" and contenido.lstrip().startswith(b"<"):
        try:
            import xml.etree.ElementTree as ET
            ET.fromstring(contenido)
        except Exception:
            raise HTTPException(status_code=400, detail="El XML no es valido")
        return "application/xml", extension
    if extension in (".jpg", ".jpeg") and contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", extension
    if extension == ".png" and contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", extension
    if extension == ".webp" and contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp", extension
    if extension == ".zip" and contenido.startswith(b"PK\x03\x04"):
        return "application/zip", extension
    raise HTTPException(status_code=400, detail="Adjunta PDF, XML, JPG, PNG, WEBP o ZIP validos")


@app.post("/documentos-financieros/{documento_id}/archivos", response_model=schemas.DocumentoArchivoOut, tags=["Documentos"])
async def adjuntar_archivo_documento(documento_id: int, archivo: UploadFile = File(...), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    documento = _del_gym(db, models.DocumentoFinanciero, documento_id, usuario)
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if len(documento.archivos) >= 5:
        raise HTTPException(status_code=400, detail="Cada documento admite hasta 5 archivos")
    contenido = await archivo.read(5 * 1024 * 1024 + 1)
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo esta vacio")
    if len(contenido) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El archivo supera 5 MB")
    nombre = os.path.basename(archivo.filename or "archivo")[:255]
    tipo_mime, _ = _validar_archivo_documento(nombre, contenido)
    digest = hashlib.sha256(contenido).hexdigest()
    if any(item.sha256 == digest for item in documento.archivos):
        raise HTTPException(status_code=409, detail="Ese archivo ya esta adjunto")
    item = models.DocumentoArchivo(documento_id=documento.id, nombre=nombre, tipo_mime=tipo_mime,
        tamano=len(contenido), sha256=digest, datos=contenido, creado_por_id=usuario.id)
    db.add(item); db.commit(); db.refresh(item)
    return item


@app.get("/documentos-financieros/{documento_id}/archivos/{archivo_id}", tags=["Documentos"])
def descargar_archivo_documento(documento_id: int, archivo_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    item = db.query(models.DocumentoArchivo).join(models.DocumentoFinanciero).filter(
        models.DocumentoArchivo.id == archivo_id, models.DocumentoArchivo.documento_id == documento_id,
        models.DocumentoFinanciero.gimnasio_id == get_gid(usuario)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    extension = os.path.splitext(item.nombre)[1]
    return Response(content=item.datos, media_type=item.tipo_mime,
        headers={"Content-Disposition": f'attachment; filename="documento_{documento_id}_{archivo_id}{extension}"', "X-Content-Type-Options": "nosniff"})


def _claves_fuentes_periodo(db: Session, gimnasio_id: int, desde: datetime, hasta: datetime) -> set[str]:
    claves = set()
    def agregar(tipo, consulta):
        claves.update(f"gym:{gimnasio_id}:{tipo}:{fila[0]}" for fila in consulta.all())
    agregar("venta", db.query(models.Venta.id).filter(models.Venta.gimnasio_id == gimnasio_id, models.Venta.anulada == False, models.Venta.fecha_venta.between(desde, hasta)))
    agregar("pago_membresia", db.query(models.PagoMembresia.id).join(models.ClienteMembresia).join(models.Cliente).filter(models.Cliente.gimnasio_id == gimnasio_id, models.PagoMembresia.anulada == False, models.PagoMembresia.fecha_pago.between(desde, hasta)))
    agregar("compra", db.query(models.Compra.id).filter(models.Compra.gimnasio_id == gimnasio_id, models.Compra.anulada == False, models.Compra.fecha.between(desde, hasta)))
    agregar("gasto", db.query(models.Gasto.id).filter(models.Gasto.gimnasio_id == gimnasio_id, models.Gasto.anulada == False, models.Gasto.fecha.between(desde, hasta)))
    agregar("pago_planilla", db.query(models.PagoPlanilla.id).filter(models.PagoPlanilla.gimnasio_id == gimnasio_id, models.PagoPlanilla.anulada == False, models.PagoPlanilla.fecha_pago.between(desde, hasta)))
    agregar("pago_servicio", db.query(models.PagoServicio.id).join(models.CargoServicio).filter(models.CargoServicio.gimnasio_id == gimnasio_id, models.PagoServicio.anulada == False, models.PagoServicio.fecha_pago.between(desde, hasta)))
    agregar("otro_ingreso", db.query(models.OtroIngreso.id).filter(models.OtroIngreso.gimnasio_id == gimnasio_id, models.OtroIngreso.anulada == False, models.OtroIngreso.fecha.between(desde, hasta)))
    return claves


def _movimientos_documentables_periodo(db: Session, gimnasio_id: int, desde: datetime, hasta: datetime) -> list[dict]:
    movimientos = []
    def agregar(tipo, item_id, fecha, direccion, descripcion, total):
        movimientos.append({"clave": f"gym:{gimnasio_id}:{tipo}:{item_id}", "fuente_tipo": tipo, "fuente_id": item_id,
            "fecha": fecha.date().isoformat(), "direccion": direccion, "descripcion": descripcion, "total": float(_dinero(total))})
    for item in db.query(models.Venta).filter(models.Venta.gimnasio_id == gimnasio_id, models.Venta.anulada == False, models.Venta.fecha_venta.between(desde, hasta)).all():
        agregar("venta", item.id, item.fecha_venta, "ingreso", f"Venta #{item.id}", item.total)
    for item in db.query(models.PagoMembresia).join(models.ClienteMembresia).join(models.Cliente).filter(models.Cliente.gimnasio_id == gimnasio_id, models.PagoMembresia.anulada == False, models.PagoMembresia.fecha_pago.between(desde, hasta)).all():
        agregar("pago_membresia", item.id, item.fecha_pago, "ingreso", f"Pago de membresia #{item.id}", item.monto)
    for item in db.query(models.OtroIngreso).filter(models.OtroIngreso.gimnasio_id == gimnasio_id, models.OtroIngreso.anulada == False, models.OtroIngreso.fecha.between(desde, hasta)).all():
        agregar("otro_ingreso", item.id, item.fecha, "ingreso", f"Otro ingreso #{item.id}", item.monto)
    for item in db.query(models.Compra).filter(models.Compra.gimnasio_id == gimnasio_id, models.Compra.anulada == False, models.Compra.fecha.between(desde, hasta)).all():
        agregar("compra", item.id, item.fecha, "egreso", f"Compra #{item.id}", item.costo_total)
    for item in db.query(models.Gasto).filter(models.Gasto.gimnasio_id == gimnasio_id, models.Gasto.anulada == False, models.Gasto.fecha.between(desde, hasta)).all():
        agregar("gasto", item.id, item.fecha, "egreso", f"Gasto #{item.id}", item.monto)
    for item in db.query(models.PagoPlanilla).filter(models.PagoPlanilla.gimnasio_id == gimnasio_id, models.PagoPlanilla.anulada == False, models.PagoPlanilla.fecha_pago.between(desde, hasta)).all():
        agregar("pago_planilla", item.id, item.fecha_pago, "egreso", f"Pago de planilla #{item.id}", item.monto_total)
    for item in db.query(models.PagoServicio).join(models.CargoServicio).filter(models.CargoServicio.gimnasio_id == gimnasio_id, models.PagoServicio.anulada == False, models.PagoServicio.fecha_pago.between(desde, hasta)).all():
        agregar("pago_servicio", item.id, item.fecha_pago, "egreso", f"Pago de servicio #{item.id}", item.monto)
    return sorted(movimientos, key=lambda item: (item["fecha"], item["fuente_tipo"], item["fuente_id"]), reverse=True)


@app.get("/documentos-financieros/pendientes/{anio}/{mes}", tags=["Documentos"])
def movimientos_pendientes_documento(anio: int, mes: int = Path(..., ge=1, le=12), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    desde_fecha = date(anio, mes, 1); hasta_fecha = date(anio, mes, calendar.monthrange(anio, mes)[1])
    movimientos = _movimientos_documentables_periodo(db, get_gid(usuario), datetime.combine(desde_fecha, datetime.min.time()), datetime.combine(hasta_fecha, datetime.max.time()))
    documentadas = {fila[0] for fila in q(db, models.DocumentoFinanciero, usuario).with_entities(models.DocumentoFinanciero.clave_fuente_vigente).filter(
        models.DocumentoFinanciero.estado == "emitido", models.DocumentoFinanciero.clave_fuente_vigente.isnot(None)).all()}
    return [item for item in movimientos if item["clave"] not in documentadas]


@app.get("/documentos-financieros/exportar/{anio}/{mes}", tags=["Documentos"])
def exportar_documentos_financieros(anio: int, mes: int = Path(..., ge=1, le=12), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    desde_fecha = date(anio, mes, 1); hasta_fecha = date(anio, mes, calendar.monthrange(anio, mes)[1])
    documentos = q(db, models.DocumentoFinanciero, usuario).filter(
        models.DocumentoFinanciero.fecha_emision.between(desde_fecha, hasta_fecha)).order_by(models.DocumentoFinanciero.fecha_emision, models.DocumentoFinanciero.id).all()
    campos = ["id", "fecha", "direccion", "tipo", "serie", "numero", "estado", "emisor_documento", "emisor_nombre",
        "receptor_documento", "receptor_nombre", "subtotal", "igv", "total", "moneda", "fuente", "archivos_sha256", "notas"]
    filas = [{"id": d.id, "fecha": d.fecha_emision.isoformat(), "direccion": d.direccion, "tipo": d.tipo, "serie": d.serie or "",
        "numero": d.numero or "", "estado": d.estado, "emisor_documento": d.emisor_documento or "", "emisor_nombre": d.emisor_nombre or "",
        "receptor_documento": d.receptor_documento or "", "receptor_nombre": d.receptor_nombre or "", "subtotal": f"{d.subtotal:.2f}",
        "igv": f"{d.igv:.2f}", "total": f"{d.total:.2f}", "moneda": d.moneda,
        "fuente": f"{d.fuente_tipo or ''}#{d.fuente_id or ''}", "archivos_sha256": "|".join(a.sha256 for a in d.archivos), "notas": d.notas or ""} for d in documentos]
    return _respuesta_csv(campos, filas, f"documentos_{anio}_{mes:02d}.csv")


@app.get("/documentos-financieros/resumen/{anio}/{mes}", tags=["Documentos"])
def resumen_documentos_financieros(anio: int, mes: int = Path(..., ge=1, le=12), db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    desde_fecha = date(anio, mes, 1)
    ultimo = calendar.monthrange(anio, mes)[1]
    hasta_fecha = date(anio, mes, ultimo)
    documentos = q(db, models.DocumentoFinanciero, usuario).filter(
        models.DocumentoFinanciero.estado == "emitido", models.DocumentoFinanciero.fecha_emision.between(desde_fecha, hasta_fecha)).all()
    totales = {"ingresos_base": Decimal("0"), "ingresos_igv": Decimal("0"), "ingresos_total": Decimal("0"),
        "egresos_base": Decimal("0"), "egresos_igv": Decimal("0"), "egresos_total": Decimal("0")}
    for documento in documentos:
        prefijo = "ingresos" if documento.direccion == "ingreso" else "egresos"
        signo = Decimal("-1") if documento.tipo == "nota_credito" else Decimal("1")
        totales[f"{prefijo}_base"] += signo * _dinero(documento.subtotal)
        totales[f"{prefijo}_igv"] += signo * _dinero(documento.igv)
        totales[f"{prefijo}_total"] += signo * _dinero(documento.total)
    desde_dt = datetime.combine(desde_fecha, datetime.min.time()); hasta_dt = datetime.combine(hasta_fecha, datetime.max.time())
    fuentes = _claves_fuentes_periodo(db, get_gid(usuario), desde_dt, hasta_dt)
    documentadas = set()
    if fuentes:
        documentadas = {fila[0] for fila in q(db, models.DocumentoFinanciero, usuario).with_entities(models.DocumentoFinanciero.clave_fuente_vigente).filter(
            models.DocumentoFinanciero.estado == "emitido", models.DocumentoFinanciero.clave_fuente_vigente.in_(fuentes)).all()}
    respuesta = {clave: float(_dinero(valor)) for clave, valor in totales.items()}
    respuesta.update({"igv_referencial": float(max(totales["ingresos_igv"] - totales["egresos_igv"], Decimal("0"))),
        "documentos_emitidos": len(documentos), "movimientos_financieros": len(fuentes),
        "movimientos_documentados": len(fuentes & documentadas), "movimientos_pendientes": len(fuentes - documentadas),
        "referencial": True})
    return respuesta


@app.get("/dashboard/stats", response_model=schemas.DashboardStats, tags=["Dashboard"])
def get_dashboard_stats(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gid = get_gid(usuario)
    _cerrar_asistencias_vencidas(db, gid)
    total_clientes = db.query(models.Cliente).filter(
        models.Cliente.activo == True,
        models.Cliente.gimnasio_id == gid,
    ).count()

    membresias_activas = (
        db.query(models.ClienteMembresia)
        .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
        .filter(
            models.ClienteMembresia.activo == True,
            models.Cliente.gimnasio_id == gid,
        )
        .count()
    )

    inicio_mes = hoy_lima().replace(day=1)
    libro_mes = listar_ingresos(desde=inicio_mes, hasta=hoy_lima(), db=db, usuario=usuario)
    ingresos_mes = libro_mes["total"]

    productos_bajo_stock = (
        db.query(models.Producto)
        .filter(
            models.Producto.stock <= models.Producto.stock_minimo,
            models.Producto.activo == True,
            models.Producto.gimnasio_id == gid,
        )
        .count()
    )

    hoy = ahora_lima().replace(hour=0, minute=0, second=0, microsecond=0)
    asistencias_hoy_query = db.query(models.Asistencia).filter(
        models.Asistencia.fecha_hora_entrada >= hoy,
        models.Asistencia.gimnasio_id == gid,
    )
    asistencias_hoy = asistencias_hoy_query.count()
    presentes_ahora = asistencias_hoy_query.filter(models.Asistencia.fecha_hora_salida.is_(None)).count()

    config = _configuracion_del_gym(db, usuario)
    limite_aviso = hoy_lima() + timedelta(days=config.dias_aviso_vencimiento or 7)
    membresias_por_vencer = (
        db.query(models.ClienteMembresia)
        .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
        .filter(
            models.ClienteMembresia.activo == True,
            models.ClienteMembresia.fecha_fin.isnot(None),
            models.ClienteMembresia.fecha_fin >= hoy_lima(),
            models.ClienteMembresia.fecha_fin <= limite_aviso,
            models.Cliente.gimnasio_id == gid,
        )
        .count()
    )

    hoy_fecha = hoy_lima()
    clientes_activos = (
        db.query(models.Cliente)
        .join(models.ClienteMembresia, models.ClienteMembresia.cliente_id == models.Cliente.id)
        .filter(
            models.Cliente.activo == True,
            models.Cliente.gimnasio_id == gid,
            models.ClienteMembresia.activo == True,
            (models.ClienteMembresia.fecha_fin.is_(None)) | (models.ClienteMembresia.fecha_fin >= hoy_fecha),
        )
        .distinct()
        .count()
    )

    detalle_hoy = [mov for mov in libro_mes["detalle"] if mov["fecha"][:10] == hoy_fecha.isoformat()]
    ingresos_hoy_membresias = sum(mov["monto"] for mov in detalle_hoy if mov["categoria"] == "membresias")
    ingresos_hoy_venta_rapida = (
        db.query(func.coalesce(func.sum(models.Venta.total), 0.0))
        .filter(
            models.Venta.fecha_venta >= hoy,
            models.Venta.es_venta_rapida == True,
            models.Venta.gimnasio_id == gid,
            models.Venta.anulada == False,
        )
        .scalar()
    )

    balance_efectivo_hoy = sum(mov["monto"] for mov in detalle_hoy if mov["metodo_pago"] == "efectivo")
    balance_cuenta_hoy = sum(
        mov["monto"] - (mov.get("comision_gym") or 0.0)
        for mov in detalle_hoy if mov["metodo_pago"] != "efectivo"
    )

    return schemas.DashboardStats(
        total_clientes=total_clientes,
        membresias_activas=membresias_activas,
        ingresos_mes=ingresos_mes,
        productos_bajo_stock=productos_bajo_stock,
        asistencias_hoy=asistencias_hoy,
        presentes_ahora=presentes_ahora,
        membresias_por_vencer=membresias_por_vencer,
        clientes_activos=clientes_activos,
        ingresos_hoy_membresias=round(ingresos_hoy_membresias, 2),
        ingresos_hoy_venta_rapida=round(ingresos_hoy_venta_rapida, 2),
        balance_efectivo_hoy=round(balance_efectivo_hoy, 2),
        balance_cuenta_hoy=round(balance_cuenta_hoy, 2),
    )


@app.get("/dashboard/empresarial", tags=["Dashboard"])
def get_dashboard_empresarial(
    anio: Optional[int] = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Indicadores anuales reales para el dashboard de gestión."""
    anio = anio or hoy_lima().year
    gid = get_gid(usuario)
    desde_fecha = date(anio, 1, 1)
    hasta_fecha = date(anio + 1, 1, 1)
    desde_dt = datetime(anio, 1, 1)
    hasta_dt = datetime(anio + 1, 1, 1)

    membresias = [0.0] * 12
    productos = [0.0] * 12
    otros = [0.0] * 12
    egresos = [0.0] * 12
    altas_clientes = [0] * 12
    accesos = [0] * 12
    membresias_vendidas = [0] * 12
    metas_membresias = [0.0] * 12

    libro_ingresos = listar_ingresos(desde=desde_fecha, hasta=date(anio, 12, 31), db=db, usuario=usuario)
    libro_egresos = listar_egresos(desde=desde_fecha, hasta=date(anio, 12, 31), db=db, usuario=usuario)
    for movimiento in libro_ingresos["detalle"]:
        mes_indice = int(movimiento["fecha"][5:7]) - 1
        if movimiento["categoria"] == "membresias":
            membresias[mes_indice] += float(movimiento["monto"] or 0)
        elif movimiento["categoria"] == "productos":
            productos[mes_indice] += float(movimiento["monto"] or 0)
        else:
            otros[mes_indice] += float(movimiento["monto"] or 0)
    for movimiento in libro_egresos["detalle"]:
        mes_indice = int(movimiento["fecha"][5:7]) - 1
        egresos[mes_indice] += float(movimiento["monto"] or 0)

    for fecha_registro, in db.query(models.Cliente.fecha_registro).filter(
        models.Cliente.gimnasio_id == gid,
        models.Cliente.fecha_registro >= desde_dt,
        models.Cliente.fecha_registro < hasta_dt,
    ).all():
        altas_clientes[fecha_registro.month - 1] += 1

    for fecha_entrada, in db.query(models.Asistencia.fecha_hora_entrada).filter(
        models.Asistencia.gimnasio_id == gid,
        models.Asistencia.fecha_hora_entrada >= desde_dt,
        models.Asistencia.fecha_hora_entrada < hasta_dt,
    ).all():
        accesos[fecha_entrada.month - 1] += 1

    for fecha_inicio, in db.query(models.ClienteMembresia.fecha_inicio).join(
        models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id,
    ).filter(
        models.Cliente.gimnasio_id == gid,
        models.ClienteMembresia.anulada == False,
        models.ClienteMembresia.fecha_inicio >= desde_fecha,
        models.ClienteMembresia.fecha_inicio < hasta_fecha,
    ).all():
        membresias_vendidas[fecha_inicio.month - 1] += 1

    for mes, meta in db.query(models.MetaMensual.mes, models.MetaMensual.meta_membresias).filter(
        models.MetaMensual.gimnasio_id == gid,
        models.MetaMensual.anio == anio,
    ).all():
        if 1 <= mes <= 12:
            metas_membresias[mes - 1] = round(float(meta or 0), 2)

    clientes_activos = db.query(func.count(models.Cliente.id)).filter(
        models.Cliente.gimnasio_id == gid,
        models.Cliente.activo == True,
    ).scalar() or 0
    clientes_con_membresia = len(db.query(models.ClienteMembresia.cliente_id).join(
        models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id,
    ).filter(
        models.Cliente.gimnasio_id == gid,
        models.Cliente.activo == True,
        models.ClienteMembresia.activo == True,
        (models.ClienteMembresia.fecha_fin.is_(None)) | (models.ClienteMembresia.fecha_fin >= hoy_lima()),
    ).distinct().all())

    ingresos = [round(membresias[i] + productos[i] + otros[i], 2) for i in range(12)]
    egresos = [round(valor, 2) for valor in egresos]
    moneda = db.query(models.Gimnasio.moneda).filter(models.Gimnasio.id == gid).scalar() or "S/"
    return {
        "anio": anio,
        "moneda": moneda,
        "ingresos": ingresos,
        "egresos": egresos,
        "balance": [round(ingresos[i] - egresos[i], 2) for i in range(12)],
        "ingresos_membresias": [round(v, 2) for v in membresias],
        "ingresos_productos": [round(v, 2) for v in productos],
        "otros_ingresos": [round(v, 2) for v in otros],
        "altas_clientes": altas_clientes,
        "accesos": accesos,
        "membresias_vendidas": membresias_vendidas,
        "metas_membresias": metas_membresias,
        "clientes_activos": clientes_activos,
        "clientes_con_membresia": clientes_con_membresia,
        "clientes_sin_membresia": max(clientes_activos - clientes_con_membresia, 0),
        "total_ingresos": round(sum(ingresos), 2),
        "total_egresos": round(sum(egresos), 2),
        "total_balance": round(sum(ingresos) - sum(egresos), 2),
        "total_accesos": sum(accesos),
    }


# ==================================================================
# CLIENTES
# ==================================================================

@app.get("/clientes/listado-completo", response_model=List[schemas.ClienteListadoRow], tags=["Clientes"])
def listado_completo_clientes(
    filtro: str = Query("activos", description="todos | activos | por_vencer"),
    dias_vencimiento: int = Query(30, description="Solo aplica si filtro=por_vencer"),
    desde: Optional[date] = Query(None, description="Filtra por fecha_registro >= desde"),
    hasta: Optional[date] = Query(None, description="Filtra por fecha_registro <= hasta"),
    orden: Optional[str] = Query(None, description="vencer ordena por dias restantes ascendente"),
    buscar: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _=Depends(auth.requiere_staff_o_profesor),
):
    hoy = hoy_lima()
    query = db.query(models.Cliente).filter(models.Cliente.gimnasio_id == get_gid(_))

    if filtro == "activos":
        # "Activos" = clientes con una ClienteMembresia VIGENTE del
        # catalogo (no basta el membresia_texto importado del sistema
        # anterior). Se usa un JOIN para exigir una fila real en
        # ClienteMembresia con fecha_fin >= hoy.
        query = (
            query.join(models.ClienteMembresia, models.ClienteMembresia.cliente_id == models.Cliente.id)
            .filter(
                models.Cliente.activo == True,
                models.ClienteMembresia.activo == True,
                models.ClienteMembresia.fecha_fin.isnot(None),
                models.ClienteMembresia.fecha_fin >= hoy,
            )
            .distinct()
        )
    elif filtro == "por_vencer":
        limite = hoy + timedelta(days=max(dias_vencimiento, 0))
        query = (
            query.join(models.ClienteMembresia, models.ClienteMembresia.cliente_id == models.Cliente.id)
            .filter(
                models.Cliente.activo == True,
                models.ClienteMembresia.activo == True,
                models.ClienteMembresia.fecha_fin.isnot(None),
                models.ClienteMembresia.fecha_fin >= hoy,
                models.ClienteMembresia.fecha_fin <= limite,
            )
            .distinct()
        )

    if desde:
        query = query.filter(func.date(models.Cliente.fecha_registro) >= desde.isoformat())
    if hasta:
        query = query.filter(func.date(models.Cliente.fecha_registro) <= hasta.isoformat())

    if buscar:
        for palabra in buscar.split():
            like = f"%{palabra}%"
            query = query.filter(
                (models.Cliente.nombre.ilike(like))
                | (models.Cliente.apellidos.ilike(like))
                | (models.Cliente.dni.ilike(like))
            )

    clientes = query.order_by(models.Cliente.nombre).all()

    filas: List[schemas.ClienteListadoRow] = []
    for c in clientes:
        ultimo_plan_cm = (
            db.query(models.ClienteMembresia)
            .filter(models.ClienteMembresia.cliente_id == c.id)
            .order_by(models.ClienteMembresia.fecha_inicio.desc(), models.ClienteMembresia.id.desc())
            .first()
        )
        ultimo_plan_nombre, costo, pagado, saldo, dias_para_vencer = None, None, None, None, None
        if ultimo_plan_cm:
            membresia = db.query(models.Membresia).filter(models.Membresia.id == ultimo_plan_cm.membresia_id).first()
            ultimo_plan_nombre = membresia.nombre if membresia else None
            costo = membresia.precio if membresia else None
            pagado = _total_pagado_membresia(db, ultimo_plan_cm.id)
            saldo = max((costo or 0.0) - pagado, 0.0)
            if ultimo_plan_cm.fecha_fin:
                dias_para_vencer = (ultimo_plan_cm.fecha_fin - hoy).days

        # Determinar si tiene membresia del catalogo vigente
        tiene_cm_vigente = bool(
            ultimo_plan_cm and ultimo_plan_cm.fecha_fin and ultimo_plan_cm.fecha_fin >= hoy
        )

        filas.append(schemas.ClienteListadoRow(
            id=c.id,
            nombre_completo=f"{c.nombre} {c.apellidos or ''}".strip(),
            activo=c.activo,
            fecha_vencimiento=ultimo_plan_cm.fecha_fin if ultimo_plan_cm else c.fecha_vencimiento,
            dias_para_vencer=dias_para_vencer if ultimo_plan_cm else (
                (c.fecha_vencimiento - hoy).days if c.fecha_vencimiento else None
            ),
            ultimo_plan=ultimo_plan_nombre if ultimo_plan_cm else c.membresia_texto,
            costo=costo,
            pagado=pagado,
            saldo=saldo,
            porcentaje_asistencia=_calcular_porcentaje_asistencia(db, c.id),
            tiene_membresia_catalogo=tiene_cm_vigente,
            fecha_pago_saldo=ultimo_plan_cm.fecha_pago_saldo if ultimo_plan_cm else None,
            ultimo_cm_id=ultimo_plan_cm.id if ultimo_plan_cm else None,
        ))

    if orden == "vencer":
        filas.sort(key=lambda f: (f.dias_para_vencer is None, f.dias_para_vencer))
    elif orden == "deuda":
        filas.sort(key=lambda f: (f.saldo or 0.0), reverse=True)

    return filas


@app.get("/clientes/", response_model=List[schemas.ClienteListItem], tags=["Clientes"])
def listar_clientes(
    skip: int = 0,
    limit: int = 50,
    buscar: Optional[str] = Query(None, description="Busca por nombre, DNI o email"),
    solo_con_membresia_activa: bool = Query(False, description="Filtra solo clientes con una membresia vigente hoy"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Listado paginado y con busqueda server-side. Nunca devuelve
    todo el historico de una vez (importante con 8000 clientes
    historicos).
    """
    query = db.query(models.Cliente).filter(models.Cliente.activo == True, models.Cliente.gimnasio_id == get_gid(usuario))

    if solo_con_membresia_activa:
        hoy = hoy_lima()
        query = (
            query.join(models.ClienteMembresia, models.ClienteMembresia.cliente_id == models.Cliente.id)
            .filter(
                models.ClienteMembresia.activo == True,
                (models.ClienteMembresia.fecha_fin.is_(None)) | (models.ClienteMembresia.fecha_fin >= hoy),
            )
            .distinct()
        )

    if buscar:
        # Busqueda por palabras, independiente del orden: "Ramos Jorge"
        # y "Jorge Ramos" encuentran lo mismo. Cada palabra debe
        # coincidir con nombre, apellidos, dni o email.
        for palabra in buscar.split():
            like = f"%{palabra}%"
            query = query.filter(
                (models.Cliente.nombre.ilike(like))
                | (models.Cliente.apellidos.ilike(like))
                | (models.Cliente.dni.ilike(like))
                | (models.Cliente.email.ilike(like))
            )

    return query.order_by(models.Cliente.nombre).offset(skip).limit(limit).all()


@app.get("/clientes/ultimos-ingresos", response_model=List[schemas.Asistencia], tags=["Clientes"])
def ultimos_clientes_con_ingreso(
    limit: int = 20,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Los ultimos N alumnos que marcaron entrada, pensado para la
    pantalla de Asistencias + Venta Rapida (acceso directo a
    asignarles producto).
    """
    return (
        db.query(models.Asistencia)
        .filter(models.Asistencia.gimnasio_id == get_gid(usuario))
        .order_by(models.Asistencia.fecha_hora_entrada.desc())
        .limit(limit)
        .all()
    )


# ---- Biometria facial (plantillas cifradas, sin fotografias) ----

def _validar_descriptor_facial(descriptor: List[float]):
    if len(descriptor) != 1024 or any(not math.isfinite(float(valor)) for valor in descriptor):
        raise HTTPException(status_code=400, detail="Plantilla facial invalida")
    if any(abs(float(valor)) > 100 for valor in descriptor):
        raise HTTPException(status_code=400, detail="Plantilla facial fuera de rango")


@app.get("/biometria-facial/descriptores", response_model=List[schemas.BiometriaFacialDescriptor], tags=["Asistencias"])
def listar_descriptores_faciales(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    registros = (
        db.query(models.BiometriaFacial, models.Cliente)
        .join(models.Cliente, models.Cliente.id == models.BiometriaFacial.cliente_id)
        .filter(
            models.BiometriaFacial.gimnasio_id == get_gid(usuario),
            models.Cliente.gimnasio_id == get_gid(usuario),
            models.Cliente.activo == True,
        )
        .all()
    )
    respuesta = []
    for biometria, cliente in registros:
        try:
            descriptor = _descifrar_descriptor_facial(biometria.descriptor_cifrado)
        except ValueError:
            logger.exception("Plantilla facial ilegible para cliente %s", cliente.id)
            continue
        respuesta.append({
            "cliente_id": cliente.id,
            "nombre_completo": f"{cliente.nombre} {cliente.apellidos or ''}".strip(),
            "foto_url": cliente.foto_url,
            "descriptor": descriptor,
        })
    return respuesta


@app.get("/clientes/{cliente_id}/biometria-facial", response_model=schemas.BiometriaFacialEstado, tags=["Clientes"])
def estado_biometria_facial(
    cliente_id: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    cliente = db.query(models.Cliente).filter(
        models.Cliente.id == cliente_id,
        models.Cliente.gimnasio_id == get_gid(usuario),
    ).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    registro = db.query(models.BiometriaFacial).filter(
        models.BiometriaFacial.cliente_id == cliente_id,
        models.BiometriaFacial.gimnasio_id == get_gid(usuario),
    ).first()
    return {
        "registrada": bool(registro),
        "consentimiento_en": registro.consentimiento_en if registro else None,
        "actualizado_en": registro.actualizado_en if registro else None,
        "version_modelo": registro.version_modelo if registro else None,
    }


@app.put("/clientes/{cliente_id}/biometria-facial", response_model=schemas.BiometriaFacialEstado, tags=["Clientes"])
def guardar_biometria_facial(
    cliente_id: int,
    datos: schemas.BiometriaFacialGuardar,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    if not datos.consentimiento:
        raise HTTPException(status_code=400, detail="Se requiere el consentimiento expreso del cliente")
    _validar_descriptor_facial(datos.descriptor)
    cliente = db.query(models.Cliente).filter(
        models.Cliente.id == cliente_id,
        models.Cliente.gimnasio_id == get_gid(usuario),
        models.Cliente.activo == True,
    ).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    registro = db.query(models.BiometriaFacial).filter(
        models.BiometriaFacial.cliente_id == cliente_id,
        models.BiometriaFacial.gimnasio_id == get_gid(usuario),
    ).first()
    ahora = ahora_lima()
    if not registro:
        registro = models.BiometriaFacial(
            gimnasio_id=get_gid(usuario),
            cliente_id=cliente_id,
            descriptor_cifrado=_cifrar_descriptor_facial(datos.descriptor),
            version_modelo=datos.version_modelo,
            consentimiento_en=ahora,
            actualizado_en=ahora,
            actualizado_por_id=usuario.id,
        )
        db.add(registro)
    else:
        registro.descriptor_cifrado = _cifrar_descriptor_facial(datos.descriptor)
        registro.version_modelo = datos.version_modelo
        registro.consentimiento_en = ahora
        registro.actualizado_en = ahora
        registro.actualizado_por_id = usuario.id
    db.commit()
    db.refresh(registro)
    return {
        "registrada": True,
        "consentimiento_en": registro.consentimiento_en,
        "actualizado_en": registro.actualizado_en,
        "version_modelo": registro.version_modelo,
    }


@app.delete("/clientes/{cliente_id}/biometria-facial", tags=["Clientes"])
def eliminar_biometria_facial(
    cliente_id: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    registro = db.query(models.BiometriaFacial).filter(
        models.BiometriaFacial.cliente_id == cliente_id,
        models.BiometriaFacial.gimnasio_id == get_gid(usuario),
    ).first()
    if not registro:
        raise HTTPException(status_code=404, detail="El cliente no tiene reconocimiento facial registrado")
    db.delete(registro)
    db.commit()
    return {"message": "Plantilla facial eliminada"}


@app.post("/clientes/", response_model=schemas.Cliente, tags=["Clientes"])
def crear_cliente(cliente: schemas.ClienteCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    _validar_limite_plan(db, usuario, "clientes")
    if cliente.dni and q(db, models.Cliente, usuario).filter(models.Cliente.dni == cliente.dni).first():
        raise HTTPException(status_code=400, detail="Ya existe un cliente con ese DNI en este gimnasio")
    valores = cliente.model_dump()
    valores["codigo_acceso"] = None
    db_cliente = models.Cliente(**valores, gimnasio_id=get_gid(usuario))
    db.add(db_cliente)
    db.commit()
    db.refresh(db_cliente)
    db_cliente.porcentaje_asistencia = None  # recien creado, todavia no tiene plan
    return db_cliente


def _calcular_porcentaje_asistencia(db: Session, cliente_id: int) -> Optional[float]:
    """Porcentaje de asistencia del cliente segun su ultimo plan."""
    ultimo_plan = (
        db.query(models.ClienteMembresia)
        .filter(models.ClienteMembresia.cliente_id == cliente_id, models.ClienteMembresia.anulada == False)
        .order_by(models.ClienteMembresia.fecha_inicio.desc())
        .first()
    )
    if not ultimo_plan or not ultimo_plan.fecha_inicio or not ultimo_plan.fecha_fin:
        return None

    hoy = hoy_lima()
    fecha_limite = min(ultimo_plan.fecha_fin, hoy)
    if fecha_limite < ultimo_plan.fecha_inicio:
        return 0.0

    # Dias transcurridos desde el inicio del plan hasta hoy (o hasta
    # que vencio, si ya vencio). Minimo 1 para evitar division por 0.
    dias_transcurridos = max((fecha_limite - ultimo_plan.fecha_inicio).days, 1)

    dias_asistidos = (
        db.query(func.count(func.distinct(func.date(models.Asistencia.fecha_hora_entrada))))
        .filter(
            models.Asistencia.cliente_id == cliente_id,
            models.Asistencia.fecha_hora_entrada >= datetime.combine(ultimo_plan.fecha_inicio, datetime.min.time()),
            models.Asistencia.fecha_hora_entrada <= datetime.combine(fecha_limite, datetime.max.time()),
        )
        .scalar()
    )
    return round(min((dias_asistidos or 0) / dias_transcurridos * 100, 100.0), 1)


# ---- Importacion directa de clientes ACTIVOS (no historicos) ----
# Columnas esperadas (no sensible a mayusculas ni al orden):
#   ID_Cliente, Nombres, Apellidos, Direccion, DNI, fec_reg, sexo,
#   Celular, email, fec_nac, fec_ren, fec_ven, Membresia, asistencia
# ID_Cliente se inserta como el id REAL del Cliente (no autogenerado).
# Gracias a como SQLite maneja INTEGER PRIMARY KEY, el siguiente
# cliente creado a mano (sin id explicito) continua solo desde el
# ID mas alto que haya en la tabla + 1 - no requiere logica extra.

_COLUMNAS_PLANTILLA_CLIENTES = [
    "id_cliente", "nombres", "apellidos", "direccion", "dni", "fec_reg", "sexo",
    "celular", "correo", "fec_nac", "fec_ren", "fec_ven", "membresia", "asistencia",
]

_FILA_EJEMPLO_PLANTILLA_CLIENTES = {
    "id_cliente": "101",
    "nombres": "Juan Carlos",
    "apellidos": "Perez Garcia",
    "direccion": "Av. Siempre Viva 123",
    "dni": "12345678",
    "fec_reg": "15/03/2024",
    "sexo": "M",
    "celular": "987654321",
    "correo": "juan.perez@email.com",
    "fec_nac": "20/05/1990",
    "fec_ren": "15/03/2024",
    "fec_ven": "15/04/2024",
    "membresia": "Mensual Full",
    "asistencia": "12",
}


def _mapear_sexo_a_genero(valor: Optional[str]) -> Optional[str]:
    """
    Mapea 'M'/'F' a Masculino/Femenino. Si viene un codigo numerico
    (ej. planillas viejas con 0/1/2 sin significado documentado), NO
    se adivina: se guarda el codigo tal cual en Cliente.genero para
    no perder el dato ni asignar un genero incorrecto. El staff puede
    corregirlo manualmente despues desde la ficha del cliente.
    """
    v = (valor or "").strip().upper()
    if v == "M":
        return "Masculino"
    if v == "F":
        return "Femenino"
    return (valor or "").strip() or None


@app.get("/clientes/plantilla-importacion", tags=["Clientes"])
def plantilla_importacion_clientes(_=Depends(auth.requiere_permiso_exportar)):
    """CSV modelo con las columnas exactas que espera POST /clientes/importar."""
    return _respuesta_csv(
        _COLUMNAS_PLANTILLA_CLIENTES,
        [_FILA_EJEMPLO_PLANTILLA_CLIENTES],
        "plantilla_importacion_clientes.csv",
    )


@app.post("/clientes/importar", response_model=schemas.ImportarClientesResultado, tags=["Clientes"])
async def importar_clientes(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(auth.requiere_permiso_exportar),
):
    """
    Importa clientes ACTIVOS directo a la tabla Cliente (distinto de
    /clientes-historicos/importar, que llena ClienteHistorico). Usa
    ID_Cliente como el id real del registro.
    """
    _validar_limite_plan(db, _, "clientes")
    contenido = (await archivo.read()).decode("utf-8-sig", errors="replace")
    lineas = contenido.splitlines()
    if not lineas:
        raise HTTPException(status_code=400, detail="El archivo esta vacio")
    delimitador = _detectar_delimitador(lineas[0])

    lector = csv.DictReader(io.StringIO(contenido), delimiter=delimitador)
    lector.fieldnames = [(c or "").strip().lower() for c in (lector.fieldnames or [])]

    total_leidas = 0
    total_importados = 0
    total_omitidos = 0
    errores: List[str] = []

    ids_existentes = {fila[0] for fila in db.query(models.Cliente.id).all()}
    dnis_existentes = {
        fila[0] for fila in db.query(models.Cliente.dni).filter(
            models.Cliente.gimnasio_id == get_gid(_)
        ).all() if fila[0]
    }
    ids_vistos_en_archivo = set()

    for fila in lector:
        total_leidas += 1
        try:
            id_cliente = _parsear_entero_legado(fila.get("id_cliente"))
            nombres = (fila.get("nombres") or "").strip()
            if not id_cliente or not nombres:
                total_omitidos += 1
                continue
            if id_cliente in ids_existentes or id_cliente in ids_vistos_en_archivo:
                total_omitidos += 1
                continue

            dni = (fila.get("dni") or "").strip() or None
            if dni and dni in dnis_existentes:
                errores.append(f"Fila {total_leidas}: DNI {dni} ya existe, se omitio")
                total_omitidos += 1
                continue

            email_raw = (fila.get("correo") or fila.get("email") or "").strip()
            fecha_reg = _parsear_fecha_legado(fila.get("fec_reg"))

            nuevo = models.Cliente(
                id=id_cliente,
                gimnasio_id=get_gid(_),
                nombre=nombres,
                apellidos=(fila.get("apellidos") or "").strip() or None,
                direccion=(fila.get("direccion") or "").strip() or None,
                dni=dni,
                fecha_registro=datetime.combine(fecha_reg, datetime.min.time()) if fecha_reg else ahora_lima(),
                genero=_mapear_sexo_a_genero(fila.get("sexo")),
                telefono=(fila.get("celular") or "").strip() or None,
                email=email_raw if "@" in email_raw else None,
                fecha_nacimiento=_parsear_fecha_legado(fila.get("fec_nac")),
                fecha_renovacion=_parsear_fecha_legado(fila.get("fec_ren")),
                fecha_vencimiento=_parsear_fecha_legado(fila.get("fec_ven")),
                membresia_texto=(fila.get("membresia") or "").strip() or None,
                asistencias_legado=_parsear_entero_legado(fila.get("asistencia")) or 0,
            )
            db.add(nuevo)
            ids_vistos_en_archivo.add(id_cliente)
            if dni:
                dnis_existentes.add(dni)
            total_importados += 1
        except Exception as e:
            errores.append(f"Fila {total_leidas}: {e}")

    db.commit()
    return schemas.ImportarClientesResultado(
        total_filas_leidas=total_leidas,
        total_importados=total_importados,
        total_omitidos_duplicados=total_omitidos,
        errores=errores[:20],
    )


@app.get("/clientes/{cliente_id}", response_model=schemas.Cliente, tags=["Clientes"])
def obtener_cliente(cliente_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.gimnasio_id == get_gid(usuario)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.porcentaje_asistencia = _calcular_porcentaje_asistencia(db, cliente_id)
    return cliente


@app.put("/clientes/{cliente_id}", response_model=schemas.Cliente, tags=["Clientes"])
def actualizar_cliente(
    cliente_id: int,
    datos: schemas.ClienteUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.gimnasio_id == get_gid(usuario)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    datos_dict = datos.model_dump(exclude_unset=True)
    if datos_dict.get("dni"):
        duplicado = q(db, models.Cliente, usuario).filter(
            models.Cliente.dni == datos_dict["dni"],
            models.Cliente.id != cliente_id,
        ).first()
        if duplicado:
            raise HTTPException(status_code=400, detail="Ya existe un cliente con ese DNI en este gimnasio")
    for campo, valor in datos_dict.items():
        if campo == "foto_url" and valor is None:
            continue
        setattr(cliente, campo, valor)

    db.commit()
    db.refresh(cliente)
    return cliente


@app.post("/clientes/{cliente_id}/reset-password", tags=["Clientes"])
def reset_password_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    cliente = q(db, models.Cliente, usuario).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.codigo_acceso = None
    db.commit()
    return {"message": "El alumno deberá crear una nueva contraseña al ingresar"}


@app.delete("/clientes/{cliente_id}", tags=["Clientes"])
def eliminar_cliente(cliente_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.gimnasio_id == get_gid(usuario)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.activo = False  # soft delete: no se borra el historico
    db.commit()
    return {"message": "Cliente desactivado correctamente"}


@app.get("/clientes/{cliente_id}/foto-contenido", tags=["Clientes"])
def contenido_foto_cliente(cliente_id: int, token: str = Query(..., min_length=24), db: Session = Depends(get_db)):
    """Sirve una foto únicamente mediante su URL opaca entregada al usuario autorizado."""
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.activo == True).first()
    if not cliente or not cliente.foto_datos:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    esperado = parse_qs(urlparse(cliente.foto_url or "").query).get("token", [""])[0]
    if not esperado or not secrets.compare_digest(token, esperado):
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    return Response(
        content=cliente.foto_datos,
        media_type=cliente.foto_tipo or "image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def _guardar_foto_cliente_persistente(db: Session, cliente: models.Cliente, contenido: bytes, content_type: str):
    contenido, content_type = _validar_y_optimizar_foto(contenido, content_type, optimizar=True)
    foto_anterior = cliente.foto_url
    cliente.foto_datos = contenido
    cliente.foto_tipo = content_type
    cliente.foto_url = f"/clientes/{cliente.id}/foto-contenido?token={secrets.token_urlsafe(32)}"
    db.commit()
    db.refresh(cliente)
    _eliminar_foto_anterior(foto_anterior)
    return cliente


def _rotar_tokens_fotos_clientes():
    """Reemplaza enlaces históricos predecibles sin modificar la imagen almacenada."""
    db = SessionLocal()
    try:
        cambiadas = 0
        for cliente in db.query(models.Cliente).filter(models.Cliente.foto_datos.isnot(None)).all():
            token = parse_qs(urlparse(cliente.foto_url or "").query).get("token", [""])[0]
            if len(token) < 24:
                cliente.foto_url = f"/clientes/{cliente.id}/foto-contenido?token={secrets.token_urlsafe(32)}"
                cambiadas += 1
        if cambiadas:
            db.commit()
    finally:
        db.close()


@app.post("/clientes/{cliente_id}/foto", response_model=schemas.Cliente, tags=["Clientes"])
async def subir_foto_cliente(
    cliente_id: int,
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Sube/reemplaza la foto de perfil. Acepta originales de camara
    hasta 20MB y los convierte a WEBP de maximo 960x960.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.gimnasio_id == get_gid(usuario)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    contenido = await foto.read()
    return _guardar_foto_cliente_persistente(db, cliente, contenido, foto.content_type)


# ==================================================================
# REPORTES (Clientes, Ventas, Productos)
# Modulo centralizado de reportes con filtros por entidad: cada uno
# se puede "ver" como tabla (JSON) o "exportar" a CSV con los MISMOS
# filtros aplicados. Requiere el permiso fino puede_exportar (ver
# auth.requiere_permiso_exportar) - no basta con ser staff comun.
# ==================================================================

import enum as _enum_module


def _serializar_valor_reporte(valor):
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, _enum_module.Enum):
        return valor.value
    return valor


def _fila_a_dict_reporte(obj, campos: List[str]) -> dict:
    return {campo: _serializar_valor_reporte(getattr(obj, campo)) for campo in campos}


def _respuesta_csv(campos: List[str], filas: List[dict], nombre_archivo: str) -> StreamingResponse:
    salida = io.StringIO()
    writer = csv.DictWriter(salida, fieldnames=campos)
    writer.writeheader()
    for fila in filas:
        writer.writerow(fila)
    salida.seek(0)
    return StreamingResponse(
        io.BytesIO(salida.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


# ---- Clientes ----

_CAMPOS_CLIENTE_EXPORTABLES = [
    "id", "nombre", "apellidos", "dni", "telefono", "email",
    "genero", "fecha_nacimiento", "direccion",
    "fecha_registro", "fecha_renovacion", "fecha_vencimiento",
    "membresia_texto", "porcentaje_asistencia", "activo",
]


def _query_reporte_clientes(
    db: Session,
    filtro: str,
    desde: Optional[date],
    hasta: Optional[date],
    dias_vencimiento: int,
    gid: Optional[int] = None,
):
    query = db.query(models.Cliente)
    if gid is not None:
        query = query.filter(models.Cliente.gimnasio_id == gid)

    if filtro == "activos":
        query = query.filter(models.Cliente.activo == True)
    elif filtro == "por_vencer":
        hoy = hoy_lima()
        limite = hoy + timedelta(days=max(dias_vencimiento, 0))
        query = (
            query.join(models.ClienteMembresia, models.ClienteMembresia.cliente_id == models.Cliente.id)
            .filter(
                models.Cliente.activo == True,
                models.ClienteMembresia.activo == True,
                models.ClienteMembresia.fecha_fin.isnot(None),
                models.ClienteMembresia.fecha_fin >= hoy,
                models.ClienteMembresia.fecha_fin <= limite,
            )
            .distinct()
        )
    # filtro == "todos": sin filtro de estado

    if desde:
        query = query.filter(func.date(models.Cliente.fecha_registro) >= desde.isoformat())
    if hasta:
        query = query.filter(func.date(models.Cliente.fecha_registro) <= hasta.isoformat())

    return query.order_by(models.Cliente.nombre)


@app.get("/reportes/clientes", tags=["Reportes"])
def reporte_clientes(
    filtro: str = Query("activos", description="todos | activos | por_vencer"),
    desde: Optional[date] = Query(None, description="Filtra por fecha_registro >= desde"),
    hasta: Optional[date] = Query(None, description="Filtra por fecha_registro <= hasta"),
    dias_vencimiento: int = Query(7, description="Solo aplica si filtro=por_vencer"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_exportar),
):
    clientes = _query_reporte_clientes(db, filtro, desde, hasta, dias_vencimiento, gid=get_gid(usuario)).all()
    for c in clientes:
        c.porcentaje_asistencia = _calcular_porcentaje_asistencia(db, c.id)
    return [_fila_a_dict_reporte(c, _CAMPOS_CLIENTE_EXPORTABLES) for c in clientes]


@app.get("/reportes/clientes/exportar", tags=["Reportes"])
def exportar_reporte_clientes(
    filtro: str = Query("activos", description="todos | activos | por_vencer"),
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    dias_vencimiento: int = 7,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_exportar),
):
    clientes = _query_reporte_clientes(db, filtro, desde, hasta, dias_vencimiento, gid=get_gid(usuario)).all()
    for c in clientes:
        c.porcentaje_asistencia = _calcular_porcentaje_asistencia(db, c.id)
    filas = [_fila_a_dict_reporte(c, _CAMPOS_CLIENTE_EXPORTABLES) for c in clientes]
    return _respuesta_csv(_CAMPOS_CLIENTE_EXPORTABLES, filas, "reporte_clientes.csv")


# Mismas columnas que espera /clientes-historicos/importar: sirve de
# "modelo" para que el staff arme su CSV/Excel de origen antes de
# importar clientes antiguos.
_COLUMNAS_PLANTILLA_HISTORICOS = [
    "num_carnet", "apellidos", "fec_reg", "sexo", "estado", "situacion",
    "direccion", "fono1", "fono2", "email", "fec_nac", "edad", "cdistrito",
    "cplan", "fec_sus", "fec_ren", "fec_ven", "tarbases", "distrito", "asistencia",
]

_FILA_EJEMPLO_PLANTILLA_HISTORICOS = {
    "num_carnet": "1024",
    "apellidos": "Perez Garcia, Juan",
    "fec_reg": "15/03/2020",
    "sexo": "1",
    "estado": "1",
    "situacion": "1",
    "direccion": "Av. Siempre Viva 123",
    "fono1": "987654321",
    "fono2": "",
    "email": "juan.perez@email.com",
    "fec_nac": "20/05/1990",
    "edad": "34",
    "cdistrito": "1",
    "cplan": "3",
    "fec_sus": "15/03/2020",
    "fec_ren": "15/03/2024",
    "fec_ven": "15/04/2024",
    "tarbases": "TRIMESTRAL BASICO",
    "distrito": "La Molina",
    "asistencia": "120",
}


@app.get("/reportes/clientes/plantilla-importacion", tags=["Reportes"])
def plantilla_importacion_clientes(_=Depends(auth.requiere_permiso_exportar)):
    """CSV modelo con las columnas exactas que espera /clientes-historicos/importar (mas una fila de ejemplo)."""
    return _respuesta_csv(
        _COLUMNAS_PLANTILLA_HISTORICOS,
        [_FILA_EJEMPLO_PLANTILLA_HISTORICOS],
        "plantilla_importacion_clientes.csv",
    )


# ---- Ventas ----

_CAMPOS_VENTA_EXPORTABLES = [
    "id", "fecha_venta", "cliente_id", "usuario_id", "total",
    "metodo_pago", "es_venta_rapida", "costo_comision_gym", "notas",
]


def _query_reporte_ventas(db: Session, desde: Optional[date], hasta: Optional[date], metodo_pago: Optional[str], gid: Optional[int] = None):
    query = db.query(models.Venta).filter(models.Venta.anulada == False)
    if gid is not None:
        query = query.filter(models.Venta.gimnasio_id == gid)
    if desde:
        query = query.filter(models.Venta.fecha_venta >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        query = query.filter(models.Venta.fecha_venta <= datetime.combine(hasta, datetime.max.time()))
    if metodo_pago:
        query = query.filter(models.Venta.metodo_pago == metodo_pago)
    return query.order_by(models.Venta.fecha_venta.desc())


@app.get("/reportes/ventas", tags=["Reportes"])
def reporte_ventas(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    metodo_pago: Optional[models.MetodoPago] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_exportar),
):
    ventas = _query_reporte_ventas(db, desde, hasta, metodo_pago, gid=get_gid(usuario)).all()
    return [_fila_a_dict_reporte(v, _CAMPOS_VENTA_EXPORTABLES) for v in ventas]


@app.get("/reportes/ventas/exportar", tags=["Reportes"])
def exportar_reporte_ventas(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    metodo_pago: Optional[models.MetodoPago] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_exportar),
):
    ventas = _query_reporte_ventas(db, desde, hasta, metodo_pago, gid=get_gid(usuario)).all()
    filas = [_fila_a_dict_reporte(v, _CAMPOS_VENTA_EXPORTABLES) for v in ventas]
    return _respuesta_csv(_CAMPOS_VENTA_EXPORTABLES, filas, "reporte_ventas.csv")


# ---- Productos ----

_CAMPOS_PRODUCTO_EXPORTABLES = [
    "id", "nombre", "categoria", "precio_compra", "precio_venta",
    "stock", "stock_minimo", "activo", "fecha_creacion",
]


def _query_reporte_productos(db: Session, filtro: str, gid: Optional[int] = None):
    query = db.query(models.Producto)
    if gid is not None:
        query = query.filter(models.Producto.gimnasio_id == gid)
    if filtro == "activos":
        query = query.filter(models.Producto.activo == True)
    elif filtro == "bajo_stock":
        query = query.filter(models.Producto.stock <= models.Producto.stock_minimo, models.Producto.activo == True)
    return query.order_by(models.Producto.nombre)


@app.get("/reportes/productos", tags=["Reportes"])
def reporte_productos(
    filtro: str = Query("activos", description="todos | activos | bajo_stock"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_exportar),
):
    productos = _query_reporte_productos(db, filtro, gid=get_gid(usuario)).all()
    return [_fila_a_dict_reporte(p, _CAMPOS_PRODUCTO_EXPORTABLES) for p in productos]


@app.get("/reportes/productos/exportar", tags=["Reportes"])
def exportar_reporte_productos(
    filtro: str = Query("activos", description="todos | activos | bajo_stock"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_exportar),
):
    productos = _query_reporte_productos(db, filtro, gid=get_gid(usuario)).all()
    filas = [_fila_a_dict_reporte(p, _CAMPOS_PRODUCTO_EXPORTABLES) for p in productos]
    return _respuesta_csv(_CAMPOS_PRODUCTO_EXPORTABLES, filas, "reporte_productos.csv")


@app.post("/reportes/clientes/importar-historicos", response_model=schemas.ImportarClientesHistoricosResultado, tags=["Reportes"])
async def importar_historicos_desde_reportes(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(auth.requiere_permiso_exportar),
):
    """Alias de /clientes-historicos/importar, expuesto tambien bajo /reportes para la pantalla de Reportes."""
    return await importar_clientes_historicos(archivo=archivo, db=db, _=_)


# ==================================================================
# ZONA DE PROFESORES (portal separado, requiere token tipo "profesor")
# ==================================================================

@app.get("/portal-profesor/mi-agenda", response_model=List[schemas.ClaseDictada], tags=["Portal Profesor"])
def mi_agenda_profesor(
    profesor: models.Empleado = Depends(auth.get_profesor_actual),
    db: Session = Depends(get_db),
):
    """Las clases propias del profesor, de hoy en adelante."""
    hoy = hoy_lima()
    return (
        db.query(models.ClaseDictada)
        .filter(
            models.ClaseDictada.profesor_id == profesor.id,
            models.ClaseDictada.gimnasio_id == profesor.gimnasio_id,
            models.ClaseDictada.fecha >= hoy,
        )
        .order_by(models.ClaseDictada.fecha, models.ClaseDictada.hora_inicio)
        .all()
    )


@app.get("/portal-profesor/otros-profesores", response_model=List[schemas.ProfesorMinimo], tags=["Portal Profesor"])
def otros_profesores(
    profesor: models.Empleado = Depends(auth.get_profesor_actual),
    db: Session = Depends(get_db),
):
    """Lista de profesores de sala activos (excepto el mismo), para elegir un reemplazo puntual."""
    return (
        db.query(models.Empleado)
        .filter(
            models.Empleado.tipo == models.TipoEmpleado.PROFESOR_DE_SALA,
            models.Empleado.activo == True,
            models.Empleado.id != profesor.id,
            models.Empleado.gimnasio_id == profesor.gimnasio_id,
        )
        .order_by(models.Empleado.nombre_completo)
        .all()
    )


@app.put("/portal-profesor/clases/{clase_id}/reemplazo", response_model=schemas.ClaseDictada, tags=["Portal Profesor"])
def asignar_reemplazo_desde_portal(
    clase_id: int,
    datos: schemas.ReemplazoRequest,
    profesor: models.Empleado = Depends(auth.get_profesor_actual),
    db: Session = Depends(get_db),
):
    """
    Permite que el propio profesor asigne (o quite) un reemplazo
    para una fecha puntual de SU clase (ej. si va a faltar). Solo
    puede hacerlo sobre clases donde el es el titular o el actual
    reemplazo (no sobre clases de otros profesores).
    """
    clase = db.query(models.ClaseDictada).filter(
        models.ClaseDictada.id == clase_id,
        models.ClaseDictada.gimnasio_id == profesor.gimnasio_id,
    ).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    if clase.profesor_id != profesor.id and clase.profesor_reemplazo_id != profesor.id:
        raise HTTPException(status_code=403, detail="Solo puedes modificar tus propias clases")
    if datos.profesor_reemplazo_id:
        reemplazo = db.query(models.Empleado).filter(
            models.Empleado.id == datos.profesor_reemplazo_id,
            models.Empleado.gimnasio_id == profesor.gimnasio_id,
        ).first()
        if not reemplazo or reemplazo.tipo != models.TipoEmpleado.PROFESOR_DE_SALA or not reemplazo.activo:
            raise HTTPException(status_code=400, detail="El reemplazo debe ser un profesor de sala activo")
    clase.profesor_reemplazo_id = datos.profesor_reemplazo_id
    db.commit()
    db.refresh(clase)
    return clase


@app.get("/portal-profesor/ocupado", response_model=List[schemas.ClaseOcupada], tags=["Portal Profesor"])
def ocupado_salas(
    dias: int = 7,
    profesor: models.Empleado = Depends(auth.get_profesor_actual),
    db: Session = Depends(get_db),
):
    """
    Calendario de ocupacion de TODAS las salas/clases (de cualquier
    profesor) en los proximos N dias, para que un profesor sepa que
    horarios/salas ya estan tomados antes de coordinar los suyos.
    """
    hoy = hoy_lima()
    limite = hoy + timedelta(days=dias)
    filas = (
        db.query(models.ClaseDictada)
        .filter(
            models.ClaseDictada.gimnasio_id == profesor.gimnasio_id,
            models.ClaseDictada.fecha >= hoy,
            models.ClaseDictada.fecha <= limite,
        )
        .order_by(models.ClaseDictada.fecha, models.ClaseDictada.hora_inicio)
        .all()
    )
    resultado = [
        schemas.ClaseOcupada(
            fecha=clase.fecha,
            hora_inicio=clase.hora_inicio,
            hora_fin=clase.hora_fin,
            sala=clase.sala,
            nombre_clase=clase.nombre_clase,
            nombre_profesor=clase.profesor.nombre_completo if clase.profesor else "—",
            nombre_profesor_reemplazo=clase.profesor_reemplazo.nombre_completo if clase.profesor_reemplazo else None,
        )
        for clase in filas
    ]
    reservas = db.query(models.ReservaSala).filter(
        models.ReservaSala.gimnasio_id == profesor.gimnasio_id,
        models.ReservaSala.fecha >= hoy,
        models.ReservaSala.fecha <= limite,
    ).all()
    resultado.extend(schemas.ClaseOcupada(
        fecha=r.fecha,
        hora_inicio=r.hora_inicio,
        hora_fin=r.hora_fin,
        sala=r.sala,
        nombre_clase=r.nombre_reserva,
        nombre_profesor="Sala alquilada",
    ) for r in reservas)
    return sorted(resultado, key=lambda x: (x.fecha, x.hora_inicio))


# ==================================================================
# CLIENTES ANTIGUOS / HISTORICOS (importacion + reingreso)
# ==================================================================

def _parsear_fecha_legado(texto: Optional[str]):
    texto = (texto or "").strip()
    if not texto or texto.replace(" ", "").replace("-", "") == "":
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _parsear_entero_legado(texto: Optional[str]):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return int(float(texto))
    except ValueError:
        return None


@app.get("/clientes-historicos/", response_model=List[schemas.ClienteHistoricoItem], tags=["Clientes Historicos"])
def buscar_clientes_historicos(
    buscar: str = Query(..., min_length=2, description="Busca por nombre, telefono o email"),
    incluir_migrados: bool = False,
    limit: int = 15,
    db: Session = Depends(get_db),
    _=Depends(auth.requiere_staff_o_profesor),
):
    """
    Busca en la base historica de clientes antiguos (puede tener
    miles de filas), usada por la intencion 'Reingreso de cliente
    antiguo' del Panel Principal. Exige al menos 2 caracteres para
    evitar escanear toda la tabla sin filtro.
    """
    # Busqueda por palabras, independiente del orden (los historicos
    # guardan "Apellidos, Nombres" y el staff suele buscar al reves).
    query = q(db, models.ClienteHistorico, _)
    for palabra in buscar.split():
        like = f"%{palabra}%"
        query = query.filter(
            (models.ClienteHistorico.nombre_completo.ilike(like))
            | (models.ClienteHistorico.telefono1.ilike(like))
            | (models.ClienteHistorico.telefono2.ilike(like))
            | (models.ClienteHistorico.email.ilike(like))
        )
    if not incluir_migrados:
        query = query.filter(models.ClienteHistorico.migrado == False)
    return query.order_by(models.ClienteHistorico.nombre_completo).limit(limit).all()


@app.post("/clientes-historicos/importar", response_model=schemas.ImportarClientesHistoricosResultado, tags=["Clientes Historicos"])
async def importar_clientes_historicos(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(auth.requiere_permiso_exportar),
):
    """
    Importa clientes antiguos desde un CSV/TSV exportado de un
    sistema anterior. Columnas esperadas en el encabezado (no
    sensible a mayusculas): num_carnet, apellidos, fec_reg, sexo,
    estado, situacion, direccion, fono1, fono2, email, fec_nac,
    edad, cdistrito, cplan, fec_sus, fec_ren, fec_ven, tarbases,
    distrito, asistencia. Detecta automaticamente si el separador es
    tabulacion o coma. Si un num_carnet ya existe, la fila se omite
    (evita duplicar en reimportaciones).
    """
    contenido = (await archivo.read()).decode("utf-8-sig", errors="replace")
    lineas = contenido.splitlines()
    if not lineas:
        raise HTTPException(status_code=400, detail="El archivo esta vacio")
    delimitador = _detectar_delimitador(lineas[0])

    lector = csv.DictReader(io.StringIO(contenido), delimiter=delimitador)
    lector.fieldnames = [(c or "").strip().lower() for c in (lector.fieldnames or [])]

    total_leidas = 0
    total_importados = 0
    total_omitidos = 0
    errores: List[str] = []

    carnets_existentes = {
        fila[0] for fila in db.query(models.ClienteHistorico.num_carnet).filter(
            models.ClienteHistorico.gimnasio_id == get_gid(_)
        ).all() if fila[0] is not None
    }

    for fila in lector:
        total_leidas += 1
        try:
            nombre_raw = (fila.get("apellidos") or "").strip()
            if not nombre_raw:
                total_omitidos += 1
                continue

            num_carnet = _parsear_entero_legado(fila.get("num_carnet"))
            if num_carnet is not None and num_carnet in carnets_existentes:
                total_omitidos += 1
                continue

            apellidos, nombres = None, None
            if "," in nombre_raw:
                partes = nombre_raw.split(",", 1)
                apellidos = partes[0].strip()
                nombres = partes[1].strip()

            sexo_raw = (fila.get("sexo") or "").strip()
            sexo = {"1": "M", "2": "F"}.get(sexo_raw, sexo_raw or None)

            email_raw = (fila.get("email") or "").strip()

            registro = models.ClienteHistorico(
                gimnasio_id=get_gid(_),
                num_carnet=num_carnet,
                nombre_completo=nombre_raw,
                apellidos=apellidos,
                nombres=nombres,
                fecha_registro=_parsear_fecha_legado(fila.get("fec_reg")),
                sexo=sexo,
                estado_legado=_parsear_entero_legado(fila.get("estado")),
                situacion_legado=_parsear_entero_legado(fila.get("situacion")),
                direccion=(fila.get("direccion") or "").strip() or None,
                telefono1=(fila.get("fono1") or "").strip() or None,
                telefono2=(fila.get("fono2") or "").strip() or None,
                email=email_raw or None,
                fecha_nacimiento=_parsear_fecha_legado(fila.get("fec_nac")),
                edad_legado=_parsear_entero_legado(fila.get("edad")),
                distrito=(fila.get("distrito") or "").strip() or None,
                codigo_distrito_legado=_parsear_entero_legado(fila.get("cdistrito")),
                codigo_plan_legado=_parsear_entero_legado(fila.get("cplan")),
                plan_texto=(fila.get("tarbases") or "").strip() or None,
                fecha_suscripcion=_parsear_fecha_legado(fila.get("fec_sus")),
                fecha_renovacion=_parsear_fecha_legado(fila.get("fec_ren")),
                fecha_vencimiento=_parsear_fecha_legado(fila.get("fec_ven")),
                total_asistencias_legado=_parsear_entero_legado(fila.get("asistencia")),
            )
            db.add(registro)
            if num_carnet is not None:
                carnets_existentes.add(num_carnet)
            total_importados += 1
        except Exception as e:
            errores.append(f"Fila {total_leidas}: {e}")

    db.commit()
    return schemas.ImportarClientesHistoricosResultado(
        total_filas_leidas=total_leidas,
        total_importados=total_importados,
        total_omitidos_duplicados=total_omitidos,
        errores=errores[:20],
    )


@app.post("/clientes-historicos/{historico_id}/reingresar", response_model=schemas.Cliente, tags=["Clientes Historicos"])
def reingresar_cliente_historico(
    historico_id: int,
    db: Session = Depends(get_db),
    _=Depends(auth.requiere_staff_o_profesor),
):
    """
    Convierte un registro historico en un Cliente activo nuevo
    (o devuelve el ya existente si este registro ya fue migrado
    antes), pensado para el flujo de 'Reingreso' en Busqueda
    inteligente: tras esto, el cliente queda listo para venderle
    una nueva membresia en Venta Rapida.
    """
    _validar_limite_plan(db, _, "clientes")
    historico = _del_gym(db, models.ClienteHistorico, historico_id, _)
    if not historico:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    if historico.migrado and historico.cliente_nuevo_id:
        cliente_existente = _del_gym(db, models.Cliente, historico.cliente_nuevo_id, _)
        if cliente_existente:
            return cliente_existente

    email_valido = historico.email if historico.email and "@" in historico.email else None

    nuevo_cliente = models.Cliente(
        nombre=historico.nombres or historico.nombre_completo,
        apellidos=historico.apellidos,
        telefono=historico.telefono1 or historico.telefono2,
        email=email_valido,
        fecha_nacimiento=historico.fecha_nacimiento,
        direccion=historico.direccion,
    )
    db.add(nuevo_cliente)
    db.commit()
    db.refresh(nuevo_cliente)

    historico.migrado = True
    historico.cliente_nuevo_id = nuevo_cliente.id
    db.commit()

    return nuevo_cliente


# ==================================================================
# MEMBRESIAS
# ==================================================================

@app.get("/membresias/", response_model=List[schemas.Membresia], tags=["Membresias"])
def listar_membresias(
    incluir_inactivas: bool = Query(False, description="Si es true, incluye tambien las tarifas desactivadas"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    query = db.query(models.Membresia).filter(models.Membresia.gimnasio_id == get_gid(usuario))
    if not incluir_inactivas:
        query = query.filter(models.Membresia.activo == True)
    return query.order_by(models.Membresia.id.desc()).all()


@app.get("/membresias/por-vencer", response_model=List[schemas.MembresiaPorVencer], tags=["Membresias"])
def membresias_por_vencer(
    dias: Optional[int] = Query(None, description="Si no se envia, usa dias_aviso_vencimiento de Configuracion"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Clientes con una membresia activa cuya fecha_fin cae dentro de
    los proximos N dias. N es configurable (ver /configuracion/),
    pensado para la tarjeta clickeable 'Membresias por vencer' del
    panel principal.
    """
    config = _configuracion_del_gym(db, usuario)
    dias_efectivos = dias if dias is not None else (config.dias_aviso_vencimiento or 7)
    hoy = hoy_lima()
    limite = hoy + timedelta(days=dias_efectivos)

    filas = (
        db.query(models.ClienteMembresia, models.Cliente, models.Membresia)
        .join(models.Cliente, models.ClienteMembresia.cliente_id == models.Cliente.id)
        .join(models.Membresia, models.ClienteMembresia.membresia_id == models.Membresia.id)
        .filter(
            models.Cliente.gimnasio_id == get_gid(usuario),
            models.ClienteMembresia.activo == True,
            models.ClienteMembresia.fecha_fin.isnot(None),
            models.ClienteMembresia.fecha_fin >= hoy,
            models.ClienteMembresia.fecha_fin <= limite,
        )
        .order_by(models.ClienteMembresia.fecha_fin)
        .all()
    )

    resultado = []
    for cm, cliente, membresia in filas:
        nombre_completo = f"{cliente.nombre} {cliente.apellidos or ''}".strip()
        resultado.append(
            schemas.MembresiaPorVencer(
                cliente_membresia_id=cm.id,
                cliente_id=cliente.id,
                nombre_cliente=nombre_completo,
                telefono=cliente.telefono,
                membresia_nombre=membresia.nombre,
                fecha_fin=cm.fecha_fin,
                dias_restantes=(cm.fecha_fin - hoy).days,
            )
        )
    return resultado


@app.post("/membresias/", response_model=schemas.Membresia, tags=["Membresias"])
def crear_membresia(membresia: schemas.MembresiaCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    db_membresia = models.Membresia(**membresia.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_membresia)
    db.commit()
    db.refresh(db_membresia)
    return db_membresia


@app.put("/membresias/{membresia_id}", response_model=schemas.Membresia, tags=["Membresias"])
def actualizar_membresia(
    membresia_id: int,
    datos: schemas.MembresiaUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    membresia = db.query(models.Membresia).filter(models.Membresia.id == membresia_id, models.Membresia.gimnasio_id == get_gid(usuario)).first()
    if not membresia:
        raise HTTPException(status_code=404, detail="Membresia no encontrada")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(membresia, campo, valor)
    db.commit()
    db.refresh(membresia)
    return membresia


@app.delete("/membresias/{membresia_id}", tags=["Membresias"])
def eliminar_membresia(membresia_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    membresia = db.query(models.Membresia).filter(models.Membresia.id == membresia_id, models.Membresia.gimnasio_id == get_gid(usuario)).first()
    if not membresia:
        raise HTTPException(status_code=404, detail="Membresia no encontrada")
    membresia.activo = False
    db.commit()
    return {"message": "Membresia desactivada correctamente"}


_CAMPOS_MEMBRESIA_EXPORTABLES = [
    "id", "nombre", "descripcion", "precio", "duracion_dias", "duracion_meses", "duracion_dias_extra",
    "monto_inicial", "fracciones_pago_deuda", "penalizacion", "dias_gracia_pago", "monto_mensual",
    "dias_congelamiento", "permite_congelamiento", "dias_acceso_periodo", "hora_inicio_acceso",
    "hora_fin_acceso", "dias_semana_acceso", "password_tarifa", "congelado_no_aparece_pagos",
    "no_aparecer_reporte_cruce_medidas", "incluye_nutricion", "activo",
]


@app.get("/membresias/exportar", tags=["Membresias"])
def exportar_membresias(
    incluir_inactivas: bool = True,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Exporta el catalogo completo de tarifas a CSV (compatible para reimportar despues)."""
    query = q(db, models.Membresia, usuario)
    if not incluir_inactivas:
        query = query.filter(models.Membresia.activo == True)
    membresias = query.order_by(models.Membresia.id).all()

    salida = io.StringIO()
    writer = csv.DictWriter(salida, fieldnames=_CAMPOS_MEMBRESIA_EXPORTABLES)
    writer.writeheader()
    for m in membresias:
        writer.writerow({campo: getattr(m, campo) for campo in _CAMPOS_MEMBRESIA_EXPORTABLES})
    salida.seek(0)

    return StreamingResponse(
        io.BytesIO(salida.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=membresias.csv"},
    )


@app.post("/membresias/importar", tags=["Membresias"])
async def importar_membresias(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Importa tarifas desde un CSV con las mismas columnas que exporta
    /membresias/exportar. La columna 'id' se ignora (siempre se
    crean como registros nuevos).
    """
    contenido = (await archivo.read()).decode("utf-8-sig", errors="replace")
    lineas = contenido.splitlines()
    if not lineas:
        raise HTTPException(status_code=400, detail="El archivo esta vacio")
    delimitador = _detectar_delimitador(lineas[0])

    lector = csv.DictReader(io.StringIO(contenido), delimiter=delimitador)
    lector.fieldnames = [(c or "").strip().lower() for c in (lector.fieldnames or [])]

    campos_bool = {"activo", "permite_congelamiento", "congelado_no_aparece_pagos", "no_aparecer_reporte_cruce_medidas", "incluye_nutricion"}
    campos_int = {"duracion_dias", "duracion_meses", "duracion_dias_extra", "fracciones_pago_deuda", "dias_gracia_pago", "dias_congelamiento", "dias_acceso_periodo"}
    campos_float = {"precio", "monto_inicial", "penalizacion", "monto_mensual"}
    campos_validos = set(_CAMPOS_MEMBRESIA_EXPORTABLES) - {"id"}

    total_importadas = 0
    errores: List[str] = []

    for indice, fila in enumerate(lector, start=1):
        try:
            datos = {}
            for campo, valor in fila.items():
                campo = (campo or "").strip()
                if campo not in campos_validos or valor is None or str(valor).strip() == "":
                    continue
                valor = str(valor).strip()
                if campo in campos_bool:
                    datos[campo] = valor.lower() in ("1", "true", "si", "s\u00ed", "yes")
                elif campo in campos_int:
                    datos[campo] = int(float(valor))
                elif campo in campos_float:
                    datos[campo] = float(valor)
                else:
                    datos[campo] = valor

            if not datos.get("nombre") or "precio" not in datos or "duracion_dias" not in datos:
                errores.append(f"Fila {indice}: falta nombre, precio o duracion_dias")
                continue

            db.add(models.Membresia(**datos, gimnasio_id=get_gid(usuario)))
            total_importadas += 1
        except Exception as e:
            errores.append(f"Fila {indice}: {e}")

    db.commit()
    return {"total_importadas": total_importadas, "errores": errores[:20]}


@app.post("/clientes/{cliente_id}/membresias", response_model=schemas.ClienteMembresia, tags=["Membresias"])
def asignar_membresia_a_cliente(
    cliente_id: int,
    datos: schemas.ClienteMembresiaCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(auth.requiere_staff),
):
    payload = {"cliente_id_url": cliente_id, **datos.model_dump(mode="json")}
    previo = _buscar_idempotente(db, usuario_actual, "asignar-membresia", idempotency_key, payload, models.ClienteMembresia)
    if previo:
        return previo
    gid = get_gid(usuario_actual)
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.gimnasio_id == gid).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    membresia = db.query(models.Membresia).filter(models.Membresia.id == datos.membresia_id, models.Membresia.gimnasio_id == gid).first()
    if not membresia:
        raise HTTPException(status_code=404, detail="Membresia no encontrada")

    if datos.cliente_id != cliente_id:
        raise HTTPException(status_code=400, detail="El cliente del cuerpo no coincide con la URL")

    fecha_inicio = datos.fecha_inicio or hoy_lima()
    fecha_fin = datos.fecha_fin or (fecha_inicio + timedelta(days=membresia.duracion_dias))
    if fecha_fin < fecha_inicio:
        raise HTTPException(status_code=400, detail="La fecha fin no puede ser anterior a la fecha de inicio")
    monto_inicial = datos.monto_pagado if datos.monto_pagado is not None else membresia.precio
    if monto_inicial < 0 or monto_inicial > membresia.precio + 0.01:
        raise HTTPException(status_code=400, detail="El monto inicial debe estar entre 0 y el precio de la membresia")

    db_cm = models.ClienteMembresia(
        cliente_id=cliente_id,
        membresia_id=datos.membresia_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        monto_pagado=round(monto_inicial, 2),
        fecha_pago_saldo=datos.fecha_pago_saldo,
        metodo_pago=datos.metodo_pago or "efectivo",
        vendido_por_id=usuario_actual.id,
    )
    db.add(db_cm)
    db.flush()

    # Registrar el pago inicial en el historial (si hay monto)
    if db_cm.monto_pagado and db_cm.monto_pagado > 0:
        pago_inicial = models.PagoMembresia(
            cliente_membresia_id=None,  # se asigna tras flush
            monto=db_cm.monto_pagado,
            metodo_pago=db_cm.metodo_pago or "efectivo",
            fecha_proximo_pago=datos.fecha_pago_saldo,
            registrado_por_id=usuario_actual.id,
            notas="Pago inicial al asignar membresía",
        )
        pago_inicial.cliente_membresia_id = db_cm.id
        db.add(pago_inicial)

    # Al matricular/renovar, estos datos del cliente se recalculan
    # solos (no se ingresan a mano en el formulario de Cliente).
    cliente.fecha_renovacion = fecha_inicio
    cliente.fecha_vencimiento = fecha_fin
    # Si el cliente tenia un texto de membresia importado del sistema
    # anterior (membresia_texto), lo limpiamos porque ahora ya tiene
    # una ClienteMembresia real que reemplaza esa referencia vieja.
    if cliente.membresia_texto:
        cliente.membresia_texto = None
    # Si el cliente estaba inactivo (por ejemplo, importado de otra
    # base y nunca editado), reactivarlo al asignarle una membresia.
    if not cliente.activo:
        cliente.activo = True

    _guardar_idempotencia(db, usuario_actual, "asignar-membresia", idempotency_key, payload, "ClienteMembresia", db_cm.id)
    db.commit()
    db.refresh(db_cm)
    return db_cm


@app.get("/clientes/{cliente_id}/membresias", response_model=List[schemas.ClienteMembresia], tags=["Membresias"])
def listar_membresias_de_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff),
):
    """Historial completo de membresias asignadas a un cliente (incluye inactivas), de la mas reciente a la mas antigua."""
    cliente = _del_gym(db, models.Cliente, cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return (
        db.query(models.ClienteMembresia)
        .filter(models.ClienteMembresia.cliente_id == cliente_id)
        .order_by(models.ClienteMembresia.fecha_inicio.desc(), models.ClienteMembresia.id.desc())
        .all()
    )


def _sincronizar_fechas_cliente(db: Session, cliente_id: int):
    """
    Recalcula fecha_renovacion / fecha_vencimiento del cliente a
    partir de su membresia mas reciente (por fecha_inicio). Se llama
    tras editar o eliminar un ClienteMembresia para que la ficha del
    cliente no quede desincronizada.
    """
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        return
    ultima = (
        db.query(models.ClienteMembresia)
        .filter(models.ClienteMembresia.cliente_id == cliente_id)
        .order_by(models.ClienteMembresia.fecha_inicio.desc(), models.ClienteMembresia.id.desc())
        .first()
    )
    cliente.fecha_renovacion = ultima.fecha_inicio if ultima else None
    cliente.fecha_vencimiento = ultima.fecha_fin if ultima else None


@app.get("/cliente-membresias/{cm_id}", response_model=schemas.ClienteMembresia, tags=["Membresias"])
def obtener_cliente_membresia(cm_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    cm = _cliente_membresia_del_gym(db, cm_id, usuario)
    if not cm:
        raise HTTPException(status_code=404, detail="Membresia asignada no encontrada")
    cm.monto_pagado = _total_pagado_membresia(db, cm.id)
    return cm


@app.put("/cliente-membresias/{cm_id}", response_model=schemas.ClienteMembresia, tags=["Membresias"])
def editar_cliente_membresia(
    cm_id: int,
    datos: schemas.ClienteMembresiaUpdate,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_administrador),
):
    """
    Correccion administrativa de una membresia asignada: plan,
    fechas, monto pagado, fecha de pago del saldo y estado. Solo
    administrador. Tras guardar, se resincronizan las fechas de
    renovacion/vencimiento de la ficha del cliente.
    """
    cm = _cliente_membresia_del_gym(db, cm_id, usuario)
    if not cm:
        raise HTTPException(status_code=404, detail="Membresia asignada no encontrada")

    datos_dict = datos.model_dump(exclude_unset=True)

    if "monto_pagado" in datos_dict and abs((datos_dict["monto_pagado"] or 0) - (cm.monto_pagado or 0)) > 0.001:
        raise HTTPException(status_code=409, detail="El total pagado no se edita directamente. Registra un pago o anula el ultimo pago desde la pestaña Pagos.")
    if "metodo_pago" in datos_dict and any(not pago.anulada for pago in cm.pagos):
        raise HTTPException(status_code=409, detail="El metodo pertenece a cada pago y no se modifica desde la membresia. Corrige el ultimo pago antes de cerrar caja.")

    if "membresia_id" in datos_dict:
        membresia = _del_gym(db, models.Membresia, datos_dict["membresia_id"], usuario)
        if not membresia:
            raise HTTPException(status_code=404, detail="Membresia no encontrada")

    if "monto_pagado" in datos_dict and datos_dict["monto_pagado"] is not None and datos_dict["monto_pagado"] < 0:
        raise HTTPException(status_code=400, detail="El monto pagado no puede ser negativo")

    for campo, valor in datos_dict.items():
        setattr(cm, campo, valor)

    plan_actual = _del_gym(db, models.Membresia, cm.membresia_id, usuario)
    if not plan_actual:
        raise HTTPException(status_code=404, detail="Membresia no encontrada")
    if _total_pagado_membresia(db, cm.id) > plan_actual.precio + 0.01:
        raise HTTPException(status_code=400, detail="El monto pagado no puede superar el precio de la membresia")

    if cm.fecha_fin and cm.fecha_inicio and cm.fecha_fin < cm.fecha_inicio:
        raise HTTPException(status_code=400, detail="La fecha fin no puede ser anterior a la fecha de inicio")

    _sincronizar_fechas_cliente(db, cm.cliente_id)
    db.commit()
    db.refresh(cm)
    return cm


@app.put("/cliente-membresias/{cm_id}/pagar-saldo", response_model=schemas.ClienteMembresia, tags=["Membresias"])
def pagar_saldo_membresia(
    cm_id: int,
    datos: schemas.PagoSaldoRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Pago rapido de saldo pendiente de una membresia asignada.
    Cualquier staff puede usarlo (no requiere administrador).
    Registra un pago individual auditable; el total se deriva del historial.
    """
    cm = _cliente_membresia_del_gym(db, cm_id, usuario)
    if not cm:
        raise HTTPException(status_code=404, detail="Membresia asignada no encontrada")
    payload = {"cm_id": cm_id, **datos.model_dump(mode="json")}
    previo = _buscar_idempotente(db, usuario, "pagar-saldo", idempotency_key, payload, models.PagoMembresia)
    if previo:
        return previo.cliente_membresia

    membresia = _del_gym(db, models.Membresia, cm.membresia_id, usuario)
    precio = membresia.precio if membresia else 0
    pagado_actual = _total_pagado_membresia(db, cm.id)
    saldo_actual = round(max(precio - pagado_actual, 0), 2)

    if datos.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    if datos.monto > saldo_actual + 0.01:
        raise HTTPException(status_code=400, detail=f"El monto ({datos.monto}) supera el saldo pendiente ({saldo_actual})")

    nuevo_pagado = round(min(pagado_actual + datos.monto, precio), 2)
    if nuevo_pagado < precio - 0.01 and not datos.fecha_proximo_pago:
        raise HTTPException(status_code=400, detail="Indica la fecha del proximo pago mientras exista saldo pendiente")
    cm.monto_pagado = nuevo_pagado
    metodo_pago = datos.metodo_pago.value if hasattr(datos.metodo_pago, "value") else datos.metodo_pago
    cm.metodo_pago = metodo_pago or cm.metodo_pago

    # Registrar el pago individual en el historial
    pago = models.PagoMembresia(
        cliente_membresia_id=cm.id,
        monto=datos.monto,
        metodo_pago=metodo_pago or "efectivo",
        fecha_proximo_pago=datos.fecha_proximo_pago,
        registrado_por_id=usuario.id,
    )
    db.add(pago)

    # Si queda saldo 0, limpiar la fecha de pago programada;
    # si queda saldo y viene fecha_proximo_pago, actualizarla
    if nuevo_pagado >= precio:
        cm.fecha_pago_saldo = None
    elif datos.fecha_proximo_pago:
        cm.fecha_pago_saldo = datos.fecha_proximo_pago

    db.flush()
    _guardar_idempotencia(db, usuario, "pagar-saldo", idempotency_key, payload, "PagoMembresia", pago.id)
    db.commit()
    db.refresh(cm)
    return cm


@app.delete("/pagos-membresia/{pago_id}", tags=["Membresias"])
def eliminar_pago_membresia(
    pago_id: int,
    datos: schemas.AnulacionOperacionRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """Anula el último pago sin borrar su evidencia histórica."""
    pago = _pago_membresia_del_gym(db, pago_id, usuario)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago de membresia no encontrado")
    if pago.anulada:
        raise HTTPException(status_code=409, detail="El pago ya fue anulado")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)
    cm = pago.cliente_membresia
    ultimo_id = db.query(models.PagoMembresia.id).filter(
        models.PagoMembresia.cliente_membresia_id == cm.id,
        models.PagoMembresia.anulada == False,
    ).order_by(
        models.PagoMembresia.fecha_pago.desc(),
        models.PagoMembresia.id.desc(),
    ).first()
    if not ultimo_id or ultimo_id[0] != pago.id:
        raise HTTPException(status_code=400, detail="Solo se puede borrar el ultimo pago registrado")
    pago.anulada = True
    pago.anulada_en = ahora_lima()
    pago.anulada_por_id = usuario.id
    pago.motivo_anulacion = datos.motivo.strip()
    db.flush()
    cm.monto_pagado = _total_pagado_membresia(db, cm.id)
    pago_anterior = db.query(models.PagoMembresia).filter(
        models.PagoMembresia.cliente_membresia_id == cm.id,
        models.PagoMembresia.anulada == False,
    ).order_by(
        models.PagoMembresia.fecha_pago.desc(),
        models.PagoMembresia.id.desc(),
    ).first()
    precio = float(cm.membresia.precio or 0.0) if cm.membresia else 0.0
    cm.fecha_pago_saldo = (
        pago_anterior.fecha_proximo_pago
        if cm.monto_pagado < precio - 0.01 and pago_anterior
        else None
    )
    db.commit()
    return {"message": "Pago de membresia anulado", "monto_pagado": cm.monto_pagado}


@app.delete("/cliente-membresias/{cm_id}", tags=["Membresias"])
def eliminar_cliente_membresia(cm_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario=Depends(auth.requiere_administrador)):
    """Anula una membresia y sus pagos sin destruir el historial."""
    cm = _cliente_membresia_del_gym(db, cm_id, usuario)
    if not cm:
        raise HTTPException(status_code=404, detail="Membresia asignada no encontrada")
    if cm.anulada:
        raise HTTPException(status_code=409, detail="La membresia asignada ya fue anulada")
    for pago in cm.pagos:
        if not pago.anulada:
            _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)
    cliente_id = cm.cliente_id; momento = ahora_lima(); motivo = datos.motivo.strip()
    cm.activo = False; cm.anulada = True; cm.anulada_en = momento; cm.anulada_por_id = usuario.id; cm.motivo_anulacion = motivo
    for pago in cm.pagos:
        if not pago.anulada:
            pago.anulada = True; pago.anulada_en = momento; pago.anulada_por_id = usuario.id; pago.motivo_anulacion = f"Membresia anulada: {motivo}"
    _sincronizar_fechas_cliente(db, cliente_id)
    db.commit()
    return {"message": "Membresia asignada anulada"}


@app.get("/clientes/{cliente_id}/membresias/{cm_id}/recibo.pdf", tags=["Membresias"])
def recibo_membresia_pdf(
    cliente_id: int,
    cm_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    cliente = _del_gym(db, models.Cliente, cliente_id, usuario)
    cm = _cliente_membresia_del_gym(db, cm_id, usuario)
    if cm and cm.cliente_id != cliente_id:
        cm = None
    if not cliente or not cm:
        raise HTTPException(status_code=404, detail="No encontrado")
    membresia = db.query(models.Membresia).filter(models.Membresia.id == cm.membresia_id).first()
    config = _configuracion_del_gym(db, usuario)
    pdf_bytes = pdf_generator.generar_recibo_membresia_pdf(cm, cliente, membresia, config)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=recibo_membresia_{cm_id}.pdf"},
    )


@app.get("/clientes/{cliente_id}/membresias/{cm_id}/contrato.pdf", tags=["Membresias"])
def contrato_matricula_pdf(
    cliente_id: int,
    cm_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    cliente = _del_gym(db, models.Cliente, cliente_id, usuario)
    cm = _cliente_membresia_del_gym(db, cm_id, usuario)
    if cm and cm.cliente_id != cliente_id:
        cm = None
    if not cliente or not cm:
        raise HTTPException(status_code=404, detail="No encontrado")
    membresia = db.query(models.Membresia).filter(models.Membresia.id == cm.membresia_id).first()
    config = _configuracion_del_gym(db, usuario)
    pdf_bytes = pdf_generator.generar_contrato_pdf(cliente, cm, membresia, config)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=contrato_{cm_id}.pdf"},
    )


@app.get("/clientes/{cliente_id}/ficha", response_model=schemas.ClienteFicha, tags=["Clientes"])
def ficha_rapida_cliente(cliente_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff_o_profesor)):
    """
    Resumen agregado para la columna de busqueda inteligente del
    panel principal: membresia activa, deuda pendiente (precio de
    la membresia menos lo pagado), % de asistencia de los ultimos
    30 dias y los ultimos 2 ingresos.
    """
    cliente = _del_gym(db, models.Cliente, cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    hoy = hoy_lima()
    cm_activa = (
        db.query(models.ClienteMembresia)
        .filter(models.ClienteMembresia.cliente_id == cliente_id, models.ClienteMembresia.activo == True)
        .order_by(models.ClienteMembresia.fecha_fin.desc())
        .first()
    )

    membresia_actual = None
    if cm_activa:
        membresia = db.query(models.Membresia).filter(models.Membresia.id == cm_activa.membresia_id).first()
        total_pagado = _total_pagado_membresia(db, cm_activa.id)
        deuda = max((membresia.precio if membresia else 0.0) - total_pagado, 0.0)
        dias_restantes = (cm_activa.fecha_fin - hoy).days if cm_activa.fecha_fin else None
        membresia_actual = schemas.FichaMembresiaActual(
            cm_id=cm_activa.id,
            nombre=membresia.nombre if membresia else "—",
            fecha_fin=cm_activa.fecha_fin,
            dias_restantes=dias_restantes,
            precio=membresia.precio if membresia else 0.0,
            monto_pagado=total_pagado,
            deuda_pendiente=deuda,
            fecha_pago_saldo=cm_activa.fecha_pago_saldo,
        )

    desde_30_dias = ahora_lima() - timedelta(days=30)
    dias_con_ingreso = (
        db.query(func.count(func.distinct(func.date(models.Asistencia.fecha_hora_entrada))))
        .filter(models.Asistencia.cliente_id == cliente_id, models.Asistencia.fecha_hora_entrada >= desde_30_dias)
        .scalar()
    )
    porcentaje_asistencia = min(round((dias_con_ingreso or 0) / 30 * 100, 1), 100.0)

    ultimos_ingresos = (
        db.query(models.Asistencia)
        .filter(models.Asistencia.cliente_id == cliente_id)
        .order_by(models.Asistencia.fecha_hora_entrada.desc())
        .limit(2)
        .all()
    )

    nombre_completo = f"{cliente.nombre} {cliente.apellidos or ''}".strip()
    return schemas.ClienteFicha(
        cliente_id=cliente.id,
        nombre_completo=nombre_completo,
        foto_url=cliente.foto_url,
        membresia_actual=membresia_actual,
        porcentaje_asistencia=porcentaje_asistencia,
        ultimos_ingresos=ultimos_ingresos,
    )


# ==================================================================
# PRODUCTOS E INVENTARIO
# ==================================================================

@app.get("/productos/", response_model=List[schemas.Producto], tags=["Productos"])
def listar_productos(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    return q(db, models.Producto, usuario).filter(models.Producto.activo == True).order_by(models.Producto.nombre).all()


@app.get("/productos/mas-vendidos", response_model=List[schemas.ProductoVendido], tags=["Productos"])
def productos_mas_vendidos(
    limit: int = 30,
    buscar: Optional[str] = Query(None, description="Filtra por nombre o categoria"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Catalogo de productos activos ordenado de mayor a menor por
    unidades vendidas historicamente (para la Venta Rapida mini del
    panel principal). Los productos sin ventas aun aparecen al
    final, con cantidad_vendida = 0.
    """
    ventas_por_producto = (
        db.query(
            models.DetalleVenta.producto_id,
            func.coalesce(func.sum(models.DetalleVenta.cantidad), 0).label("total_vendido"),
        )
        .group_by(models.DetalleVenta.producto_id)
        .subquery()
    )

    query = (
        db.query(models.Producto, func.coalesce(ventas_por_producto.c.total_vendido, 0))
        .outerjoin(ventas_por_producto, models.Producto.id == ventas_por_producto.c.producto_id)
        .filter(models.Producto.activo == True, models.Producto.gimnasio_id == get_gid(usuario))
    )

    if buscar:
        like = f"%{buscar}%"
        query = query.filter((models.Producto.nombre.ilike(like)) | (models.Producto.categoria.ilike(like)))

    filas = (
        query.order_by(func.coalesce(ventas_por_producto.c.total_vendido, 0).desc(), models.Producto.nombre)
        .limit(limit)
        .all()
    )

    return [schemas.ProductoVendido(producto=producto, cantidad_vendida=int(cantidad)) for producto, cantidad in filas]


@app.post("/productos/", response_model=schemas.Producto, tags=["Productos"])
def crear_producto(producto: schemas.ProductoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    _validar_limite_plan(db, usuario, "productos")
    db_producto = models.Producto(**producto.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_producto)
    db.commit()
    db.refresh(db_producto)
    return db_producto


@app.put("/productos/{producto_id}", response_model=schemas.Producto, tags=["Productos"])
def actualizar_producto(
    producto_id: int,
    datos: schemas.ProductoUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    producto = db.query(models.Producto).filter(models.Producto.id == producto_id, models.Producto.gimnasio_id == get_gid(usuario)).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if campo == "foto_url" and valor is None:
            continue
        setattr(producto, campo, valor)
    db.commit()
    db.refresh(producto)
    return producto


@app.delete("/productos/{producto_id}", tags=["Productos"])
def eliminar_producto(producto_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    producto = db.query(models.Producto).filter(models.Producto.id == producto_id, models.Producto.gimnasio_id == get_gid(usuario)).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    producto.activo = False
    db.commit()
    return {"message": "Producto desactivado correctamente"}


@app.get("/productos/{producto_id}/foto-contenido", tags=["Productos"])
def contenido_foto_producto(producto_id: int, db: Session = Depends(get_db)):
    """Sirve la foto persistente del producto desde la base de datos."""
    producto = db.query(models.Producto).filter(models.Producto.id == producto_id, models.Producto.activo == True).first()
    if not producto or not producto.foto_datos:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    return Response(
        content=producto.foto_datos,
        media_type=producto.foto_tipo or "image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.post("/productos/{producto_id}/foto", response_model=schemas.Producto, tags=["Productos"])
async def subir_foto_producto(
    producto_id: int,
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Sube/reemplaza la foto de un producto. Si hay foto, tiene prioridad sobre el icono emoji en Venta Rapida."""
    producto = db.query(models.Producto).filter(models.Producto.id == producto_id, models.Producto.gimnasio_id == get_gid(usuario)).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    contenido = await foto.read()
    contenido, content_type = _validar_y_optimizar_foto(contenido, foto.content_type, optimizar=True)
    foto_anterior = producto.foto_url
    producto.foto_datos = contenido
    producto.foto_tipo = content_type
    producto.foto_url = f"/productos/{producto.id}/foto-contenido?v={uuid.uuid4().hex[:12]}"
    db.commit()
    db.refresh(producto)
    _eliminar_foto_anterior(foto_anterior)
    return producto


# ---- Compras (reposicion de stock con costo, alimenta Egresos) ----
# AUDITORIA: este endpoint no existia. Sin el, el modelo Compra nunca
# se llenaba y "Compra de productos" en Egresos/Resumen siempre
# mostraba S/0, aunque se repusiera stock a mano desde "Ajustar Stock".

@app.get("/compras/", response_model=List[schemas.Compra], tags=["Productos"])
def listar_compras(
    producto_id: Optional[int] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    query = db.query(models.Compra).join(models.Producto, models.Compra.producto_id == models.Producto.id).filter(models.Producto.gimnasio_id == get_gid(usuario))
    if producto_id:
        query = query.filter(models.Compra.producto_id == producto_id)
    if desde:
        query = query.filter(models.Compra.fecha >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        query = query.filter(models.Compra.fecha <= datetime.combine(hasta, datetime.max.time()))
    return query.order_by(models.Compra.fecha.desc()).limit(limit).all()


@app.post("/compras/", response_model=schemas.Compra, tags=["Productos"])
def registrar_compra(
    datos: schemas.CompraCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Registra una compra real de mercaderia: aumenta el stock del
    producto, actualiza su precio_compra (el mas reciente) y queda
    como egreso en /egresos/ y /resumen (categoria compra_producto).
    """
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario_actual, "compras", idempotency_key, payload, models.Compra)
    if previo:
        return previo
    if datos.cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")
    if datos.costo_unitario < 0:
        raise HTTPException(status_code=400, detail="El costo unitario no puede ser negativo")

    producto = db.query(models.Producto).filter(models.Producto.id == datos.producto_id, models.Producto.gimnasio_id == get_gid(usuario_actual)).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    costo_total = round(datos.cantidad * datos.costo_unitario, 2)
    db_compra = models.Compra(
        producto_id=datos.producto_id,
        cantidad=datos.cantidad,
        costo_unitario=datos.costo_unitario,
        costo_total=costo_total,
        usuario_id=usuario_actual.id,
        notas=datos.notas,
        metodo_pago=datos.metodo_pago,
        gimnasio_id=get_gid(usuario_actual),
    )
    db.add(db_compra)

    producto.stock += datos.cantidad
    producto.precio_compra = datos.costo_unitario

    db.flush()
    _guardar_idempotencia(db, usuario_actual, "compras", idempotency_key, payload, "Compra", db_compra.id)
    db.commit()
    db.refresh(db_compra)
    return db_compra


@app.delete("/compras/{compra_id}", tags=["Productos"])
def eliminar_compra(compra_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    """Anula una compra y revierte el stock sin borrar el registro."""
    compra = (
        db.query(models.Compra)
        .join(models.Producto, models.Compra.producto_id == models.Producto.id)
        .filter(models.Compra.id == compra_id, models.Producto.gimnasio_id == get_gid(usuario))
        .first()
    )
    if not compra:
        raise HTTPException(status_code=404, detail="Compra no encontrada")
    if compra.anulada:
        raise HTTPException(status_code=409, detail="La compra ya fue anulada")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), compra.fecha)
    producto = db.query(models.Producto).filter(models.Producto.id == compra.producto_id).first()
    if producto:
        if producto.stock < compra.cantidad:
            raise HTTPException(status_code=409, detail="No se puede anular: parte de ese stock ya fue vendido. Corrige primero las ventas relacionadas")
        producto.stock -= compra.cantidad
    compra.anulada = True
    compra.anulada_en = ahora_lima()
    compra.anulada_por_id = usuario.id
    compra.motivo_anulacion = datos.motivo.strip()
    db.commit()
    return {"message": "Compra anulada y stock corregido"}


# ==================================================================
# VENTAS (incluye venta rapida)
# ==================================================================

def _escalar_porcion(porcion_casera: str, factor: float) -> str:
    """Escala una porcion casera segun el factor de gramos.
    Ej: porcion_casera='1 unidad', factor=2.0 -> '2 unidades'
        porcion_casera='1/2 vaso', factor=1.5 -> 'aprox 3/4 vaso'
    """
    import re
    if not porcion_casera or factor <= 0:
        return porcion_casera or ""
    # Extraer numero (entero, decimal o fraccion) al inicio
    m = re.match(r'^([\d./]+)\s*(.*)$', porcion_casera.strip())
    if not m:
        return porcion_casera  # no empieza con numero, devolver tal cual
    num_str, resto = m.group(1), m.group(2).strip()
    try:
        if '/' in num_str:
            partes = num_str.split('/')
            base = float(partes[0]) / float(partes[1])
        else:
            base = float(num_str)
    except (ValueError, ZeroDivisionError):
        return porcion_casera
    resultado = round(base * factor, 1)
    # Formatear bonito: 1.0->"1", 0.5->"1/2", 0.25->"1/4", 1.5->"1 1/2", 0.33->"1/3"
    fracciones_comunes = {0.25: "1/4", 0.33: "1/3", 0.5: "1/2", 0.67: "2/3", 0.75: "3/4"}
    if resultado == int(resultado):
        num_fmt = str(int(resultado))
    else:
        parte_entera = int(resultado)
        parte_decimal = round(resultado - parte_entera, 2)
        frac = fracciones_comunes.get(parte_decimal)
        if frac:
            num_fmt = f"{parte_entera} {frac}" if parte_entera else frac
        else:
            num_fmt = f"{resultado:.1f}"
    return f"{num_fmt} {resto}"


def _sin_tildes(texto: str) -> str:
    return "".join(
        caracter for caracter in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(caracter) != "Mn"
    ).lower()


def _formatear_cuartos(valor: float) -> str:
    """Redondea a medidas faciles: 1/4, 1/2, 3/4 o unidades enteras."""
    cuartos = max(1, int(round(valor * 4)))
    entero, resto = divmod(cuartos, 4)
    fraccion = {0: "", 1: "1/4", 2: "1/2", 3: "3/4"}[resto]
    if entero and fraccion:
        return f"{entero} {fraccion}"
    return str(entero) if entero else fraccion


def _porcion_cliente_facil(
    alimento: models.Alimento,
    gramos: float,
    porcion_explicita: Optional[str] = None,
) -> str:
    """Convierte gramos internos en una instruccion casera facil para el cliente."""
    if porcion_explicita and porcion_explicita.strip():
        return porcion_explicita.strip()

    nombre = _sin_tildes(alimento.nombre)
    gramos = max(float(gramos or alimento.porcion_gramos or 100), 1.0)

    if "huevo" in nombre:
        cantidad = max(1, int(round(gramos / 50.0)))
        return f"{cantidad} {'huevo' if cantidad == 1 else 'huevos'}"

    if "atun" in nombre:
        cantidad = max(1, int(round(gramos / 150.0)))
        return f"{cantidad} {'lata' if cantidad == 1 else 'latas'}"

    proteinas_en_filete = (
        "pollo", "pechuga", "pescado", "merluza", "bonito", "jurel",
        "tilapia", "trucha", "res", "bistec", "lomo",
    )
    if alimento.categoria == models.CategoriaAlimento.PROTEINA and any(
        proteina in nombre for proteina in proteinas_en_filete
    ):
        cantidad = max(1, int(round(gramos / 200.0)))
        return f"{cantidad} {'filete mediano' if cantidad == 1 else 'filetes medianos'}"

    if "palta" in nombre or "aguacate" in nombre:
        cantidad = max(0.5, round((gramos / 200.0) * 2) / 2)
        texto = _formatear_cuartos(cantidad)
        return f"{texto} {'palta' if cantidad <= 1 else 'paltas'}"

    granos = (
        "arroz", "choclo", "arveja", "lenteja", "frejol", "frijol",
        "garbanzo", "pallar", "quinua", "mote", "trigo", "cebada", "kiwicha",
    )
    if any(grano in nombre for grano in granos):
        gramos_taza = 165.0 if any(x in nombre for x in ("choclo", "arveja")) else 195.0
        cantidad = gramos / gramos_taza
        texto = _formatear_cuartos(cantidad)
        singular = texto in {"1/4", "1/2", "3/4", "1"}
        return f"{texto} {'taza' if singular else 'tazas'}"

    casera = (alimento.porcion_casera or "").strip()
    if casera:
        import re
        coincidencia = re.match(r'^([\d./]+)\s*(.*)$', casera)
        if coincidencia:
            numero, unidad = coincidencia.groups()
            try:
                base = (float(numero.split('/')[0]) / float(numero.split('/')[1])) if '/' in numero else float(numero)
                factor = gramos / float(alimento.porcion_gramos or 100)
                valor = base * factor
                # Frutas, tomates y equivalencias en unidades deben ser numeros enteros.
                if alimento.categoria == models.CategoriaAlimento.FRUTA or any(
                    palabra in _sin_tildes(unidad) for palabra in ("unidad", "huevo", "tomate")
                ):
                    cantidad = max(1, int(round(valor)))
                    unidad_limpia = unidad.strip()
                    return f"{cantidad} {unidad_limpia}"
                texto = _formatear_cuartos(valor)
                unidad_limpia = unidad.strip()
                singular = texto in {"1/4", "1/2", "3/4", "1"}
                if not singular:
                    partes = unidad_limpia.split(" ", 1)
                    if not partes[0].endswith("s"):
                        partes[0] += "s"
                    unidad_limpia = " ".join(partes)
                return f"{texto} {unidad_limpia}"
            except (ValueError, ZeroDivisionError):
                pass
        return casera

    return "1 porcion mediana"


def _limitar_gramos_proteina(alimento: models.Alimento, gramos: float) -> float:
    """Evita porciones proteicas desproporcionadas en paquetes y planes."""
    gramos = max(float(gramos or alimento.porcion_gramos or 100), 1.0)
    nombre = _sin_tildes(alimento.nombre)
    if "atun" in nombre:
        return min(gramos, 150.0)  # una lata estandar
    if "huevo" in nombre:
        return min(gramos, 200.0)  # cuatro huevos aprox.
    if alimento.categoria == models.CategoriaAlimento.PROTEINA:
        return min(gramos, 200.0)  # una porcion principal razonable
    return gramos


def _normalizar_porciones_cliente():
    """Completa porciones faciles en datos antiguos y oculta el gramaje del nombre visible."""
    db = SessionLocal()
    try:
        for item in db.query(models.PaqueteAlimento).all():
            if item.alimento:
                item.cantidad_gramos = _limitar_gramos_proteina(item.alimento, item.cantidad_gramos)
                item.porcion_cliente = _porcion_cliente_facil(
                    item.alimento, item.cantidad_gramos
                )
        for comida in db.query(models.ComidaPlan).all():
            if comida.alimento:
                if comida.plan and comida.plan.origen == "automatico":
                    comida.cantidad_gramos = _limitar_gramos_proteina(comida.alimento, comida.cantidad_gramos)
                    factor = comida.cantidad_gramos / float(comida.alimento.porcion_gramos or 100)
                    comida.calorias = round((comida.alimento.calorias or 0.0) * factor)
                comida.porcion_cliente = _porcion_cliente_facil(
                    comida.alimento, comida.cantidad_gramos,
                    None if comida.plan and comida.plan.origen == "automatico" else comida.porcion_cliente,
                )
                comida.nombre_alimento = comida.alimento.nombre
        db.commit()
    finally:
        db.close()


def _calcular_costo_comision_gym(subtotal: float, metodo_pago: models.MetodoPago, config: models.Gimnasio) -> float:
    """
    La comision de la pasarela (tarjeta/QR) NO se le cobra al
    cliente: el gimnasio la asume como gasto. Esta funcion devuelve
    cuanto absorbe el gimnasio (solo para fines contables), y el
    total que paga el cliente sigue siendo el subtotal tal cual.
    """
    if metodo_pago == models.MetodoPago.TARJETA:
        return round(subtotal * config.comision_tarjeta / 100, 2)
    if metodo_pago == models.MetodoPago.QR:
        return round(subtotal * config.comision_qr / 100, 2)
    return 0.0


@app.get("/ventas/", response_model=List[schemas.Venta], tags=["Ventas"])
def listar_ventas(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    return (
        q(db, models.Venta, usuario)
        .order_by(models.Venta.fecha_venta.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@app.get("/ventas/recientes", response_model=List[schemas.Venta], tags=["Ventas"])
def ventas_recientes(limit: int = 5, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    return q(db, models.Venta, usuario).filter(models.Venta.anulada == False).order_by(models.Venta.fecha_venta.desc()).limit(limit).all()


class VentaUpdateAdmin(schemas.BaseModel):
    cliente_id: Optional[int] = None
    metodo_pago: Optional[models.MetodoPago] = None
    notas: Optional[str] = None


@app.put("/ventas/{venta_id}", response_model=schemas.Venta, tags=["Ventas"])
def editar_venta(
    venta_id: int,
    datos: VentaUpdateAdmin,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """
    Correccion administrativa de una venta: cliente, metodo de pago
    y notas. NO permite editar los productos/montos de la venta (eso
    afectaria el stock ya descontado); para corregir productos, se
    recomienda eliminar la venta y registrarla de nuevo.
    """
    venta = db.query(models.Venta).filter(models.Venta.id == venta_id, models.Venta.gimnasio_id == get_gid(usuario)).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    if venta.anulada:
        raise HTTPException(status_code=409, detail="Una venta anulada no se puede editar")
    if {"metodo_pago"}.intersection(datos.model_dump(exclude_unset=True)):
        _exigir_periodo_financiero_abierto(db, get_gid(usuario), venta.fecha_venta)
    datos_dict = datos.model_dump(exclude_unset=True)
    if datos_dict.get("cliente_id") is not None and not _del_gym(db, models.Cliente, datos_dict["cliente_id"], usuario):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    for campo, valor in datos_dict.items():
        setattr(venta, campo, valor)
    db.commit()
    db.refresh(venta)
    return venta


@app.delete("/ventas/{venta_id}", tags=["Ventas"])
def eliminar_venta(venta_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    """Anula una venta y restaura stock conservando toda la evidencia."""
    venta = db.query(models.Venta).filter(models.Venta.id == venta_id, models.Venta.gimnasio_id == get_gid(usuario)).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    if venta.anulada:
        raise HTTPException(status_code=409, detail="La venta ya fue anulada")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), venta.fecha_venta)
    for detalle in venta.detalles:
        producto = db.query(models.Producto).filter(models.Producto.id == detalle.producto_id).first()
        if producto:
            producto.stock += detalle.cantidad
    venta.anulada = True
    venta.anulada_en = ahora_lima()
    venta.anulada_por_id = usuario.id
    venta.motivo_anulacion = datos.motivo.strip()
    db.commit()
    return {"message": "Venta anulada y stock restaurado"}


@app.get("/ventas/{venta_id}/boleta.pdf", tags=["Ventas"])
def boleta_venta_pdf(venta_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    venta = db.query(models.Venta).filter(models.Venta.id == venta_id, models.Venta.gimnasio_id == get_gid(usuario)).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    if venta.anulada:
        raise HTTPException(status_code=409, detail="No se emite recibo de una venta anulada")
    cliente = db.query(models.Cliente).filter(models.Cliente.id == venta.cliente_id).first() if venta.cliente_id else None
    config = _configuracion_del_gym(db, usuario)
    pdf_bytes = pdf_generator.generar_boleta_pdf(venta, cliente, config)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=recibo_interno_venta_{venta_id}.pdf"},
    )


@app.post("/ventas/", response_model=schemas.Venta, tags=["Ventas"])
def crear_venta(venta: schemas.VentaCreate, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"), db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(auth.requiere_staff)):
    payload = venta.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario_actual, "ventas", idempotency_key, payload, models.Venta)
    if previo:
        return previo
    if not venta.detalles:
        raise HTTPException(status_code=400, detail="La venta debe tener al menos un producto")

    config = _configuracion_del_gym(db, usuario_actual)
    gid = get_gid(usuario_actual)

    if venta.cliente_id is not None and not _del_gym(db, models.Cliente, venta.cliente_id, usuario_actual):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    subtotal_total = 0.0
    detalles_db = []

    for item in venta.detalles:
        if item.cantidad <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")
        producto = db.query(models.Producto).filter(models.Producto.id == item.producto_id, models.Producto.gimnasio_id == gid).first()
        if not producto:
            raise HTTPException(status_code=404, detail=f"Producto {item.producto_id} no encontrado")
        if producto.stock < item.cantidad:
            raise HTTPException(status_code=400, detail=f"Stock insuficiente para {producto.nombre}")

        # El precio es autoridad del servidor. El valor enviado por el
        # navegador nunca puede alterar una venta ni las comisiones.
        precio_unitario = round(producto.precio_venta, 2)
        subtotal_item = round(item.cantidad * precio_unitario, 2)
        subtotal_total += subtotal_item

        producto.stock -= item.cantidad

        detalles_db.append(
            models.DetalleVenta(
                producto_id=item.producto_id,
                cantidad=item.cantidad,
                precio_unitario=precio_unitario,
                subtotal=subtotal_item,
            )
        )

    total_final = subtotal_total  # el cliente paga el subtotal exacto; la comision la absorbe el gimnasio
    costo_comision_gym = _calcular_costo_comision_gym(subtotal_total, venta.metodo_pago, config)

    db_venta = models.Venta(
        cliente_id=venta.cliente_id,
        total=total_final,
        metodo_pago=venta.metodo_pago,
        es_venta_rapida=venta.es_venta_rapida,
        notas=venta.notas,
        detalles=detalles_db,
        usuario_id=usuario_actual.id,
        costo_comision_gym=costo_comision_gym,
        gimnasio_id=gid,
    )
    db.add(db_venta)
    db.flush()
    _guardar_idempotencia(db, usuario_actual, "ventas", idempotency_key, payload, "Venta", db_venta.id)
    db.commit()
    db.refresh(db_venta)
    return db_venta


# ==================================================================
# ASISTENCIAS (clientes)
# ==================================================================

DURACION_MAXIMA_ASISTENCIA = timedelta(hours=3)


def _cerrar_asistencias_vencidas(db: Session, gimnasio_id: int, ahora: Optional[datetime] = None) -> int:
    """Cierra entradas abiertas al cumplir tres horas, sin alterar otros gimnasios."""
    momento = ahora or ahora_lima()
    limite = momento - DURACION_MAXIMA_ASISTENCIA
    vencidas = db.query(models.Asistencia).filter(
        models.Asistencia.gimnasio_id == gimnasio_id,
        models.Asistencia.fecha_hora_salida.is_(None),
        models.Asistencia.fecha_hora_entrada <= limite,
    ).all()
    for asistencia in vencidas:
        asistencia.fecha_hora_salida = asistencia.fecha_hora_entrada + DURACION_MAXIMA_ASISTENCIA
    if vencidas:
        db.commit()
    return len(vencidas)

@app.get("/asistencias/", response_model=List[schemas.Asistencia], tags=["Asistencias"])
def listar_asistencias(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    cliente_id: Optional[int] = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Listado general de asistencias de alumnos con filtros de rango
    de fechas y de cliente (para la pantalla de Asistencias: vista
    general, por alumno y por horarios). Si no se envian fechas,
    devuelve las mas recientes hasta el limite.
    """
    _cerrar_asistencias_vencidas(db, get_gid(usuario))
    query = q(db, models.Asistencia, usuario)
    if desde:
        query = query.filter(models.Asistencia.fecha_hora_entrada >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        query = query.filter(models.Asistencia.fecha_hora_entrada <= datetime.combine(hasta, datetime.max.time()))
    if cliente_id:
        query = query.filter(models.Asistencia.cliente_id == cliente_id)
    return query.order_by(models.Asistencia.fecha_hora_entrada.desc()).limit(limit).all()


@app.get("/asistencias/hoy", response_model=List[schemas.Asistencia], tags=["Asistencias"])
def asistencias_de_hoy(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    _cerrar_asistencias_vencidas(db, get_gid(usuario))
    hoy = ahora_lima().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        q(db, models.Asistencia, usuario)
        .filter(models.Asistencia.fecha_hora_entrada >= hoy)
        .order_by(models.Asistencia.fecha_hora_entrada.desc())
        .all()
    )


@app.post("/asistencias/", response_model=schemas.Asistencia, tags=["Asistencias"])
def registrar_entrada(datos: schemas.AsistenciaCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    _cerrar_asistencias_vencidas(db, get_gid(usuario))
    cliente = db.query(models.Cliente).filter(models.Cliente.id == datos.cliente_id, models.Cliente.gimnasio_id == get_gid(usuario)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    db_asistencia = models.Asistencia(
        cliente_id=datos.cliente_id,
        gimnasio_id=get_gid(usuario),
        fecha_hora_entrada=ahora_lima(),
    )
    db.add(db_asistencia)
    db.commit()
    db.refresh(db_asistencia)
    return db_asistencia


@app.put("/asistencias/registrar-salida", response_model=schemas.Asistencia, tags=["Asistencias"])
def registrar_salida(datos: schemas.RegistrarSalidaRequest, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff_o_profesor)):
    asistencia = _del_gym(db, models.Asistencia, datos.asistencia_id, usuario)
    if not asistencia:
        raise HTTPException(status_code=404, detail="Asistencia no encontrada")
    asistencia.fecha_hora_salida = ahora_lima()
    db.commit()
    db.refresh(asistencia)
    return asistencia


# ==================================================================
# ASISTENCIA DE STAFF FIJO (AsistenciaEmpleado)
# ==================================================================

@app.get("/asistencias-empleado/", response_model=List[schemas.AsistenciaEmpleado], tags=["Personal"])
def listar_asistencias_empleado(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    empleado_id: Optional[int] = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Listado de marcajes de entrada/salida del personal (staff fijo), con filtros de fechas y de empleado."""
    query = db.query(models.AsistenciaEmpleado).join(models.Empleado, models.AsistenciaEmpleado.empleado_id == models.Empleado.id).filter(models.Empleado.gimnasio_id == get_gid(usuario))
    if desde:
        query = query.filter(models.AsistenciaEmpleado.fecha_hora_entrada >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        query = query.filter(models.AsistenciaEmpleado.fecha_hora_entrada <= datetime.combine(hasta, datetime.max.time()))
    if empleado_id:
        query = query.filter(models.AsistenciaEmpleado.empleado_id == empleado_id)
    return query.order_by(models.AsistenciaEmpleado.fecha_hora_entrada.desc()).limit(limit).all()


@app.post("/asistencias-empleado/", response_model=schemas.AsistenciaEmpleado, tags=["Personal"])
def registrar_entrada_empleado(
    datos: schemas.AsistenciaEmpleadoCreate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    empleado = db.query(models.Empleado).filter(models.Empleado.id == datos.empleado_id, models.Empleado.gimnasio_id == get_gid(usuario)).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    db_asistencia = models.AsistenciaEmpleado(
        empleado_id=datos.empleado_id,
        fecha_hora_entrada=ahora_lima(),
    )
    db.add(db_asistencia)
    db.commit()
    db.refresh(db_asistencia)
    return db_asistencia


@app.put("/asistencias-empleado/{asistencia_id}/salida", response_model=schemas.AsistenciaEmpleado, tags=["Personal"])
def registrar_salida_empleado(asistencia_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    asistencia = (
        db.query(models.AsistenciaEmpleado)
        .join(models.Empleado, models.Empleado.id == models.AsistenciaEmpleado.empleado_id)
        .filter(models.AsistenciaEmpleado.id == asistencia_id, models.Empleado.gimnasio_id == get_gid(usuario))
        .first()
    )
    if not asistencia:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    asistencia.fecha_hora_salida = ahora_lima()
    db.commit()
    db.refresh(asistencia)
    return asistencia


# ==================================================================
# PROGRESO FISICO
# ==================================================================

@app.get("/progreso/cliente/{cliente_id}", response_model=List[schemas.Progreso], tags=["Progreso"])
def progreso_de_cliente(cliente_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff_o_profesor)):
    if not _del_gym(db, models.Cliente, cliente_id, usuario):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return (
        db.query(models.Progreso)
        .filter(models.Progreso.cliente_id == cliente_id, models.Progreso.gimnasio_id == get_gid(usuario))
        .order_by(models.Progreso.fecha.desc())
        .all()
    )


@app.post("/progreso/", response_model=schemas.Progreso, tags=["Progreso"])
def registrar_progreso(datos: schemas.ProgresoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    cliente = _del_gym(db, models.Cliente, datos.cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    db_progreso = models.Progreso(**datos.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_progreso)
    db.commit()
    db.refresh(db_progreso)
    return db_progreso


# ==================================================================
# ENTRENAMIENTOS / RUTINAS
# ==================================================================

# ---- Catalogo de Ejercicios (antes 'Entrenamientos' en el menu) ----
FOTOS_EJERCICIOS_DIR = os.path.join(UPLOADS_DIR, "ejercicios")
os.makedirs(FOTOS_EJERCICIOS_DIR, exist_ok=True)


def _sincronizar_nombres_ejercicios_catalogo():
    """Repara nombres antiguos en rutinas/paquetes que siguen enlazados al catalogo."""
    db = SessionLocal()
    try:
        for ejercicio in db.query(models.RutinaEjercicio).filter(
            models.RutinaEjercicio.tipo_ejercicio_id.isnot(None)
        ).all():
            if ejercicio.tipo_ejercicio and ejercicio.nombre != ejercicio.tipo_ejercicio.nombre:
                ejercicio.nombre = ejercicio.tipo_ejercicio.nombre
        for ejercicio in db.query(models.PaqueteRutinaEjercicio).filter(
            models.PaqueteRutinaEjercicio.tipo_ejercicio_id.isnot(None)
        ).all():
            if ejercicio.tipo_ejercicio and ejercicio.nombre != ejercicio.tipo_ejercicio.nombre:
                ejercicio.nombre = ejercicio.tipo_ejercicio.nombre
        db.commit()
    finally:
        db.close()


@app.get("/tipos-ejercicio/", response_model=List[schemas.TipoEjercicio], tags=["Entrenamientos"])
def listar_tipos_ejercicio(
    solo_activos: bool = True,
    grupo_muscular: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    query = q(db, models.TipoEjercicio, usuario)
    if solo_activos:
        query = query.filter(models.TipoEjercicio.activo == True)
    if grupo_muscular:
        query = query.filter(models.TipoEjercicio.grupo_muscular == grupo_muscular)
    return query.order_by(models.TipoEjercicio.nombre).all()


@app.post("/tipos-ejercicio/", response_model=schemas.TipoEjercicio, tags=["Entrenamientos"])
def crear_tipo_ejercicio(datos: schemas.TipoEjercicioCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gimnasio = _configuracion_del_gym(db, usuario)
    if datos.equipamiento and datos.equipamiento != "sin_equipo" and datos.equipamiento not in _codigos_equipamiento_gym(gimnasio):
        raise HTTPException(status_code=400, detail="El equipamiento indicado no existe en el inventario")
    db_te = models.TipoEjercicio(**datos.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_te)
    db.commit()
    db.refresh(db_te)
    return db_te


@app.put("/tipos-ejercicio/{tipo_id}", response_model=schemas.TipoEjercicio, tags=["Entrenamientos"])
def actualizar_tipo_ejercicio(tipo_id: int, datos: schemas.TipoEjercicioUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    te = db.query(models.TipoEjercicio).filter(models.TipoEjercicio.id == tipo_id, models.TipoEjercicio.gimnasio_id == get_gid(usuario)).first()
    if not te:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    cambios = datos.model_dump(exclude_unset=True)
    equipo_nuevo = cambios.get("equipamiento")
    gimnasio = _configuracion_del_gym(db, usuario)
    if equipo_nuevo and equipo_nuevo != "sin_equipo" and equipo_nuevo not in _codigos_equipamiento_gym(gimnasio):
        raise HTTPException(status_code=400, detail="El equipamiento indicado no existe en el inventario")
    nombre_nuevo = cambios.get("nombre")
    if nombre_nuevo is not None:
        nombre_nuevo = nombre_nuevo.strip()
        if not nombre_nuevo:
            raise HTTPException(status_code=400, detail="El nombre del ejercicio es obligatorio")
        cambios["nombre"] = nombre_nuevo
    nombre_cambio = nombre_nuevo is not None and nombre_nuevo != te.nombre

    for campo, valor in cambios.items():
        setattr(te, campo, valor)

    if nombre_cambio:
        # Las rutinas y paquetes enlazados al catalogo usan el nombre
        # canonico. Los ejercicios de texto libre (sin tipo_ejercicio_id)
        # permanecen intactos.
        gid = get_gid(usuario)
        ids_rutinas = [fila[0] for fila in (
            db.query(models.RutinaEjercicio.id)
            .join(models.RutinaDia, models.RutinaDia.id == models.RutinaEjercicio.dia_id)
            .join(models.Rutina, models.Rutina.id == models.RutinaDia.rutina_id)
            .filter(
                models.RutinaEjercicio.tipo_ejercicio_id == te.id,
                models.Rutina.gimnasio_id == gid,
            ).all()
        )]
        ids_paquetes = [fila[0] for fila in (
            db.query(models.PaqueteRutinaEjercicio.id)
            .join(models.PaqueteRutinaDia, models.PaqueteRutinaDia.id == models.PaqueteRutinaEjercicio.dia_id)
            .join(models.PaqueteRutina, models.PaqueteRutina.id == models.PaqueteRutinaDia.paquete_id)
            .filter(
                models.PaqueteRutinaEjercicio.tipo_ejercicio_id == te.id,
                models.PaqueteRutina.gimnasio_id == gid,
            ).all()
        )]
        if ids_rutinas:
            db.query(models.RutinaEjercicio).filter(
                models.RutinaEjercicio.id.in_(ids_rutinas)
            ).update({models.RutinaEjercicio.nombre: nombre_nuevo}, synchronize_session=False)
        if ids_paquetes:
            db.query(models.PaqueteRutinaEjercicio).filter(
                models.PaqueteRutinaEjercicio.id.in_(ids_paquetes)
            ).update({models.PaqueteRutinaEjercicio.nombre: nombre_nuevo}, synchronize_session=False)
    db.commit()
    db.refresh(te)
    return te


@app.delete("/tipos-ejercicio/{tipo_id}", tags=["Entrenamientos"])
def eliminar_tipo_ejercicio(tipo_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    te = db.query(models.TipoEjercicio).filter(models.TipoEjercicio.id == tipo_id, models.TipoEjercicio.gimnasio_id == get_gid(usuario)).first()
    if not te:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    te.activo = False
    db.commit()
    return {"message": "Ejercicio desactivado correctamente"}


@app.post("/tipos-ejercicio/{tipo_id}/imagen", response_model=schemas.TipoEjercicio, tags=["Entrenamientos"])
async def subir_imagen_tipo_ejercicio(
    tipo_id: int,
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Sube/reemplaza la imagen demostrativa de un ejercicio del catalogo."""
    te = db.query(models.TipoEjercicio).filter(models.TipoEjercicio.id == tipo_id, models.TipoEjercicio.gimnasio_id == get_gid(usuario)).first()
    if not te:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    contenido, tipo = _validar_y_optimizar_foto(await foto.read(), foto.content_type, optimizar=True)
    te.imagen_datos = contenido
    te.imagen_tipo = tipo
    te.imagen_url = f"/tipos-ejercicio/{te.id}/imagen-publica"
    db.commit()
    db.refresh(te)
    return te


@app.get("/tipos-ejercicio/{tipo_id}/imagen-publica", tags=["Entrenamientos"])
def imagen_publica_tipo_ejercicio(tipo_id: int, db: Session = Depends(get_db)):
    te = db.query(models.TipoEjercicio).filter(models.TipoEjercicio.id == tipo_id, models.TipoEjercicio.activo == True).first()
    if not te or not te.imagen_datos:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    return Response(content=te.imagen_datos, media_type=te.imagen_tipo or "image/webp", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/rutinas/recomendar/{cliente_id}", response_model=schemas.RecomendacionRutina, tags=["Entrenamientos"])
def recomendar_paquetes_rutina_cliente(
    cliente_id: int,
    objetivo: Optional[str] = None,
    nivel: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    """Ordena paquetes existentes segun perfil, ultima medida y meta del alumno."""
    cliente = _del_gym(db, models.Cliente, cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    objetivos_validos = {"inicio", "bajar_peso", "ganar_masa", "tonificacion", "definicion", "rendimiento"}
    niveles_validos = {"basico", "intermedio", "avanzado", "competencia"}
    if objetivo is not None and objetivo not in objetivos_validos:
        raise HTTPException(status_code=400, detail="Objetivo de rutina no valido")
    if nivel is not None and nivel not in niveles_validos:
        raise HTTPException(status_code=400, detail="Nivel de rutina no valido")

    medida = (
        db.query(models.Medida)
        .filter(models.Medida.cliente_id == cliente.id, models.Medida.gimnasio_id == get_gid(usuario))
        .order_by(models.Medida.fecha.desc(), models.Medida.id.desc())
        .first()
    )
    genero_crudo = (cliente.genero or "").strip().lower()
    genero = "femenino" if genero_crudo.startswith("fem") else "masculino" if genero_crudo.startswith("mas") else "todos"
    edad = None
    if cliente.fecha_nacimiento:
        hoy = hoy_lima()
        edad = hoy.year - cliente.fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (cliente.fecha_nacimiento.month, cliente.fecha_nacimiento.day)
        )

    peso = medida.peso_kg if medida else None
    estatura = medida.estatura_cm if medida else None
    imc = round(peso / ((estatura / 100) ** 2), 1) if peso and estatura else None
    peso_objetivo = medida.peso_objetivo_kg if medida else None
    razones_perfil = []

    objetivo_sugerido = objetivo
    if not objetivo_sugerido and peso and peso_objetivo:
        diferencia_pct = (peso_objetivo - peso) / peso
        if diferencia_pct <= -0.03:
            objetivo_sugerido = "bajar_peso"
            razones_perfil.append(f"Meta de peso: bajar de {peso:.1f} a {peso_objetivo:.1f} kg")
        elif diferencia_pct >= 0.03:
            objetivo_sugerido = "ganar_masa"
            razones_perfil.append(f"Meta de peso: subir de {peso:.1f} a {peso_objetivo:.1f} kg")
    if not objetivo_sugerido:
        if imc is None:
            objetivo_sugerido = "inicio"
            razones_perfil.append("Sin peso y estatura completos: se prioriza adaptacion")
        elif imc >= 30:
            objetivo_sugerido = "bajar_peso"
            razones_perfil.append(f"IMC {imc}: se prioriza reduccion de peso con progresion segura")
        elif imc >= 25:
            objetivo_sugerido = "definicion"
            razones_perfil.append(f"IMC {imc}: se prioriza composicion corporal")
        elif imc < 18.5:
            objetivo_sugerido = "ganar_masa"
            razones_perfil.append(f"IMC {imc}: se prioriza ganancia de masa")
        else:
            objetivo_sugerido = "tonificacion"
            razones_perfil.append(f"IMC {imc}: rango saludable, se prioriza tonificacion")
    elif objetivo is not None:
        razones_perfil.append("Objetivo seleccionado por el entrenador o el alumno")

    rutinas_previas = q(db, models.Rutina, usuario).filter(
        models.Rutina.cliente_id == cliente.id,
        models.Rutina.activo == True,
    ).count()
    nivel_sugerido = nivel or ("intermedio" if rutinas_previas >= 2 and (edad is None or 16 <= edad <= 60) else "basico")
    if nivel is None:
        razones_perfil.append(
            "Nivel intermedio por historial de rutinas" if nivel_sugerido == "intermedio"
            else "Nivel basico para iniciar con una progresion controlada"
        )

    niveles_orden = {"basico": 0, "intermedio": 1, "avanzado": 2, "competencia": 3}
    paquetes = q(db, models.PaqueteRutina, usuario).filter(models.PaqueteRutina.activo == True).all()
    compatibles_genero = [p for p in paquetes if p.genero_recomendado in {"todos", genero}]
    if compatibles_genero:
        paquetes = compatibles_genero

    opciones = []
    for paquete in paquetes:
        puntuacion = 0
        motivos = []
        if paquete.objetivo == objetivo_sugerido:
            puntuacion += 55
            motivos.append("Coincide con el objetivo")
        elif {paquete.objetivo, objetivo_sugerido} <= {"tonificacion", "definicion"}:
            puntuacion += 24
            motivos.append("Objetivo de composicion corporal compatible")

        if paquete.genero_recomendado == genero and genero != "todos":
            puntuacion += 20
            motivos.append(f"Perfil {genero}")
        elif paquete.genero_recomendado == "todos":
            puntuacion += 13
            motivos.append("Perfil mixto compatible")

        distancia_nivel = abs(niveles_orden.get(paquete.nivel, 0) - niveles_orden.get(nivel_sugerido, 0))
        if distancia_nivel == 0:
            puntuacion += 25
            motivos.append(f"Nivel {nivel_sugerido}")
        elif distancia_nivel == 1:
            puntuacion += 8
            motivos.append("Nivel cercano, requiere adaptacion")
        else:
            puntuacion -= 12

        if edad is not None:
            if paquete.edad_min is not None and edad < paquete.edad_min:
                puntuacion -= 30
            if paquete.edad_max is not None and edad > paquete.edad_max:
                puntuacion -= 30
        opciones.append({"paquete": paquete, "puntuacion": puntuacion, "motivos": motivos})

    opciones.sort(key=lambda opcion: (-opcion["puntuacion"], opcion["paquete"].nombre))
    return {
        "perfil": {
            "genero": genero,
            "edad": edad,
            "peso_kg": peso,
            "estatura_cm": estatura,
            "imc": imc,
            "peso_objetivo_kg": peso_objetivo,
            "objetivo_sugerido": objetivo_sugerido,
            "nivel_sugerido": nivel_sugerido,
            "razones": razones_perfil,
        },
        "opciones": opciones[:5],
    }


@app.post("/paquetes-rutina/guardar-y-asignar", response_model=schemas.GuardarRecomendacionRutinaResponse, tags=["Entrenamientos"])
def guardar_recomendacion_rutina(
    datos: schemas.GuardarRecomendacionRutinaRequest,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    """Guarda una recomendacion editada como paquete nuevo y la asigna en una sola transaccion."""
    origen = _del_gym(db, models.PaqueteRutina, datos.paquete_origen_id, usuario)
    cliente = _del_gym(db, models.Cliente, datos.cliente_id, usuario)
    if not origen:
        raise HTTPException(status_code=404, detail="Paquete de origen no encontrado")
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    _validar_limite_plan(db, usuario, "rutinas")
    _validar_perfil_paquete(datos.paquete)
    nombre_nuevo = datos.paquete.nombre.strip()
    if nombre_nuevo.casefold() == origen.nombre.strip().casefold():
        raise HTTPException(status_code=400, detail="Debes poner un nombre nuevo al paquete adaptado")

    paquete = models.PaqueteRutina(
        gimnasio_id=get_gid(usuario),
        nombre=nombre_nuevo,
        descripcion=datos.paquete.descripcion,
        nivel=datos.paquete.nivel,
        objetivo=datos.paquete.objetivo,
        etapa=datos.paquete.etapa,
        genero_recomendado=datos.paquete.genero_recomendado,
        edad_min=datos.paquete.edad_min,
        edad_max=datos.paquete.edad_max,
        duracion_semanas=datos.paquete.duracion_semanas,
        dias=_validar_dias_paquete(datos.paquete.dias, db, usuario),
    )
    db.add(paquete)
    db.flush()

    dias_rutina = [models.RutinaDia(
        nombre=dia.nombre,
        orden=dia.orden,
        ejercicios=[models.RutinaEjercicio(
            tipo_ejercicio_id=ejercicio.tipo_ejercicio_id,
            nombre=ejercicio.nombre,
            series=ejercicio.series,
            repeticiones=ejercicio.repeticiones,
            peso=ejercicio.peso,
            notas=ejercicio.notas,
        ) for ejercicio in dia.ejercicios],
    ) for dia in paquete.dias]
    rutina = models.Rutina(
        gimnasio_id=get_gid(usuario),
        cliente_id=cliente.id,
        nombre=nombre_nuevo,
        dias=dias_rutina,
    )
    db.add(rutina)
    db.commit()
    db.refresh(paquete)
    db.refresh(rutina)
    return {"paquete": paquete, "rutina": rutina}


@app.get("/rutinas/cliente/{cliente_id}", response_model=List[schemas.Rutina], tags=["Entrenamientos"])
def rutinas_de_cliente(cliente_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff_o_profesor)):
    if not _del_gym(db, models.Cliente, cliente_id, usuario):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return db.query(models.Rutina).filter(
        models.Rutina.cliente_id == cliente_id,
        models.Rutina.gimnasio_id == get_gid(usuario),
        models.Rutina.activo == True,
    ).all()


@app.post("/rutina-dias/{dia_id}/ejercicios", response_model=schemas.RutinaEjercicio, tags=["Entrenamientos"])
def agregar_ejercicio_a_dia(
    dia_id: int,
    datos: schemas.RutinaEjercicioCreate,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    """Agrega un ejercicio a un dia de rutina ya existente. Si tipo_ejercicio_id viene del catalogo, el nombre puede autocompletarse en el frontend pero queda editable."""
    dia = _rutina_dia_del_gym(db, dia_id, usuario)
    if not dia:
        raise HTTPException(status_code=404, detail="Dia de rutina no encontrado")
    ej = models.RutinaEjercicio(dia_id=dia_id, **datos.model_dump())
    db.add(ej)
    db.commit()
    db.refresh(ej)
    return ej


@app.delete("/rutina-ejercicios/{ejercicio_id}", tags=["Entrenamientos"])
def eliminar_ejercicio_de_dia(ejercicio_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff_o_profesor)):
    ej = _rutina_ejercicio_del_gym(db, ejercicio_id, usuario)
    if not ej:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    db.delete(ej)
    db.commit()
    return {"message": "Ejercicio eliminado"}


@app.post("/rutinas/", response_model=schemas.Rutina, tags=["Entrenamientos"])
def crear_rutina(datos: schemas.RutinaCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    _validar_limite_plan(db, usuario, "rutinas")
    cliente = _del_gym(db, models.Cliente, datos.cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    dias_db = []
    for dia in datos.dias:
        ejercicios_db = [models.RutinaEjercicio(**ej.model_dump()) for ej in dia.ejercicios]
        dias_db.append(models.RutinaDia(nombre=dia.nombre, orden=dia.orden, ejercicios=ejercicios_db))

    db_rutina = models.Rutina(cliente_id=datos.cliente_id, nombre=datos.nombre, dias=dias_db, gimnasio_id=get_gid(usuario))
    db.add(db_rutina)
    db.commit()
    db.refresh(db_rutina)
    return db_rutina


@app.delete("/rutinas/{rutina_id}", tags=["Entrenamientos"])
def eliminar_rutina(rutina_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    rutina = _del_gym(db, models.Rutina, rutina_id, usuario)
    if not rutina:
        raise HTTPException(status_code=404, detail="Rutina no encontrada")
    db.delete(rutina)
    db.commit()
    return {"ok": True}


def _validar_dias_paquete(datos_dias, db: Session, usuario):
    """Valida referencias al catalogo y construye el arbol de una plantilla."""
    gid = get_gid(usuario)
    ids = {
        ejercicio.tipo_ejercicio_id
        for dia in datos_dias for ejercicio in dia.ejercicios
        if ejercicio.tipo_ejercicio_id is not None
    }
    if ids:
        ejercicios_catalogo = db.query(models.TipoEjercicio).filter(
                models.TipoEjercicio.gimnasio_id == gid,
                models.TipoEjercicio.id.in_(ids),
            ).all()
        validos = {ejercicio.id for ejercicio in ejercicios_catalogo}
        if validos != ids:
            raise HTTPException(status_code=400, detail="Uno o mas ejercicios no pertenecen a este gimnasio")
    return [
        models.PaqueteRutinaDia(
            nombre=dia.nombre,
            orden=dia.orden,
            ejercicios=[models.PaqueteRutinaEjercicio(**ej.model_dump()) for ej in dia.ejercicios],
        )
        for dia in datos_dias
    ]


def _alternativa_ejercicio_disponible(
    db: Session,
    ejercicio: models.TipoEjercicio,
    disponibles: set,
) -> Optional[models.TipoEjercicio]:
    """Busca un equivalente realizable sin modificar la plantilla original."""
    if (ejercicio.equipamiento or "sin_equipo") in disponibles:
        return ejercicio
    candidatos = db.query(models.TipoEjercicio).filter(
        models.TipoEjercicio.gimnasio_id == ejercicio.gimnasio_id,
        models.TipoEjercicio.activo == True,
        models.TipoEjercicio.id != ejercicio.id,
        models.TipoEjercicio.grupo_muscular == ejercicio.grupo_muscular,
        models.TipoEjercicio.equipamiento.in_(disponibles),
    ).all()
    if not candidatos:
        return None

    def puntuacion(candidato):
        return (
            (50 if candidato.categoria == ejercicio.categoria else 0)
            + (30 if (candidato.equipamiento or "sin_equipo") == "sin_equipo" else 0)
            + (15 if candidato.objetivo == ejercicio.objetivo else 0)
            + (10 if candidato.nivel == ejercicio.nivel else 0)
            + (5 if candidato.genero_recomendado == ejercicio.genero_recomendado else 0)
        )

    return sorted(candidatos, key=lambda c: (-puntuacion(c), c.nombre))[0]


def _validar_perfil_paquete(datos):
    if datos.edad_min is not None and datos.edad_max is not None and datos.edad_max < datos.edad_min:
        raise HTTPException(status_code=400, detail="La edad maxima no puede ser menor que la edad minima")
    if not datos.nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre del paquete es obligatorio")


@app.get("/paquetes-rutina/", response_model=List[schemas.PaqueteRutina], tags=["Entrenamientos"])
def listar_paquetes_rutina(
    solo_activos: bool = True,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    query = q(db, models.PaqueteRutina, usuario)
    if solo_activos:
        query = query.filter(models.PaqueteRutina.activo == True)
    return query.order_by(models.PaqueteRutina.nivel, models.PaqueteRutina.nombre).all()


@app.post("/paquetes-rutina/", response_model=schemas.PaqueteRutina, tags=["Entrenamientos"])
def crear_paquete_rutina(
    datos: schemas.PaqueteRutinaCreate,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    _validar_perfil_paquete(datos)
    paquete = models.PaqueteRutina(
        gimnasio_id=get_gid(usuario),
        nombre=datos.nombre.strip(),
        descripcion=datos.descripcion,
        nivel=datos.nivel,
        objetivo=datos.objetivo,
        etapa=datos.etapa,
        genero_recomendado=datos.genero_recomendado,
        edad_min=datos.edad_min,
        edad_max=datos.edad_max,
        duracion_semanas=datos.duracion_semanas,
        dias=_validar_dias_paquete(datos.dias, db, usuario),
    )
    db.add(paquete)
    db.commit()
    db.refresh(paquete)
    return paquete


@app.put("/paquetes-rutina/{paquete_id}", response_model=schemas.PaqueteRutina, tags=["Entrenamientos"])
def actualizar_paquete_rutina(
    paquete_id: int,
    datos: schemas.PaqueteRutinaCreate,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    paquete = _del_gym(db, models.PaqueteRutina, paquete_id, usuario)
    if not paquete:
        raise HTTPException(status_code=404, detail="Paquete de rutina no encontrado")
    _validar_perfil_paquete(datos)
    for campo in ("descripcion", "nivel", "objetivo", "etapa", "genero_recomendado", "edad_min", "edad_max", "duracion_semanas"):
        setattr(paquete, campo, getattr(datos, campo))
    paquete.nombre = datos.nombre.strip()
    paquete.dias.clear()
    paquete.dias.extend(_validar_dias_paquete(datos.dias, db, usuario))
    db.commit()
    db.refresh(paquete)
    return paquete


@app.delete("/paquetes-rutina/{paquete_id}", tags=["Entrenamientos"])
def desactivar_paquete_rutina(
    paquete_id: int,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff),
):
    paquete = _del_gym(db, models.PaqueteRutina, paquete_id, usuario)
    if not paquete:
        raise HTTPException(status_code=404, detail="Paquete de rutina no encontrado")
    paquete.activo = False
    db.commit()
    return {"ok": True}


@app.post("/paquetes-rutina/{paquete_id}/asignar", response_model=schemas.Rutina, tags=["Entrenamientos"])
def asignar_paquete_rutina(
    paquete_id: int,
    datos: schemas.AsignarPaqueteRutina,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff_o_profesor),
):
    _validar_limite_plan(db, usuario, "rutinas")
    paquete = _del_gym(db, models.PaqueteRutina, paquete_id, usuario)
    cliente = _del_gym(db, models.Cliente, datos.cliente_id, usuario)
    if not paquete or not paquete.activo:
        raise HTTPException(status_code=404, detail="Paquete de rutina no encontrado")
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    disponibles = _equipamiento_disponible_gym(_configuracion_del_gym(db, usuario))
    dias = []
    sin_alternativa = []
    for dia in paquete.dias:
        ejercicios_adaptados = []
        for ejercicio_paquete in dia.ejercicios:
            original = ejercicio_paquete.tipo_ejercicio
            elegido = _alternativa_ejercicio_disponible(db, original, disponibles) if original else None
            if original and not elegido:
                sin_alternativa.append(original.nombre)
                continue
            fue_adaptado = bool(original and elegido and elegido.id != original.id)
            notas = ejercicio_paquete.notas
            if fue_adaptado:
                aviso = f"Adaptado automaticamente de: {original.nombre}"
                notas = f"{notas}\n{aviso}" if notas else aviso
            ejercicios_adaptados.append(models.RutinaEjercicio(
                tipo_ejercicio_id=elegido.id if elegido else ejercicio_paquete.tipo_ejercicio_id,
                nombre=elegido.nombre if elegido else ejercicio_paquete.nombre,
                series=ejercicio_paquete.series,
                repeticiones=ejercicio_paquete.repeticiones,
                peso=ejercicio_paquete.peso,
                notas=notas,
            ))
        dias.append(models.RutinaDia(nombre=dia.nombre, orden=dia.orden, ejercicios=ejercicios_adaptados))

    if sin_alternativa:
        raise HTTPException(
            status_code=400,
            detail="No existe una alternativa disponible para: " + ", ".join(sorted(set(sin_alternativa))),
        )
    rutina = models.Rutina(
        gimnasio_id=get_gid(usuario),
        cliente_id=cliente.id,
        nombre=(datos.nombre or paquete.nombre).strip(),
        dias=dias,
    )
    db.add(rutina)
    db.commit()
    db.refresh(rutina)
    return rutina


# ==================================================================
# NUTRICION
# ==================================================================

# ---- Catalogo de Alimentos (editable, base peruana precargada) ----

@app.get("/alimentos/", response_model=List[schemas.Alimento], tags=["Nutricion"])
def listar_alimentos(
    solo_activos: bool = True,
    categoria: Optional[models.CategoriaAlimento] = None,
    buscar: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    query = q(db, models.Alimento, usuario)
    if solo_activos:
        query = query.filter(models.Alimento.activo == True)
    if categoria:
        query = query.filter(models.Alimento.categoria == categoria)
    if buscar:
        query = query.filter(models.Alimento.nombre.ilike(f"%{buscar}%"))
    return query.order_by(models.Alimento.nombre).all()


@app.post("/alimentos/", response_model=schemas.Alimento, tags=["Nutricion"])
def crear_alimento(datos: schemas.AlimentoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    db_al = models.Alimento(**datos.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_al)
    db.commit()
    db.refresh(db_al)
    return db_al


@app.put("/alimentos/{alimento_id}", response_model=schemas.Alimento, tags=["Nutricion"])
def actualizar_alimento(alimento_id: int, datos: schemas.AlimentoUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    al = db.query(models.Alimento).filter(models.Alimento.id == alimento_id, models.Alimento.gimnasio_id == get_gid(usuario)).first()
    if not al:
        raise HTTPException(status_code=404, detail="Alimento no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(al, campo, valor)
    db.commit()
    db.refresh(al)
    return al


@app.delete("/alimentos/{alimento_id}", tags=["Nutricion"])
def eliminar_alimento(alimento_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    al = db.query(models.Alimento).filter(models.Alimento.id == alimento_id, models.Alimento.gimnasio_id == get_gid(usuario)).first()
    if not al:
        raise HTTPException(status_code=404, detail="Alimento no encontrado")
    al.activo = False
    db.commit()
    return {"message": "Alimento desactivado correctamente"}


# ---- Paquetes de nutricion (plantillas desayuno/almuerzo/cena por proposito) ----

@app.get("/paquetes-nutricion/", response_model=List[schemas.PaqueteNutricion], tags=["Nutricion"])
def listar_paquetes_nutricion(
    tipo_comida: Optional[models.TipoComida] = None,
    proposito: Optional[models.PropositoNutricion] = None,
    solo_activos: bool = True,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    query = q(db, models.PaqueteNutricion, usuario)
    if solo_activos:
        query = query.filter(models.PaqueteNutricion.activo == True)
    if tipo_comida:
        query = query.filter(models.PaqueteNutricion.tipo_comida == tipo_comida)
    if proposito:
        query = query.filter(models.PaqueteNutricion.proposito == proposito)
    return query.order_by(models.PaqueteNutricion.nombre).all()


@app.post("/paquetes-nutricion/", response_model=schemas.PaqueteNutricion, tags=["Nutricion"])
def crear_paquete_nutricion(datos: schemas.PaqueteNutricionCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    items_db = []
    for item in datos.items:
        alimento = _del_gym(db, models.Alimento, item.alimento_id, usuario)
        if not alimento:
            raise HTTPException(status_code=404, detail="Alimento no encontrado")
        gramos_item = _limitar_gramos_proteina(alimento, item.cantidad_gramos)
        items_db.append(models.PaqueteAlimento(
            alimento_id=item.alimento_id,
            cantidad_gramos=gramos_item,
            porcion_cliente=_porcion_cliente_facil(alimento, gramos_item, item.porcion_cliente),
        ))
    db_paq = models.PaqueteNutricion(
        nombre=datos.nombre, tipo_comida=datos.tipo_comida, proposito=datos.proposito,
        notas=datos.notas, items=items_db, gimnasio_id=get_gid(usuario),
    )
    db.add(db_paq)
    db.commit()
    db.refresh(db_paq)
    return db_paq


@app.put("/paquetes-nutricion/{paquete_id}", response_model=schemas.PaqueteNutricion, tags=["Nutricion"])
def actualizar_paquete_nutricion(
    paquete_id: int,
    datos: schemas.PaqueteNutricionUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    paq = db.query(models.PaqueteNutricion).filter(models.PaqueteNutricion.id == paquete_id, models.PaqueteNutricion.gimnasio_id == get_gid(usuario)).first()
    if not paq:
        raise HTTPException(status_code=404, detail="Paquete no encontrado")
    datos_dict = datos.model_dump(exclude_unset=True)
    items_nuevos = datos_dict.pop("items", None)
    for campo, valor in datos_dict.items():
        setattr(paq, campo, valor)
    if items_nuevos is not None:
        db.query(models.PaqueteAlimento).filter(models.PaqueteAlimento.paquete_id == paquete_id).delete()
        for item in items_nuevos:
            alimento = _del_gym(db, models.Alimento, item["alimento_id"], usuario)
            if not alimento:
                raise HTTPException(status_code=404, detail="Alimento no encontrado")
            gramos_item = _limitar_gramos_proteina(alimento, item["cantidad_gramos"])
            db.add(models.PaqueteAlimento(
                paquete_id=paquete_id,
                alimento_id=item["alimento_id"],
                cantidad_gramos=gramos_item,
                porcion_cliente=_porcion_cliente_facil(
                    alimento, gramos_item, item.get("porcion_cliente")
                ),
            ))
    db.commit()
    db.refresh(paq)
    return paq


@app.delete("/paquetes-nutricion/{paquete_id}", tags=["Nutricion"])
def eliminar_paquete_nutricion(paquete_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    paq = db.query(models.PaqueteNutricion).filter(models.PaqueteNutricion.id == paquete_id, models.PaqueteNutricion.gimnasio_id == get_gid(usuario)).first()
    if not paq:
        raise HTTPException(status_code=404, detail="Paquete no encontrado")
    paq.activo = False
    db.commit()
    return {"message": "Paquete desactivado correctamente"}


@app.post("/paquetes-nutricion/{paquete_id}/aplicar", response_model=List[schemas.ComidaPlan], tags=["Nutricion"])
def aplicar_paquete_a_plan(
    paquete_id: int,
    datos: schemas.AplicarPaqueteRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """Genera las filas ComidaPlan de un plan de cliente a partir de los alimentos de un Paquete (calcula las calorias segun la cantidad_gramos de cada item)."""
    paquete = _del_gym(db, models.PaqueteNutricion, paquete_id, usuario)
    if not paquete:
        raise HTTPException(status_code=404, detail="Paquete no encontrado")
    plan = _del_gym(db, models.PlanNutricion, datos.plan_id, usuario)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan de nutricion no encontrado")

    # tipo de ComidaPlan: 'comida' es el nombre historico para almuerzo
    tipo_comida_map = {
        models.TipoComida.DESAYUNO: models.TipoComida.DESAYUNO,
        models.TipoComida.COMIDA: models.TipoComida.COMIDA,
        models.TipoComida.CENA: models.TipoComida.CENA,
        models.TipoComida.APERITIVO: models.TipoComida.APERITIVO,
    }

    creadas = []
    for item in paquete.items:
        alimento = item.alimento
        gramos_item = _limitar_gramos_proteina(alimento, item.cantidad_gramos)
        factor = gramos_item / (alimento.porcion_gramos or 100.0)
        calorias_item = round((alimento.calorias or 0.0) * factor)
        porcion_cliente = _porcion_cliente_facil(
            alimento, gramos_item
        )
        comida = models.ComidaPlan(
            plan_id=plan.id,
            tipo=tipo_comida_map[paquete.tipo_comida],
            alimento_id=alimento.id,
            nombre_alimento=alimento.nombre,
            calorias=calorias_item,
            cantidad_gramos=gramos_item,
            porcion_cliente=porcion_cliente,
        )
        db.add(comida)
        creadas.append(comida)

    db.commit()
    for c in creadas:
        db.refresh(c)
    return creadas


@app.get("/nutricion/", response_model=List[schemas.PlanNutricion], tags=["Nutricion"])
def listar_planes_nutricion(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    return q(db, models.PlanNutricion, usuario).filter(models.PlanNutricion.activo == True).all()


@app.get("/nutricion/cliente/{cliente_id}", response_model=List[schemas.PlanNutricion], tags=["Nutricion"])
def planes_de_cliente(cliente_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    if not _del_gym(db, models.Cliente, cliente_id, usuario):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return (
        db.query(models.PlanNutricion)
        .filter(
            models.PlanNutricion.cliente_id == cliente_id,
            models.PlanNutricion.gimnasio_id == get_gid(usuario),
            models.PlanNutricion.activo == True,
        )
        .all()
    )


@app.post("/nutricion/", response_model=schemas.PlanNutricion, tags=["Nutricion"])
def crear_plan_nutricion(datos: schemas.PlanNutricionCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    _validar_nutricion_habilitada(db, usuario)
    if datos.cliente_id is not None and not _del_gym(db, models.Cliente, datos.cliente_id, usuario):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    comidas_db = []
    for comida in datos.comidas:
        alimento = None
        if comida.alimento_id is not None:
            alimento = _del_gym(db, models.Alimento, comida.alimento_id, usuario)
            if not alimento:
                raise HTTPException(status_code=404, detail="Alimento no encontrado")
        datos_comida = comida.model_dump()
        if alimento:
            datos_comida["cantidad_gramos"] = _limitar_gramos_proteina(
                alimento, comida.cantidad_gramos
            )
            datos_comida["nombre_alimento"] = alimento.nombre
            datos_comida["porcion_cliente"] = _porcion_cliente_facil(
                alimento, datos_comida["cantidad_gramos"], comida.porcion_cliente
            )
            factor = datos_comida["cantidad_gramos"] / float(alimento.porcion_gramos or 100)
            datos_comida["calorias"] = round((alimento.calorias or 0.0) * factor)
        comidas_db.append(models.ComidaPlan(**datos_comida))
    db_plan = models.PlanNutricion(
        cliente_id=datos.cliente_id,
        titulo=datos.titulo,
        descripcion=datos.descripcion,
        calorias_objetivo=datos.calorias_objetivo,
        comidas=comidas_db,
        gimnasio_id=get_gid(usuario),
    )
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan


@app.put("/nutricion/{plan_id}", response_model=schemas.PlanNutricion, tags=["Nutricion"])
def actualizar_plan_nutricion(plan_id: int, datos: schemas.PlanNutricionUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    """
    Actualiza campos sueltos de un plan (titulo, descripcion, calorias
    objetivo o activo). Se usa sobre todo para desactivar un plan
    (activo=False) cuando se lo reemplaza por una version adaptada
    nueva, sin borrar el historico.
    """
    plan = _del_gym(db, models.PlanNutricion, plan_id, usuario)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(plan, campo, valor)
    db.commit()
    db.refresh(plan)
    return plan


# ---- Generacion automatica de plan segun medidas (peso/estatura/edad/sexo) ----

def _cliente_tiene_nutricion_incluida(db: Session, cliente_id: int) -> bool:
    """True si el cliente tiene una membresia activa y vigente cuyo plan incluye nutricion (Membresia.incluye_nutricion)."""
    hoy = hoy_lima()
    cm = (
        db.query(models.ClienteMembresia)
        .join(models.Membresia, models.ClienteMembresia.membresia_id == models.Membresia.id)
        .filter(
            models.ClienteMembresia.cliente_id == cliente_id,
            models.ClienteMembresia.activo == True,
            models.Membresia.incluye_nutricion == True,
            (models.ClienteMembresia.fecha_fin.is_(None)) | (models.ClienteMembresia.fecha_fin >= hoy),
        )
        .first()
    )
    return cm is not None


def _computar_perfil_nutricional(cliente: models.Cliente, medida: Optional[models.Medida]) -> Optional[dict]:
    """
    Calcula BMR (formula Mifflin-St Jeor, distinta para hombre/mujer),
    el gasto energetico total (TDEE, actividad moderada por defecto ya
    que el nivel de actividad no se persiste en Medida) y determina el
    proposito nutricional segun el IMC:
        IMC < 18.5        -> ganar_masa   (superavit)
        18.5 <= IMC < 25  -> mantenimiento
        25   <= IMC < 30  -> definicion   (deficit leve)
        IMC >= 30         -> bajar_peso   (deficit mayor)
    Devuelve None si faltan datos indispensables (fecha de nacimiento
    del cliente, o peso/estatura en la ultima toma de medidas).
    """
    if not medida or not medida.peso_kg or not medida.estatura_cm:
        return None
    if not cliente.fecha_nacimiento:
        return None

    hoy = hoy_lima()
    edad = hoy.year - cliente.fecha_nacimiento.year - ((hoy.month, hoy.day) < (cliente.fecha_nacimiento.month, cliente.fecha_nacimiento.day))
    if edad <= 0 or edad > 110:
        return None

    peso = medida.peso_kg
    estatura_cm = medida.estatura_cm
    estatura_m = estatura_cm / 100
    if estatura_m <= 0:
        return None

    es_mujer = (cliente.genero or "").strip().lower().startswith("fem")
    bmr = 10 * peso + 6.25 * estatura_cm - 5 * edad + (-161 if es_mujer else 5)
    tdee = bmr * 1.55  # actividad moderada (no se pide nivel de actividad al registrar medidas)

    imc = peso / (estatura_m ** 2)
    if imc < 18.5:
        proposito, ajuste = models.PropositoNutricion.GANAR_MASA, 1.15
    elif imc < 25:
        proposito, ajuste = models.PropositoNutricion.MANTENIMIENTO, 1.0
    elif imc < 30:
        proposito, ajuste = models.PropositoNutricion.DEFINICION, 0.90
    else:
        proposito, ajuste = models.PropositoNutricion.BAJAR_PESO, 0.80

    calorias_objetivo = round(tdee * ajuste)
    return {
        "imc": round(imc, 1),
        "bmr": round(bmr),
        "tdee": round(tdee),
        "proposito": proposito,
        "calorias_objetivo": calorias_objetivo,
        "reparto": {
            "desayuno": round(calorias_objetivo * 0.28),
            "comida": round(calorias_objetivo * 0.42),
            "cena": round(calorias_objetivo * 0.30),
        },
    }


def _calorias_totales_paquete(paquete: models.PaqueteNutricion) -> float:
    total = 0.0
    for item in paquete.items:
        alimento = item.alimento
        if not alimento:
            continue
        factor = (item.cantidad_gramos or 0.0) / (alimento.porcion_gramos or 100.0)
        total += (alimento.calorias or 0.0) * factor
    return total


def _elegir_paquete_por_calorias(db: Session, gimnasio_id: int, tipo_comida, proposito, kcal_objetivo: float) -> Optional[models.PaqueteNutricion]:
    """De los paquetes activos que calzan con el tipo de comida y el proposito, elige el que mas se acerca a kcal_objetivo."""
    candidatos = (
        db.query(models.PaqueteNutricion)
        .filter(
            models.PaqueteNutricion.tipo_comida == tipo_comida,
            models.PaqueteNutricion.proposito == proposito,
            models.PaqueteNutricion.activo == True,
            models.PaqueteNutricion.gimnasio_id == gimnasio_id,
        )
        .all()
    )
    if not candidatos:
        return None
    return min(candidatos, key=lambda p: abs(_calorias_totales_paquete(p) - kcal_objetivo))


_ETIQUETAS_PROPOSITO = {
    models.PropositoNutricion.BAJAR_PESO: "Bajar de peso",
    models.PropositoNutricion.GANAR_MASA: "Ganar masa muscular",
    models.PropositoNutricion.MANTENIMIENTO: "Mantenimiento",
    models.PropositoNutricion.DEFINICION: "Definicion",
}


def _generar_plan_automatico_interno(db: Session, cliente: models.Cliente, perfil: dict) -> models.PlanNutricion:
    """
    Crea el plan automatico del cliente (desactivando el automatico
    anterior, si tenia uno; los planes creados a mano por el staff
    nunca se tocan) escogiendo, para desayuno/almuerzo/cena, el
    paquete cuyo total calorico mas se acerca al reparto calculado.
    """
    db.query(models.PlanNutricion).filter(
        models.PlanNutricion.cliente_id == cliente.id,
        models.PlanNutricion.origen == "automatico",
        models.PlanNutricion.activo == True,
    ).update({"activo": False})

    comidas_db = []
    tipos_map = {"desayuno": models.TipoComida.DESAYUNO, "comida": models.TipoComida.COMIDA, "cena": models.TipoComida.CENA}
    for clave, tipo_enum in tipos_map.items():
        paquete = _elegir_paquete_por_calorias(db, cliente.gimnasio_id, tipo_enum, perfil["proposito"], perfil["reparto"][clave])
        if not paquete:
            continue
        for item in paquete.items:
            alimento = item.alimento
            if not alimento:
                continue
            gramos_item = _limitar_gramos_proteina(alimento, item.cantidad_gramos)
            factor = gramos_item / (alimento.porcion_gramos or 100.0)
            comidas_db.append(models.ComidaPlan(
                tipo=tipo_enum, alimento_id=alimento.id,
                nombre_alimento=alimento.nombre,
                calorias=round((alimento.calorias or 0.0) * factor),
                cantidad_gramos=gramos_item,
                porcion_cliente=_porcion_cliente_facil(
                    alimento, gramos_item
                ),
            ))

    db_plan = models.PlanNutricion(
        cliente_id=cliente.id,
        titulo=f"Plan automatico - {_ETIQUETAS_PROPOSITO[perfil['proposito']]}",
        descripcion=f"Generado segun IMC {perfil['imc']}, BMR {perfil['bmr']} kcal, gasto energetico estimado {perfil['tdee']} kcal.",
        calorias_objetivo=perfil["calorias_objetivo"],
        origen="automatico",
        comidas=comidas_db,
        gimnasio_id=cliente.gimnasio_id,
    )
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan


def _intentar_generar_plan_automatico(db: Session, cliente_id: int):
    """
    Se llama tras registrar/editar una toma de medidas. Si el cliente
    tiene nutricion incluida en su membresia vigente y hay datos
    suficientes, regenera su plan automatico. Nunca lanza excepcion
    hacia el endpoint que la invoca (una toma de medidas SI debe
    guardarse aunque el calculo nutricional no se pueda hacer todavia).
    """
    try:
        if not _cliente_tiene_nutricion_incluida(db, cliente_id):
            return
        cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
        if not cliente:
            return
        ultima_medida = (
            db.query(models.Medida)
            .filter(models.Medida.cliente_id == cliente_id)
            .order_by(models.Medida.fecha.desc(), models.Medida.id.desc())
            .first()
        )
        perfil = _computar_perfil_nutricional(cliente, ultima_medida)
        if not perfil:
            return
        _generar_plan_automatico_interno(db, cliente, perfil)
    except Exception:
        pass


@app.post("/nutricion/generar-automatico/{cliente_id}", response_model=schemas.PlanNutricion, tags=["Nutricion"])
def generar_plan_automatico(cliente_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    """
    Genera (o regenera) el plan de nutricion AUTOMATICO de un cliente
    a partir de su ultima toma de medidas y su perfil (genero, fecha
    de nacimiento): calcula BMR/TDEE, determina el proposito segun su
    IMC, y arma desayuno/almuerzo/cena con los paquetes ya creados.
    No requiere que el cliente tenga nutricion incluida en su plan
    (a diferencia del disparo automatico tras una toma de medidas):
    esto permite generarlo manualmente bajo pedido para cualquier cliente.
    """
    _validar_nutricion_habilitada(db, usuario)
    cliente = _del_gym(db, models.Cliente, cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    ultima_medida = (
        db.query(models.Medida)
        .filter(models.Medida.cliente_id == cliente_id)
        .order_by(models.Medida.fecha.desc(), models.Medida.id.desc())
        .first()
    )
    perfil = _computar_perfil_nutricional(cliente, ultima_medida)
    if not perfil:
        raise HTTPException(
            status_code=400,
            detail="Faltan datos para calcular el plan automatico: se necesita la fecha de nacimiento del cliente (pestaña Datos) y una toma de medidas con peso y estatura (pestaña Medidas).",
        )
    return _generar_plan_automatico_interno(db, cliente, perfil)


@app.post("/nutricion/generar-automatico-masivo", tags=["Nutricion"])
def generar_planes_automaticos_masivo(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    """
    Genera/actualiza el plan automatico de TODOS los clientes activos
    con una membresia vigente que incluye nutricion y que ya tienen
    al menos una toma de medidas con peso y estatura. Pensado para
    correrlo despues de ampliar el catalogo de paquetes, o la primera
    vez que se activa esta funcionalidad (los clientes nuevos despues
    se actualizan solos al registrarles una toma de medidas).
    """
    hoy = hoy_lima()
    clientes_elegibles = (
        db.query(models.Cliente)
        .join(models.ClienteMembresia, models.ClienteMembresia.cliente_id == models.Cliente.id)
        .join(models.Membresia, models.ClienteMembresia.membresia_id == models.Membresia.id)
        .filter(
            models.Cliente.gimnasio_id == get_gid(usuario),
            models.Membresia.gimnasio_id == get_gid(usuario),
            models.Cliente.activo == True,
            models.ClienteMembresia.activo == True,
            models.Membresia.incluye_nutricion == True,
            (models.ClienteMembresia.fecha_fin.is_(None)) | (models.ClienteMembresia.fecha_fin >= hoy),
        )
        .distinct()
        .all()
    )

    generados, omitidos = 0, 0
    for cliente in clientes_elegibles:
        ultima_medida = (
            db.query(models.Medida)
            .filter(models.Medida.cliente_id == cliente.id)
            .order_by(models.Medida.fecha.desc(), models.Medida.id.desc())
            .first()
        )
        perfil = _computar_perfil_nutricional(cliente, ultima_medida)
        if not perfil:
            omitidos += 1
            continue
        _generar_plan_automatico_interno(db, cliente, perfil)
        generados += 1

    return {"total_elegibles": len(clientes_elegibles), "generados": generados, "omitidos_sin_datos": omitidos}


# ==================================================================
# RETOS
# ==================================================================

@app.get("/retos/", response_model=List[schemas.Reto], tags=["Retos"])
def listar_retos(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    return q(db, models.Reto, usuario).filter(models.Reto.activo == True).all()


@app.post("/retos/", response_model=schemas.Reto, tags=["Retos"])
def crear_reto(reto: schemas.RetoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    db_reto = models.Reto(**reto.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_reto)
    db.commit()
    db.refresh(db_reto)
    return db_reto


# ==================================================================
# PERSONAL Y PLANILLA
# ==================================================================

@app.get("/empleados/", response_model=List[schemas.Empleado], tags=["Personal"])
def listar_empleados(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    return q(db, models.Empleado, usuario).filter(models.Empleado.activo == True).all()


@app.get("/agenda/profesores", response_model=List[schemas.ProfesorMinimo], tags=["Agenda"])
def listar_profesores_agenda(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """Vista minima para Agenda; no expone sueldos ni datos privados de Personal."""
    return (
        q(db, models.Empleado, usuario)
        .filter(
            models.Empleado.activo == True,
            models.Empleado.tipo == models.TipoEmpleado.PROFESOR_DE_SALA,
        )
        .order_by(models.Empleado.nombre_completo)
        .all()
    )


@app.get("/agenda/conceptos-ingreso", response_model=List[schemas.ConceptoOtroIngreso], tags=["Agenda"])
def listar_conceptos_agenda(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """Conceptos habilitados para alquileres, sin abrir la zona financiera completa."""
    return (
        q(db, models.ConceptoOtroIngreso, usuario)
        .filter(
            models.ConceptoOtroIngreso.activo == True,
            models.ConceptoOtroIngreso.mostrar_agenda == True,
        )
        .order_by(models.ConceptoOtroIngreso.nombre)
        .all()
    )


# ---- Puestos / especialidades (catalogo editable) ----

@app.get("/puestos/", response_model=List[schemas.Puesto], tags=["Personal"])
def listar_puestos(
    tipo: Optional[models.TipoEmpleado] = None,
    solo_activos: bool = True,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Catalogo de puestos (staff) / especialidades (profesor).
    solo_activos=True (default) es lo que se usa para poblar el
    selector al asignar puesto a personal nuevo; solo_activos=False
    trae TODOS (incluye los desmarcados), para la pantalla de
    gestion en Usuarios.
    """
    query = q(db, models.Puesto, usuario)
    if tipo:
        query = query.filter(models.Puesto.tipo == tipo)
    if solo_activos:
        query = query.filter(models.Puesto.activo == True)
    return query.order_by(models.Puesto.nombre).all()


@app.post("/puestos/", response_model=schemas.Puesto, tags=["Personal"])
def crear_puesto(datos: schemas.PuestoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gid = get_gid(usuario)
    existente = (
        db.query(models.Puesto)
        .filter(models.Puesto.tipo == datos.tipo, func.lower(models.Puesto.nombre) == datos.nombre.strip().lower(), models.Puesto.gimnasio_id == gid)
        .first()
    )
    if existente:
        if not existente.activo:
            existente.activo = True
            db.commit()
            db.refresh(existente)
        return existente
    db_puesto = models.Puesto(nombre=datos.nombre.strip(), tipo=datos.tipo, activo=True, gimnasio_id=gid)
    db.add(db_puesto)
    db.commit()
    db.refresh(db_puesto)
    return db_puesto


@app.put("/puestos/{puesto_id}", response_model=schemas.Puesto, tags=["Personal"])
def actualizar_puesto(puesto_id: int, datos: schemas.PuestoUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """Se usa tanto para renombrar como para el checkbox de visibilidad (activo=True/False). Desactivar NO borra el puesto de los empleados que ya lo tenian."""
    puesto = db.query(models.Puesto).filter(models.Puesto.id == puesto_id, models.Puesto.gimnasio_id == get_gid(usuario)).first()
    if not puesto:
        raise HTTPException(status_code=404, detail="Puesto no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(puesto, campo, valor)
    db.commit()
    db.refresh(puesto)
    return puesto


@app.post("/empleados/", response_model=schemas.Empleado, tags=["Personal"])
def crear_empleado(empleado: schemas.EmpleadoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    valores = empleado.model_dump()
    if valores.get("codigo_acceso"):
        valores["codigo_acceso"] = auth.hash_codigo_acceso(valores["codigo_acceso"])
    db_empleado = models.Empleado(**valores, gimnasio_id=get_gid(usuario))
    db.add(db_empleado)
    db.commit()
    db.refresh(db_empleado)
    return db_empleado


@app.put("/empleados/{empleado_id}", response_model=schemas.Empleado, tags=["Personal"])
def actualizar_empleado(
    empleado_id: int,
    datos: schemas.EmpleadoUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    empleado = db.query(models.Empleado).filter(models.Empleado.id == empleado_id, models.Empleado.gimnasio_id == get_gid(usuario)).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if campo == "codigo_acceso" and valor:
            valor = auth.hash_codigo_acceso(valor)
        setattr(empleado, campo, valor)
    db.commit()
    db.refresh(empleado)
    return empleado


# ---- Agenda / Clases dictadas ----

def _asegurar_tabla_salas():
    """Garantiza el catálogo en despliegues antiguos donde create_all no lo creó al arrancar."""
    models.SalaGimnasio.__table__.create(bind=engine, checkfirst=True)

@app.get("/salas/", response_model=List[schemas.SalaGimnasio], tags=["Agenda"])
def listar_salas(db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff_o_profesor)):
    _asegurar_tabla_salas()
    gid = get_gid(usuario)
    # Conserva como opciones las salas históricas creadas antes del catálogo.
    existentes = {s.nombre.strip().lower() for s in db.query(models.SalaGimnasio).filter(
        models.SalaGimnasio.gimnasio_id == gid).all()}
    nombres = {x[0].strip() for x in db.query(models.ClaseDictada.sala).filter(
        models.ClaseDictada.gimnasio_id == gid, models.ClaseDictada.sala.isnot(None)).distinct().all() if x[0] and x[0].strip()}
    nombres |= {x[0].strip() for x in db.query(models.ReservaSala.sala).filter(
        models.ReservaSala.gimnasio_id == gid, models.ReservaSala.sala.isnot(None)).distinct().all() if x[0] and x[0].strip()}
    for nombre in nombres:
        if nombre.lower() not in existentes:
            db.add(models.SalaGimnasio(gimnasio_id=gid, nombre=nombre))
    if nombres:
        db.commit()
    activas = db.query(models.SalaGimnasio).filter(models.SalaGimnasio.gimnasio_id == gid,
        models.SalaGimnasio.activo == True).order_by(models.SalaGimnasio.nombre).all()
    if not activas:
        principal = models.SalaGimnasio(gimnasio_id=gid, nombre="Agenda principal")
        db.add(principal); db.commit(); db.refresh(principal)
        activas = [principal]
    return activas


@app.post("/salas/", response_model=schemas.SalaGimnasio, tags=["Agenda"])
def crear_sala(datos: schemas.SalaGimnasioCreate, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    _asegurar_tabla_salas()
    nombre = datos.nombre.strip()
    sala = db.query(models.SalaGimnasio).filter(models.SalaGimnasio.gimnasio_id == get_gid(usuario),
        func.lower(models.SalaGimnasio.nombre) == nombre.lower()).first()
    if sala:
        if sala.activo:
            raise HTTPException(status_code=400, detail="La sala ya existe")
        sala.activo = True
    else:
        sala = models.SalaGimnasio(gimnasio_id=get_gid(usuario), nombre=nombre)
        db.add(sala)
    db.commit(); db.refresh(sala)
    return sala


@app.delete("/salas/{sala_id}", tags=["Agenda"])
def eliminar_sala(sala_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    sala = db.query(models.SalaGimnasio).filter(models.SalaGimnasio.id == sala_id,
        models.SalaGimnasio.gimnasio_id == get_gid(usuario)).first()
    if not sala:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    total_activas = db.query(func.count(models.SalaGimnasio.id)).filter(
        models.SalaGimnasio.gimnasio_id == get_gid(usuario), models.SalaGimnasio.activo == True).scalar() or 0
    if total_activas <= 1:
        raise HTTPException(status_code=400, detail="Debe existir al menos una agenda")
    sala.activo = False
    db.commit()
    return {"ok": True}


@app.put("/salas/{sala_id}", response_model=schemas.SalaGimnasio, tags=["Agenda"])
def renombrar_sala(sala_id: int, datos: schemas.SalaGimnasioCreate, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    sala = db.query(models.SalaGimnasio).filter(models.SalaGimnasio.id == sala_id,
        models.SalaGimnasio.gimnasio_id == get_gid(usuario), models.SalaGimnasio.activo == True).first()
    if not sala:
        raise HTTPException(status_code=404, detail="Agenda no encontrada")
    nombre_nuevo = datos.nombre.strip()
    duplicada = db.query(models.SalaGimnasio.id).filter(models.SalaGimnasio.gimnasio_id == get_gid(usuario),
        func.lower(models.SalaGimnasio.nombre) == nombre_nuevo.lower(), models.SalaGimnasio.id != sala_id,
        models.SalaGimnasio.activo == True).first()
    if duplicada:
        raise HTTPException(status_code=400, detail="Ya existe una agenda con ese nombre")
    nombre_anterior = sala.nombre
    sala.nombre = nombre_nuevo
    db.query(models.ClaseDictada).filter(models.ClaseDictada.gimnasio_id == get_gid(usuario),
        models.ClaseDictada.sala == nombre_anterior).update({models.ClaseDictada.sala: nombre_nuevo}, synchronize_session=False)
    db.query(models.ReservaSala).filter(models.ReservaSala.gimnasio_id == get_gid(usuario),
        models.ReservaSala.sala == nombre_anterior).update({models.ReservaSala.sala: nombre_nuevo}, synchronize_session=False)
    db.commit(); db.refresh(sala)
    return sala

def _validar_sala_disponible(db: Session, gid: int, sala: Optional[str], fecha_evento: date, inicio: datetime, fin: Optional[datetime]):
    """Evita superponer clases y alquileres en una misma sala."""
    if not sala or not sala.strip():
        return
    fin_evento = fin or (inicio + timedelta(hours=1))
    clases = db.query(models.ClaseDictada).filter(
        models.ClaseDictada.gimnasio_id == gid,
        models.ClaseDictada.fecha == fecha_evento,
        func.lower(models.ClaseDictada.sala) == sala.strip().lower(),
    ).all()
    reservas = db.query(models.ReservaSala).filter(
        models.ReservaSala.gimnasio_id == gid,
        models.ReservaSala.fecha == fecha_evento,
        func.lower(models.ReservaSala.sala) == sala.strip().lower(),
    ).all()
    for ocupado in [*clases, *reservas]:
        fin_ocupado = ocupado.hora_fin or (ocupado.hora_inicio + timedelta(hours=1))
        if inicio < fin_ocupado and ocupado.hora_inicio < fin_evento:
            raise HTTPException(status_code=409, detail=f"La sala {sala} ya esta ocupada en ese horario")

@app.get("/reservas-sala/", response_model=List[schemas.ReservaSala], tags=["Agenda"])
def listar_reservas_sala(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    usuario=Depends(auth.requiere_staff),
):
    query = q(db, models.ReservaSala, usuario)
    if desde:
        query = query.filter(models.ReservaSala.fecha >= desde)
    if hasta:
        query = query.filter(models.ReservaSala.fecha <= hasta)
    return query.order_by(models.ReservaSala.fecha, models.ReservaSala.hora_inicio).all()


@app.post("/reservas-sala/", response_model=schemas.ReservaSala, tags=["Agenda"])
def crear_reserva_sala(datos: schemas.ReservaSalaCreate, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    concepto = _del_gym(db, models.ConceptoOtroIngreso, datos.concepto_ingreso_id, usuario)
    if not concepto or not concepto.activo or not concepto.mostrar_agenda:
        raise HTTPException(status_code=400, detail="El concepto no esta habilitado para Agenda")
    if datos.hora_fin and datos.hora_fin <= datos.hora_inicio:
        raise HTTPException(status_code=400, detail="La hora fin debe ser posterior a la hora de inicio")
    _validar_sala_disponible(db, get_gid(usuario), datos.sala, datos.fecha, datos.hora_inicio, datos.hora_fin)
    reserva = models.ReservaSala(**datos.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(reserva); db.commit(); db.refresh(reserva)
    return reserva


@app.delete("/reservas-sala/{reserva_id}", tags=["Agenda"])
def eliminar_reserva_sala(reserva_id: int, db: Session = Depends(get_db), usuario=Depends(auth.requiere_staff)):
    reserva = _del_gym(db, models.ReservaSala, reserva_id, usuario)
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    db.delete(reserva); db.commit()
    return {"ok": True}


@app.get("/clases/", response_model=List[schemas.ClaseDictada], tags=["Agenda"])
def listar_clases(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    profesor_id: Optional[int] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    query = q(db, models.ClaseDictada, usuario)
    if desde:
        query = query.filter(models.ClaseDictada.fecha >= desde)
    if hasta:
        query = query.filter(models.ClaseDictada.fecha <= hasta)
    if profesor_id:
        query = query.filter(models.ClaseDictada.profesor_id == profesor_id)
    return query.order_by(models.ClaseDictada.fecha, models.ClaseDictada.hora_inicio).all()


@app.post("/clases/", response_model=List[schemas.ClaseDictada], tags=["Agenda"])
def agendar_clase(datos: schemas.ClaseDictadaCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """
    Agenda una clase. Si se envian dias_semana (lunes=0..domingo=6) y
    semanas > 1, crea una SERIE: una clase por cada dia de semana
    elegido, repetida esa cantidad de semanas (todas comparten
    serie_id, lo que permite despues borrar 'esta' o 'esta y las
    futuras'). Sin repeticion, crea una sola clase (lista de 1).
    """
    profesor = _del_gym(db, models.Empleado, datos.profesor_id, usuario)
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")
    if profesor.tipo != models.TipoEmpleado.PROFESOR_DE_SALA:
        raise HTTPException(status_code=400, detail="El empleado seleccionado no es un profesor de sala")

    dias_semana = sorted(set(d for d in datos.dias_semana if 0 <= d <= 6))
    semanas = max(datos.semanas or 1, 1)

    hora_inicio_t = datos.hora_inicio.time()
    hora_fin_t = datos.hora_fin.time() if datos.hora_fin else None

    fechas_a_crear: List[date] = []
    if not dias_semana or semanas <= 1:
        fechas_a_crear = [datos.fecha]
    else:
        lunes_base = datos.fecha - timedelta(days=datos.fecha.weekday())
        for semana in range(semanas):
            for dia in dias_semana:
                candidata = lunes_base + timedelta(days=semana * 7 + dia)
                if candidata >= datos.fecha:
                    fechas_a_crear.append(candidata)
        fechas_a_crear = sorted(set(fechas_a_crear))

    serie_id = uuid.uuid4().hex if len(fechas_a_crear) > 1 else None

    clases_creadas = []
    for fecha_clase in fechas_a_crear:
        inicio_clase = datetime.combine(fecha_clase, hora_inicio_t)
        fin_clase = datetime.combine(fecha_clase, hora_fin_t) if hora_fin_t else None
        _validar_sala_disponible(db, get_gid(usuario), datos.sala, fecha_clase, inicio_clase, fin_clase)
        db_clase = models.ClaseDictada(
            profesor_id=datos.profesor_id,
            nombre_clase=datos.nombre_clase,
            sala=datos.sala,
            fecha=fecha_clase,
            hora_inicio=inicio_clase,
            hora_fin=fin_clase,
            notas=datos.notas,
            agenda_nombre=(datos.agenda_nombre or "Clases").strip(),
            permite_registro=datos.permite_registro,
            serie_id=serie_id,
            gimnasio_id=get_gid(usuario),
        )
        db.add(db_clase)
        clases_creadas.append(db_clase)

    db.commit()
    for c in clases_creadas:
        db.refresh(c)
    return clases_creadas


@app.put("/clases/{clase_id}/reemplazo", response_model=schemas.ClaseDictada, tags=["Agenda"])
def asignar_reemplazo_staff(
    clase_id: int,
    datos: schemas.ReemplazoRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Asigna (o quita, si profesor_reemplazo_id es null) un profesor de reemplazo puntual para esta fecha. No afecta al resto de la serie."""
    clase = db.query(models.ClaseDictada).filter(models.ClaseDictada.id == clase_id, models.ClaseDictada.gimnasio_id == get_gid(usuario)).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    if datos.profesor_reemplazo_id:
        reemplazo = _del_gym(db, models.Empleado, datos.profesor_reemplazo_id, usuario)
        if not reemplazo or reemplazo.tipo != models.TipoEmpleado.PROFESOR_DE_SALA or not reemplazo.activo:
            raise HTTPException(status_code=400, detail="El reemplazo debe ser un profesor de sala activo")
    clase.profesor_reemplazo_id = datos.profesor_reemplazo_id
    db.commit()
    db.refresh(clase)
    return clase


@app.delete("/clases/{clase_id}", tags=["Agenda"])
def eliminar_clase(
    clase_id: int,
    alcance: str = Query("una", description="una | futuras"),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar),
):
    """
    Elimina una clase. alcance='futuras' borra esta clase y todas
    las de la misma serie con fecha >= esta (util cuando una clase
    recurrente ya no va mas desde cierta fecha). Si la clase no
    pertenece a una serie (serie_id nulo), 'futuras' se comporta
    igual que 'una'.
    """
    clase = db.query(models.ClaseDictada).filter(models.ClaseDictada.id == clase_id, models.ClaseDictada.gimnasio_id == get_gid(usuario)).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    if alcance == "futuras" and clase.serie_id:
        eliminadas = (
            db.query(models.ClaseDictada)
            .filter(
                models.ClaseDictada.serie_id == clase.serie_id,
                models.ClaseDictada.gimnasio_id == get_gid(usuario),
                models.ClaseDictada.fecha >= clase.fecha,
            )
            .delete(synchronize_session=False)
        )
    else:
        db.delete(clase)
        eliminadas = 1

    db.commit()
    return {"message": "Clase(s) eliminada(s)", "cantidad": eliminadas}


@app.put("/clases/{clase_id}/marcar-dictada", response_model=schemas.ClaseDictada, tags=["Agenda"])
def marcar_clase_dictada(
    clase_id: int,
    datos: schemas.MarcarDictadaRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Cierra una clase: registra cuantos alumnos asistieron y calcula
    automaticamente el monto a pagar. Las tarifas del profesor
    (tarifa_por_clase / tarifa_reducida) son MONTO POR HORA: se
    multiplican por la duracion real de la clase (hora_fin -
    hora_inicio; si no hay hora_fin, se asume 1 hora), y se usa la
    completa o la reducida segun si se cumplio el minimo de alumnos.
    """
    clase = _del_gym(db, models.ClaseDictada, clase_id, usuario)
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    profesor = db.query(models.Empleado).filter(models.Empleado.id == clase.profesor_id).first()

    horas_duracion = 1.0
    if clase.hora_fin and clase.hora_inicio:
        horas_duracion = max((clase.hora_fin - clase.hora_inicio).total_seconds() / 3600, 0.25)

    minimo = profesor.minimo_alumnos_tarifa_completa or 0
    if datos.cantidad_alumnos >= minimo:
        tarifa_hora = profesor.tarifa_por_clase or 0.0
    else:
        tarifa_hora = profesor.tarifa_reducida or 0.0
    monto = round(tarifa_hora * horas_duracion, 2)

    clase.cantidad_alumnos = datos.cantidad_alumnos
    clase.monto_pagado = monto
    clase.dictada = True

    db.commit()
    db.refresh(clase)
    return clase


@app.get("/planilla/profesor/{profesor_id}", response_model=schemas.ResumenPlanilla, tags=["Personal"])
def calcular_planilla_profesor(
    profesor_id: int,
    desde: date,
    hasta: date,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """
    Calcula el total a pagar a un profesor de sala en un periodo,
    sumando el monto_pagado (snapshot) de cada clase marcada como
    dictada dentro del rango. Tambien informa cuanto ya se le pago
    para ESE MISMO rango exacto (desde/hasta) y cuanto queda
    pendiente, para permitir pagos en partes sin pagar de mas.
    """
    profesor = _del_gym(db, models.Empleado, profesor_id, usuario)
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesor no encontrado")

    clases = (
        db.query(models.ClaseDictada)
        .filter(
            models.ClaseDictada.profesor_id == profesor_id,
            models.ClaseDictada.gimnasio_id == get_gid(usuario),
            models.ClaseDictada.dictada == True,
            models.ClaseDictada.fecha >= desde,
            models.ClaseDictada.fecha <= hasta,
        )
        .order_by(models.ClaseDictada.fecha)
        .all()
    )

    total = sum(c.monto_pagado or 0.0 for c in clases)

    pagos = (
        db.query(models.PagoPlanilla)
        .filter(
            models.PagoPlanilla.empleado_id == profesor_id,
            models.PagoPlanilla.gimnasio_id == get_gid(usuario),
            models.PagoPlanilla.tipo == "profesor",
            models.PagoPlanilla.anulada == False,
            models.PagoPlanilla.desde == desde,
            models.PagoPlanilla.hasta == hasta,
        )
        .all()
    )
    total_pagado = round(sum(p.monto_total for p in pagos), 2)

    return schemas.ResumenPlanilla(
        profesor_id=profesor_id,
        nombre_profesor=profesor.nombre_completo,
        cantidad_clases_dictadas=len(clases),
        total_a_pagar=round(total, 2),
        total_pagado=total_pagado,
        pendiente=round(total - total_pagado, 2),
        detalle_clases=clases,
    )


def _calcular_comisiones_periodo(db: Session, usuario_id: int, gimnasio_id: int, anio: int, mes: int) -> tuple:
    """
    Devuelve (comision_membresias, comision_productos) para un
    usuario en un mes especifico, aplicando la meta y los tramos
    configurados (misma logica que /comisiones/resumen, pero para
    UN periodo puntual en vez de para todo el staff a la vez).
    """
    desde = date(anio, mes, 1)
    hasta = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)

    meta = db.query(models.MetaMensual).filter(
        models.MetaMensual.gimnasio_id == gimnasio_id,
        models.MetaMensual.anio == anio,
        models.MetaMensual.mes == mes,
    ).first()
    meta_membresias = meta.meta_membresias if meta else 0.0

    config = db.query(models.Gimnasio).filter(models.Gimnasio.id == gimnasio_id).first()
    comision_producto_flat = config.comision_producto_porcentaje or 0.0

    tramos = db.query(models.TramoComision).filter(
        models.TramoComision.gimnasio_id == gimnasio_id,
        models.TramoComision.activo == True,
        models.TramoComision.tipo == "membresia",
    ).all()

    ventas_membresias = (
        db.query(func.coalesce(func.sum(models.PagoMembresia.monto), 0.0))
        .join(models.ClienteMembresia, models.ClienteMembresia.id == models.PagoMembresia.cliente_membresia_id)
        .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
        .filter(
            models.Cliente.gimnasio_id == gimnasio_id,
            models.ClienteMembresia.vendido_por_id == usuario_id,
            models.ClienteMembresia.anulada == False,
            models.PagoMembresia.anulada == False,
            models.PagoMembresia.fecha_pago >= datetime.combine(desde, datetime.min.time()),
            models.PagoMembresia.fecha_pago < datetime.combine(hasta, datetime.min.time()),
        )
        .scalar()
    )
    ventas_productos = (
        db.query(func.coalesce(func.sum(models.Venta.total), 0.0))
        .filter(
            models.Venta.usuario_id == usuario_id,
            models.Venta.anulada == False,
            models.Venta.fecha_venta >= desde,
            models.Venta.fecha_venta < hasta,
        )
        .scalar()
    )

    pct_meta_membresias = round((ventas_membresias / meta_membresias * 100), 1) if meta_membresias else 0.0
    pct_comision_membresias = _comision_aplicable(pct_meta_membresias, tramos)

    comision_membresias = round(ventas_membresias * pct_comision_membresias / 100, 2)
    comision_productos = round(ventas_productos * comision_producto_flat / 100, 2)
    return comision_membresias, comision_productos


@app.get("/planilla/staff/{empleado_id}", response_model=schemas.ResumenPlanillaStaff, tags=["Personal"])
def calcular_planilla_staff(
    empleado_id: int,
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Calcula lo que corresponde pagarle a un STAFF FIJO en un mes:
    su sueldo fijo de ESE mes, mas las comisiones (membresias y
    productos) que genero en el MES ANTERIOR -- se pagan con un mes
    de arrastre (ej. sueldo de julio + comisiones de junio, se
    cobra en julio). Tambien informa cuanto ya se le pago en este
    periodo (pagos_planilla) y cuanto queda pendiente, para permitir
    pagos en partes.
    """
    if mes < 1 or mes > 12:
        raise HTTPException(status_code=400, detail="Mes invalido (1-12)")

    empleado = _del_gym(db, models.Empleado, empleado_id, usuario)
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    mes_comision = mes - 1
    anio_comision = anio
    if mes_comision == 0:
        mes_comision = 12
        anio_comision -= 1

    comision_membresias, comision_productos = 0.0, 0.0
    if empleado.usuario:
        comision_membresias, comision_productos = _calcular_comisiones_periodo(
            db, empleado.usuario.id, get_gid(usuario), anio_comision, mes_comision
        )

    sueldo = empleado.sueldo_fijo_mensual or 0.0
    total_a_pagar = round(sueldo + comision_membresias + comision_productos, 2)

    pagos = (
        db.query(models.PagoPlanilla)
        .filter(
            models.PagoPlanilla.empleado_id == empleado_id,
            models.PagoPlanilla.gimnasio_id == get_gid(usuario),
            models.PagoPlanilla.tipo == "staff",
            models.PagoPlanilla.anulada == False,
            models.PagoPlanilla.anio == anio,
            models.PagoPlanilla.mes == mes,
        )
        .all()
    )
    total_pagado = round(sum(p.monto_total for p in pagos), 2)

    return schemas.ResumenPlanillaStaff(
        empleado_id=empleado.id,
        nombre_empleado=empleado.nombre_completo,
        anio=anio,
        mes=mes,
        sueldo_fijo_mensual=sueldo,
        mes_comision_anio=anio_comision,
        mes_comision_mes=mes_comision,
        comision_membresias=comision_membresias,
        comision_productos=comision_productos,
        total_a_pagar=total_a_pagar,
        total_pagado=total_pagado,
        pendiente=round(total_a_pagar - total_pagado, 2),
    )


@app.post("/pagos-planilla/", response_model=schemas.PagoPlanilla, tags=["Personal"])
def crear_pago_planilla(
    datos: schemas.PagoPlanillaCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Registra un pago de planilla (staff o profesor). Se guarda como
    snapshot: si luego se edita el sueldo/tarifa del empleado, este
    registro no cambia. Admite pagos EN PARTES: se puede llamar mas
    de una vez para el mismo periodo, sumando monto_total cada vez.
    Valida contra el saldo pendiente real (recalculado en el
    servidor, no confia en lo que mande el frontend): no se puede
    registrar un pago que supere lo que efectivamente se debe.
    """
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario_actual, "pagos-planilla", idempotency_key, payload, models.PagoPlanilla)
    if previo:
        return previo
    if datos.tipo not in ("staff", "profesor"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'staff' o 'profesor'")
    empleado = _del_gym(db, models.Empleado, datos.empleado_id, usuario_actual)
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    if datos.mes < 1 or datos.mes > 12:
        raise HTTPException(status_code=400, detail="Mes invalido (1-12)")
    if datos.monto_total <= 0:
        raise HTTPException(status_code=400, detail="El monto a pagar debe ser mayor a 0")

    if datos.tipo == "staff":
        resumen = calcular_planilla_staff(
            empleado_id=datos.empleado_id, anio=datos.anio, mes=datos.mes, db=db, usuario=usuario_actual
        )
        pendiente = resumen.pendiente
    else:
        if not datos.desde or not datos.hasta:
            raise HTTPException(status_code=400, detail="desde y hasta son obligatorios para pagos de profesor")
        resumen = calcular_planilla_profesor(
            profesor_id=datos.empleado_id, desde=datos.desde, hasta=datos.hasta, db=db, usuario=usuario_actual
        )
        pendiente = resumen.pendiente

    if datos.monto_total > pendiente + 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"El monto ({datos.monto_total:.2f}) supera el saldo pendiente ({pendiente:.2f}). Ya se pago {resumen.total_pagado:.2f} de {resumen.total_a_pagar:.2f}.",
        )

    db_pago = models.PagoPlanilla(
        **datos.model_dump(),
        usuario_registro_id=usuario_actual.id,
        gimnasio_id=get_gid(usuario_actual),
    )
    db.add(db_pago)
    db.flush()
    _guardar_idempotencia(db, usuario_actual, "pagos-planilla", idempotency_key, payload, "PagoPlanilla", db_pago.id)
    db.commit()
    db.refresh(db_pago)
    return db_pago


@app.get("/pagos-planilla/", response_model=List[schemas.PagoPlanilla], tags=["Personal"])
def listar_pagos_planilla(
    tipo: Optional[str] = Query(None, description="staff | profesor"),
    empleado_id: Optional[int] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    incluir_anulados: bool = False,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """Historial de pagos de planilla, con filtros de tipo, trabajador/profesor y rango de fechas (sobre fecha_pago)."""
    query = q(db, models.PagoPlanilla, usuario)
    if not incluir_anulados:
        query = query.filter(models.PagoPlanilla.anulada == False)
    if tipo:
        query = query.filter(models.PagoPlanilla.tipo == tipo)
    if empleado_id:
        query = query.filter(models.PagoPlanilla.empleado_id == empleado_id)
    if desde:
        query = query.filter(models.PagoPlanilla.fecha_pago >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        query = query.filter(models.PagoPlanilla.fecha_pago <= datetime.combine(hasta, datetime.max.time()))
    return query.order_by(models.PagoPlanilla.fecha_pago.desc()).all()


@app.put("/pagos-planilla/{pago_id}", response_model=schemas.PagoPlanilla, tags=["Personal"])
def editar_pago_planilla(
    pago_id: int,
    datos: schemas.PagoPlanillaUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """
    Correccion administrativa de un pago ya registrado (monto y/o
    notas). Solo administrador. El nuevo monto se revalida contra el
    saldo pendiente REAL del periodo, excluyendo este mismo pago del
    calculo (es decir: nuevo monto <= total del periodo - resto de
    pagos del mismo periodo), para no permitir pagar de mas.
    """
    pago = _del_gym(db, models.PagoPlanilla, pago_id, usuario)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.anulada:
        raise HTTPException(status_code=409, detail="Un pago anulado no se puede editar")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)

    datos_dict = datos.model_dump(exclude_unset=True)

    if "monto_total" in datos_dict and datos_dict["monto_total"] is not None:
        nuevo_monto = datos_dict["monto_total"]
        if nuevo_monto <= 0:
            raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")

        # Total calculado del periodo (mismo calculo que al crear el pago)
        if pago.tipo == "staff":
            resumen = calcular_planilla_staff(
                empleado_id=pago.empleado_id, anio=pago.anio, mes=pago.mes, db=db, usuario=usuario
            )
        else:
            if not pago.desde or not pago.hasta:
                raise HTTPException(status_code=400, detail="Este pago de profesor no tiene rango desde/hasta; no se puede revalidar el saldo")
            resumen = calcular_planilla_profesor(
                profesor_id=pago.empleado_id, desde=pago.desde, hasta=pago.hasta, db=db, usuario=usuario
            )

        # Pendiente excluyendo ESTE pago: lo que se debe si este pago no existiera
        pagado_sin_este = round(resumen.total_pagado - pago.monto_total, 2)
        pendiente_sin_este = round(resumen.total_a_pagar - pagado_sin_este, 2)
        if nuevo_monto > pendiente_sin_este + 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"El monto ({nuevo_monto:.2f}) supera el saldo del periodo ({pendiente_sin_este:.2f} disponibles, sin contar este pago). Total del periodo: {resumen.total_a_pagar:.2f}, otros pagos: {pagado_sin_este:.2f}.",
            )
        pago.monto_total = nuevo_monto

    if "notas" in datos_dict:
        pago.notas = datos_dict["notas"]
    if "metodo_pago" in datos_dict and datos_dict["metodo_pago"] is not None:
        pago.metodo_pago = datos_dict["metodo_pago"]

    db.commit()
    db.refresh(pago)
    return pago


@app.delete("/pagos-planilla/{pago_id}", tags=["Personal"])
def eliminar_pago_planilla(pago_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    """Anula un pago conservando su evidencia y recalculando el pendiente."""
    pago = _del_gym(db, models.PagoPlanilla, pago_id, usuario)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.anulada:
        raise HTTPException(status_code=409, detail="El pago ya fue anulado")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)
    pago.anulada = True; pago.anulada_en = ahora_lima(); pago.anulada_por_id = usuario.id; pago.motivo_anulacion = datos.motivo.strip()
    db.commit()
    return {"message": "Pago anulado"}


@app.get("/pagos-planilla/{pago_id}/recibo.pdf", tags=["Personal"])
def recibo_pago_planilla_pdf(pago_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    pago = _del_gym(db, models.PagoPlanilla, pago_id, usuario)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    empleado = db.query(models.Empleado).filter(models.Empleado.id == pago.empleado_id).first()
    config = _configuracion_del_gym(db, usuario)
    pdf_bytes = pdf_generator.generar_recibo_pago_planilla(pago, empleado, config)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=recibo_pago_{pago_id}.pdf"},
    )


# ==================================================================
# SERVICIOS / DEUDAS (Pagos > Servicios: limpieza, internet, agua,
# mantenimiento, alquiler, deudas con proveedores, etc.)
# ==================================================================

@app.get("/servicios/", response_model=List[schemas.Servicio], tags=["Servicios"])
def listar_servicios(solo_activos: bool = True, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """
    Catalogo de servicios/conceptos de deuda. solo_activos=True
    (default) es lo que se usa para poblar el selector al crear un
    cargo nuevo; solo_activos=False trae TODOS, para la pantalla de
    gestion en Pagos > Servicios.
    """
    query = q(db, models.Servicio, usuario)
    if solo_activos:
        query = query.filter(models.Servicio.activo == True)
    return query.order_by(models.Servicio.nombre).all()


@app.post("/servicios/", response_model=schemas.Servicio, tags=["Servicios"])
def crear_servicio(datos: schemas.ServicioCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gid = get_gid(usuario)
    existente = db.query(models.Servicio).filter(func.lower(models.Servicio.nombre) == datos.nombre.strip().lower(), models.Servicio.gimnasio_id == gid).first()
    if existente:
        if not existente.activo:
            existente.activo = True
            db.commit()
            db.refresh(existente)
        return existente
    db_servicio = models.Servicio(nombre=datos.nombre.strip(), notas=datos.notas, activo=True, gimnasio_id=gid)
    db.add(db_servicio)
    db.commit()
    db.refresh(db_servicio)
    return db_servicio


@app.put("/servicios/{servicio_id}", response_model=schemas.Servicio, tags=["Servicios"])
def actualizar_servicio(servicio_id: int, datos: schemas.ServicioUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """Se usa tanto para renombrar/anotar como para el checkbox de visibilidad (activo=True/False). Desactivar NO borra los cargos ya registrados con este servicio."""
    servicio = db.query(models.Servicio).filter(models.Servicio.id == servicio_id, models.Servicio.gimnasio_id == get_gid(usuario)).first()
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(servicio, campo, valor)
    db.commit()
    db.refresh(servicio)
    return servicio


def _cargo_con_totales(cargo: models.CargoServicio) -> models.CargoServicio:
    total_pagado = round(sum(p.monto for p in cargo.pagos if not p.anulada), 2)
    cargo.total_pagado = total_pagado
    cargo.pendiente = round(cargo.monto_total - total_pagado, 2)
    return cargo


@app.get("/cargos-servicio/", response_model=List[schemas.CargoServicio], tags=["Servicios"])
def listar_cargos_servicio(
    servicio_id: Optional[int] = None,
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    solo_pendientes: bool = False,
    incluir_anulados: bool = False,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff),
):
    """
    Lista de cargos (cobros/deudas) de servicios, con total_pagado y
    pendiente ya calculados. Filtrable por servicio y/o periodo
    (anio/mes), pensado para la vista mensual de Pagos > Servicios.
    """
    query = q(db, models.CargoServicio, usuario)
    if not incluir_anulados:
        query = query.filter(models.CargoServicio.anulada == False)
    if servicio_id:
        query = query.filter(models.CargoServicio.servicio_id == servicio_id)
    if anio:
        query = query.filter(models.CargoServicio.anio == anio)
    if mes:
        query = query.filter(models.CargoServicio.mes == mes)
    cargos = query.order_by(models.CargoServicio.anio.asc(), models.CargoServicio.mes.asc(), models.CargoServicio.fecha_vencimiento.asc(), models.CargoServicio.id.asc()).all()
    for c in cargos:
        _cargo_con_totales(c)
    if solo_pendientes:
        cargos = [c for c in cargos if c.pendiente > 0.009]
    return cargos


@app.get("/cargos-servicio/{cargo_id}", response_model=schemas.CargoServicio, tags=["Servicios"])
def obtener_cargo_servicio(cargo_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    cargo = db.query(models.CargoServicio).filter(models.CargoServicio.id == cargo_id, models.CargoServicio.gimnasio_id == get_gid(usuario)).first()
    if not cargo:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    return _cargo_con_totales(cargo)


@app.post("/cargos-servicio/", response_model=schemas.CargoServicio, tags=["Servicios"])
def crear_cargo_servicio(datos: schemas.CargoServicioCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    """
    Registra un cobro/deuda nuevo de un servicio para un periodo (ej.
    'Recibo de agua - Julio 2026'). Si se marca como recurrente
    (semanal/mensual/anual), en vez de crear un solo cargo se genera
    de una vez toda la serie a futuro (agrupada por serie_id):
      - semanal: un cargo por cada dia de la semana marcado, durante
        las proximas 12 ocurrencias (se toma como fecha de partida
        el Vencimiento indicado, o hoy si no se indico).
      - mensual: 12 cargos (el actual + 11 meses mas), mismo dia de
        vencimiento cada mes.
      - anual: 5 cargos (el actual + 4 años mas), misma fecha cada año.
    Se devuelve solo el primer cargo de la serie; el resto queda
    creado en la base (se ven al refrescar el listado).
    """
    servicio = _del_gym(db, models.Servicio, datos.servicio_id, usuario)
    if not servicio:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if datos.monto_total <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    if datos.mes < 1 or datos.mes > 12:
        raise HTTPException(status_code=400, detail="Mes invalido (1-12)")

    gid = get_gid(usuario)

    if not datos.recurrente_tipo:
        db_cargo = models.CargoServicio(**datos.model_dump(), gimnasio_id=gid)
        db.add(db_cargo)
        db.commit()
        db.refresh(db_cargo)
        return _cargo_con_totales(db_cargo)

    # ---- Generacion de una serie recurrente ----
    import calendar as _cal

    def _sumar_meses(anio, mes, cantidad):
        total = (anio * 12 + (mes - 1)) + cantidad
        return total // 12, (total % 12) + 1

    def _clip_dia(anio, mes, dia):
        return min(dia, _cal.monthrange(anio, mes)[1])

    serie_id = str(uuid.uuid4())
    primer_cargo = None

    if datos.recurrente_tipo == "mensual":
        dia_venc = datos.fecha_vencimiento.day if datos.fecha_vencimiento else None
        for i in range(12):
            nuevo_anio, nuevo_mes = _sumar_meses(datos.anio, datos.mes, i)
            venc = date(nuevo_anio, nuevo_mes, _clip_dia(nuevo_anio, nuevo_mes, dia_venc)) if dia_venc else None
            cargo = models.CargoServicio(
                servicio_id=datos.servicio_id, concepto=datos.concepto, monto_total=datos.monto_total,
                anio=nuevo_anio, mes=nuevo_mes, fecha_vencimiento=venc, notas=datos.notas,
                recurrente_tipo=datos.recurrente_tipo, serie_id=serie_id, gimnasio_id=gid,
            )
            db.add(cargo)
            if primer_cargo is None:
                primer_cargo = cargo

    elif datos.recurrente_tipo == "anual":
        dia_venc = datos.fecha_vencimiento.day if datos.fecha_vencimiento else None
        for i in range(5):
            nuevo_anio = datos.anio + i
            venc = date(nuevo_anio, datos.mes, _clip_dia(nuevo_anio, datos.mes, dia_venc)) if dia_venc else None
            cargo = models.CargoServicio(
                servicio_id=datos.servicio_id, concepto=datos.concepto, monto_total=datos.monto_total,
                anio=nuevo_anio, mes=datos.mes, fecha_vencimiento=venc, notas=datos.notas,
                recurrente_tipo=datos.recurrente_tipo, serie_id=serie_id, gimnasio_id=gid,
            )
            db.add(cargo)
            if primer_cargo is None:
                primer_cargo = cargo

    elif datos.recurrente_tipo == "semanal":
        dias_csv = datos.recurrente_dias_semana or ""
        dias_deseados = [d for d in dias_csv.split(",") if d]
        if not dias_deseados:
            raise HTTPException(status_code=400, detail="Selecciona al menos un dia de la semana para un cargo semanal")
        mapa_dias = {"lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}
        indices_deseados = {mapa_dias[d] for d in dias_deseados if d in mapa_dias}
        fecha_cursor = datos.fecha_vencimiento or date(datos.anio, datos.mes, 1)
        generados = 0
        intentos = 0
        while generados < 12 and intentos < 120:
            if fecha_cursor.weekday() in indices_deseados:
                cargo = models.CargoServicio(
                    servicio_id=datos.servicio_id, concepto=datos.concepto, monto_total=datos.monto_total,
                    anio=fecha_cursor.year, mes=fecha_cursor.month, fecha_vencimiento=fecha_cursor, notas=datos.notas,
                    recurrente_tipo=datos.recurrente_tipo, recurrente_dias_semana=dias_csv, serie_id=serie_id, gimnasio_id=gid,
                )
                db.add(cargo)
                if primer_cargo is None:
                    primer_cargo = cargo
                generados += 1
            fecha_cursor = fecha_cursor + timedelta(days=1)
            intentos += 1
    else:
        raise HTTPException(status_code=400, detail="Tipo de recurrencia invalido (usa semanal, mensual o anual)")

    db.commit()
    db.refresh(primer_cargo)
    return _cargo_con_totales(primer_cargo)


@app.put("/cargos-servicio/{cargo_id}", response_model=schemas.CargoServicio, tags=["Servicios"])
def actualizar_cargo_servicio(
    cargo_id: int,
    datos: schemas.CargoServicioUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """Correccion administrativa de un cargo (monto, periodo, vencimiento, etc). Solo administrador. No permite bajar el monto por debajo de lo ya pagado."""
    cargo = db.query(models.CargoServicio).filter(models.CargoServicio.id == cargo_id, models.CargoServicio.gimnasio_id == get_gid(usuario)).first()
    if not cargo:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    datos_dict = datos.model_dump(exclude_unset=True)
    if "monto_total" in datos_dict and datos_dict["monto_total"] is not None:
        if datos_dict["monto_total"] <= 0:
            raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
        total_pagado = round(sum(p.monto for p in cargo.pagos if not p.anulada), 2)
        if datos_dict["monto_total"] < total_pagado:
            raise HTTPException(status_code=400, detail=f"El nuevo monto no puede ser menor a lo ya pagado ({total_pagado:.2f})")
    for campo, valor in datos_dict.items():
        setattr(cargo, campo, valor)
    db.commit()
    db.refresh(cargo)
    return _cargo_con_totales(cargo)


@app.delete("/cargos-servicio/{cargo_id}", tags=["Servicios"])
def eliminar_cargo_servicio(cargo_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    """Anula un cargo y sus pagos asociados conservando la evidencia."""
    cargo = db.query(models.CargoServicio).filter(models.CargoServicio.id == cargo_id, models.CargoServicio.gimnasio_id == get_gid(usuario)).first()
    if not cargo:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    if cargo.anulada:
        raise HTTPException(status_code=409, detail="El cargo ya fue anulado")
    for pago in cargo.pagos:
        if not pago.anulada:
            _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)
    momento = ahora_lima(); motivo = datos.motivo.strip()
    cargo.anulada = True; cargo.anulada_en = momento; cargo.anulada_por_id = usuario.id; cargo.motivo_anulacion = motivo
    for pago in cargo.pagos:
        if not pago.anulada:
            pago.anulada = True; pago.anulada_en = momento; pago.anulada_por_id = usuario.id; pago.motivo_anulacion = f"Cargo anulado: {motivo}"
    db.commit()
    return {"message": "Cargo anulado"}


@app.post("/pagos-servicio/", response_model=schemas.PagoServicio, tags=["Servicios"])
def crear_pago_servicio(
    datos: schemas.PagoServicioCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(auth.requiere_staff),
):
    """Registra un pago (total o parcial) contra un cargo de servicio, validando que no supere el saldo pendiente real (recalculado en el servidor)."""
    payload = datos.model_dump(mode="json")
    previo = _buscar_idempotente(db, usuario_actual, "pagos-servicio", idempotency_key, payload, models.PagoServicio)
    if previo:
        return previo
    cargo = _del_gym(db, models.CargoServicio, datos.cargo_id, usuario_actual)
    if not cargo:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    if datos.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    total_pagado = round(sum(p.monto for p in cargo.pagos if not p.anulada), 2)
    pendiente = round(cargo.monto_total - total_pagado, 2)
    if datos.monto > pendiente + 0.01:
        raise HTTPException(status_code=400, detail=f"El monto ({datos.monto:.2f}) supera el saldo pendiente ({pendiente:.2f})")
    db_pago = models.PagoServicio(
        cargo_id=datos.cargo_id, monto=datos.monto, notas=datos.notas,
        metodo_pago=datos.metodo_pago,
        usuario_registro_id=usuario_actual.id,
    )
    db.add(db_pago)
    db.flush()
    _guardar_idempotencia(db, usuario_actual, "pagos-servicio", idempotency_key, payload, "PagoServicio", db_pago.id)
    db.commit()
    db.refresh(db_pago)
    return db_pago


@app.get("/pagos-servicio/", response_model=List[schemas.PagoServicio], tags=["Servicios"])
def listar_pagos_servicio(cargo_id: Optional[int] = None, incluir_anulados: bool = False, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    query = db.query(models.PagoServicio).join(
        models.CargoServicio, models.CargoServicio.id == models.PagoServicio.cargo_id
    ).filter(models.CargoServicio.gimnasio_id == get_gid(usuario))
    if not incluir_anulados:
        query = query.filter(models.PagoServicio.anulada == False)
    if cargo_id:
        query = query.filter(models.PagoServicio.cargo_id == cargo_id)
    return query.order_by(models.PagoServicio.fecha_pago.desc()).all()


@app.put("/pagos-servicio/{pago_id}", response_model=schemas.PagoServicio, tags=["Servicios"])
def editar_pago_servicio(
    pago_id: int,
    datos: schemas.PagoServicioUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """Correccion administrativa de un pago ya registrado. Solo administrador. El nuevo monto se revalida contra el saldo disponible del cargo, excluyendo este mismo pago del calculo."""
    pago = _pago_servicio_del_gym(db, pago_id, usuario)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.anulada:
        raise HTTPException(status_code=409, detail="Un pago anulado no se puede editar")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)
    datos_dict = datos.model_dump(exclude_unset=True)
    if "monto" in datos_dict and datos_dict["monto"] is not None:
        nuevo_monto = datos_dict["monto"]
        if nuevo_monto <= 0:
            raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
        cargo = pago.cargo
        pagado_sin_este = round(sum(p.monto for p in cargo.pagos if p.id != pago.id and not p.anulada), 2)
        pendiente_sin_este = round(cargo.monto_total - pagado_sin_este, 2)
        if nuevo_monto > pendiente_sin_este + 0.01:
            raise HTTPException(status_code=400, detail=f"El monto ({nuevo_monto:.2f}) supera el saldo disponible ({pendiente_sin_este:.2f}, sin contar este pago).")
        pago.monto = nuevo_monto
    if "notas" in datos_dict:
        pago.notas = datos_dict["notas"]
    if "metodo_pago" in datos_dict and datos_dict["metodo_pago"] is not None:
        pago.metodo_pago = datos_dict["metodo_pago"].value if hasattr(datos_dict["metodo_pago"], "value") else datos_dict["metodo_pago"]
    db.commit()
    db.refresh(pago)
    return pago


@app.delete("/pagos-servicio/{pago_id}", tags=["Servicios"])
def eliminar_pago_servicio(pago_id: int, datos: schemas.AnulacionOperacionRequest, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    """Anula un pago; el pendiente se recalcula sin borrar evidencia."""
    pago = _pago_servicio_del_gym(db, pago_id, usuario)
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago.anulada:
        raise HTTPException(status_code=409, detail="El pago ya fue anulado")
    _exigir_periodo_financiero_abierto(db, get_gid(usuario), pago.fecha_pago)
    pago.anulada = True; pago.anulada_en = ahora_lima(); pago.anulada_por_id = usuario.id; pago.motivo_anulacion = datos.motivo.strip()
    db.commit()
    return {"message": "Pago anulado"}


# ==================================================================
# MEDIDAS (toma antropometrica completa, historial por fecha)
# ==================================================================

@app.get("/medidas/cliente/{cliente_id}", response_model=List[schemas.Medida], tags=["Medidas"])
def listar_medidas_de_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """Historial de tomas de medidas de un cliente, de la mas reciente a la mas antigua."""
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id, models.Cliente.gimnasio_id == get_gid(usuario)).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return (
        db.query(models.Medida)
        .filter(models.Medida.cliente_id == cliente_id)
        .order_by(models.Medida.fecha.desc(), models.Medida.id.desc())
        .all()
    )


@app.post("/medidas/", response_model=schemas.Medida, tags=["Medidas"])
def registrar_medida(
    datos: schemas.MedidaCreate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    """Registra una nueva toma de medidas para un cliente (el trainer llena los campos que haya medido esa vez)."""
    cliente = _del_gym(db, models.Cliente, datos.cliente_id, usuario)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    datos_dict = datos.model_dump()
    if not datos_dict.get("fecha"):
        datos_dict["fecha"] = hoy_lima()
    db_medida = models.Medida(**datos_dict, gimnasio_id=get_gid(usuario))
    db.add(db_medida)
    db.commit()
    db.refresh(db_medida)
    _intentar_generar_plan_automatico(db, datos.cliente_id)
    return db_medida


@app.put("/medidas/{medida_id}", response_model=schemas.Medida, tags=["Medidas"])
def editar_medida(
    medida_id: int,
    datos: schemas.MedidaUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor),
):
    medida = db.query(models.Medida).filter(models.Medida.id == medida_id, models.Medida.gimnasio_id == get_gid(usuario)).first()
    if not medida:
        raise HTTPException(status_code=404, detail="Toma de medidas no encontrada")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(medida, campo, valor)
    db.commit()
    db.refresh(medida)
    _intentar_generar_plan_automatico(db, medida.cliente_id)
    return medida


@app.delete("/medidas/{medida_id}", tags=["Medidas"])
def eliminar_medida(medida_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_permiso_eliminar)):
    medida = db.query(models.Medida).filter(models.Medida.id == medida_id, models.Medida.gimnasio_id == get_gid(usuario)).first()
    if not medida:
        raise HTTPException(status_code=404, detail="Toma de medidas no encontrada")
    db.delete(medida)
    db.commit()
    return {"message": "Toma de medidas eliminada"}


# ==================================================================
# CONFIGURACION
# ==================================================================

EQUIPAMIENTO_GIMNASIO = [
    # Pesos libres
    ("mancuernas", "Mancuernas", "Pesos libres"),
    ("barra_discos", "Barras y discos", "Pesos libres"),
    ("barra_olimpica", "Barras olímpicas", "Pesos libres"),
    ("barra_ez", "Barra Z / EZ", "Pesos libres"),
    ("barra_hexagonal", "Barra hexagonal", "Pesos libres"),
    ("kettlebell", "Kettlebells", "Pesos libres"),
    ("banco_plano", "Banco plano", "Pesos libres"),
    ("banco_inclinado", "Banco inclinable", "Pesos libres"),
    ("rack_sentadillas", "Rack para sentadillas", "Pesos libres"),
    ("jaula_potencia", "Jaula de potencia", "Pesos libres"),
    ("landmine", "Landmine", "Pesos libres"),
    ("barra_dominadas", "Barra de dominadas", "Pesos libres"),
    ("paralelas", "Barras paralelas", "Pesos libres"),
    # Maquinas de fuerza - tren superior
    ("multiestacion", "Multiestación", "Máquinas · Tren superior"),
    ("poleas", "Polea alta y baja", "Máquinas · Tren superior"),
    ("crossover", "Cruce de poleas / crossover", "Máquinas · Tren superior"),
    ("entrenador_funcional", "Entrenador funcional de doble polea", "Máquinas · Tren superior"),
    ("press_pecho_maquina", "Press de pecho horizontal", "Máquinas · Tren superior"),
    ("press_inclinado_maquina", "Press de pecho inclinado", "Máquinas · Tren superior"),
    ("press_declinado_maquina", "Press de pecho declinado", "Máquinas · Tren superior"),
    ("pec_deck", "Pec deck / aperturas", "Máquinas · Tren superior"),
    ("pullover_maquina", "Pullover", "Máquinas · Tren superior"),
    ("jalon_maquina", "Jalón dorsal", "Máquinas · Tren superior"),
    ("remo_maquina", "Remo sentado", "Máquinas · Tren superior"),
    ("remo_alto_maquina", "Remo alto", "Máquinas · Tren superior"),
    ("dominadas_asistidas", "Dominadas y fondos asistidos", "Máquinas · Tren superior"),
    ("press_hombros_maquina", "Press de hombros", "Máquinas · Tren superior"),
    ("elevacion_lateral_maquina", "Elevación lateral", "Máquinas · Tren superior"),
    ("deltoide_posterior", "Deltoide posterior", "Máquinas · Tren superior"),
    ("biceps_maquina", "Bíceps / predicador", "Máquinas · Tren superior"),
    ("triceps_maquina", "Tríceps", "Máquinas · Tren superior"),
    # Maquinas de fuerza - piernas y gluteos
    ("smith", "Máquina Smith", "Máquinas · Piernas y glúteos"),
    ("hack_sentadilla", "Hack squat", "Máquinas · Piernas y glúteos"),
    ("sentadilla_pendular", "Sentadilla pendular", "Máquinas · Piernas y glúteos"),
    ("belt_squat", "Belt squat", "Máquinas · Piernas y glúteos"),
    ("sissy_squat", "Sissy squat", "Máquinas · Piernas y glúteos"),
    ("prensa_piernas", "Prensa de piernas 45°", "Máquinas · Piernas y glúteos"),
    ("prensa_horizontal", "Prensa horizontal", "Máquinas · Piernas y glúteos"),
    ("prensa_vertical", "Prensa vertical", "Máquinas · Piernas y glúteos"),
    ("extension_cuadriceps", "Extensión de cuádriceps", "Máquinas · Piernas y glúteos"),
    ("curl_femoral", "Curl femoral", "Máquinas · Piernas y glúteos"),
    ("curl_femoral_sentado", "Curl femoral sentado", "Máquinas · Piernas y glúteos"),
    ("curl_femoral_tumbado", "Curl femoral tumbado", "Máquinas · Piernas y glúteos"),
    ("curl_femoral_pie", "Curl femoral de pie", "Máquinas · Piernas y glúteos"),
    ("hip_thrust_maquina", "Hip thrust", "Máquinas · Piernas y glúteos"),
    ("gluteo_maquina", "Patada de glúteo", "Máquinas · Piernas y glúteos"),
    ("abductores_aductores", "Abductores / aductores", "Máquinas · Piernas y glúteos"),
    ("glute_ham", "Glute ham developer", "Máquinas · Piernas y glúteos"),
    ("pantorrilla_maquina", "Pantorrilla", "Máquinas · Piernas y glúteos"),
    ("pantorrilla_sentado", "Pantorrilla sentado", "Máquinas · Piernas y glúteos"),
    ("pantorrilla_pie", "Pantorrilla de pie", "Máquinas · Piernas y glúteos"),
    # Maquinas de core
    ("abdominal_maquina", "Abdominales", "Máquinas · Core"),
    ("lumbar_maquina", "Extensión lumbar", "Máquinas · Core"),
    ("rotacion_torso", "Rotación de torso", "Máquinas · Core"),
    # Cardio
    ("caminadora", "Caminadora", "Cardio"),
    ("bicicleta_estatica", "Bicicleta estática", "Cardio"),
    ("eliptica", "Elíptica", "Cardio"),
    ("escaladora", "Escaladora", "Cardio"),
    ("remo_cardio", "Remo ergómetro", "Cardio"),
    ("bicicleta_spinning", "Bicicletas de spinning", "Cardio"),
    ("bicicleta_reclinada", "Bicicleta reclinada", "Cardio"),
    ("air_bike", "Air bike", "Cardio"),
    ("ski_erg", "Ski erg", "Cardio"),
    ("arc_trainer", "Arc trainer", "Cardio"),
    ("cinta_curva", "Caminadora curva / manual", "Cardio"),
    # Funcional y accesorios
    ("bandas_elasticas", "Bandas elásticas", "Funcional y accesorios"),
    ("trx", "TRX / suspensión", "Funcional y accesorios"),
    ("step", "Steps", "Funcional y accesorios"),
    ("cajon", "Cajón pliométrico", "Funcional y accesorios"),
    ("colchoneta", "Colchonetas", "Funcional y accesorios"),
    ("cuerda_saltar", "Cuerdas para saltar", "Funcional y accesorios"),
    ("cuerda_batida", "Cuerdas de batalla", "Funcional y accesorios"),
    ("fitball", "Pelotas de estabilidad", "Funcional y accesorios"),
    ("balon_medicinal", "Balones medicinales", "Funcional y accesorios"),
    ("bosu", "BOSU", "Funcional y accesorios"),
    ("foam_roller", "Rodillos de espuma", "Funcional y accesorios"),
    ("discos_deslizantes", "Discos deslizantes", "Funcional y accesorios"),
    ("escalera_agilidad", "Escalera de agilidad", "Funcional y accesorios"),
    ("conos", "Conos", "Funcional y accesorios"),
    ("vallas", "Vallas de entrenamiento", "Funcional y accesorios"),
    ("chaleco_lastrado", "Chalecos lastrados", "Funcional y accesorios"),
    ("trineo", "Trineo de empuje", "Funcional y accesorios"),
    ("rueda_abdominal", "Rueda abdominal", "Funcional y accesorios"),
    ("agarres_polea", "Agarres y manijas para polea", "Funcional y accesorios"),
    ("tobilleras_polea", "Tobilleras para polea", "Funcional y accesorios"),
    # Boxeo
    ("saco_boxeo", "Saco de boxeo", "Boxeo"),
    ("pera_boxeo", "Pera de boxeo", "Boxeo"),
    ("paos_boxeo", "Paos / manoplas", "Boxeo"),
]
EQUIPAMIENTO_CODIGOS = {item[0] for item in EQUIPAMIENTO_GIMNASIO}

# Ejercicios base que pueden incorporarse de forma incremental cuando
# el gimnasio compra o habilita equipamiento nuevo.
EJERCICIOS_GENERABLES_EQUIPO = {
    "mancuernas": [("Press con mancuernas", "Pecho", "fuerza", "principiante", "10-12"), ("Remo con mancuerna", "Espalda", "fuerza", "principiante", "10-12"), ("Zancadas con mancuernas", "Piernas", "fuerza", "principiante", "12 por lado")],
    "barra_discos": [("Sentadilla con barra", "Piernas", "fuerza", "intermedio", "8-10"), ("Remo con barra", "Espalda", "fuerza", "intermedio", "8-10"), ("Peso muerto rumano con barra", "Piernas", "fuerza", "intermedio", "10")],
    "barra_olimpica": [("Peso muerto con barra olimpica", "Piernas", "fuerza", "intermedio", "6-8"), ("Clean con barra olimpica", "Cuerpo completo", "funcional", "avanzado", "6")],
    "barra_ez": [("Curl de biceps con barra Z", "Biceps", "fuerza", "principiante", "10-12"), ("Extension de triceps con barra Z", "Triceps", "fuerza", "intermedio", "10-12")],
    "barra_hexagonal": [("Peso muerto con barra hexagonal", "Piernas", "fuerza", "intermedio", "8-10")],
    "kettlebell": [("Kettlebell swing", "Cuerpo completo", "funcional", "intermedio", "15"), ("Sentadilla goblet con kettlebell", "Piernas", "fuerza", "principiante", "12")],
    "banco_plano": [("Fondos apoyados en banco", "Triceps", "fuerza", "principiante", "12"), ("Step up en banco", "Piernas", "funcional", "principiante", "12 por lado")],
    "banco_inclinado": [("Flexiones inclinadas en banco", "Pecho", "fuerza", "principiante", "12")],
    "rack_sentadillas": [("Sentadilla en rack", "Piernas", "fuerza", "intermedio", "8-10")],
    "jaula_potencia": [("Sentadilla en jaula de potencia", "Piernas", "fuerza", "intermedio", "8-10")],
    "landmine": [("Press landmine", "Hombros", "fuerza", "intermedio", "10 por lado"), ("Remo landmine", "Espalda", "fuerza", "intermedio", "10")],
    "barra_dominadas": [("Dominadas", "Espalda", "fuerza", "avanzado", "Al fallo tecnico"), ("Elevacion de rodillas colgado", "Core", "fuerza", "intermedio", "12")],
    "paralelas": [("Fondos en paralelas", "Triceps", "fuerza", "avanzado", "8-12")],
    "multiestacion": [("Circuito en multiestacion", "Cuerpo completo", "fuerza", "principiante", "12 por estacion")],
    "poleas": [("Jalon al pecho en polea", "Espalda", "fuerza", "principiante", "12"), ("Patada de gluteo en polea", "Gluteos", "fuerza", "principiante", "12 por lado"), ("Extension de triceps en polea", "Triceps", "fuerza", "principiante", "12")],
    "crossover": [("Cruce de poleas para pecho", "Pecho", "fuerza", "principiante", "12")],
    "entrenador_funcional": [("Press alterno en doble polea", "Pecho", "funcional", "intermedio", "12")],
    "smith": [("Sentadilla en maquina Smith", "Piernas", "fuerza", "principiante", "10-12"), ("Press de pecho en Smith", "Pecho", "fuerza", "intermedio", "10")],
    "hack_sentadilla": [("Sentadilla Hack", "Piernas", "fuerza", "principiante", "10-12")],
    "sentadilla_pendular": [("Sentadilla pendular", "Piernas", "fuerza", "principiante", "10-12")],
    "belt_squat": [("Sentadilla belt squat", "Piernas", "fuerza", "principiante", "12")],
    "sissy_squat": [("Sentadilla sissy", "Piernas", "fuerza", "intermedio", "12")],
    "press_pecho_maquina": [("Press en maquina de pecho", "Pecho", "fuerza", "principiante", "12")],
    "press_inclinado_maquina": [("Press inclinado en maquina", "Pecho", "fuerza", "principiante", "12")],
    "press_declinado_maquina": [("Press declinado en maquina", "Pecho", "fuerza", "principiante", "12")],
    "pullover_maquina": [("Pullover en maquina", "Espalda", "fuerza", "principiante", "12")],
    "jalon_maquina": [("Jalon dorsal en maquina", "Espalda", "fuerza", "principiante", "12")],
    "remo_maquina": [("Remo en maquina", "Espalda", "fuerza", "principiante", "12")],
    "remo_alto_maquina": [("Remo alto en maquina", "Espalda", "fuerza", "intermedio", "12")],
    "dominadas_asistidas": [("Dominadas asistidas", "Espalda", "fuerza", "principiante", "10"), ("Fondos asistidos", "Triceps", "fuerza", "principiante", "10")],
    "prensa_piernas": [("Prensa de piernas", "Piernas", "fuerza", "principiante", "12")],
    "prensa_horizontal": [("Prensa horizontal de piernas", "Piernas", "fuerza", "principiante", "12")],
    "prensa_vertical": [("Prensa vertical de piernas", "Piernas", "fuerza", "intermedio", "10")],
    "extension_cuadriceps": [("Extension de cuadriceps", "Piernas", "fuerza", "principiante", "12-15")],
    "curl_femoral": [("Curl femoral en maquina", "Piernas", "fuerza", "principiante", "12")],
    "curl_femoral_sentado": [("Curl femoral sentado", "Piernas", "fuerza", "principiante", "12")],
    "curl_femoral_tumbado": [("Curl femoral tumbado", "Piernas", "fuerza", "principiante", "12")],
    "curl_femoral_pie": [("Curl femoral de pie", "Piernas", "fuerza", "principiante", "12 por lado")],
    "hip_thrust_maquina": [("Hip thrust en maquina", "Gluteos", "fuerza", "principiante", "12")],
    "abductores_aductores": [("Abduccion de cadera en maquina", "Gluteos", "fuerza", "principiante", "15"), ("Aduccion de cadera en maquina", "Piernas", "fuerza", "principiante", "15")],
    "glute_ham": [("Extension glute ham", "Piernas", "fuerza", "intermedio", "10")],
    "pantorrilla_maquina": [("Elevacion de pantorrilla en maquina", "Piernas", "fuerza", "principiante", "15")],
    "pantorrilla_sentado": [("Elevacion de pantorrilla sentado", "Piernas", "fuerza", "principiante", "15")],
    "pantorrilla_pie": [("Elevacion de pantorrilla de pie", "Piernas", "fuerza", "principiante", "15")],
    "press_hombros_maquina": [("Press de hombros en maquina", "Hombros", "fuerza", "principiante", "12")],
    "elevacion_lateral_maquina": [("Elevacion lateral en maquina", "Hombros", "fuerza", "principiante", "12")],
    "pec_deck": [("Aperturas en pec deck", "Pecho", "fuerza", "principiante", "12")],
    "deltoide_posterior": [("Apertura posterior en maquina", "Hombros", "fuerza", "principiante", "12")],
    "biceps_maquina": [("Curl de biceps en maquina", "Biceps", "fuerza", "principiante", "12")],
    "triceps_maquina": [("Extension de triceps en maquina", "Triceps", "fuerza", "principiante", "12")],
    "gluteo_maquina": [("Patada de gluteo en maquina", "Gluteos", "fuerza", "principiante", "12 por lado")],
    "abdominal_maquina": [("Crunch en maquina abdominal", "Core", "fuerza", "principiante", "15")],
    "lumbar_maquina": [("Extension lumbar en maquina", "Espalda", "fuerza", "principiante", "12")],
    "rotacion_torso": [("Rotacion de torso en maquina", "Core", "fuerza", "principiante", "12 por lado")],
    "caminadora": [("Caminata en caminadora", "Piernas", "cardio", "principiante", "15 min"), ("Intervalos en caminadora", "Piernas", "cardio", "intermedio", "10 min")],
    "bicicleta_estatica": [("Bicicleta estatica", "Piernas", "cardio", "principiante", "15 min")],
    "eliptica": [("Trabajo en eliptica", "Cuerpo completo", "cardio", "principiante", "15 min")],
    "escaladora": [("Intervalos en escaladora", "Piernas", "cardio", "intermedio", "10 min")],
    "remo_cardio": [("Remo ergometro", "Cuerpo completo", "cardio", "intermedio", "1000 m")],
    "bicicleta_spinning": [("Spinning por intervalos", "Piernas", "cardio", "intermedio", "20 min")],
    "bicicleta_reclinada": [("Bicicleta reclinada", "Piernas", "cardio", "principiante", "15 min")],
    "air_bike": [("Intervalos en air bike", "Cuerpo completo", "cardio", "intermedio", "10 x 30 s")],
    "ski_erg": [("Intervalos en ski erg", "Cuerpo completo", "cardio", "intermedio", "10 min")],
    "arc_trainer": [("Trabajo en arc trainer", "Cuerpo completo", "cardio", "principiante", "15 min")],
    "cinta_curva": [("Intervalos en caminadora curva", "Piernas", "cardio", "intermedio", "10 min")],
    "bandas_elasticas": [("Sentadilla con banda elastica", "Piernas", "funcional", "principiante", "15"), ("Pull apart con banda", "Espalda", "funcional", "principiante", "15")],
    "trx": [("Remo en TRX", "Espalda", "funcional", "principiante", "12"), ("Sentadilla asistida en TRX", "Piernas", "funcional", "principiante", "15")],
    "step": [("Step con rodillazo", "Piernas", "cardio", "intermedio", "16"), ("Step lateral", "Piernas", "cardio", "principiante", "16")],
    "cajon": [("Salto al cajon", "Piernas", "funcional", "intermedio", "10")],
    "colchoneta": [("Plancha frontal", "Core", "fuerza", "principiante", "30 s"), ("Crunch abdominal", "Core", "fuerza", "principiante", "15")],
    "cuerda_saltar": [("Saltar cuerda basico", "Cuerpo completo", "cardio", "principiante", "60 s"), ("Saltar cuerda doble", "Cuerpo completo", "cardio", "intermedio", "30 s")],
    "cuerda_batida": [("Battle ropes", "Cuerpo completo", "funcional", "intermedio", "30 s")],
    "fitball": [("Crunch con fitball", "Core", "fuerza", "principiante", "15"), ("Puente de gluteos con fitball", "Gluteos", "funcional", "intermedio", "12")],
    "balon_medicinal": [("Wall ball con balon medicinal", "Cuerpo completo", "funcional", "intermedio", "15")],
    "bosu": [("Sentadilla sobre BOSU", "Piernas", "funcional", "intermedio", "12")],
    "foam_roller": [("Movilidad con foam roller", "Cuerpo completo", "estiramiento", "principiante", "8 min")],
    "discos_deslizantes": [("Mountain climbers con deslizadores", "Core", "funcional", "intermedio", "30 s")],
    "escalera_agilidad": [("Pasos rapidos en escalera", "Piernas", "cardio", "intermedio", "6 vueltas")],
    "conos": [("Zigzag entre conos", "Piernas", "cardio", "principiante", "6 vueltas")],
    "vallas": [("Saltos sobre vallas", "Piernas", "funcional", "intermedio", "10")],
    "chaleco_lastrado": [("Caminata con chaleco lastrado", "Cuerpo completo", "fuerza", "intermedio", "10 min")],
    "trineo": [("Empuje de trineo", "Piernas", "funcional", "intermedio", "20 m")],
    "rueda_abdominal": [("Despliegue con rueda abdominal", "Core", "fuerza", "intermedio", "10")],
    "saco_boxeo": [("Golpes rectos al saco", "Cuerpo completo", "cardio", "principiante", "3 min"), ("Combinaciones al saco", "Cuerpo completo", "cardio", "intermedio", "3 min")],
    "pera_boxeo": [("Trabajo de pera de boxeo", "Hombros", "cardio", "intermedio", "3 min")],
    "paos_boxeo": [("Combinaciones con paos", "Cuerpo completo", "cardio", "intermedio", "3 min")],
}

EQUIPAMIENTO_GRUPOS = {
    codigo: sorted({plantilla[1] for plantilla in plantillas})
    for codigo, plantillas in EJERCICIOS_GENERABLES_EQUIPO.items()
}
EQUIPAMIENTO_POR_CODIGO = {codigo: (nombre, categoria) for codigo, nombre, categoria in EQUIPAMIENTO_GIMNASIO}


def _equipamiento_personalizado_gym(gimnasio: models.Gimnasio) -> list:
    try:
        elementos = json.loads(gimnasio.equipamiento_personalizado or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(elementos, list):
        return []
    return [
        item for item in elementos
        if isinstance(item, dict) and item.get("codigo") and item.get("nombre")
    ]


def _codigos_equipamiento_gym(gimnasio: models.Gimnasio) -> set:
    return EQUIPAMIENTO_CODIGOS | {
        item["codigo"] for item in _equipamiento_personalizado_gym(gimnasio)
    }


def _catalogo_equipamiento_gym(gimnasio: models.Gimnasio) -> list:
    catalogo = [
        {"codigo": c, "nombre": n, "categoria": cat, "grupos_musculares": EQUIPAMIENTO_GRUPOS.get(c, ["Cuerpo completo"]), "personalizado": False}
        for c, n, cat in EQUIPAMIENTO_GIMNASIO
    ]
    return catalogo + [dict(item, personalizado=True) for item in _equipamiento_personalizado_gym(gimnasio)]


def _equipamiento_disponible_gym(gimnasio: models.Gimnasio) -> set:
    codigos_validos = _codigos_equipamiento_gym(gimnasio)
    return {"sin_equipo"} | {
        codigo.strip() for codigo in (gimnasio.equipamiento_disponible or "").split(",")
        if codigo.strip() in codigos_validos
    }


def _equipos_pendientes_generacion(db: Session, gimnasio_id: int, seleccionados: set) -> list:
    generados = {
        fila[0] for fila in db.query(models.PaqueteRutina.equipamiento_origen).filter(
            models.PaqueteRutina.gimnasio_id == gimnasio_id,
            models.PaqueteRutina.equipamiento_origen.isnot(None),
        ).all()
    }
    return sorted((seleccionados & set(EJERCICIOS_GENERABLES_EQUIPO)) - generados)


@app.get("/equipamiento-gimnasio", tags=["Entrenamientos"])
def obtener_equipamiento_gimnasio(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    gimnasio = _configuracion_del_gym(db, usuario)
    seleccionados = _equipamiento_disponible_gym(gimnasio) - {"sin_equipo"}
    return {
        "catalogo": _catalogo_equipamiento_gym(gimnasio),
        "seleccionados": sorted(seleccionados),
        "pendientes_generacion": _equipos_pendientes_generacion(db, gimnasio.id, seleccionados),
    }


@app.put("/equipamiento-gimnasio", tags=["Entrenamientos"])
def guardar_equipamiento_gimnasio(datos: schemas.EquipamientoGimnasioUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gimnasio = _configuracion_del_gym(db, usuario)
    desconocidos = set(datos.equipos) - _codigos_equipamiento_gym(gimnasio)
    if desconocidos:
        raise HTTPException(status_code=400, detail="Hay equipamiento no reconocido")
    seleccionados = set(datos.equipos)
    gimnasio.equipamiento_disponible = ",".join(sorted(seleccionados))
    db.commit()
    return {
        "seleccionados": sorted(seleccionados),
        "pendientes_generacion": _equipos_pendientes_generacion(db, gimnasio.id, seleccionados),
    }


@app.post("/equipamiento-gimnasio/personalizado", tags=["Entrenamientos"])
def crear_equipamiento_personalizado(datos: schemas.EquipamientoPersonalizadoCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gimnasio = _configuracion_del_gym(db, usuario)
    personalizados = _equipamiento_personalizado_gym(gimnasio)
    nombre = " ".join(datos.nombre.strip().split())
    if any(item["nombre"].casefold() == nombre.casefold() for item in _catalogo_equipamiento_gym(gimnasio)):
        raise HTTPException(status_code=400, detail="Ese equipamiento ya existe en el catalogo")

    nombre_ascii = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii").lower()
    base = "_".join("".join(c if c.isalnum() else " " for c in nombre_ascii).split()) or "equipo"
    codigo_base = f"personalizado_{base}"[:80]
    codigo = codigo_base
    usados = _codigos_equipamiento_gym(gimnasio)
    numero = 2
    while codigo in usados:
        codigo = f"{codigo_base[:75]}_{numero}"
        numero += 1

    grupos = list(dict.fromkeys(" ".join(g.strip().split()) for g in datos.grupos_musculares if g.strip()))
    item = {
        "codigo": codigo,
        "nombre": nombre,
        "categoria": " ".join(datos.categoria.strip().split()) or "Otros",
        "grupos_musculares": grupos or ["Cuerpo completo"],
    }
    personalizados.append(item)
    gimnasio.equipamiento_personalizado = json.dumps(personalizados, ensure_ascii=False)
    seleccionados = _equipamiento_disponible_gym(gimnasio) - {"sin_equipo"}
    seleccionados.add(codigo)
    gimnasio.equipamiento_disponible = ",".join(sorted(seleccionados))
    db.commit()
    return {
        "catalogo": _catalogo_equipamiento_gym(gimnasio),
        "seleccionados": sorted(seleccionados),
        "pendientes_generacion": _equipos_pendientes_generacion(db, gimnasio.id, seleccionados),
        "creado": dict(item, personalizado=True),
    }


@app.post("/equipamiento-gimnasio/generar-rutinas", tags=["Entrenamientos"])
def generar_rutinas_por_equipamiento(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    gimnasio = _configuracion_del_gym(db, usuario)
    seleccionados = _equipamiento_disponible_gym(gimnasio) - {"sin_equipo"}
    pendientes = _equipos_pendientes_generacion(db, gimnasio.id, seleccionados)
    paquetes_creados = []
    ejercicios_creados = 0

    for codigo in pendientes:
        nombre_equipo, categoria_equipo = EQUIPAMIENTO_POR_CODIGO[codigo]
        ejercicios_paquete = []
        for nombre, grupo, categoria, nivel, repeticiones in EJERCICIOS_GENERABLES_EQUIPO[codigo]:
            ejercicio = db.query(models.TipoEjercicio).filter(
                models.TipoEjercicio.gimnasio_id == gimnasio.id,
                models.TipoEjercicio.nombre == nombre,
            ).first()
            if not ejercicio:
                ejercicio = models.TipoEjercicio(
                    gimnasio_id=gimnasio.id,
                    nombre=nombre,
                    grupo_muscular=grupo,
                    categoria=categoria,
                    equipamiento=codigo,
                    nivel=nivel,
                    genero_recomendado="todos",
                    objetivo="bajar_peso" if categoria == "cardio" else "ganar_masa",
                    activo=True,
                )
                db.add(ejercicio)
                db.flush()
                ejercicios_creados += 1
            else:
                ejercicio.activo = True
                ejercicio.equipamiento = codigo
                ejercicio.grupo_muscular = ejercicio.grupo_muscular or grupo
                ejercicio.categoria = ejercicio.categoria or categoria
            ejercicios_paquete.append(models.PaqueteRutinaEjercicio(
                tipo_ejercicio_id=ejercicio.id,
                nombre=ejercicio.nombre,
                series=1 if "min" in repeticiones else 3,
                repeticiones=repeticiones,
                notas=f"Usar {nombre_equipo}",
            ))

        objetivo = "bajar_peso" if categoria_equipo == "Cardio" else ("rendimiento" if categoria_equipo in {"Boxeo", "Funcional y accesorios"} else "ganar_masa")
        paquete = models.PaqueteRutina(
            gimnasio_id=gimnasio.id,
            nombre=f"Rutina · {nombre_equipo}",
            descripcion=f"Generada al habilitar {nombre_equipo}. No modifica los paquetes ni las rutinas existentes.",
            nivel="basico",
            objetivo=objetivo,
            etapa="adaptacion",
            genero_recomendado="todos",
            duracion_semanas=4,
            equipamiento_origen=codigo,
            dias=[models.PaqueteRutinaDia(
                nombre=f"Día 1 · {nombre_equipo}",
                orden=0,
                ejercicios=ejercicios_paquete,
            )],
        )
        db.add(paquete)
        paquetes_creados.append(nombre_equipo)

    db.commit()
    return {
        "equipos_procesados": paquetes_creados,
        "ejercicios_creados": ejercicios_creados,
        "paquetes_creados": len(paquetes_creados),
        "mensaje": "Se agregaron ejercicios y paquetes nuevos sin modificar las rutinas existentes" if paquetes_creados else "No hay equipamiento nuevo pendiente",
    }

@app.get("/configuracion/", response_model=schemas.Configuracion, tags=["Configuracion"])
def obtener_configuracion(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff_o_profesor)):
    return _configuracion_del_gym(db, usuario)


@app.put("/configuracion/", response_model=schemas.Configuracion, tags=["Configuracion"])
def actualizar_configuracion(datos: schemas.ConfiguracionUpdate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_staff)):
    config = _configuracion_del_gym(db, usuario)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(config, campo, valor)
    db.commit()
    db.refresh(config)
    return config


def _whatsapp_configuracion_del_gym(db: Session, gimnasio_id: int):
    config = db.query(models.WhatsAppConfiguracion).filter(
        models.WhatsAppConfiguracion.gimnasio_id == gimnasio_id,
    ).first()
    if not config:
        config = models.WhatsAppConfiguracion(gimnasio_id=gimnasio_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@app.get("/whatsapp/configuracion", response_model=schemas.WhatsAppConfiguracionOut, tags=["WhatsApp"])
def obtener_whatsapp_configuracion(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    return _whatsapp_configuracion_del_gym(db, usuario.gimnasio_id)


@app.put("/whatsapp/configuracion", response_model=schemas.WhatsAppConfiguracionOut, tags=["WhatsApp"])
def actualizar_whatsapp_configuracion(
    datos: schemas.WhatsAppConfiguracionUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    config = _whatsapp_configuracion_del_gym(db, usuario.gimnasio_id)
    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(config, campo, valor)
    config.actualizado_en = ahora_lima()
    db.commit()
    db.refresh(config)
    return config


@app.get("/whatsapp/mensajes", response_model=List[schemas.WhatsAppMensajeOut], tags=["WhatsApp"])
def listar_whatsapp_mensajes(
    limite: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    return db.query(models.WhatsAppMensaje).filter(
        models.WhatsAppMensaje.gimnasio_id == usuario.gimnasio_id,
    ).order_by(models.WhatsAppMensaje.creado_en.desc()).limit(limite).all()


# ==================================================================
# METAS DE VENTAS Y COMISIONES (solo administrador)
# ==================================================================

@app.get("/metas/", response_model=List[schemas.MetaMensual], tags=["Metas"])
def listar_metas(
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    query = q(db, models.MetaMensual, usuario)
    if anio:
        query = query.filter(models.MetaMensual.anio == anio)
    return query.order_by(models.MetaMensual.anio, models.MetaMensual.mes).all()


@app.put("/metas/{anio}/{mes}", response_model=schemas.MetaMensual, tags=["Metas"])
def guardar_meta_mensual(
    anio: int,
    mes: int,
    datos: schemas.MetaMensualUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """
    Crea o actualiza (upsert) la meta de un mes especifico. Pensado
    para la grilla editable de proyeccion a 1 anio: cada celda
    guardada llama a este endpoint con su anio/mes.
    """
    if mes < 1 or mes > 12:
        raise HTTPException(status_code=400, detail="Mes invalido (1-12)")

    meta = db.query(models.MetaMensual).filter(models.MetaMensual.anio == anio, models.MetaMensual.mes == mes, models.MetaMensual.gimnasio_id == get_gid(usuario)).first()
    if not meta:
        meta = models.MetaMensual(anio=anio, mes=mes, gimnasio_id=get_gid(usuario))
        db.add(meta)

    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(meta, campo, valor)

    db.commit()
    db.refresh(meta)
    return meta


@app.get("/comisiones/tramos", response_model=List[schemas.TramoComision], tags=["Metas"])
def listar_tramos_comision(db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    return q(db, models.TramoComision, usuario).order_by(models.TramoComision.tipo, models.TramoComision.porcentaje_meta_minimo).all()


@app.post("/comisiones/tramos", response_model=schemas.TramoComision, tags=["Metas"])
def crear_tramo_comision(datos: schemas.TramoComisionCreate, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    if datos.tipo not in ("membresia", "producto"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'membresia' o 'producto'")
    db_tramo = models.TramoComision(**datos.model_dump(), gimnasio_id=get_gid(usuario))
    db.add(db_tramo)
    db.commit()
    db.refresh(db_tramo)
    return db_tramo


@app.put("/comisiones/tramos/{tramo_id}", response_model=schemas.TramoComision, tags=["Metas"])
def actualizar_tramo_comision(
    tramo_id: int,
    datos: schemas.TramoComisionUpdate,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    tramo = db.query(models.TramoComision).filter(models.TramoComision.id == tramo_id, models.TramoComision.gimnasio_id == get_gid(usuario)).first()
    if not tramo:
        raise HTTPException(status_code=404, detail="Tramo no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(tramo, campo, valor)
    db.commit()
    db.refresh(tramo)
    return tramo


@app.delete("/comisiones/tramos/{tramo_id}", tags=["Metas"])
def eliminar_tramo_comision(tramo_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(auth.requiere_administrador)):
    tramo = db.query(models.TramoComision).filter(models.TramoComision.id == tramo_id, models.TramoComision.gimnasio_id == get_gid(usuario)).first()
    if not tramo:
        raise HTTPException(status_code=404, detail="Tramo no encontrado")
    db.delete(tramo)
    db.commit()
    return {"message": "Tramo eliminado"}


def _comision_aplicable(porcentaje_meta: float, tramos: List[models.TramoComision]) -> float:
    """Devuelve el % de comision del tramo mas alto que se alcanza (0 si ninguno)."""
    mejor = 0.0
    for tramo in tramos:
        if tramo.activo and porcentaje_meta >= tramo.porcentaje_meta_minimo:
            mejor = max(mejor, tramo.porcentaje_comision)
    return mejor


@app.get("/comisiones/resumen", response_model=List[schemas.ResumenComisionUsuario], tags=["Metas"])
def resumen_comisiones(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """
    Calcula, para cada trabajador de staff activo, sus ventas de
    membresias y productos en el mes, el % de cumplimiento respecto
    a la meta mensual, y la comision resultante segun los tramos
    configurados (se aplica el tramo mas alto alcanzado).
    """
    if mes < 1 or mes > 12:
        raise HTTPException(status_code=400, detail="Mes invalido (1-12)")

    desde = date(anio, mes, 1)
    hasta = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)

    meta = q(db, models.MetaMensual, usuario).filter(
        models.MetaMensual.anio == anio,
        models.MetaMensual.mes == mes,
    ).first()
    meta_membresias = meta.meta_membresias if meta else 0.0
    meta_productos = meta.meta_productos if meta else 0.0

    config = _configuracion_del_gym(db, usuario)
    comision_producto_flat = config.comision_producto_porcentaje or 0.0

    tramos = q(db, models.TramoComision, usuario).filter(models.TramoComision.activo == True, models.TramoComision.tipo == "membresia").all()

    usuarios = q(db, models.Usuario, usuario).filter(models.Usuario.activo == True).all()

    resultado = []
    for usuario in usuarios:
        ventas_membresias = (
            db.query(func.coalesce(func.sum(models.PagoMembresia.monto), 0.0))
            .join(models.ClienteMembresia, models.ClienteMembresia.id == models.PagoMembresia.cliente_membresia_id)
            .join(models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id)
            .filter(
                models.Cliente.gimnasio_id == get_gid(usuario),
                models.ClienteMembresia.vendido_por_id == usuario.id,
                models.ClienteMembresia.anulada == False,
                models.PagoMembresia.anulada == False,
                models.PagoMembresia.fecha_pago >= datetime.combine(desde, datetime.min.time()),
                models.PagoMembresia.fecha_pago < datetime.combine(hasta, datetime.min.time()),
            )
            .scalar()
        )
        ventas_productos = (
            db.query(func.coalesce(func.sum(models.Venta.total), 0.0))
            .filter(
                models.Venta.usuario_id == usuario.id,
                models.Venta.anulada == False,
                models.Venta.fecha_venta >= desde,
                models.Venta.fecha_venta < hasta,
            )
            .scalar()
        )

        if ventas_membresias == 0 and ventas_productos == 0:
            continue

        pct_meta_membresias = round((ventas_membresias / meta_membresias * 100), 1) if meta_membresias else 0.0
        pct_meta_productos = round((ventas_productos / meta_productos * 100), 1) if meta_productos else 0.0

        pct_comision_membresias = _comision_aplicable(pct_meta_membresias, tramos)
        # Productos: comision plana por cada venta, NO depende de metas.
        pct_comision_productos = comision_producto_flat

        comision_membresias = round(ventas_membresias * pct_comision_membresias / 100, 2)
        comision_productos = round(ventas_productos * pct_comision_productos / 100, 2)

        resultado.append(
            schemas.ResumenComisionUsuario(
                usuario_id=usuario.id,
                nombre_completo=usuario.nombre_completo,
                ventas_membresias=ventas_membresias,
                ventas_productos=ventas_productos,
                meta_membresias=meta_membresias,
                meta_productos=meta_productos,
                porcentaje_meta_membresias=pct_meta_membresias,
                porcentaje_meta_productos=pct_meta_productos,
                porcentaje_comision_membresias=pct_comision_membresias,
                porcentaje_comision_productos=pct_comision_productos,
                comision_membresias=comision_membresias,
                comision_productos=comision_productos,
                comision_total=round(comision_membresias + comision_productos, 2),
            )
        )

    resultado.sort(key=lambda r: r.comision_total, reverse=True)
    return resultado


@app.get("/metas/evolucion", tags=["Metas"])
def evolucion_metas_anual(
    anio: int,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    """Resumen mensual compacto para comparar metas, ventas y comisiones."""
    gid = get_gid(usuario)
    metas = {
        m.mes: m for m in q(db, models.MetaMensual, usuario)
        .filter(models.MetaMensual.anio == anio).all()
    }
    config = _configuracion_del_gym(db, usuario)
    porcentaje_producto = float(config.comision_producto_porcentaje or 0.0)
    tramos = q(db, models.TramoComision, usuario).filter(
        models.TramoComision.activo == True,
        models.TramoComision.tipo == "membresia",
    ).all()
    evolucion = []

    for mes in range(1, 13):
        desde = date(anio, mes, 1)
        hasta = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        meta = metas.get(mes)
        meta_membresias = float(meta.meta_membresias or 0.0) if meta else 0.0
        meta_productos = float(meta.meta_productos or 0.0) if meta else 0.0

        membresias_por_usuario = dict(db.query(
            models.ClienteMembresia.vendido_por_id,
            func.coalesce(func.sum(models.PagoMembresia.monto), 0.0),
        ).join(
            models.PagoMembresia, models.PagoMembresia.cliente_membresia_id == models.ClienteMembresia.id,
        ).join(
            models.Cliente, models.Cliente.id == models.ClienteMembresia.cliente_id,
        ).filter(
            models.Cliente.gimnasio_id == gid,
            models.ClienteMembresia.anulada == False,
            models.PagoMembresia.anulada == False,
            models.PagoMembresia.fecha_pago >= datetime.combine(desde, datetime.min.time()),
            models.PagoMembresia.fecha_pago < datetime.combine(hasta, datetime.min.time()),
        ).group_by(models.ClienteMembresia.vendido_por_id).all())
        productos_por_usuario = dict(db.query(
            models.Venta.usuario_id,
            func.coalesce(func.sum(models.Venta.total), 0.0),
        ).filter(
            models.Venta.gimnasio_id == gid,
            models.Venta.anulada == False,
            models.Venta.fecha_venta >= desde,
            models.Venta.fecha_venta < hasta,
        ).group_by(models.Venta.usuario_id).all())

        ventas_membresias = round(sum(float(v or 0) for v in membresias_por_usuario.values()), 2)
        ventas_productos = round(sum(float(v or 0) for v in productos_por_usuario.values()), 2)
        comisiones = 0.0
        for usuario_id in set(membresias_por_usuario) | set(productos_por_usuario):
            if usuario_id is None:
                continue
            venta_m = float(membresias_por_usuario.get(usuario_id) or 0.0)
            venta_p = float(productos_por_usuario.get(usuario_id) or 0.0)
            cumplimiento = (venta_m / meta_membresias * 100) if meta_membresias else 0.0
            comisiones += venta_m * _comision_aplicable(cumplimiento, tramos) / 100
            comisiones += venta_p * porcentaje_producto / 100

        evolucion.append({
            "mes": mes,
            "meta_membresias": round(meta_membresias, 2),
            "ventas_membresias": ventas_membresias,
            "cumplimiento_membresias": round(ventas_membresias / meta_membresias * 100, 1) if meta_membresias else 0.0,
            "meta_productos": round(meta_productos, 2),
            "ventas_productos": ventas_productos,
            "cumplimiento_productos": round(ventas_productos / meta_productos * 100, 1) if meta_productos else 0.0,
            "comisiones": round(comisiones, 2),
        })
    return evolucion


# ==================================================================
# SAAS / SUPER-ADMIN (gestion de gimnasios y planes)
# ==================================================================


@app.post("/auth/registro-gimnasio", response_model=schemas.TokenResponse, tags=["Auth"])
def registro_gimnasio(datos: schemas.RegistroGimnasioRequest, request: Request, db: Session = Depends(get_db)):
    """
    Registro publico: un dueño de gimnasio crea su cuenta.
    Crea el gimnasio (plan Free), su usuario admin, siembra datos
    iniciales y devuelve un token listo para usar.
    """
    import re
    if os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true" and not email_service.esta_configurado():
        raise HTTPException(
            status_code=503,
            detail="El registro esta temporalmente pausado porque el correo de verificacion no esta disponible",
        )
    try:
        auth.validar_password_segura(datos.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    slug = datos.slug.strip().lower()
    if not re.match(r'^[a-z0-9][a-z0-9\-]{1,48}[a-z0-9]$', slug):
        raise HTTPException(status_code=400, detail="El slug debe tener 3-50 caracteres, solo letras minusculas, numeros y guiones, sin empezar ni terminar en guion")
    if db.query(models.Gimnasio).filter(models.Gimnasio.slug == slug).first():
        raise HTTPException(status_code=400, detail=f"Ya existe un gimnasio con el identificador '{slug}'")
    username = datos.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="El usuario debe tener al menos 3 caracteres")
    if db.query(models.Usuario).filter(models.Usuario.username == username).first():
        raise HTTPException(status_code=400, detail=f"El usuario '{username}' ya esta en uso")
    if len(datos.password) < 4:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 4 caracteres")

    plan_free = db.query(models.PlanSaas).filter_by(nombre="Free").first()

    db_gimnasio = models.Gimnasio(
        nombre=datos.nombre_gimnasio.strip(),
        slug=slug,
        plan_id=plan_free.id if plan_free else None,
        email_contacto=datos.email,
        telefono=datos.telefono,
    )
    db.add(db_gimnasio)
    db.flush()

    db_admin = models.Usuario(
        gimnasio_id=db_gimnasio.id,
        nombre_completo=datos.nombre_admin.strip(),
        username=username,
        email=str(datos.email).lower(),
        email_verificado=False,
        password_hash=auth.hash_password(datos.password),
        rol=models.RolUsuario.STAFF,
        es_administrador=True,
        puede_eliminar=True,
        puede_exportar=True,
    )
    db.add(db_admin)
    db.flush()

    _crear_prueba_saas(db, db_gimnasio)
    _sembrar_datos_gimnasio_nuevo(db, db_gimnasio.id)
    db.commit()
    db.refresh(db_admin)

    if email_service.esta_configurado():
        try:
            token_email = _crear_token_un_solo_uso(db, db_admin.id, "verificar_email", 24 * 60)
            base = os.getenv("APP_BASE_URL", "http://localhost:3001").rstrip("/")
            url = f"{base}/verificar-email.html?token={token_email}"
            email_service.enviar(
                db_admin.email,
                "Verifica tu correo de Soft-Gym",
                email_service.plantilla_accion("Verifica tu correo", "Confirma que este correo pertenece al propietario del gimnasio.", "Verificar correo", url),
            )
        except Exception:
            logger.exception("No se pudo enviar el correo de verificacion del gimnasio %s", db_gimnasio.id)

    sesion = _crear_sesion_usuario(db, db_admin, request)
    token = auth.crear_access_token({
        "sub": str(db_admin.id),
        "tipo": "usuario",
        "rol": db_admin.rol.value,
        "gimnasio_id": db_gimnasio.id,
        "sv": db_admin.sesion_version or 1,
        "jti": sesion.jti,
    })
    return schemas.TokenResponse(
        access_token=token,
        rol=db_admin.rol.value,
        nombre=db_admin.nombre_completo,
        es_administrador=True,
        puede_eliminar=True,
        puede_exportar=True,
        gimnasio_id=db_gimnasio.id,
    )

def _sembrar_datos_gimnasio_nuevo(db: Session, gimnasio_id: int):
    """
    Copia los datos iniciales (ejercicios, paquetes de rutinas,
    alimentos, paquetes de nutricion, puestos y servicios) del gimnasio 1 al
    nuevo gimnasio. Asi cada gym nuevo arranca con el catalogo
    completo sin hardcodear la data aqui.
    """
    GYM_TEMPLATE = 1
    if gimnasio_id == GYM_TEMPLATE:
        return

    # --- Ejercicios ---
    mapa_ejercicios = {}  # id_viejo -> obj_nuevo (para paquetes de rutinas)
    for ej in db.query(models.TipoEjercicio).filter(models.TipoEjercicio.gimnasio_id == GYM_TEMPLATE).all():
        nuevo_ejercicio = models.TipoEjercicio(
            gimnasio_id=gimnasio_id, nombre=ej.nombre, grupo_muscular=ej.grupo_muscular,
            categoria=ej.categoria, equipamiento=ej.equipamiento, nivel=ej.nivel,
            genero_recomendado=ej.genero_recomendado, objetivo=ej.objetivo,
            descripcion=ej.descripcion,
        )
        db.add(nuevo_ejercicio)
        db.flush()
        mapa_ejercicios[ej.id] = nuevo_ejercicio

    # --- Paquetes de rutinas (con dias y ejercicios enlazados) ---
    for paquete in db.query(models.PaqueteRutina).filter(
        models.PaqueteRutina.gimnasio_id == GYM_TEMPLATE,
        models.PaqueteRutina.activo == True,
        models.PaqueteRutina.equipamiento_origen.is_(None),
    ).all():
        dias = []
        for dia in paquete.dias:
            ejercicios = []
            for ejercicio in dia.ejercicios:
                nuevo_catalogo = mapa_ejercicios.get(ejercicio.tipo_ejercicio_id)
                ejercicios.append(models.PaqueteRutinaEjercicio(
                    tipo_ejercicio_id=nuevo_catalogo.id if nuevo_catalogo else None,
                    nombre=nuevo_catalogo.nombre if nuevo_catalogo else ejercicio.nombre,
                    series=ejercicio.series,
                    repeticiones=ejercicio.repeticiones,
                    peso=ejercicio.peso,
                    notas=ejercicio.notas,
                ))
            dias.append(models.PaqueteRutinaDia(
                nombre=dia.nombre,
                orden=dia.orden,
                ejercicios=ejercicios,
            ))
        db.add(models.PaqueteRutina(
            gimnasio_id=gimnasio_id,
            nombre=paquete.nombre,
            descripcion=paquete.descripcion,
            nivel=paquete.nivel,
            objetivo=paquete.objetivo,
            etapa=paquete.etapa,
            genero_recomendado=paquete.genero_recomendado,
            edad_min=paquete.edad_min,
            edad_max=paquete.edad_max,
            duracion_semanas=paquete.duracion_semanas,
            dias=dias,
        ))

    # --- Alimentos ---
    mapa_alimentos = {}  # id_viejo -> obj_nuevo (para paquetes)
    for al in db.query(models.Alimento).filter(models.Alimento.gimnasio_id == GYM_TEMPLATE).all():
        nuevo = models.Alimento(
            gimnasio_id=gimnasio_id, nombre=al.nombre, categoria=al.categoria,
            calorias=al.calorias, proteinas_g=al.proteinas_g,
            carbohidratos_g=al.carbohidratos_g, grasas_g=al.grasas_g,
            fibra_g=al.fibra_g, porcion_gramos=al.porcion_gramos,
            porcion_casera=al.porcion_casera,
        )
        db.add(nuevo)
        db.flush()
        mapa_alimentos[al.id] = nuevo

    # --- Paquetes de nutricion (con sus items) ---
    for paq in db.query(models.PaqueteNutricion).filter(models.PaqueteNutricion.gimnasio_id == GYM_TEMPLATE).all():
        nuevo_paq = models.PaqueteNutricion(
            gimnasio_id=gimnasio_id, nombre=paq.nombre,
            tipo_comida=paq.tipo_comida, proposito=paq.proposito, notas=paq.notas,
        )
        db.add(nuevo_paq)
        db.flush()
        for item in paq.items:
            nuevo_al = mapa_alimentos.get(item.alimento_id)
            if nuevo_al:
                db.add(models.PaqueteAlimento(
                    paquete_id=nuevo_paq.id, alimento_id=nuevo_al.id,
                    cantidad_gramos=item.cantidad_gramos,
                    porcion_cliente=item.porcion_cliente,
                ))

    # --- Puestos ---
    for p in db.query(models.Puesto).filter(models.Puesto.gimnasio_id == GYM_TEMPLATE).all():
        db.add(models.Puesto(gimnasio_id=gimnasio_id, nombre=p.nombre, tipo=p.tipo))

    # --- Servicios ---
    for s in db.query(models.Servicio).filter(models.Servicio.gimnasio_id == GYM_TEMPLATE).all():
        db.add(models.Servicio(gimnasio_id=gimnasio_id, nombre=s.nombre, notas=s.notas))

    db.flush()

@app.get("/saas/planes", response_model=List[schemas.PlanSaas], tags=["SaaS"])
def listar_planes_saas(db: Session = Depends(get_db), _: models.Usuario = Depends(auth.requiere_superadmin)):
    return db.query(models.PlanSaas).order_by(models.PlanSaas.id).all()


@app.post("/saas/planes", response_model=schemas.PlanSaas, tags=["SaaS"])
def crear_plan_saas(datos: schemas.PlanSaasCreate, db: Session = Depends(get_db), _: models.Usuario = Depends(auth.requiere_superadmin)):
    db_plan = models.PlanSaas(**datos.model_dump())
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan


@app.put("/saas/planes/{plan_id}", response_model=schemas.PlanSaas, tags=["SaaS"])
def actualizar_plan_saas(plan_id: int, datos: schemas.PlanSaasUpdate, db: Session = Depends(get_db), _: models.Usuario = Depends(auth.requiere_superadmin)):
    plan = db.query(models.PlanSaas).filter(models.PlanSaas.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(plan, campo, valor)
    db.commit()
    db.refresh(plan)
    return plan


@app.get("/saas/gimnasios", response_model=List[schemas.GimnasioDetalle], tags=["SaaS"])
def listar_gimnasios(db: Session = Depends(get_db), _: models.Usuario = Depends(auth.requiere_superadmin)):
    """Dashboard de gimnasios con stats basicas."""
    gimnasios = db.query(models.Gimnasio).order_by(models.Gimnasio.id).all()
    resultado = []
    for g in gimnasios:
        total_clientes = db.query(func.count(models.Cliente.id)).filter(
            models.Cliente.gimnasio_id == g.id, models.Cliente.activo == True
        ).scalar() or 0
        total_usuarios = db.query(func.count(models.Usuario.id)).filter(
            models.Usuario.gimnasio_id == g.id, models.Usuario.activo == True
        ).scalar() or 0
        nombre_plan = g.plan.nombre if g.plan else None
        suscripcion = g.suscripcion_saas
        estado_suscripcion = _estado_suscripcion(suscripcion)
        limite = (suscripcion.fecha_fin_gracia or suscripcion.fecha_fin_periodo) if suscripcion else None
        resultado.append(schemas.GimnasioDetalle(
            id=g.id, nombre=g.nombre, slug=g.slug, plan_id=g.plan_id,
            activo=g.activo, fecha_registro=g.fecha_registro,
            email_contacto=g.email_contacto, telefono=g.telefono,
            direccion=g.direccion, logo_url=g.logo_url,
            total_clientes=total_clientes, total_usuarios=total_usuarios,
            nombre_plan=nombre_plan,
            estado_suscripcion=estado_suscripcion,
            fecha_fin_periodo=suscripcion.fecha_fin_periodo if suscripcion else None,
            fecha_fin_gracia=suscripcion.fecha_fin_gracia if suscripcion else None,
            dias_restantes=max((limite - hoy_lima()).days, 0) if limite else None,
        ))
    return resultado


@app.post("/saas/gimnasios", response_model=schemas.Gimnasio, tags=["SaaS"])
def crear_gimnasio(
    datos: schemas.GimnasioCreate,
    db: Session = Depends(get_db),
    _: models.Usuario = Depends(auth.requiere_superadmin),
):
    """
    Crea un gimnasio nuevo con su usuario admin inicial.
    El slug debe ser unico (URL-friendly).
    """
    try:
        auth.validar_password_segura(datos.admin_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    existente = db.query(models.Gimnasio).filter(models.Gimnasio.slug == datos.slug).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"Ya existe un gimnasio con slug '{datos.slug}'")
    existente_user = db.query(models.Usuario).filter(models.Usuario.username == datos.admin_username).first()
    if existente_user:
        raise HTTPException(status_code=400, detail=f"Ya existe un usuario con username '{datos.admin_username}'")

    db_gimnasio = models.Gimnasio(
        nombre=datos.nombre, slug=datos.slug, plan_id=datos.plan_id,
        email_contacto=datos.email_contacto, telefono=datos.telefono, direccion=datos.direccion,
    )
    db.add(db_gimnasio)
    db.flush()

    db_admin = models.Usuario(
        gimnasio_id=db_gimnasio.id,
        nombre_completo=datos.admin_nombre,
        username=datos.admin_username,
        password_hash=auth.hash_password(datos.admin_password),
        rol=models.RolUsuario.STAFF,
        es_administrador=True,
        puede_eliminar=True,
        puede_exportar=True,
    )
    db.add(db_admin)
    _crear_prueba_saas(db, db_gimnasio)
    _sembrar_datos_gimnasio_nuevo(db, db_gimnasio.id)
    db.commit()
    db.refresh(db_gimnasio)
    return db_gimnasio


@app.put("/saas/gimnasios/{gimnasio_id}", response_model=schemas.Gimnasio, tags=["SaaS"])
def actualizar_gimnasio(
    gimnasio_id: int,
    datos: schemas.GimnasioUpdate,
    db: Session = Depends(get_db),
    _: models.Usuario = Depends(auth.requiere_superadmin),
):
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gimnasio_id).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    datos_dict = datos.model_dump(exclude_unset=True)
    if "slug" in datos_dict:
        otro = db.query(models.Gimnasio).filter(
            models.Gimnasio.slug == datos_dict["slug"], models.Gimnasio.id != gimnasio_id
        ).first()
        if otro:
            raise HTTPException(status_code=400, detail=f"Ya existe otro gimnasio con slug '{datos_dict['slug']}'")
    for campo, valor in datos_dict.items():
        setattr(gimnasio, campo, valor)
    db.commit()
    db.refresh(gimnasio)
    return gimnasio


@app.get("/saas/gimnasios/{gimnasio_id}/suscripcion", response_model=schemas.SuscripcionSaasOut, tags=["SaaS"])
def ver_suscripcion_saas(
    gimnasio_id: int,
    db: Session = Depends(get_db),
    _: models.Usuario = Depends(auth.requiere_superadmin),
):
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gimnasio_id).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    return _serializar_suscripcion(gimnasio)


@app.get("/suscripcion/mi-plan", response_model=schemas.SuscripcionSaasOut, tags=["SaaS"])
def mi_suscripcion_saas(
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_administrador),
):
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == get_gid(usuario)).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    return _serializar_suscripcion(gimnasio)


@app.put("/saas/gimnasios/{gimnasio_id}/suscripcion", response_model=schemas.SuscripcionSaasOut, tags=["SaaS"])
def actualizar_suscripcion_saas(
    gimnasio_id: int,
    datos: schemas.SuscripcionSaasUpdate,
    db: Session = Depends(get_db),
    _: models.Usuario = Depends(auth.requiere_superadmin),
):
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gimnasio_id).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    suscripcion = gimnasio.suscripcion_saas
    if not suscripcion:
        suscripcion = models.SuscripcionSaas(
            gimnasio_id=gimnasio.id,
            plan_id=gimnasio.plan_id,
            estado="activa",
            fecha_inicio=hoy_lima(),
            fecha_fin_periodo=hoy_lima(),
            fecha_fin_gracia=hoy_lima() + timedelta(days=5),
            dias_gracia=5,
        )
        db.add(suscripcion)
        db.flush()

    cambios = datos.model_dump(exclude_unset=True)
    if "plan_id" in cambios:
        plan = db.query(models.PlanSaas).filter(
            models.PlanSaas.id == cambios["plan_id"], models.PlanSaas.activo == True
        ).first()
        if not plan:
            raise HTTPException(status_code=400, detail="Plan SaaS no encontrado o inactivo")
        gimnasio.plan_id = plan.id
    for campo, valor in cambios.items():
        if campo not in {"plan_id"}:
            setattr(suscripcion, campo, valor)
    if "plan_id" in cambios:
        suscripcion.plan_id = cambios["plan_id"]
    if "estado" in cambios:
        suscripcion.fecha_suspension = ahora_lima() if cambios["estado"] in {"suspendida", "cancelada"} else None
    if "fecha_fin_periodo" in cambios or "dias_gracia" in cambios:
        suscripcion.fecha_fin_gracia = suscripcion.fecha_fin_periodo + timedelta(days=suscripcion.dias_gracia)
    db.commit()
    db.refresh(gimnasio)
    return _serializar_suscripcion(gimnasio)


@app.post("/saas/gimnasios/{gimnasio_id}/suscripcion/renovar", response_model=schemas.SuscripcionSaasOut, tags=["SaaS"])
def renovar_suscripcion_saas(
    gimnasio_id: int,
    datos: schemas.RenovacionSaasRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(auth.requiere_superadmin),
):
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gimnasio_id).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")
    plan_id = datos.plan_id or gimnasio.plan_id
    plan = db.query(models.PlanSaas).filter(
        models.PlanSaas.id == plan_id, models.PlanSaas.activo == True
    ).first()
    if not plan:
        raise HTTPException(status_code=400, detail="Selecciona un plan SaaS activo")

    suscripcion = gimnasio.suscripcion_saas
    hoy = hoy_lima()
    if suscripcion and suscripcion.fecha_fin_periodo >= hoy and _estado_suscripcion(suscripcion) not in {"cancelada"}:
        periodo_inicio = suscripcion.fecha_fin_periodo + timedelta(days=1)
    else:
        periodo_inicio = hoy
    periodo_fin = _sumar_meses(periodo_inicio, datos.meses) - timedelta(days=1)

    if not suscripcion:
        suscripcion = models.SuscripcionSaas(
            gimnasio_id=gimnasio.id,
            plan_id=plan.id,
            estado="activa",
            fecha_inicio=periodo_inicio,
            fecha_fin_periodo=periodo_fin,
            fecha_fin_gracia=periodo_fin + timedelta(days=5),
            dias_gracia=5,
        )
        db.add(suscripcion)
        db.flush()
    else:
        suscripcion.plan_id = plan.id
        suscripcion.estado = "activa"
        suscripcion.fecha_fin_periodo = periodo_fin
        suscripcion.fecha_fin_gracia = periodo_fin + timedelta(days=suscripcion.dias_gracia)
        suscripcion.fecha_suspension = None

    gimnasio.plan_id = plan.id
    pago = models.PagoSaas(
        gimnasio_id=gimnasio.id,
        suscripcion_id=suscripcion.id,
        plan_id=plan.id,
        monto=datos.monto,
        moneda=datos.moneda,
        metodo_pago=datos.metodo_pago,
        referencia=datos.referencia,
        fecha_pago=datos.fecha_pago or ahora_lima(),
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        registrado_por_id=usuario.id,
        notas=datos.notas,
    )
    db.add(pago)
    db.commit()
    db.refresh(gimnasio)
    return _serializar_suscripcion(gimnasio)


@app.delete("/saas/gimnasios/{gimnasio_id}", tags=["SaaS"])
def eliminar_gimnasio(
    gimnasio_id: int,
    db: Session = Depends(get_db),
    _: models.Usuario = Depends(auth.requiere_superadmin),
):
    """
    Elimina un gimnasio y TODOS sus datos asociados. Irreversible.
    No permite eliminar el gimnasio template (id=1).
    """
    if gimnasio_id == 1:
        raise HTTPException(status_code=400, detail="No se puede eliminar el gimnasio principal (template)")
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == gimnasio_id).first()
    if not gimnasio:
        raise HTTPException(status_code=404, detail="Gimnasio no encontrado")

    # Eliminar datos en orden (hijos antes que padres)
    tablas_con_gimnasio_id = [
        models.Medida, models.Progreso, models.Asistencia,
        models.PagoPlanilla, models.CargoServicio,
        models.Venta, models.Compra, models.Producto,
        models.ClaseDictada, models.Empleado, models.Puesto,
        models.Servicio, models.MetaMensual, models.TramoComision,
        models.PaqueteNutricion, models.PlanNutricion,
        models.Alimento, models.TipoEjercicio, models.Rutina,
        models.Reto, models.Membresia, models.Cliente,
        models.Usuario,
    ]
    for modelo in tablas_con_gimnasio_id:
        db.query(modelo).filter(modelo.gimnasio_id == gimnasio_id).delete(synchronize_session=False)

    db.delete(gimnasio)
    db.commit()
    return {"ok": True, "detalle": f"Gimnasio '{gimnasio.nombre}' y todos sus datos eliminados"}


@app.get("/saas/dashboard", tags=["SaaS"])
def dashboard_saas(db: Session = Depends(get_db), _: models.Usuario = Depends(auth.requiere_superadmin)):
    """Stats globales de la plataforma para el super-admin."""
    total_gimnasios = db.query(func.count(models.Gimnasio.id)).scalar() or 0
    gimnasios_activos = db.query(func.count(models.Gimnasio.id)).filter(models.Gimnasio.activo == True).scalar() or 0
    total_clientes = db.query(func.count(models.Cliente.id)).filter(models.Cliente.activo == True).scalar() or 0
    total_usuarios = db.query(func.count(models.Usuario.id)).filter(models.Usuario.activo == True).scalar() or 0
    suscripciones = db.query(models.SuscripcionSaas).all()
    estados = {"prueba": 0, "activa": 0, "gracia": 0, "vencida": 0, "suspendida": 0, "cancelada": 0, "sin_configurar": 0}
    for suscripcion in suscripciones:
        estados[_estado_suscripcion(suscripcion)] += 1
    estados["sin_configurar"] = max(total_gimnasios - len(suscripciones), 0)
    ingresos_mes = db.query(func.sum(models.PagoSaas.monto)).filter(
        func.extract("month", models.PagoSaas.fecha_pago) == hoy_lima().month,
        func.extract("year", models.PagoSaas.fecha_pago) == hoy_lima().year,
    ).scalar() or 0.0
    return {
        "total_gimnasios": total_gimnasios,
        "gimnasios_activos": gimnasios_activos,
        "total_clientes_plataforma": total_clientes,
        "total_usuarios_plataforma": total_usuarios,
        "suscripciones_por_estado": estados,
        "ingresos_saas_mes": round(float(ingresos_mes), 2),
    }


# ==================================================================
# PORTAL DEL ALUMNO (solo lectura, requiere token de tipo "alumno")
# ==================================================================

@app.get("/portal-alumno/mi-perfil", response_model=schemas.Cliente, tags=["Portal Alumno"])
def mi_perfil(cliente: models.Cliente = Depends(auth.get_cliente_actual)):
    return cliente


def _cliente_tiene_pago_vencido(db: Session, cliente_id: int) -> bool:
    membresia = (db.query(models.ClienteMembresia)
        .filter(models.ClienteMembresia.cliente_id == cliente_id, models.ClienteMembresia.activo == True)
        .order_by(models.ClienteMembresia.fecha_inicio.desc()).first())
    if not membresia or not membresia.fecha_pago_saldo or membresia.fecha_pago_saldo >= hoy_lima():
        return False
    precio = float(membresia.membresia.precio or 0) if membresia.membresia else 0
    return max(precio - _total_pagado_membresia(db, membresia.id), 0) > 0.009


def _validar_acceso_modulos_alumno(db: Session, cliente: models.Cliente):
    if _cliente_tiene_pago_vencido(db, cliente.id):
        raise HTTPException(status_code=403, detail="Tienes un pago vencido. Regulariza tu saldo para acceder a este modulo")


@app.get("/portal-alumno/resumen", tags=["Portal Alumno"])
def resumen_portal_alumno(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    membresia = (db.query(models.ClienteMembresia)
        .filter(models.ClienteMembresia.cliente_id == cliente.id, models.ClienteMembresia.activo == True)
        .order_by(models.ClienteMembresia.fecha_inicio.desc()).first())
    asistencia_hoy = db.query(models.Asistencia.id).filter(
        models.Asistencia.cliente_id == cliente.id,
        func.date(models.Asistencia.fecha_hora_entrada) == hoy_lima().isoformat(),
    ).first() is not None
    plan = None
    pago_vencido = False
    sin_pagos_pendientes = False
    if membresia:
        precio = float(membresia.membresia.precio or 0)
        pagado = _total_pagado_membresia(db, membresia.id)
        saldo = round(max(precio - pagado, 0), 2)
        pago_vencido = bool(saldo > 0.009 and membresia.fecha_pago_saldo and membresia.fecha_pago_saldo < hoy_lima())
        sin_pagos_pendientes = saldo <= 0.009
        plan = {"nombre": membresia.membresia.nombre, "inicio": membresia.fecha_inicio,
                "fin": membresia.fecha_fin, "precio": round(precio, 2), "pagado": round(pagado, 2),
                "saldo": saldo, "fecha_proximo_pago": membresia.fecha_pago_saldo,
                "incluye_nutricion": bool(membresia.membresia.incluye_nutricion),
                "incluye_retos": bool(membresia.membresia.incluye_retos)}
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == cliente.gimnasio_id).first()
    return {"perfil": schemas.Cliente.model_validate(cliente).model_dump(mode="json"), "plan": plan,
            "asistencia_hoy": asistencia_hoy, "pago_online_url": os.getenv("IZIPAY_PAYMENT_URL") or None,
            "pago_vencido": pago_vencido, "sin_pagos_pendientes": sin_pagos_pendientes,
            "asistencia_ubicacion_configurada": bool(gimnasio and gimnasio.latitud is not None and gimnasio.longitud is not None),
            "gimnasio": {"nombre": gimnasio.nombre, "logo_url": gimnasio.logo_url,
                          "logo_oscuro_url": gimnasio.logo_oscuro_url,
                          "logo_version": _version_contenido_imagen(gimnasio.logo_datos),
                          "logo_oscuro_version": _version_contenido_imagen(gimnasio.logo_oscuro_datos)} if gimnasio else None}


def _distancia_metros(latitud_1: float, longitud_1: float, latitud_2: float, longitud_2: float) -> float:
    """Distancia Haversine entre dos coordenadas, en metros."""
    radio_tierra = 6371000.0
    lat_1, lat_2 = math.radians(latitud_1), math.radians(latitud_2)
    delta_lat = math.radians(latitud_2 - latitud_1)
    delta_lon = math.radians(longitud_2 - longitud_1)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat_1) * math.cos(lat_2) * math.sin(delta_lon / 2) ** 2
    a = min(1.0, max(0.0, a))
    return radio_tierra * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.post("/portal-alumno/marcar-asistencia", tags=["Portal Alumno"])
def marcar_asistencia_desde_portal(
    datos: schemas.AsistenciaAlumnoUbicacion,
    cliente: models.Cliente = Depends(auth.get_cliente_actual),
    db: Session = Depends(get_db),
):
    """Registra la entrada solo si el alumno esta dentro de la geocerca configurada."""
    _validar_acceso_modulos_alumno(db, cliente)
    gimnasio = db.query(models.Gimnasio).filter(models.Gimnasio.id == cliente.gimnasio_id).first()
    if not gimnasio or gimnasio.latitud is None or gimnasio.longitud is None:
        raise HTTPException(status_code=409, detail="El gimnasio aun no configuro la ubicacion para marcar asistencia")
    hoy = hoy_lima()
    membresia = db.query(models.ClienteMembresia).filter(
        models.ClienteMembresia.cliente_id == cliente.id,
        models.ClienteMembresia.activo == True,
        models.ClienteMembresia.fecha_inicio <= hoy,
        models.ClienteMembresia.fecha_fin >= hoy,
    ).first()
    if not membresia:
        raise HTTPException(status_code=403, detail="Necesitas una membresia vigente para marcar asistencia")

    existente = db.query(models.Asistencia).filter(
        models.Asistencia.cliente_id == cliente.id,
        func.date(models.Asistencia.fecha_hora_entrada) == hoy.isoformat(),
    ).first()
    if existente:
        return {"registrada": True, "ya_registrada": True, "mensaje": "Tu asistencia de hoy ya estaba registrada"}

    distancia = _distancia_metros(datos.latitud, datos.longitud, gimnasio.latitud, gimnasio.longitud)
    radio_permitido = float(gimnasio.radio_asistencia_metros or 150.0)
    if distancia > radio_permitido:
        detalle_precision = ""
        if datos.precision_metros is not None and datos.precision_metros > 250:
            detalle_precision = " La ubicacion del celular es aproximada; activa Ubicacion precisa para mejorarla."
        raise HTTPException(
            status_code=403,
            detail=(f"Debes estar en el gimnasio para marcar asistencia. Estas aproximadamente a "
                    f"{int(round(distancia))} metros.{detalle_precision}"),
        )

    asistencia = models.Asistencia(
        cliente_id=cliente.id,
        gimnasio_id=cliente.gimnasio_id,
        fecha_hora_entrada=ahora_lima(),
    )
    db.add(asistencia)
    db.commit()
    db.refresh(asistencia)
    return {"registrada": True, "ya_registrada": False, "mensaje": "Asistencia registrada", "distancia_metros": round(distancia, 1)}


@app.put("/portal-alumno/cambiar-password", tags=["Portal Alumno"])
def cambiar_password_alumno(
    datos: schemas.CambioPasswordAlumnoRequest,
    cliente: models.Cliente = Depends(auth.get_cliente_para_configurar_password),
    db: Session = Depends(get_db),
):
    nueva = datos.nueva_password.strip()
    if not nueva.isdigit():
        raise HTTPException(status_code=400, detail="La contraseña debe contener solo números")
    if nueva == PASSWORD_LEGACY_ALUMNO:
        raise HTTPException(status_code=400, detail="Elige una contraseña menos predecible")
    cliente.codigo_acceso = auth.hash_codigo_acceso(nueva)
    db.commit()
    token = auth.crear_access_token({"sub": str(cliente.id), "tipo": "alumno", "gimnasio_id": cliente.gimnasio_id})
    return {
        "message": "Contraseña actualizada correctamente",
        "access_token": token,
        "token_type": "bearer",
        "nombre": cliente.nombre,
        "gimnasio_id": cliente.gimnasio_id,
    }


@app.get("/portal-alumno/mi-rutina", response_model=List[schemas.Rutina], tags=["Portal Alumno"])
def mi_rutina(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    return db.query(models.Rutina).filter(models.Rutina.cliente_id == cliente.id, models.Rutina.activo == True).all()


@app.get("/portal-alumno/ejercicios-completados", tags=["Portal Alumno"])
def ejercicios_completados_alumno(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    ids = db.query(models.EjercicioCompletadoAlumno.ejercicio_id).filter(
        models.EjercicioCompletadoAlumno.cliente_id == cliente.id,
        models.EjercicioCompletadoAlumno.fecha == hoy_lima()).all()
    return {"fecha": hoy_lima(), "ejercicios": [x[0] for x in ids]}


@app.post("/portal-alumno/ejercicios/{ejercicio_id}/completar", tags=["Portal Alumno"])
def alternar_ejercicio_completado(ejercicio_id: int, cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    asistencia = db.query(models.Asistencia.id).filter(models.Asistencia.cliente_id == cliente.id,
        func.date(models.Asistencia.fecha_hora_entrada) == hoy_lima().isoformat()).first()
    if not asistencia:
        raise HTTPException(status_code=403, detail="Primero debes marcar tu asistencia")
    ejercicio = (db.query(models.RutinaEjercicio).join(models.RutinaDia).join(models.Rutina)
        .filter(models.RutinaEjercicio.id == ejercicio_id, models.Rutina.cliente_id == cliente.id,
                models.Rutina.activo == True).first())
    if not ejercicio:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado")
    actual = db.query(models.EjercicioCompletadoAlumno).filter_by(
        cliente_id=cliente.id, ejercicio_id=ejercicio_id, fecha=hoy_lima()).first()
    if actual:
        db.delete(actual); completado = False
    else:
        db.add(models.EjercicioCompletadoAlumno(cliente_id=cliente.id, ejercicio_id=ejercicio_id)); completado = True
    db.commit()
    return {"completado": completado}


@app.get("/portal-alumno/mi-nutricion", response_model=List[schemas.PlanNutricion], tags=["Portal Alumno"])
def mi_nutricion(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    return (
        db.query(models.PlanNutricion)
        .filter(models.PlanNutricion.cliente_id == cliente.id, models.PlanNutricion.activo == True)
        .all()
    )


@app.get("/portal-alumno/mi-progreso", response_model=List[schemas.Progreso], tags=["Portal Alumno"])
def mi_progreso(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    return (
        db.query(models.Progreso)
        .filter(models.Progreso.cliente_id == cliente.id)
        .order_by(models.Progreso.fecha.desc())
        .all()
    )


@app.get("/portal-alumno/progreso-entrenamiento", tags=["Portal Alumno"])
def progreso_entrenamiento(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    desde = hoy_lima() - timedelta(days=29)
    total = db.query(func.count(models.EjercicioCompletadoAlumno.id)).filter(
        models.EjercicioCompletadoAlumno.cliente_id == cliente.id,
        models.EjercicioCompletadoAlumno.fecha >= desde).scalar() or 0
    dias = db.query(func.count(func.distinct(models.EjercicioCompletadoAlumno.fecha))).filter(
        models.EjercicioCompletadoAlumno.cliente_id == cliente.id,
        models.EjercicioCompletadoAlumno.fecha >= desde).scalar() or 0
    return {"ejercicios_30_dias": total, "dias_entrenados_30_dias": dias}


@app.get("/portal-alumno/retos", tags=["Portal Alumno"])
def retos_disponibles(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    retos = db.query(models.Reto).filter(models.Reto.activo == True, models.Reto.gimnasio_id == cliente.gimnasio_id).all()
    resultado = []
    for reto in retos:
        fechas = [x[0] for x in db.query(models.RetoCumplidoAlumno.fecha).filter(
            models.RetoCumplidoAlumno.reto_id == reto.id,
            models.RetoCumplidoAlumno.cliente_id == cliente.id).order_by(models.RetoCumplidoAlumno.fecha).all()]
        resultado.append({"id": reto.id, "titulo": reto.titulo, "descripcion": reto.descripcion,
            "icono": reto.icono, "duracion_dias": reto.duracion_dias, "dificultad": reto.dificultad,
            "dias_cumplidos": len(fechas), "cumplido_hoy": hoy_lima() in fechas})
    return resultado


@app.post("/portal-alumno/retos/{reto_id}/cumplir", tags=["Portal Alumno"])
def cumplir_reto_hoy(reto_id: int, cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    reto = db.query(models.Reto).filter(models.Reto.id == reto_id, models.Reto.gimnasio_id == cliente.gimnasio_id,
        models.Reto.activo == True).first()
    if not reto:
        raise HTTPException(status_code=404, detail="Reto no encontrado")
    actual = db.query(models.RetoCumplidoAlumno).filter_by(reto_id=reto_id, cliente_id=cliente.id, fecha=hoy_lima()).first()
    if actual:
        db.delete(actual); cumplido = False
    else:
        db.add(models.RetoCumplidoAlumno(reto_id=reto_id, cliente_id=cliente.id)); cumplido = True
    db.commit()
    return {"cumplido": cumplido}


@app.get("/portal-alumno/agenda", tags=["Portal Alumno"])
def agenda_alumno(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    hoy = hoy_lima()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    clases = db.query(models.ClaseDictada).filter(
        models.ClaseDictada.gimnasio_id == cliente.gimnasio_id,
        models.ClaseDictada.fecha >= inicio_semana,
    ).order_by(models.ClaseDictada.fecha, models.ClaseDictada.hora_inicio).limit(200).all()
    inscritas = {x[0] for x in db.query(models.InscripcionClaseAlumno.clase_id).filter(
        models.InscripcionClaseAlumno.cliente_id == cliente.id).all()}
    return [{"id": c.id, "agenda": c.sala or "General", "nombre": c.nombre_clase,
             "fecha": c.fecha, "hora_inicio": c.hora_inicio, "hora_fin": c.hora_fin,
             "sala": c.sala, "profesor_id": c.profesor_id,
             "profesor": c.profesor.nombre_completo if c.profesor else None,
             "permite_registro": bool(c.permite_registro and c.fecha >= hoy),
             "inscrito": c.id in inscritas} for c in clases]


@app.get("/portal-alumno/salas", tags=["Portal Alumno"])
def salas_portal_alumno(cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    salas = db.query(models.SalaGimnasio).filter(models.SalaGimnasio.gimnasio_id == cliente.gimnasio_id,
        models.SalaGimnasio.activo == True).order_by(models.SalaGimnasio.nombre).all()
    if not salas:
        principal = models.SalaGimnasio(gimnasio_id=cliente.gimnasio_id, nombre="Agenda principal")
        db.add(principal); db.commit(); db.refresh(principal)
        salas = [principal]
    resultado = [{"id": s.id, "nombre": s.nombre} for s in salas]
    nombres = {s.nombre.strip().lower() for s in salas}
    inicio_semana = hoy_lima() - timedelta(days=hoy_lima().weekday())
    salas_clases = db.query(models.ClaseDictada.sala).filter(
        models.ClaseDictada.gimnasio_id == cliente.gimnasio_id,
        models.ClaseDictada.fecha >= inicio_semana,
    ).distinct().all()
    for fila in salas_clases:
        nombre = (fila[0] or "General").strip()
        if nombre.lower() not in nombres:
            resultado.append({"id": None, "nombre": nombre})
            nombres.add(nombre.lower())
    return resultado


@app.post("/portal-alumno/agenda/{clase_id}/inscripcion", tags=["Portal Alumno"])
def alternar_inscripcion_clase(clase_id: int, cliente: models.Cliente = Depends(auth.get_cliente_actual), db: Session = Depends(get_db)):
    _validar_acceso_modulos_alumno(db, cliente)
    clase = db.query(models.ClaseDictada).filter(models.ClaseDictada.id == clase_id,
        models.ClaseDictada.gimnasio_id == cliente.gimnasio_id).first()
    if not clase or not clase.permite_registro or clase.fecha < hoy_lima():
        raise HTTPException(status_code=400, detail="Esta clase no admite inscripciones")
    actual = db.query(models.InscripcionClaseAlumno).filter_by(clase_id=clase_id, cliente_id=cliente.id).first()
    if actual:
        db.delete(actual); inscrito = False
    else:
        db.add(models.InscripcionClaseAlumno(clase_id=clase_id, cliente_id=cliente.id)); inscrito = True
    db.commit()
    return {"inscrito": inscrito}


@app.post("/portal-alumno/mi-foto", response_model=schemas.Cliente, tags=["Portal Alumno"])
async def actualizar_mi_foto(
    foto: UploadFile = File(...),
    cliente: models.Cliente = Depends(auth.get_cliente_actual),
    db: Session = Depends(get_db),
):
    """
    Permite que el propio alumno actualice siempre su foto mientras
    su cuenta este activa. La imagen se redimensiona y comprime.
    """
    if not cliente.activo:
        raise HTTPException(status_code=403, detail="Tu cuenta esta inactiva. Acercate a recepcion.")

    contenido = await foto.read()
    return _guardar_foto_cliente_persistente(db, cliente, contenido, foto.content_type)
