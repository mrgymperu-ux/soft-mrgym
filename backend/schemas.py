"""
schemas.py
Esquemas Pydantic para validacion de entrada/salida de la API.

Convencion usada en todo el archivo:
  - XxxBase: campos compartidos
  - XxxCreate: lo que se recibe al crear (hereda de Base)
  - XxxUpdate: campos opcionales para actualizar parcialmente
  - Xxx: lo que se devuelve al cliente (incluye id y relaciones
    cuando aplica), con from_attributes=True para leer desde ORM
"""

from datetime import datetime, date
from typing import Optional, List

from pydantic import BaseModel, EmailStr, ConfigDict, Field, model_validator

from .models import (
    RolUsuario,
    MetodoPago,
    TipoComida,
    TipoEmpleado,
    CategoriaAlimento,
    PropositoNutricion,
)


# ==================================================================
# PAGO RAPIDO DE SALDO
# ==================================================================

class PagoSaldoRequest(BaseModel):
    """Request para pagar (parcial o totalmente) el saldo pendiente de una membresia asignada."""
    monto: float = Field(gt=0)
    metodo_pago: MetodoPago = MetodoPago.EFECTIVO
    fecha_proximo_pago: Optional[date] = None  # si queda saldo, fecha del proximo pago


# ==================================================================
# 1. AUTENTICACION Y USUARIOS (staff / profesores)
# ==================================================================

class UsuarioBase(BaseModel):
    nombre_completo: str
    username: str
    rol: RolUsuario
    empleado_id: Optional[int] = None
    es_administrador: bool = True
    puede_eliminar: bool = True
    puede_exportar: bool = False
    zonas_permitidas: Optional[str] = None


class UsuarioCreate(UsuarioBase):
    # En el flujo Counter el trabajador entra con un PIN. La contrasena
    # queda opcional para conservar compatibilidad con el login tradicional.
    password: Optional[str] = Field(default=None, min_length=10, max_length=128)


class UsuarioUpdate(BaseModel):
    nombre_completo: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=10, max_length=128)
    activo: Optional[bool] = None
    empleado_id: Optional[int] = None
    es_administrador: Optional[bool] = None
    puede_eliminar: Optional[bool] = None
    puede_exportar: Optional[bool] = None
    zonas_permitidas: Optional[str] = None


class Usuario(UsuarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    fecha_creacion: datetime


class LoginRequest(BaseModel):
    """Login de staff/profesores: usuario y contraseña."""
    username: str
    password: str


class LoginAlumnoRequest(BaseModel):
    """Login de alumnos: DNI + codigo de acceso corto. slug identifica el gimnasio."""
    dni: str
    codigo_acceso: str
    slug: Optional[str] = None


class InicioLoginAlumnoRequest(BaseModel):
    """Primer paso del portal: identifica al alumno solo por DNI."""
    dni: str
    slug: Optional[str] = None


class SolicitarRecuperacionRequest(BaseModel):
    email: EmailStr


class RestablecerPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    nueva_password: str = Field(min_length=10, max_length=128)


class VerificarEmailRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class InvitacionUsuarioCreate(BaseModel):
    email: EmailStr
    rol: RolUsuario = RolUsuario.STAFF
    empleado_id: Optional[int] = None
    es_administrador: bool = False
    puede_eliminar: bool = False
    puede_exportar: bool = False
    zonas_permitidas: Optional[str] = None


class InvitacionUsuarioAceptar(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    nombre_completo: str = Field(min_length=2, max_length=150)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str
    es_administrador: bool = False
    es_superadmin: bool = False
    puede_eliminar: bool = False
    puede_exportar: bool = False
    zonas_permitidas: Optional[str] = None
    gimnasio_id: Optional[int] = None
    gimnasio_slug: Optional[str] = None
    debe_cambiar_password: bool = False


class CounterVincularRequest(BaseModel):
    nombre: str = Field(default="Counter", min_length=2, max_length=80)


class CounterVincularResponse(BaseModel):
    dispositivo_token: str
    dispositivo_id: int
    gimnasio_nombre: str


class CounterUsuarioOut(BaseModel):
    id: int
    nombre: str
    rol: str


class CounterLoginRequest(BaseModel):
    dispositivo_token: str = Field(min_length=32, max_length=256)
    usuario_id: int
    pin: str = Field(pattern=r"^\d{6}$")


class CounterPinRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6}$")


# ==================================================================
# 0. SAAS / MULTI-TENANT
# ==================================================================

class PlanSaasBase(BaseModel):
    nombre: str
    precio_mensual: float = 0.0
    max_clientes: int = 50
    max_productos: int = 20
    max_rutinas: int = 10
    max_usuarios_staff: int = 1
    nutricion_habilitada: bool = False
    reportes_avanzados: bool = False
    dominio_propio: bool = False

class PlanSaasCreate(PlanSaasBase):
    pass

class PlanSaasUpdate(BaseModel):
    nombre: Optional[str] = None
    precio_mensual: Optional[float] = None
    max_clientes: Optional[int] = None
    max_productos: Optional[int] = None
    max_rutinas: Optional[int] = None
    max_usuarios_staff: Optional[int] = None
    nutricion_habilitada: Optional[bool] = None
    reportes_avanzados: Optional[bool] = None
    dominio_propio: Optional[bool] = None
    activo: Optional[bool] = None

class PlanSaas(PlanSaasBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool


class GimnasioBase(BaseModel):
    nombre: str
    slug: str
    plan_id: Optional[int] = None
    email_contacto: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None

class GimnasioCreate(GimnasioBase):
    admin_username: str = "admin"
    admin_password: str = Field(min_length=10, max_length=128)
    admin_nombre: str = "Administrador"

class GimnasioUpdate(BaseModel):
    nombre: Optional[str] = None
    slug: Optional[str] = None
    plan_id: Optional[int] = None
    activo: Optional[bool] = None
    email_contacto: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None

class Gimnasio(GimnasioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    fecha_registro: Optional[datetime] = None
    logo_url: Optional[str] = None
    logo_oscuro_url: Optional[str] = None

class GimnasioDetalle(Gimnasio):
    """Gimnasio con stats para el dashboard del superadmin."""
    total_clientes: int = 0
    total_usuarios: int = 0
    nombre_plan: Optional[str] = None
    estado_suscripcion: str = "sin_configurar"
    fecha_fin_periodo: Optional[date] = None
    fecha_fin_gracia: Optional[date] = None
    dias_restantes: Optional[int] = None


class PagoSaasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    gimnasio_id: int
    suscripcion_id: int
    plan_id: Optional[int] = None
    monto: float
    moneda: str
    metodo_pago: str
    referencia: Optional[str] = None
    fecha_pago: datetime
    periodo_inicio: date
    periodo_fin: date
    notas: Optional[str] = None


class SuscripcionSaasOut(BaseModel):
    id: Optional[int] = None
    gimnasio_id: int
    plan_id: Optional[int] = None
    nombre_plan: Optional[str] = None
    estado: str
    fecha_inicio: Optional[date] = None
    fecha_fin_periodo: Optional[date] = None
    fecha_fin_gracia: Optional[date] = None
    dias_gracia: int = 0
    dias_restantes: Optional[int] = None
    auto_renovacion: bool = False
    notas: Optional[str] = None
    pagos: List[PagoSaasOut] = Field(default_factory=list)


class RenovacionSaasRequest(BaseModel):
    plan_id: Optional[int] = None
    meses: int = Field(default=1, ge=1, le=24)
    monto: float = Field(ge=0)
    moneda: str = Field(default="S/", min_length=1, max_length=10)
    metodo_pago: str = Field(default="manual", min_length=1, max_length=40)
    referencia: Optional[str] = Field(default=None, max_length=120)
    fecha_pago: Optional[datetime] = None
    notas: Optional[str] = Field(default=None, max_length=500)


class SuscripcionSaasUpdate(BaseModel):
    plan_id: Optional[int] = None
    estado: Optional[str] = Field(default=None, pattern="^(prueba|activa|gracia|vencida|suspendida|cancelada)$")
    fecha_fin_periodo: Optional[date] = None
    dias_gracia: Optional[int] = Field(default=None, ge=0, le=60)
    auto_renovacion: Optional[bool] = None
    notas: Optional[str] = Field(default=None, max_length=500)


class RegistroGimnasioRequest(BaseModel):
    """Registro publico de un gimnasio nuevo (onboarding)."""
    nombre_gimnasio: str
    slug: str
    nombre_admin: str
    username: str
    password: str = Field(min_length=10, max_length=128)
    email: EmailStr
    telefono: Optional[str] = None


# ==================================================================
# 2. CLIENTES / ALUMNOS
# ==================================================================

class ClienteBase(BaseModel):
    nombre: str
    apellidos: Optional[str] = None
    dni: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    fecha_nacimiento: Optional[date] = None
    direccion: Optional[str] = None
    foto_url: Optional[str] = None
    genero: Optional[str] = None
    fecha_renovacion: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    membresia_texto: Optional[str] = None


class ClienteCreate(ClienteBase):
    codigo_acceso: Optional[str] = None


class ClienteUpdate(BaseModel):
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    dni: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    fecha_nacimiento: Optional[date] = None
    direccion: Optional[str] = None
    foto_url: Optional[str] = None
    codigo_acceso: Optional[str] = None
    activo: Optional[bool] = None
    genero: Optional[str] = None
    fecha_renovacion: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    membresia_texto: Optional[str] = None


class CambioPasswordAlumnoRequest(BaseModel):
    nueva_password: str = Field(min_length=6, max_length=12)


class Cliente(ClienteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fecha_registro: datetime
    activo: bool
    password_configurada: bool = False
    # Calculado (no es columna): dias asistidos / dias del ULTIMO
    # plan asignado, como %. None si el cliente nunca tuvo un plan.
    porcentaje_asistencia: Optional[float] = None


class ClienteListItem(BaseModel):
    """Version liviana para listados paginados (no trae relaciones)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    apellidos: Optional[str] = None
    dni: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    foto_url: Optional[str] = None
    activo: bool
    genero: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    membresia_texto: Optional[str] = None


class BiometriaFacialGuardar(BaseModel):
    descriptor: List[float] = Field(min_length=1024, max_length=1024)
    consentimiento: bool
    version_modelo: str = Field(default="human-3.3.6-faceres", min_length=3, max_length=40)


class BiometriaFacialDescriptor(BaseModel):
    cliente_id: int
    nombre_completo: str
    foto_url: Optional[str] = None
    descriptor: List[float]


class BiometriaFacialEstado(BaseModel):
    registrada: bool
    consentimiento_en: Optional[datetime] = None
    actualizado_en: Optional[datetime] = None
    version_modelo: Optional[str] = None


# ==================================================================
# 2b. CLIENTES ANTIGUOS / HISTORICOS
# ==================================================================

class ClienteHistoricoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    num_carnet: Optional[int] = None
    nombre_completo: str
    telefono1: Optional[str] = None
    telefono2: Optional[str] = None
    email: Optional[str] = None
    distrito: Optional[str] = None
    plan_texto: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    total_asistencias_legado: Optional[int] = None
    migrado: bool
    cliente_nuevo_id: Optional[int] = None


class ImportarClientesHistoricosResultado(BaseModel):
    total_filas_leidas: int
    total_importados: int
    total_omitidos_duplicados: int
    errores: List[str] = []


class ImportarClientesResultado(BaseModel):
    """Resultado de importar clientes ACTIVOS directo (no historicos), ver /clientes/importar."""
    total_filas_leidas: int
    total_importados: int
    total_omitidos_duplicados: int
    errores: List[str] = []


# ==================================================================
# 3. MEMBRESIAS
# ==================================================================

class MembresiaBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    precio: float = Field(ge=0)
    duracion_dias: int = Field(gt=0)

    duracion_meses: Optional[int] = None
    duracion_dias_extra: Optional[int] = None

    monto_inicial: Optional[float] = None
    fracciones_pago_deuda: Optional[int] = None
    penalizacion: Optional[float] = None
    dias_gracia_pago: Optional[int] = None

    monto_mensual: Optional[float] = None

    dias_congelamiento: Optional[int] = None
    permite_congelamiento: bool = True

    dias_acceso_periodo: Optional[int] = None
    hora_inicio_acceso: str = "00:00"
    hora_fin_acceso: str = "24:00"
    dias_semana_acceso: str = "dom,lun,mar,mie,jue,vie,sab"

    password_tarifa: Optional[str] = None
    congelado_no_aparece_pagos: bool = False
    no_aparecer_reporte_cruce_medidas: bool = False
    incluye_nutricion: bool = False
    incluye_retos: bool = False


class MembresiaCreate(MembresiaBase):
    pass


class MembresiaUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    precio: Optional[float] = None
    duracion_dias: Optional[int] = None
    duracion_meses: Optional[int] = None
    duracion_dias_extra: Optional[int] = None
    monto_inicial: Optional[float] = None
    fracciones_pago_deuda: Optional[int] = None
    penalizacion: Optional[float] = None
    dias_gracia_pago: Optional[int] = None
    monto_mensual: Optional[float] = None
    dias_congelamiento: Optional[int] = None
    permite_congelamiento: Optional[bool] = None
    dias_acceso_periodo: Optional[int] = None
    hora_inicio_acceso: Optional[str] = None
    hora_fin_acceso: Optional[str] = None
    dias_semana_acceso: Optional[str] = None
    password_tarifa: Optional[str] = None
    congelado_no_aparece_pagos: Optional[bool] = None
    no_aparecer_reporte_cruce_medidas: Optional[bool] = None
    incluye_nutricion: Optional[bool] = None
    incluye_retos: Optional[bool] = None
    activo: Optional[bool] = None


class Membresia(MembresiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool


class ClienteMembresiaCreate(BaseModel):
    cliente_id: int
    membresia_id: int
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    monto_pagado: Optional[float] = None
    fecha_pago_saldo: Optional[date] = None
    metodo_pago: Optional[MetodoPago] = MetodoPago.EFECTIVO


class ClienteMembresiaUpdate(BaseModel):
    """Correccion administrativa de una membresia ya asignada (solo admin)."""
    membresia_id: Optional[int] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    monto_pagado: Optional[float] = None
    fecha_pago_saldo: Optional[date] = None
    metodo_pago: Optional[MetodoPago] = None
    activo: Optional[bool] = None


class PagoMembresiaOut(BaseModel):
    """Registro individual de un pago contra una membresia asignada."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_membresia_id: int
    monto: float
    metodo_pago: str = "efectivo"
    fecha_pago: datetime
    fecha_proximo_pago: Optional[date] = None
    registrado_por_id: Optional[int] = None
    notas: Optional[str] = None
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    anulada_por_id: Optional[int] = None
    motivo_anulacion: Optional[str] = None


class ClienteMembresia(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: int
    membresia_id: int
    fecha_inicio: date
    fecha_fin: Optional[date] = None
    monto_pagado: float
    fecha_pago_saldo: Optional[date] = None
    metodo_pago: Optional[MetodoPago] = MetodoPago.EFECTIVO
    vendido_por_id: Optional[int] = None
    activo: bool
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None
    membresia: Optional[Membresia] = None
    pagos: List[PagoMembresiaOut] = []


class MembresiaPorVencer(BaseModel):
    """Item del listado de vencimientos: cliente + su membresia activa que vence pronto."""
    cliente_membresia_id: int
    cliente_id: int
    nombre_cliente: str
    telefono: Optional[str] = None
    membresia_nombre: str
    fecha_fin: date
    dias_restantes: int


# ==================================================================
# 4. PRODUCTOS E INVENTARIO
# ==================================================================

class ProductoBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    precio_venta: float = Field(ge=0)
    stock: int = Field(default=0, ge=0)
    stock_minimo: int = Field(default=5, ge=0)
    icono: Optional[str] = None
    foto_url: Optional[str] = None


class ProductoCreate(ProductoBase):
    pass


class ProductoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    precio_venta: Optional[float] = None
    stock: Optional[int] = None
    stock_minimo: Optional[int] = None
    icono: Optional[str] = None
    foto_url: Optional[str] = None
    activo: Optional[bool] = None


class Producto(ProductoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    precio_compra: Optional[float] = None
    activo: bool
    fecha_creacion: datetime


class ProductoVendido(BaseModel):
    """Producto con su total de unidades vendidas, para venta rapida ordenada por popularidad."""
    producto: Producto
    cantidad_vendida: int


# ==================================================================
# 5. VENTAS
# ==================================================================

class DetalleVentaCreate(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0)
    precio_unitario: float = Field(ge=0)  # compatibilidad; el backend usa el precio del producto


class DetalleVenta(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    producto_id: int
    cantidad: int
    precio_unitario: float
    subtotal: float
    producto: Optional[Producto] = None


class VentaCreate(BaseModel):
    cliente_id: Optional[int] = None
    metodo_pago: MetodoPago
    es_venta_rapida: bool = False
    notas: Optional[str] = None
    detalles: List[DetalleVentaCreate]


class Venta(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: Optional[int] = None
    fecha_venta: datetime
    total: float
    metodo_pago: MetodoPago
    es_venta_rapida: bool
    notas: Optional[str] = None
    usuario_id: Optional[int] = None
    costo_comision_gym: float = 0.0
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    anulada_por_id: Optional[int] = None
    motivo_anulacion: Optional[str] = None
    detalles: List[DetalleVenta] = []


class CompraCreate(BaseModel):
    producto_id: int
    cantidad: int = Field(gt=0)
    costo_unitario: float = Field(ge=0)
    notas: Optional[str] = None
    metodo_pago: str = Field(default="efectivo", pattern="^(efectivo|cuenta)$")


class Compra(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    producto_id: int
    cantidad: int
    costo_unitario: float
    costo_total: float
    fecha: datetime
    usuario_id: Optional[int] = None
    notas: Optional[str] = None
    metodo_pago: Optional[str] = None
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    anulada_por_id: Optional[int] = None
    motivo_anulacion: Optional[str] = None
    producto: Optional[Producto] = None


class AnulacionOperacionRequest(BaseModel):
    motivo: str = Field(min_length=5, max_length=500)


# ==================================================================
# 6. ASISTENCIAS (clientes)
# ==================================================================

class AsistenciaCreate(BaseModel):
    cliente_id: int


class AsistenciaAlumnoUbicacion(BaseModel):
    latitud: float = Field(ge=-90, le=90)
    longitud: float = Field(ge=-180, le=180)
    precision_metros: Optional[float] = Field(default=None, ge=0, le=5000)


class Asistencia(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: int
    fecha_hora_entrada: datetime
    fecha_hora_salida: Optional[datetime] = None
    cliente: Optional[ClienteListItem] = None


class RegistrarSalidaRequest(BaseModel):
    asistencia_id: int


# ==================================================================
# 7. PROGRESO FISICO
# ==================================================================

class ProgresoBase(BaseModel):
    peso: Optional[float] = None
    altura: Optional[float] = None
    porcentaje_grasa: Optional[float] = None
    porcentaje_musculo: Optional[float] = None
    notas: Optional[str] = None


class ProgresoCreate(ProgresoBase):
    cliente_id: int


class Progreso(ProgresoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: int
    fecha: datetime


# ==================================================================
# 8. ENTRENAMIENTOS / RUTINAS
# ==================================================================

class RutinaEjercicioBase(BaseModel):
    nombre: str
    tipo_ejercicio_id: Optional[int] = None
    series: Optional[int] = None
    repeticiones: Optional[str] = None
    peso: Optional[str] = None
    notas: Optional[str] = None


class RutinaEjercicioCreate(RutinaEjercicioBase):
    pass


class RutinaEjercicio(RutinaEjercicioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class RutinaDiaBase(BaseModel):
    nombre: str
    orden: int = 0


class RutinaDiaCreate(RutinaDiaBase):
    ejercicios: List[RutinaEjercicioCreate] = []


class RutinaDia(RutinaDiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ejercicios: List[RutinaEjercicio] = []


class RutinaCreate(BaseModel):
    cliente_id: int
    nombre: str
    dias: List[RutinaDiaCreate] = []


class Rutina(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: int
    nombre: str
    fecha_creacion: datetime
    activo: bool
    dias: List[RutinaDia] = []


class PaqueteRutinaEjercicioCreate(RutinaEjercicioBase):
    pass


class PaqueteRutinaEjercicio(RutinaEjercicioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PaqueteRutinaDiaCreate(RutinaDiaBase):
    ejercicios: List[PaqueteRutinaEjercicioCreate] = []


class PaqueteRutinaDia(RutinaDiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ejercicios: List[PaqueteRutinaEjercicio] = []


class PaqueteRutinaCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    nivel: str = "basico"
    objetivo: str = "inicio"
    etapa: str = "inicio"
    genero_recomendado: str = "todos"
    edad_min: Optional[int] = Field(default=None, ge=0, le=120)
    edad_max: Optional[int] = Field(default=None, ge=0, le=120)
    duracion_semanas: int = Field(default=4, ge=1, le=52)
    dias: List[PaqueteRutinaDiaCreate] = []


class PaqueteRutina(PaqueteRutinaCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    equipamiento_origen: Optional[str] = None
    activo: bool
    fecha_creacion: datetime
    dias: List[PaqueteRutinaDia] = []


class AsignarPaqueteRutina(BaseModel):
    cliente_id: int
    nombre: Optional[str] = None


class PerfilRecomendacionRutina(BaseModel):
    genero: str
    edad: Optional[int] = None
    peso_kg: Optional[float] = None
    estatura_cm: Optional[float] = None
    imc: Optional[float] = None
    peso_objetivo_kg: Optional[float] = None
    objetivo_sugerido: str
    nivel_sugerido: str
    razones: List[str] = Field(default_factory=list)


class PaqueteRutinaSugerido(BaseModel):
    paquete: PaqueteRutina
    puntuacion: int
    motivos: List[str] = Field(default_factory=list)


class RecomendacionRutina(BaseModel):
    perfil: PerfilRecomendacionRutina
    opciones: List[PaqueteRutinaSugerido] = Field(default_factory=list)


class GuardarRecomendacionRutinaRequest(BaseModel):
    cliente_id: int
    paquete_origen_id: int
    paquete: PaqueteRutinaCreate


class GuardarRecomendacionRutinaResponse(BaseModel):
    paquete: PaqueteRutina
    rutina: Rutina


# ---- Catalogo de Ejercicios (imagen/video demostrativo) ----

class TipoEjercicioCreate(BaseModel):
    nombre: str
    grupo_muscular: Optional[str] = None
    descripcion: Optional[str] = None
    video_url: Optional[str] = None
    categoria: Optional[str] = None
    equipamiento: Optional[str] = None
    nivel: Optional[str] = None
    genero_recomendado: Optional[str] = "todos"
    objetivo: Optional[str] = None


class TipoEjercicioUpdate(BaseModel):
    nombre: Optional[str] = None
    grupo_muscular: Optional[str] = None
    descripcion: Optional[str] = None
    video_url: Optional[str] = None
    activo: Optional[bool] = None
    categoria: Optional[str] = None
    equipamiento: Optional[str] = None
    nivel: Optional[str] = None
    genero_recomendado: Optional[str] = None
    objetivo: Optional[str] = None


class TipoEjercicio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    grupo_muscular: Optional[str] = None
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    imagen_url_2: Optional[str] = None
    imagen_url_3: Optional[str] = None
    video_url: Optional[str] = None
    activo: bool
    fecha_creacion: datetime
    categoria: Optional[str] = None
    equipamiento: Optional[str] = None
    nivel: Optional[str] = None
    genero_recomendado: Optional[str] = "todos"
    objetivo: Optional[str] = None


# ==================================================================
# 9. NUTRICION
# ==================================================================

class ComidaPlanBase(BaseModel):
    tipo: TipoComida
    nombre_alimento: str
    calorias: Optional[int] = None
    alimento_id: Optional[int] = None
    cantidad_gramos: Optional[float] = None
    porcion_cliente: Optional[str] = None


class ComidaPlanCreate(ComidaPlanBase):
    pass


class ComidaPlan(ComidaPlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---- Catalogo de Alimentos (editable, base peruana) ----

class AlimentoBase(BaseModel):
    nombre: str
    categoria: CategoriaAlimento = CategoriaAlimento.OTRO
    porcion_gramos: float = 100.0
    calorias: float = 0.0
    proteinas_g: float = 0.0
    carbohidratos_g: float = 0.0
    grasas_g: float = 0.0
    fibra_g: Optional[float] = None


class AlimentoCreate(AlimentoBase):
    porcion_casera: Optional[str] = None


class AlimentoUpdate(BaseModel):
    nombre: Optional[str] = None
    categoria: Optional[CategoriaAlimento] = None
    porcion_gramos: Optional[float] = None
    calorias: Optional[float] = None
    proteinas_g: Optional[float] = None
    carbohidratos_g: Optional[float] = None
    grasas_g: Optional[float] = None
    fibra_g: Optional[float] = None
    activo: Optional[bool] = None
    porcion_casera: Optional[str] = None


class Alimento(AlimentoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    porcion_casera: Optional[str] = None


# ---- Paquetes de nutricion (plantillas desayuno/almuerzo/cena por proposito) ----

class PaqueteAlimentoCreate(BaseModel):
    alimento_id: int
    cantidad_gramos: float = 100.0
    porcion_cliente: Optional[str] = None


class PaqueteAlimentoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    alimento_id: int
    cantidad_gramos: float
    porcion_cliente: Optional[str] = None
    alimento: Optional[Alimento] = None


class PaqueteNutricionCreate(BaseModel):
    nombre: str
    tipo_comida: TipoComida
    proposito: PropositoNutricion
    notas: Optional[str] = None
    items: List[PaqueteAlimentoCreate] = []


class PaqueteNutricionUpdate(BaseModel):
    nombre: Optional[str] = None
    tipo_comida: Optional[TipoComida] = None
    proposito: Optional[PropositoNutricion] = None
    notas: Optional[str] = None
    activo: Optional[bool] = None
    items: Optional[List[PaqueteAlimentoCreate]] = None


class PaqueteNutricion(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    tipo_comida: TipoComida
    proposito: PropositoNutricion
    notas: Optional[str] = None
    activo: bool
    fecha_creacion: datetime
    items: List[PaqueteAlimentoItem] = []


class AplicarPaqueteRequest(BaseModel):
    """Aplica un Paquete de nutricion a un plan de un cliente: genera las filas ComidaPlan a partir de los items del paquete."""
    plan_id: int


class PlanNutricionCreate(BaseModel):
    cliente_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    calorias_objetivo: Optional[int] = None
    origen: str = "membresia"
    comidas: List[ComidaPlanCreate] = []


class PlanNutricionUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    calorias_objetivo: Optional[int] = None
    activo: Optional[bool] = None


class PlanNutricion(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    calorias_objetivo: Optional[int] = None
    origen: str = "membresia"
    activo: bool
    fecha_creacion: datetime
    comidas: List[ComidaPlan] = []


# ==================================================================
# 10. RETOS
# ==================================================================

class RetoBase(BaseModel):
    titulo: str
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    duracion_dias: Optional[int] = None
    dificultad: Optional[str] = None


class RetoCreate(RetoBase):
    pass


class RetoUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    duracion_dias: Optional[int] = None
    dificultad: Optional[str] = None
    activo: Optional[bool] = None


class Reto(RetoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    fecha_creacion: datetime


# ==================================================================
# 11. PERSONAL Y PLANILLA
# ==================================================================

class PuestoCreate(BaseModel):
    nombre: str
    tipo: TipoEmpleado


class PuestoUpdate(BaseModel):
    nombre: Optional[str] = None
    activo: Optional[bool] = None


class Puesto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    tipo: TipoEmpleado
    activo: bool


class HorarioStaffBloque(BaseModel):
    dias: List[int] = Field(min_length=1, max_length=7)
    hora_inicio: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    hora_fin: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validar_bloque(self):
        if len(set(self.dias)) != len(self.dias) or any(dia < 0 or dia > 6 for dia in self.dias):
            raise ValueError("Los dias del horario deben ser unicos y estar entre lunes y domingo")
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("La hora de salida debe ser posterior a la hora de entrada")
        self.dias = sorted(self.dias)
        return self


def _validar_dias_sin_repetir(horario: Optional[List[HorarioStaffBloque]]):
    vistos = set()
    for bloque in horario or []:
        repetidos = vistos.intersection(bloque.dias)
        if repetidos:
            raise ValueError("Un mismo dia no puede aparecer en dos franjas de horario")
        vistos.update(bloque.dias)


class EmpleadoBase(BaseModel):
    nombre_completo: str
    tipo: TipoEmpleado
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    dni: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    puesto: Optional[str] = None
    codigo_acceso: Optional[str] = None
    # staff fijo:
    sueldo_fijo_mensual: Optional[float] = None
    horario_semanal: List[HorarioStaffBloque] = Field(default_factory=list)
    # profesor de sala:
    tarifa_por_clase: Optional[float] = None
    minimo_alumnos_tarifa_completa: Optional[int] = None
    tarifa_reducida: Optional[float] = None

    @model_validator(mode="after")
    def validar_horario_semanal(self):
        _validar_dias_sin_repetir(self.horario_semanal)
        return self


class EmpleadoCreate(EmpleadoBase):
    pass


class EmpleadoUpdate(BaseModel):
    nombre_completo: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    dni: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    puesto: Optional[str] = None
    codigo_acceso: Optional[str] = None
    sueldo_fijo_mensual: Optional[float] = None
    horario_semanal: Optional[List[HorarioStaffBloque]] = None
    tarifa_por_clase: Optional[float] = None
    minimo_alumnos_tarifa_completa: Optional[int] = None
    tarifa_reducida: Optional[float] = None
    activo: Optional[bool] = None

    @model_validator(mode="after")
    def validar_horario_semanal(self):
        _validar_dias_sin_repetir(self.horario_semanal)
        return self


class Empleado(EmpleadoBase):
    model_config = ConfigDict(from_attributes=True)
    codigo_acceso: Optional[str] = Field(default=None, exclude=True)
    id: int
    activo: bool
    fecha_ingreso: date


class AsistenciaEmpleadoCreate(BaseModel):
    empleado_id: int


class AsistenciaEmpleado(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    empleado_id: int
    fecha_hora_entrada: datetime
    fecha_hora_salida: Optional[datetime] = None


class ClaseDictadaCreate(BaseModel):
    profesor_id: int
    nombre_clase: str
    sala: Optional[str] = None
    fecha: date
    hora_inicio: datetime
    hora_fin: Optional[datetime] = None
    notas: Optional[str] = None
    # Repeticion (opcional): si dias_semana no esta vacio y semanas > 1,
    # se crean varias clases (una serie) en vez de una sola.
    # dias_semana usa convencion Python weekday: Lunes=0 ... Domingo=6.
    dias_semana: List[int] = []
    semanas: int = 1
    agenda_nombre: str = "Clases"
    permite_registro: bool = False


class ClaseDictadaUpdate(BaseModel):
    nombre_clase: Optional[str] = None
    sala: Optional[str] = None
    hora_inicio: Optional[datetime] = None
    hora_fin: Optional[datetime] = None
    notas: Optional[str] = None
    agenda_nombre: Optional[str] = None
    permite_registro: Optional[bool] = None


class MarcarDictadaRequest(BaseModel):
    """
    Se usa al cerrar una clase: registra cuantos alumnos asistieron.
    El backend calcula automaticamente monto_pagado comparando con
    el minimo_alumnos_tarifa_completa del profesor.
    """
    cantidad_alumnos: int


class ReemplazoRequest(BaseModel):
    """Asigna (o quita, si es None) un profesor de reemplazo puntual para una fecha especifica."""
    profesor_reemplazo_id: Optional[int] = None


class ClaseDictada(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profesor_id: int
    nombre_clase: str
    sala: Optional[str] = None
    fecha: date
    hora_inicio: datetime
    hora_fin: Optional[datetime] = None
    dictada: bool
    cantidad_alumnos: Optional[int] = None
    monto_pagado: Optional[float] = None
    serie_id: Optional[str] = None
    profesor_reemplazo_id: Optional[int] = None
    notas: Optional[str] = None
    agenda_nombre: str = "Clases"
    permite_registro: bool = False
    profesor: Optional[Empleado] = None
    profesor_reemplazo: Optional[Empleado] = None


class SalaGimnasioCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)


class SalaGimnasio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    activo: bool


class ReservaSalaCreate(BaseModel):
    concepto_ingreso_id: int
    nombre_reserva: str
    responsable: Optional[str] = None
    sala: Optional[str] = None
    fecha: date
    hora_inicio: datetime
    hora_fin: Optional[datetime] = None
    notas: Optional[str] = None


class ReservaSala(ReservaSalaCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ClaseOcupada(BaseModel):
    """Vista minima de una clase para el calendario de 'Ocupado' del portal de profesores."""
    fecha: date
    hora_inicio: datetime
    hora_fin: Optional[datetime] = None
    sala: Optional[str] = None
    nombre_clase: str
    nombre_profesor: str
    nombre_profesor_reemplazo: Optional[str] = None


class ProfesorMinimo(BaseModel):
    """Vista minima de un profesor de sala, para que otro profesor pueda elegirlo como reemplazo (no expone tarifas ni datos sensibles)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre_completo: str


class ResumenPlanilla(BaseModel):
    """Resultado del calculo de planilla de un profesor en un periodo (desde/hasta), con lo ya pagado y el pendiente para ESE MISMO rango."""
    profesor_id: int
    nombre_profesor: str
    cantidad_clases_dictadas: int
    total_a_pagar: float
    total_pagado: float = 0.0
    pendiente: float = 0.0
    detalle_clases: List[ClaseDictada] = []


class ResumenPlanillaStaff(BaseModel):
    """
    Calculo de planilla de un staff fijo para un mes: sueldo fijo de
    ESE mes + comisiones generadas en el mes ANTERIOR (se pagan con
    un mes de arrastre), menos lo que ya se le haya pagado en ese
    periodo (permite pagos en partes).
    """
    empleado_id: int
    nombre_empleado: str
    anio: int
    mes: int
    sueldo_fijo_mensual: float
    mes_comision_anio: int
    mes_comision_mes: int
    comision_membresias: float
    comision_productos: float
    total_a_pagar: float
    total_pagado: float
    pendiente: float


class PagoPlanillaCreate(BaseModel):
    empleado_id: int
    tipo: str  # "staff" | "profesor"
    anio: int
    mes: int
    monto_sueldo_fijo: float = 0.0
    monto_comision_membresias: float = 0.0
    monto_comision_productos: float = 0.0
    cantidad_clases: Optional[int] = None
    monto_clases: float = 0.0
    monto_total: float = Field(gt=0)
    notas: Optional[str] = None
    # Solo para tipo="profesor": rango exacto usado en el calculo,
    # para poder comparar el pendiente contra pagos previos del
    # MISMO rango (ver ResumenPlanilla/PagoPlanilla.desde/hasta).
    desde: Optional[date] = None
    hasta: Optional[date] = None
    metodo_pago: str = Field(default="efectivo", pattern="^(efectivo|cuenta)$")


class ConceptoOtroIngresoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    monto_sugerido: float = Field(default=0.0, ge=0)
    mostrar_agenda: bool = False
    sala_sugerida: Optional[str] = None


class ConceptoOtroIngresoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    monto_sugerido: Optional[float] = Field(default=None, ge=0)
    mostrar_agenda: Optional[bool] = None
    sala_sugerida: Optional[str] = None
    activo: Optional[bool] = None


class ConceptoOtroIngreso(ConceptoOtroIngresoCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    fecha_creacion: datetime


class OtroIngresoCreate(BaseModel):
    concepto_id: int
    fecha: Optional[datetime] = None
    monto: float = Field(gt=0)
    metodo_pago: str = Field(default="efectivo", pattern="^(efectivo|tarjeta|qr)$")
    descripcion: Optional[str] = None


class OtroIngreso(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    concepto_id: int
    fecha: datetime
    monto: float
    metodo_pago: str
    descripcion: Optional[str] = None
    concepto: Optional[ConceptoOtroIngreso] = None
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None


class GastoCreate(BaseModel):
    fecha: Optional[datetime] = None
    categoria: str  # ver CategoriaGasto en models.py (validado por SQLAlchemy al guardar)
    monto: float = Field(gt=0)
    descripcion: Optional[str] = None
    referencia_id: Optional[int] = None
    notas: Optional[str] = None
    metodo_pago: str = Field(default="efectivo", pattern="^(efectivo|cuenta)$")


class GastoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fecha: datetime
    categoria: str
    monto: float
    descripcion: Optional[str] = None
    referencia_id: Optional[int] = None
    notas: Optional[str] = None
    metodo_pago: Optional[str] = None
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None


class ResumenIngresos(BaseModel):
    total: float
    membresias: float
    productos: float
    otros: float
    detalle: list


class ResumenEgresos(BaseModel):
    total: float
    compras_producto: float
    pago_staff: float
    pago_profesor: float
    otros: float
    detalle: list


class PagoPlanillaUpdate(BaseModel):
    """Correccion administrativa de un pago ya registrado (solo admin). El monto se revalida contra el saldo pendiente en el servidor."""
    monto_total: Optional[float] = None
    notas: Optional[str] = None
    metodo_pago: Optional[str] = Field(default=None, pattern="^(efectivo|cuenta)$")


class PagoPlanilla(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    empleado_id: int
    tipo: str
    anio: int
    mes: int
    monto_sueldo_fijo: float
    monto_comision_membresias: float
    monto_comision_productos: float
    cantidad_clases: Optional[int] = None
    monto_clases: float
    monto_total: float
    fecha_pago: datetime
    notas: Optional[str] = None
    usuario_registro_id: Optional[int] = None
    desde: Optional[date] = None
    hasta: Optional[date] = None
    empleado: Optional[Empleado] = None
    metodo_pago: Optional[str] = None
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None


# ==================================================================
# 11b. SERVICIOS / DEUDAS (Pagos > Servicios)
# ==================================================================

class ServicioCreate(BaseModel):
    nombre: str
    notas: Optional[str] = None


class ServicioUpdate(BaseModel):
    nombre: Optional[str] = None
    notas: Optional[str] = None
    activo: Optional[bool] = None


class Servicio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    notas: Optional[str] = None
    activo: bool


class PagoServicioCreate(BaseModel):
    cargo_id: int
    monto: float = Field(gt=0)
    notas: Optional[str] = None
    metodo_pago: str = Field(default="efectivo", pattern="^(efectivo|cuenta)$")


class PagoServicioUpdate(BaseModel):
    """Correccion administrativa de un pago ya registrado (solo admin). Se revalida contra el saldo pendiente del cargo."""
    monto: Optional[float] = None
    notas: Optional[str] = None
    metodo_pago: Optional[str] = Field(default=None, pattern="^(efectivo|cuenta)$")


class PagoServicio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cargo_id: int
    monto: float
    fecha_pago: datetime
    notas: Optional[str] = None
    usuario_registro_id: Optional[int] = None
    metodo_pago: Optional[str] = "efectivo"
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None


class AperturaCajaRequest(BaseModel):
    monto_apertura: float = Field(ge=0)
    nota: Optional[str] = Field(default=None, max_length=500)


class CierreCajaRequest(BaseModel):
    monto_contado: float = Field(ge=0)
    nota: Optional[str] = Field(default=None, max_length=500)


class AjusteCajaCreate(BaseModel):
    tipo: str = Field(pattern="^(ingreso|egreso)$")
    monto: float = Field(gt=0, le=9999999999.99)
    motivo: str = Field(min_length=5, max_length=500)
    referencia: Optional[str] = Field(default=None, max_length=200)


class DocumentoFinancieroCreate(BaseModel):
    direccion: str = Field(pattern="^(ingreso|egreso)$")
    tipo: str = Field(pattern="^(boleta|factura|recibo|nota_credito|nota_debito|sustento_egreso|otro)$")
    serie: Optional[str] = Field(default=None, max_length=10)
    numero: Optional[int] = Field(default=None, ge=1)
    fecha_emision: date = Field(default_factory=date.today)
    emisor_documento: Optional[str] = Field(default=None, max_length=20)
    emisor_nombre: Optional[str] = Field(default=None, max_length=200)
    receptor_documento: Optional[str] = Field(default=None, max_length=20)
    receptor_nombre: Optional[str] = Field(default=None, max_length=200)
    subtotal: Optional[float] = Field(default=None, ge=0)
    igv: float = Field(default=0, ge=0)
    total: Optional[float] = Field(default=None, gt=0)
    moneda: str = Field(default="S/", max_length=10)
    fuente_tipo: Optional[str] = Field(default=None, pattern="^(venta|pago_membresia|compra|gasto|pago_servicio|pago_planilla|otro_ingreso)$")
    fuente_id: Optional[int] = Field(default=None, ge=1)
    notas: Optional[str] = Field(default=None, max_length=1000)


class DocumentoFinancieroUpdate(BaseModel):
    direccion: Optional[str] = Field(default=None, pattern="^(ingreso|egreso)$")
    tipo: Optional[str] = Field(default=None, pattern="^(boleta|factura|recibo|nota_credito|nota_debito|sustento_egreso|otro)$")
    serie: Optional[str] = Field(default=None, max_length=10)
    numero: Optional[int] = Field(default=None, ge=1)
    fecha_emision: Optional[date] = None
    emisor_documento: Optional[str] = Field(default=None, max_length=20)
    emisor_nombre: Optional[str] = Field(default=None, max_length=200)
    receptor_documento: Optional[str] = Field(default=None, max_length=20)
    receptor_nombre: Optional[str] = Field(default=None, max_length=200)
    subtotal: Optional[float] = Field(default=None, ge=0)
    igv: Optional[float] = Field(default=None, ge=0)
    total: Optional[float] = Field(default=None, gt=0)
    moneda: Optional[str] = Field(default=None, max_length=10)
    notas: Optional[str] = Field(default=None, max_length=1000)


class DocumentoArchivoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    tipo_mime: str
    tamano: int
    sha256: str
    creado_en: datetime


class DocumentoFinancieroOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    direccion: str
    tipo: str
    serie: Optional[str] = None
    numero: Optional[int] = None
    fecha_emision: date
    emisor_documento: Optional[str] = None
    emisor_nombre: Optional[str] = None
    receptor_documento: Optional[str] = None
    receptor_nombre: Optional[str] = None
    subtotal: float
    igv: float
    total: float
    moneda: str
    estado: str
    fuente_tipo: Optional[str] = None
    fuente_id: Optional[int] = None
    descripcion_fuente: Optional[str] = None
    notas: Optional[str] = None
    creado_en: datetime
    emitido_en: Optional[datetime] = None
    anulado_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None
    archivos: List[DocumentoArchivoOut] = []


class CargoServicioCreate(BaseModel):
    servicio_id: int
    concepto: Optional[str] = None
    monto_total: float
    anio: int
    mes: int
    fecha_vencimiento: Optional[date] = None
    notas: Optional[str] = None
    # Recurrencia opcional: si se define, el backend genera de una vez
    # los cargos futuros de la serie en lugar de uno solo.
    recurrente_tipo: Optional[str] = None  # "semanal" | "mensual" | "anual"
    recurrente_dias_semana: Optional[str] = None  # csv (lun,mar,...), solo si recurrente_tipo == "semanal"


class CargoServicioUpdate(BaseModel):
    """Correccion administrativa de un cargo (solo admin)."""
    concepto: Optional[str] = None
    monto_total: Optional[float] = None
    anio: Optional[int] = None
    mes: Optional[int] = None
    fecha_vencimiento: Optional[date] = None
    notas: Optional[str] = None
    recurrente_tipo: Optional[str] = None
    recurrente_dias_semana: Optional[str] = None


class CargoServicio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    servicio_id: int
    concepto: Optional[str] = None
    monto_total: float
    anio: int
    mes: int
    fecha_vencimiento: Optional[date] = None
    fecha_registro: datetime
    notas: Optional[str] = None
    recurrente_tipo: Optional[str] = None
    recurrente_dias_semana: Optional[str] = None
    serie_id: Optional[str] = None
    servicio: Optional[Servicio] = None
    pagos: List[PagoServicio] = []
    # Calculados en el endpoint (no son columnas de la tabla)
    total_pagado: float = 0.0
    pendiente: float = 0.0
    anulada: bool = False
    anulada_en: Optional[datetime] = None
    motivo_anulacion: Optional[str] = None


# ==================================================================
# 12. CONFIGURACION GENERAL
# ==================================================================

class ConfiguracionBase(BaseModel):
    moneda: str = "S/"
    nombre_gimnasio: str = "Mi Gimnasio"
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    ruc: Optional[str] = Field(default=None, pattern="^$|^[0-9]{11}$")
    razon_social: Optional[str] = Field(default=None, max_length=200)
    regimen_tributario: Optional[str] = Field(default=None, max_length=60)
    latitud: Optional[float] = Field(default=None, ge=-90, le=90)
    longitud: Optional[float] = Field(default=None, ge=-180, le=180)
    radio_asistencia_metros: float = Field(default=150.0, ge=20, le=2000)
    comision_tarjeta: float = 3.5
    comision_qr: float = 2.0
    dias_aviso_vencimiento: int = 7
    comision_producto_porcentaje: float = 0.0
    tema: str = "lavanda"
    modo_tema: str = "claro"
    clausulas_contrato: Optional[str] = None
    medidas_campos_visibles: Optional[str] = None
    medidas_valores_visibles: Optional[str] = None
    equipamiento_disponible: Optional[str] = None


class ConfiguracionUpdate(ConfiguracionBase):
    pass


class Configuracion(ConfiguracionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class EquipamientoGimnasioUpdate(BaseModel):
    equipos: List[str] = Field(default_factory=list)


class EquipamientoPersonalizadoCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    categoria: str = Field(default="Otros", min_length=2, max_length=80)
    grupos_musculares: List[str] = Field(default_factory=list)


# ==================================================================
# 13. DASHBOARD
# ==================================================================

class DashboardStats(BaseModel):
    """Resumen de stats para la pantalla principal del staff."""
    total_clientes: int
    membresias_activas: int
    ingresos_mes: float
    productos_bajo_stock: int
    asistencias_hoy: int
    presentes_ahora: int
    membresias_por_vencer: int
    # --- Ampliado para las tarjetas del Panel ---
    clientes_activos: int = 0            # clientes con membresia vigente HOY
    ingresos_hoy_membresias: float = 0.0
    ingresos_hoy_venta_rapida: float = 0.0
    balance_efectivo_hoy: float = 0.0    # ventas+membresias de HOY pagadas en efectivo
    balance_cuenta_hoy: float = 0.0      # ventas+membresias de HOY (tarjeta+QR) menos la comision de la pasarela


class ClienteListadoRow(BaseModel):
    """
    Fila del listado completo de Clientes (tabla sin foto): datos
    agregados de la membresia mas reciente + %asistencia, usados por
    /clientes/listado-completo.
    """
    id: int
    nombre_completo: str
    activo: bool
    fecha_vencimiento: Optional[date] = None
    dias_para_vencer: Optional[int] = None
    ultimo_plan: Optional[str] = None
    costo: Optional[float] = None
    pagado: Optional[float] = None
    saldo: Optional[float] = None
    porcentaje_asistencia: Optional[float] = None
    tiene_membresia_catalogo: bool = False
    fecha_pago_saldo: Optional[date] = None
    ultimo_cm_id: Optional[int] = None


# ==================================================================
# 14. FICHA RAPIDA DE CLIENTE (panel principal)
# ==================================================================

class FichaMembresiaActual(BaseModel):
    cm_id: int
    nombre: str
    fecha_fin: Optional[date] = None
    dias_restantes: Optional[int] = None
    precio: float = 0.0
    monto_pagado: float = 0.0
    deuda_pendiente: float = 0.0
    fecha_pago_saldo: Optional[date] = None


class ClienteFicha(BaseModel):
    """
    Resumen agregado de un cliente para la columna de busqueda
    inteligente del panel principal: evita que el frontend tenga
    que hacer 4 llamadas por separado.
    """
    cliente_id: int
    nombre_completo: str
    foto_url: Optional[str] = None
    membresia_actual: Optional[FichaMembresiaActual] = None
    porcentaje_asistencia: float
    ultimos_ingresos: List[Asistencia] = []


# ==================================================================
# 15. METAS DE VENTAS Y COMISIONES (solo administrador)
# ==================================================================

class MetaMensualBase(BaseModel):
    anio: int
    mes: int  # 1-12
    meta_membresias: float = 0.0
    meta_productos: float = 0.0
    notas: Optional[str] = None


class MetaMensualCreate(MetaMensualBase):
    pass


class MetaMensualUpdate(BaseModel):
    meta_membresias: Optional[float] = None
    meta_productos: Optional[float] = None
    notas: Optional[str] = None


class MetaMensual(MetaMensualBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TramoComisionBase(BaseModel):
    tipo: str  # "membresia" | "producto"
    porcentaje_meta_minimo: float
    porcentaje_comision: float


class TramoComisionCreate(TramoComisionBase):
    pass


class TramoComisionUpdate(BaseModel):
    porcentaje_meta_minimo: Optional[float] = None
    porcentaje_comision: Optional[float] = None
    activo: Optional[bool] = None


class TramoComision(TramoComisionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool


class ResumenComisionUsuario(BaseModel):
    """Comision calculada de un trabajador para un mes especifico."""
    usuario_id: int
    nombre_completo: str
    ventas_membresias: float
    ventas_productos: float
    meta_membresias: float
    meta_productos: float
    porcentaje_meta_membresias: float
    porcentaje_meta_productos: float
    porcentaje_comision_membresias: float
    porcentaje_comision_productos: float
    comision_membresias: float
    comision_productos: float
    comision_total: float


# ==================================================================
# 16. MEDIDAS
# ==================================================================

class MedidaBase(BaseModel):
    fecha: Optional[date] = None
    notas: Optional[str] = None
    estatura_cm: Optional[float] = None
    peso_kg: Optional[float] = None
    cuello_cm: Optional[float] = None
    hombros_cm: Optional[float] = None
    pecho_cm: Optional[float] = None
    brazo_derecho_relajado_cm: Optional[float] = None
    brazo_izquierdo_relajado_cm: Optional[float] = None
    brazo_derecho_contraido_cm: Optional[float] = None
    brazo_izquierdo_contraido_cm: Optional[float] = None
    antebrazo_derecho_cm: Optional[float] = None
    antebrazo_izquierdo_cm: Optional[float] = None
    cintura_cm: Optional[float] = None
    abdomen_cm: Optional[float] = None
    cadera_cm: Optional[float] = None
    muslo_derecho_cm: Optional[float] = None
    muslo_izquierdo_cm: Optional[float] = None
    pantorrilla_derecha_cm: Optional[float] = None
    pantorrilla_izquierda_cm: Optional[float] = None
    muneca_derecha_cm: Optional[float] = None
    muneca_izquierda_cm: Optional[float] = None
    tobillo_derecho_cm: Optional[float] = None
    tobillo_izquierdo_cm: Optional[float] = None
    presion_arterial: Optional[str] = None
    frecuencia_cardiaca_reposo: Optional[int] = None
    saturacion_oxigeno: Optional[float] = None
    porcentaje_grasa_corporal: Optional[float] = None
    masa_muscular_kg: Optional[float] = None
    grasa_visceral_nivel: Optional[float] = None
    agua_corporal_pct: Optional[float] = None
    masa_osea_kg: Optional[float] = None
    edad_metabolica: Optional[int] = None
    peso_objetivo_kg: Optional[float] = None


class MedidaCreate(MedidaBase):
    cliente_id: int


class MedidaUpdate(MedidaBase):
    pass


class Medida(MedidaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: int
    fecha: date


# ==================================================================
# 17. WHATSAPP BUSINESS (configuracion por gimnasio)
# ==================================================================

class WhatsAppConfiguracionUpdate(BaseModel):
    bienvenida_automatica: Optional[bool] = None
    vencimientos_automaticos: Optional[bool] = None
    pagos_automaticos: Optional[bool] = None
    recuperacion_acceso: Optional[bool] = None
    consentimiento_confirmado: Optional[bool] = None


class WhatsAppConfiguracionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    gimnasio_id: int
    estado: str
    numero_visible: Optional[str] = None
    nombre_verificado: Optional[str] = None
    bienvenida_automatica: bool
    vencimientos_automaticos: bool
    pagos_automaticos: bool
    recuperacion_acceso: bool
    consentimiento_confirmado: bool
    conectado_en: Optional[datetime] = None
    actualizado_en: datetime


class WhatsAppMensajeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: Optional[int] = None
    direccion: str
    categoria: str
    destinatario: Optional[str] = None
    plantilla: Optional[str] = None
    estado: str
    error: Optional[str] = None
    creado_en: datetime
