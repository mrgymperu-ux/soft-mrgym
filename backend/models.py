"""
models.py
Definicion de tablas ORM (SQLAlchemy) para Soft-Gym.

Organizado por bloques segun el plan de arquitectura:
  1. Autenticacion y roles (Usuario)
  2. Clientes / alumnos
  3. Membresias
  4. Productos e inventario
  5. Ventas
  6. Asistencias
  7. Progreso fisico
  8. Entrenamientos / rutinas
  9. Nutricion
  10. Retos
  11. Personal y planilla (Empleado, ClaseDictada)
  12. Configuracion general del gimnasio
"""

from datetime import datetime, date

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Date,
    Text,
    ForeignKey,
    Enum,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
import enum

from .time_utils import ahora_lima, hoy_lima

from .database import Base


# ==================================================================
# 0. SAAS / MULTI-TENANT
# ==================================================================

class PlanSaas(Base):
    """
    Catalogo de planes del SaaS (Free, Pro, Enterprise, etc.).
    Tabla GLOBAL — NO lleva gimnasio_id.
    Administrada solo por el superadmin de la plataforma.
    """
    __tablename__ = "planes_saas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)  # "Free", "Pro", "Enterprise"
    precio_mensual = Column(Float, default=0.0)
    max_clientes = Column(Integer, default=50)  # 0 = ilimitado
    max_productos = Column(Integer, default=20)
    max_rutinas = Column(Integer, default=10)
    max_usuarios_staff = Column(Integer, default=1)
    nutricion_habilitada = Column(Boolean, default=False)
    reportes_avanzados = Column(Boolean, default=False)
    dominio_propio = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)

    gimnasios = relationship("Gimnasio", back_populates="plan")
    suscripciones = relationship("SuscripcionSaas", back_populates="plan")


class Gimnasio(Base):
    """
    Un gimnasio registrado en la plataforma (tenant).
    Toda la data de la app se filtra por gimnasio_id.
    Absorbe lo que antes era Configuracion (fila unica).
    """
    __tablename__ = "gimnasios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)  # URL-friendly, ej. "mrgym-fitness"
    plan_id = Column(Integer, ForeignKey("planes_saas.id"), nullable=True)
    activo = Column(Boolean, default=True)
    fecha_registro = Column(DateTime, default=ahora_lima)

    # --- Contacto ---
    email_contacto = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    logo_oscuro_url = Column(String, nullable=True)

    # --- Configuracion (antes en tabla Configuracion) ---
    moneda = Column(String, default="S/")
    comision_tarjeta = Column(Float, default=3.5)
    comision_qr = Column(Float, default=2.0)
    dias_aviso_vencimiento = Column(Integer, default=7)
    comision_producto_porcentaje = Column(Float, default=0.0)
    tema = Column(String, default="lavanda")
    modo_tema = Column(String, default="claro")
    clausulas_contrato = Column(Text, nullable=True)
    medidas_campos_visibles = Column(Text, nullable=True)
    medidas_valores_visibles = Column(Text, nullable=True)

    plan = relationship("PlanSaas", back_populates="gimnasios")
    suscripcion_saas = relationship(
        "SuscripcionSaas", back_populates="gimnasio", uselist=False,
        cascade="all, delete-orphan",
    )
    pagos_saas = relationship(
        "PagoSaas", back_populates="gimnasio", cascade="all, delete-orphan",
    )

    # Compatibilidad temporal con ConfiguracionBase / pdf_generator.
    # La configuracion operativa vive en esta tabla por tenant; estos
    # alias permiten retirar la fila global legacy sin romper contratos
    # de respuesta ni generadores de PDF existentes.
    @property
    def nombre_gimnasio(self):
        return self.nombre

    @nombre_gimnasio.setter
    def nombre_gimnasio(self, valor):
        self.nombre = valor

    @property
    def email(self):
        return self.email_contacto

    @email.setter
    def email(self, valor):
        self.email_contacto = valor


class SuscripcionSaas(Base):
    """Ciclo de acceso que paga un gimnasio para usar la plataforma."""
    __tablename__ = "suscripciones_saas"
    __table_args__ = (UniqueConstraint("gimnasio_id", name="uq_suscripcion_saas_gimnasio"),)

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("planes_saas.id"), nullable=True)
    estado = Column(String, nullable=False, default="prueba")
    fecha_inicio = Column(Date, nullable=False, default=hoy_lima)
    fecha_fin_periodo = Column(Date, nullable=False)
    fecha_fin_gracia = Column(Date, nullable=True)
    dias_gracia = Column(Integer, nullable=False, default=5)
    auto_renovacion = Column(Boolean, nullable=False, default=False)
    fecha_suspension = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_lima)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_lima, onupdate=ahora_lima)

    gimnasio = relationship("Gimnasio", back_populates="suscripcion_saas")
    plan = relationship("PlanSaas", back_populates="suscripciones")
    pagos = relationship("PagoSaas", back_populates="suscripcion", cascade="all, delete-orphan")


class PagoSaas(Base):
    """Pago de la membresia SaaS realizado por un gimnasio."""
    __tablename__ = "pagos_saas"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    suscripcion_id = Column(Integer, ForeignKey("suscripciones_saas.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("planes_saas.id"), nullable=True)
    monto = Column(Float, nullable=False)
    moneda = Column(String, nullable=False, default="S/")
    metodo_pago = Column(String, nullable=False, default="manual")
    referencia = Column(String, nullable=True)
    fecha_pago = Column(DateTime, nullable=False, default=ahora_lima)
    periodo_inicio = Column(Date, nullable=False)
    periodo_fin = Column(Date, nullable=False)
    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notas = Column(Text, nullable=True)

    gimnasio = relationship("Gimnasio", back_populates="pagos_saas")
    suscripcion = relationship("SuscripcionSaas", back_populates="pagos")
    plan = relationship("PlanSaas")


# ==================================================================
# 1. AUTENTICACION Y ROLES
# ==================================================================

class RolUsuario(str, enum.Enum):
    """
    Roles del sistema. STAFF y PROFESOR usan login con
    usuario/contraseña (tabla Usuario). ALUMNO usa login propio
    con DNI + codigo (no pasa por esta tabla, ver Cliente).
    """
    STAFF = "staff"
    PROFESOR = "profesor"


class Usuario(Base):
    """
    Cuenta de acceso para personal del gimnasio (recepcion/admin)
    y profesores. Los alumnos NO tienen fila aqui: su acceso al
    portal se valida directamente contra Cliente (dni + codigo_acceso).
    """
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre_completo = Column(String, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    rol = Column(Enum(RolUsuario), nullable=False)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)

    # --- Permisos finos para staff (no aplica a rol PROFESOR) ---
    # es_administrador=True => acceso total, ignora zonas_permitidas.
    # Un staff no-administrador solo ve/usa las zonas listadas en
    # zonas_permitidas (csv, ver ZONAS_DISPONIBLES en auth.py) y solo
    # puede borrar registros si puede_eliminar=True.
    es_administrador = Column(Boolean, default=True)
    es_superadmin = Column(Boolean, default=False)  # superadmin de plataforma SaaS — acceso cross-gimnasio
    puede_eliminar = Column(Boolean, default=True)
    # Exportar/importar datos (CSV) es sensible por la cantidad de
    # informacion personal que expone: por defecto NO se concede,
    # incluso a staff sin ser administrador.
    puede_exportar = Column(Boolean, default=False)
    zonas_permitidas = Column(String, nullable=True)

    # Si el usuario es un profesor, se enlaza a su ficha de Empleado
    # para poder calcular su planilla. Es opcional (un staff fijo
    # tambien puede tener ficha de Empleado, pero no es obligatorio).
    empleado_id = Column(Integer, ForeignKey("empleados.id"), nullable=True)
    empleado = relationship("Empleado", back_populates="usuario")


# ==================================================================
# 2. CLIENTES / ALUMNOS
# ==================================================================

class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (
        UniqueConstraint("gimnasio_id", "dni", name="uq_clientes_gimnasio_dni"),
    )

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False, index=True)
    apellidos = Column(String, nullable=True)
    dni = Column(String, index=True, nullable=True)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True, index=True)
    fecha_nacimiento = Column(Date, nullable=True)
    direccion = Column(String, nullable=True)
    foto_url = Column(String, nullable=True)  # ruta relativa servida por /uploads/...

    # Acceso al portal del alumno: codigo corto, no password
    # tradicional, pensado para que sea rapido de usar.
    codigo_acceso = Column(String, nullable=True)

    genero = Column(String, nullable=True)  # "Masculino" | "Femenino" | "Otro"
    # Datos informativos de membresia/asistencia, editables directo
    # en la ficha del cliente (ademas del historial real en
    # ClienteMembresia/Asistencia). Utiles para migrar clientes que
    # ya traian estos datos de un sistema anterior.
    fecha_renovacion = Column(Date, nullable=True)
    fecha_vencimiento = Column(Date, nullable=True)
    membresia_texto = Column(String, nullable=True)  # nombre del plan tal como se conoce (texto libre, no FK)
    asistencias_legado = Column(Integer, nullable=True, default=0)

    fecha_registro = Column(DateTime, default=ahora_lima)
    activo = Column(Boolean, default=True)

    asistencias = relationship("Asistencia", back_populates="cliente")
    ventas = relationship("Venta", back_populates="cliente")
    progresos = relationship("Progreso", back_populates="cliente")
    rutinas = relationship("Rutina", back_populates="cliente")
    planes_nutricion = relationship("PlanNutricion", back_populates="cliente")
    membresias_cliente = relationship("ClienteMembresia", back_populates="cliente")
    medidas = relationship("Medida", back_populates="cliente")


# ==================================================================
# 2b. CLIENTES ANTIGUOS / HISTORICOS (base historica, ej. 8000 alumnos)
# ==================================================================

class ClienteHistorico(Base):
    """
    Base de clientes antiguos importada de un sistema anterior
    (puede tener miles de registros). Separada de Cliente a proposito:
    la busqueda normal de asistencia solo debe considerar clientes
    activos con membresia vigente; la intencion 'Reingreso de cliente
    antiguo' del Panel Principal busca aqui. Al reingresar, se crea
    un Cliente nuevo y se enlaza con cliente_nuevo_id.
    """
    __tablename__ = "clientes_historicos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    num_carnet = Column(Integer, nullable=True, index=True)
    nombre_completo = Column(String, nullable=False, index=True)  # tal cual venia en el Excel ("Apellidos, Nombres")
    apellidos = Column(String, nullable=True)
    nombres = Column(String, nullable=True)
    fecha_registro = Column(Date, nullable=True)
    sexo = Column(String, nullable=True)  # "M"/"F" si se pudo mapear, o el codigo crudo
    estado_legado = Column(Integer, nullable=True)  # codigo tal cual del sistema anterior, significado no confirmado
    situacion_legado = Column(Integer, nullable=True)
    direccion = Column(String, nullable=True)
    telefono1 = Column(String, nullable=True)
    telefono2 = Column(String, nullable=True)
    email = Column(String, nullable=True)
    fecha_nacimiento = Column(Date, nullable=True)
    edad_legado = Column(Integer, nullable=True)
    distrito = Column(String, nullable=True)
    codigo_distrito_legado = Column(Integer, nullable=True)
    codigo_plan_legado = Column(Integer, nullable=True)
    plan_texto = Column(String, nullable=True)  # 'tarbases', ej. "TRIMESTRAL BASICO"
    fecha_suscripcion = Column(Date, nullable=True)
    fecha_renovacion = Column(Date, nullable=True)
    fecha_vencimiento = Column(Date, nullable=True)
    total_asistencias_legado = Column(Integer, nullable=True)

    migrado = Column(Boolean, default=False)  # True cuando ya se creo un Cliente activo a partir de este registro
    cliente_nuevo_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)

    fecha_importacion = Column(DateTime, default=ahora_lima)


# ==================================================================
# 3. MEMBRESIAS
# ==================================================================

class Membresia(Base):
    """
    Catalogo de planes de membresia (Tarifas). Cubre tanto planes de
    duracion fija (ej. Mensual, Trimestral, con monto base y meses/dias
    de duracion) como planes recurrentes/restringidos (monto mensual,
    dias de la semana y horario de acceso permitido, limite de dias
    de uso dentro del periodo, congelamiento, etc.), inspirado en el
    formulario de 'Tarifas Bases' de sistemas de gestion de gimnasios.
    """
    __tablename__ = "membresias"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)  # Descripcion de la tarifa
    descripcion = Column(Text, nullable=True)  # notas internas adicionales
    precio = Column(Float, nullable=False)  # Monto base
    duracion_dias = Column(Integer, nullable=False)  # duracion total en dias (fuente de verdad para fecha_fin)
    activo = Column(Boolean, default=True)

    # --- Duracion, para redisplay en el formulario (duracion_dias es la fuente de verdad) ---
    duracion_meses = Column(Integer, nullable=True)
    duracion_dias_extra = Column(Integer, nullable=True)

    # --- Pago fragmentado / deuda ---
    monto_inicial = Column(Float, nullable=True)  # solo para pago fragmentado
    fracciones_pago_deuda = Column(Integer, nullable=True)
    penalizacion = Column(Float, nullable=True)
    dias_gracia_pago = Column(Integer, nullable=True)

    # --- Tarifas recurrentes / mensuales ---
    monto_mensual = Column(Float, nullable=True)

    # --- Congelamiento ---
    dias_congelamiento = Column(Integer, nullable=True)
    permite_congelamiento = Column(Boolean, default=True)  # inverso de 'No permitir freezing'

    # --- Restriccion de acceso ---
    dias_acceso_periodo = Column(Integer, nullable=True)  # solo para tarifas con cantidad de dias dentro del periodo
    hora_inicio_acceso = Column(String, default="00:00")
    hora_fin_acceso = Column(String, default="24:00")
    dias_semana_acceso = Column(String, default="dom,lun,mar,mie,jue,vie,sab")  # csv de dias habilitados

    # --- Otros ---
    password_tarifa = Column(String, nullable=True)  # 0-10 caracteres
    congelado_no_aparece_pagos = Column(Boolean, default=False)
    no_aparecer_reporte_cruce_medidas = Column(Boolean, default=False)
    incluye_nutricion = Column(Boolean, default=False)  # si True, el cliente puede tener plan de nutricion incluido en esta tarifa
    incluye_retos = Column(Boolean, default=False)

    clientes_con_este_plan = relationship("ClienteMembresia", back_populates="membresia")


class ClienteMembresia(Base):
    """
    Membresia concreta asignada a un cliente, con su propia
    fecha de inicio/fin (un cliente puede tener historial de
    varias membresias a lo largo del tiempo).
    """
    __tablename__ = "cliente_membresias"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    membresia_id = Column(Integer, ForeignKey("membresias.id"), nullable=False)
    fecha_inicio = Column(Date, default=hoy_lima)
    fecha_fin = Column(Date, nullable=True)
    monto_pagado = Column(Float, default=0.0)
    # Si queda saldo (monto_pagado < precio del plan), fecha en la
    # que el personal espera cobrar el resto (recordatorio, no
    # automatiza nada por si solo).
    fecha_pago_saldo = Column(Date, nullable=True)
    vendido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # para comisiones
    activo = Column(Boolean, default=True)
    # Metodo con el que se cobro monto_pagado (para el balance de caja
    # Efectivo vs Cuenta del Panel). Si el pago se hizo en partes con
    # distintos metodos, se guarda el del ultimo pago registrado.
    metodo_pago = Column(String, default="efectivo")

    cliente = relationship("Cliente", back_populates="membresias_cliente")
    membresia = relationship("Membresia", back_populates="clientes_con_este_plan")
    pagos = relationship(
        "PagoMembresia",
        back_populates="cliente_membresia",
        order_by="PagoMembresia.fecha_pago.desc()",
        cascade="all, delete-orphan",
    )


class PagoMembresia(Base):
    """
    Registro individual de cada pago realizado contra una
    ClienteMembresia. Permite ver el historial completo de pagos
    (parciales o totales) de una membresia asignada.
    """
    __tablename__ = "pagos_membresia"

    id = Column(Integer, primary_key=True, index=True)
    cliente_membresia_id = Column(Integer, ForeignKey("cliente_membresias.id"), nullable=False, index=True)
    monto = Column(Float, nullable=False)
    metodo_pago = Column(String, default="efectivo")
    fecha_pago = Column(DateTime, default=ahora_lima)
    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notas = Column(String, nullable=True)

    cliente_membresia = relationship("ClienteMembresia", back_populates="pagos")
    registrado_por = relationship("Usuario")


# ==================================================================
# 4. PRODUCTOS E INVENTARIO
# ==================================================================

class Producto(Base):
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    categoria = Column(String, nullable=True)
    precio_compra = Column(Float, nullable=True)
    precio_venta = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    stock_minimo = Column(Integer, default=5)
    icono = Column(String, nullable=True)  # emoji o nombre de icono para venta rapida
    foto_url = Column(String, nullable=True)  # ruta relativa servida por /uploads/... (opcional, tiene prioridad sobre icono)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)

    detalles_venta = relationship("DetalleVenta", back_populates="producto")


# ==================================================================
# 5. VENTAS
# ==================================================================

class MetodoPago(str, enum.Enum):
    EFECTIVO = "efectivo"
    TARJETA = "tarjeta"
    QR = "qr"


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    fecha_venta = Column(DateTime, default=ahora_lima)
    total = Column(Float, nullable=False)
    metodo_pago = Column(Enum(MetodoPago), nullable=False)
    es_venta_rapida = Column(Boolean, default=False)
    notas = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # quien registro la venta, para comisiones
    costo_comision_gym = Column(Float, default=0.0)  # comision de tarjeta/QR que absorbe el gimnasio (no se cobra al cliente)

    cliente = relationship("Cliente", back_populates="ventas")
    detalles = relationship("DetalleVenta", back_populates="venta", cascade="all, delete-orphan")


class DetalleVenta(Base):
    __tablename__ = "detalle_ventas"

    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)

    venta = relationship("Venta", back_populates="detalles")
    producto = relationship("Producto", back_populates="detalles_venta")


class Compra(Base):
    """
    Registro de compra de mercaderia (reposicion de stock). El
    precio_compra del Producto ya NO se define al crear el
    producto: se actualiza aqui, cada vez que se registra una
    compra real, junto con el aumento de stock.
    """
    __tablename__ = "compras"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    costo_unitario = Column(Float, nullable=False)
    costo_total = Column(Float, nullable=False)
    fecha = Column(DateTime, default=ahora_lima)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notas = Column(Text, nullable=True)
    metodo_pago = Column(String, default="efectivo")  # efectivo | cuenta

    producto = relationship("Producto")


# ==================================================================
# 6. ASISTENCIAS
# ==================================================================

class Asistencia(Base):
    """
    Asistencia de un cliente. El staff y los profesores marcan su
    propia asistencia/clase a traves de ClaseDictada (seccion 11),
    no de esta tabla, para no mezclar el dominio de planilla con
    el de aforo de alumnos.
    """
    __tablename__ = "asistencias"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha_hora_entrada = Column(DateTime, default=ahora_lima)
    fecha_hora_salida = Column(DateTime, nullable=True)

    cliente = relationship("Cliente", back_populates="asistencias")


# ==================================================================
# 7. PROGRESO FISICO
# ==================================================================

class Progreso(Base):
    __tablename__ = "progresos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha = Column(DateTime, default=ahora_lima)
    peso = Column(Float, nullable=True)
    altura = Column(Float, nullable=True)
    porcentaje_grasa = Column(Float, nullable=True)
    porcentaje_musculo = Column(Float, nullable=True)
    notas = Column(Text, nullable=True)

    cliente = relationship("Cliente", back_populates="progresos")


# ==================================================================
# 8. ENTRENAMIENTOS / RUTINAS
# ==================================================================

class TipoEjercicio(Base):
    """
    Catalogo de ejercicios (Ejercicios en el menu, antes
    'Entrenamientos'): nombre, grupo muscular, descripcion de la
    tecnica, e imagen o video demostrativo. Se usa como catalogo al
    armar el detalle de una Rutina (RutinaEjercicio.tipo_ejercicio_id).
    """
    __tablename__ = "tipos_ejercicio"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False, index=True)
    grupo_muscular = Column(String, nullable=True)  # ej. "Pecho", "Espalda", "Piernas", "Cardio"
    descripcion = Column(Text, nullable=True)  # como se hace / tecnica
    imagen_url = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)
    # Campos para sugerencia automatica segun perfil del alumno
    categoria = Column(String, nullable=True)  # calentamiento|fuerza|cardio|estiramiento|funcional
    equipamiento = Column(String, nullable=True)  # sin_equipo|step|pelota|cuerda|mancuernas|barra|maquina|banda|colchoneta
    nivel = Column(String, nullable=True)  # principiante|intermedio|avanzado
    genero_recomendado = Column(String, default="todos")  # todos|masculino|femenino
    objetivo = Column(String, nullable=True)  # bajar_peso|ganar_masa|tonificar|mantenimiento|flexibilidad
    imagen_url_2 = Column(String, nullable=True)
    imagen_url_3 = Column(String, nullable=True)


class Rutina(Base):
    """Plan de entrenamiento asignado a un cliente."""
    __tablename__ = "rutinas"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    nombre = Column(String, nullable=False)
    fecha_creacion = Column(DateTime, default=ahora_lima)
    activo = Column(Boolean, default=True)

    cliente = relationship("Cliente", back_populates="rutinas")
    dias = relationship("RutinaDia", back_populates="rutina", cascade="all, delete-orphan")


class RutinaDia(Base):
    """Un dia dentro de un plan de entrenamiento (ej. 'Dia 1')."""
    __tablename__ = "rutina_dias"

    id = Column(Integer, primary_key=True, index=True)
    rutina_id = Column(Integer, ForeignKey("rutinas.id"), nullable=False)
    nombre = Column(String, nullable=False)
    orden = Column(Integer, default=0)

    rutina = relationship("Rutina", back_populates="dias")
    ejercicios = relationship("RutinaEjercicio", back_populates="dia", cascade="all, delete-orphan")


class RutinaEjercicio(Base):
    """Un ejercicio dentro de un dia de rutina. Si se elige del
    catalogo (tipo_ejercicio_id), conserva el nombre canonico y recibe
    sus cambios; tambien se admite texto libre sin catalogo."""
    __tablename__ = "rutina_ejercicios"

    id = Column(Integer, primary_key=True, index=True)
    dia_id = Column(Integer, ForeignKey("rutina_dias.id"), nullable=False)
    tipo_ejercicio_id = Column(Integer, ForeignKey("tipos_ejercicio.id"), nullable=True)
    nombre = Column(String, nullable=False)
    series = Column(Integer, nullable=True)
    repeticiones = Column(String, nullable=True)  # texto: "12, 10, 8" admite series piramidales
    peso = Column(String, nullable=True)  # texto: "20kg, 22kg, 24kg"
    notas = Column(Text, nullable=True)

    dia = relationship("RutinaDia", back_populates="ejercicios")
    tipo_ejercicio = relationship("TipoEjercicio")


class EjercicioCompletadoAlumno(Base):
    __tablename__ = "ejercicios_completados_alumno"
    __table_args__ = (UniqueConstraint("cliente_id", "ejercicio_id", "fecha", name="uq_ejercicio_cliente_fecha"),)
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    ejercicio_id = Column(Integer, ForeignKey("rutina_ejercicios.id"), nullable=False, index=True)
    fecha = Column(Date, default=hoy_lima, nullable=False)
    fecha_registro = Column(DateTime, default=ahora_lima)


class PaqueteRutina(Base):
    """Plantilla reutilizable de entrenamiento para un perfil especifico."""
    __tablename__ = "paquetes_rutina"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    nombre = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    nivel = Column(String, default="basico")
    objetivo = Column(String, default="inicio")
    etapa = Column(String, default="inicio")
    genero_recomendado = Column(String, default="todos")
    edad_min = Column(Integer, nullable=True)
    edad_max = Column(Integer, nullable=True)
    duracion_semanas = Column(Integer, default=4)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)

    dias = relationship("PaqueteRutinaDia", back_populates="paquete", cascade="all, delete-orphan", order_by="PaqueteRutinaDia.orden")


class PaqueteRutinaDia(Base):
    __tablename__ = "paquete_rutina_dias"

    id = Column(Integer, primary_key=True, index=True)
    paquete_id = Column(Integer, ForeignKey("paquetes_rutina.id"), nullable=False)
    nombre = Column(String, nullable=False)
    orden = Column(Integer, default=0)

    paquete = relationship("PaqueteRutina", back_populates="dias")
    ejercicios = relationship("PaqueteRutinaEjercicio", back_populates="dia", cascade="all, delete-orphan", order_by="PaqueteRutinaEjercicio.id")


class PaqueteRutinaEjercicio(Base):
    __tablename__ = "paquete_rutina_ejercicios"

    id = Column(Integer, primary_key=True, index=True)
    dia_id = Column(Integer, ForeignKey("paquete_rutina_dias.id"), nullable=False)
    tipo_ejercicio_id = Column(Integer, ForeignKey("tipos_ejercicio.id"), nullable=True)
    nombre = Column(String, nullable=False)
    series = Column(Integer, nullable=True)
    repeticiones = Column(String, nullable=True)
    peso = Column(String, nullable=True)
    notas = Column(Text, nullable=True)

    dia = relationship("PaqueteRutinaDia", back_populates="ejercicios")
    tipo_ejercicio = relationship("TipoEjercicio")


# ==================================================================
# 9. NUTRICION
# ==================================================================

class PlanNutricion(Base):
    __tablename__ = "planes_nutricion"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    titulo = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    calorias_objetivo = Column(Integer, nullable=True)
    origen = Column(String, default="membresia")  # "membresia" (incluido en la tarifa) o "pago_separado" (venta aparte)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)

    cliente = relationship("Cliente", back_populates="planes_nutricion")
    comidas = relationship("ComidaPlan", back_populates="plan", cascade="all, delete-orphan")


class TipoComida(str, enum.Enum):
    DESAYUNO = "desayuno"
    COMIDA = "comida"
    APERITIVO = "aperitivo"
    CENA = "cena"


class ComidaPlan(Base):
    """Un alimento dentro de un plan de nutricion, agrupado por tipo de comida."""
    __tablename__ = "comidas_plan"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("planes_nutricion.id"), nullable=False)
    tipo = Column(Enum(TipoComida), nullable=False)
    alimento_id = Column(Integer, ForeignKey("alimentos.id"), nullable=True)
    nombre_alimento = Column(String, nullable=False)
    calorias = Column(Integer, nullable=True)
    cantidad_gramos = Column(Float, nullable=True)
    # Texto sencillo que ve el cliente (ej. "3 huevos", "1/2 taza").
    # Los gramos se conservan aparte solo para los calculos nutricionales.
    porcion_cliente = Column(String, nullable=True)

    plan = relationship("PlanNutricion", back_populates="comidas")
    alimento = relationship("Alimento")


# ---- Catalogo de alimentos peruanos (editable) ----

class CategoriaAlimento(str, enum.Enum):
    PROTEINA = "proteina"
    CARBOHIDRATO = "carbohidrato"
    VEGETAL = "vegetal"
    FRUTA = "fruta"
    LACTEO = "lacteo"
    GRASA = "grasa"
    LEGUMBRE = "legumbre"
    OTRO = "otro"


class Alimento(Base):
    """
    Catalogo de alimentos (base peruana precargada, editable desde
    Nutricion) con su valor nutricional por porcion de referencia.
    Sirve tanto para armar ComidaPlan individuales como para los
    Paquetes de nutricion (desayuno/almuerzo/cena por proposito).
    """
    __tablename__ = "alimentos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False, index=True)
    categoria = Column(Enum(CategoriaAlimento), nullable=False, default=CategoriaAlimento.OTRO)
    porcion_gramos = Column(Float, default=100.0)  # base de referencia para los valores de abajo
    calorias = Column(Float, nullable=False, default=0.0)
    proteinas_g = Column(Float, default=0.0)
    carbohidratos_g = Column(Float, default=0.0)
    grasas_g = Column(Float, default=0.0)
    fibra_g = Column(Float, nullable=True)
    porcion_casera = Column(String, nullable=True)  # ej. "1 unidad", "1 taza", "1/2 vaso" — para 1 porcion_gramos
    activo = Column(Boolean, default=True)


class PropositoNutricion(str, enum.Enum):
    BAJAR_PESO = "bajar_peso"
    GANAR_MASA = "ganar_masa"
    MANTENIMIENTO = "mantenimiento"
    DEFINICION = "definicion"


class PaqueteNutricion(Base):
    """
    Plantilla reutilizable de comida (desayuno/almuerzo/cena) armada
    con alimentos del catalogo, clasificada por proposito. El staff
    la crea una vez y luego la 'aplica' a distintos clientes,
    generando las filas de ComidaPlan correspondientes.
    """
    __tablename__ = "paquetes_nutricion"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)
    tipo_comida = Column(Enum(TipoComida), nullable=False)
    proposito = Column(Enum(PropositoNutricion), nullable=False)
    notas = Column(Text, nullable=True)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)

    items = relationship("PaqueteAlimento", back_populates="paquete", cascade="all, delete-orphan")


class PaqueteAlimento(Base):
    """Un alimento (con cantidad) dentro de un Paquete de nutricion."""
    __tablename__ = "paquete_alimentos"

    id = Column(Integer, primary_key=True, index=True)
    paquete_id = Column(Integer, ForeignKey("paquetes_nutricion.id"), nullable=False)
    alimento_id = Column(Integer, ForeignKey("alimentos.id"), nullable=False)
    cantidad_gramos = Column(Float, nullable=False, default=100.0)
    porcion_cliente = Column(String, nullable=True)

    paquete = relationship("PaqueteNutricion", back_populates="items")
    alimento = relationship("Alimento")


# ==================================================================
# 10. RETOS
# ==================================================================

class Reto(Base):
    __tablename__ = "retos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    titulo = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    icono = Column(String, nullable=True)
    duracion_dias = Column(Integer, nullable=True)
    dificultad = Column(String, nullable=True)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)


class RetoCumplidoAlumno(Base):
    __tablename__ = "retos_cumplidos_alumno"
    __table_args__ = (UniqueConstraint("reto_id", "cliente_id", "fecha", name="uq_reto_cliente_fecha"),)
    id = Column(Integer, primary_key=True, index=True)
    reto_id = Column(Integer, ForeignKey("retos.id"), nullable=False, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    fecha = Column(Date, default=hoy_lima, nullable=False)


# ==================================================================
# 11. PERSONAL Y PLANILLA
# ==================================================================

class TipoEmpleado(str, enum.Enum):
    STAFF_FIJO = "staff_fijo"
    PROFESOR_DE_SALA = "profesor_de_sala"


class Puesto(Base):
    """
    Catalogo de puestos (staff) / especialidades (profesor), gestionable
    desde Usuarios (checklist con visibilidad). activo=False significa
    que ya no aparece como opcion al asignar puesto a personal nuevo,
    pero NO borra el dato en los empleados que ya lo tenian asignado
    (Empleado.puesto sigue siendo texto libre, no una FK).
    """
    __tablename__ = "puestos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)
    tipo = Column(Enum(TipoEmpleado), nullable=False)
    activo = Column(Boolean, default=True)


class Empleado(Base):
    """
    Ficha de personal.

    STAFF_FIJO: trabajador de planta (recepcion/admin/entrenador),
    tiene un 'puesto' (Counter, Entrenador, etc.) y opcionalmente una
    cuenta Usuario para acceder al software completo.

    PROFESOR_DE_SALA: dicta clases especificas en distintas salas
    (ej. baile). Tiene una 'especialidad' en vez de puesto, y NO
    tiene acceso al software de staff: en cambio, entra a su propia
    'Zona de Profesores' (portal aparte) con DNI + codigo_acceso,
    donde ve su agenda de clases y la ocupacion de otras salas.
    Se le paga por clase dictada, con una tarifa propia y un minimo
    de alumnos requerido para cobrarla completa:
      - Si la clase tuvo >= minimo_alumnos_tarifa_completa alumnos,
        se paga tarifa_por_clase.
      - Si tuvo menos, se paga tarifa_reducida (si no se define,
        se asume 0, es decir no se paga la clase).
    """
    __tablename__ = "empleados"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre_completo = Column(String, nullable=False)
    tipo = Column(Enum(TipoEmpleado), nullable=False)
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    dni = Column(String, nullable=True, index=True)
    fecha_nacimiento = Column(Date, nullable=True)
    puesto = Column(String, nullable=True)  # staff: "Counter", etc. / profesor: "Yoga", etc.

    # --- Solo para PROFESOR_DE_SALA: acceso a su Zona de Profesores ---
    codigo_acceso = Column(String, nullable=True)

    # --- Solo aplica a STAFF_FIJO ---
    sueldo_fijo_mensual = Column(Float, nullable=True)

    # --- Solo aplica a PROFESOR_DE_SALA ---
    tarifa_por_clase = Column(Float, nullable=True)
    minimo_alumnos_tarifa_completa = Column(Integer, nullable=True)
    tarifa_reducida = Column(Float, nullable=True)  # si no llega al minimo

    activo = Column(Boolean, default=True)
    fecha_ingreso = Column(Date, default=hoy_lima)

    usuario = relationship("Usuario", back_populates="empleado", uselist=False)
    clases_dictadas = relationship("ClaseDictada", back_populates="profesor", foreign_keys="ClaseDictada.profesor_id")
    asistencias_empleado = relationship("AsistenciaEmpleado", back_populates="empleado")


class AsistenciaEmpleado(Base):
    """
    Marcaje de entrada/salida del staff fijo (recepcion/admin).
    Separado de Asistencia (que es solo para clientes/alumnos) y
    de ClaseDictada (que es el marcaje de los profesores de sala).
    """
    __tablename__ = "asistencias_empleado"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("empleados.id"), nullable=False)
    fecha_hora_entrada = Column(DateTime, default=ahora_lima)
    fecha_hora_salida = Column(DateTime, nullable=True)

    empleado = relationship("Empleado", back_populates="asistencias_empleado")


class ClaseDictada(Base):
    """
    Registro de una clase dictada por un profesor de sala (ej.
    clase de baile). Alimenta tanto la Agenda como el calculo de
    Planilla.

    El pago real de la clase (campo monto_pagado) se calcula al
    momento de marcarla como dictada y registrar cantidad_alumnos,
    comparando contra minimo_alumnos_tarifa_completa del profesor.
    Las tarifas del profesor (tarifa_por_clase / tarifa_reducida) se
    interpretan como MONTO POR HORA de clase, multiplicado por la
    duracion real (hora_fin - hora_inicio; si no hay hora_fin, se
    asume 1 hora):
      - cantidad_alumnos >= minimo  -> monto_pagado = tarifa_por_clase * horas
      - cantidad_alumnos <  minimo  -> monto_pagado = tarifa_reducida * horas
    Se guarda como snapshot (no se recalcula despues) para que un
    cambio futuro en la tarifa del profesor no altere el historico
    de planilla ya pagado.

    serie_id agrupa las instancias creadas juntas por una regla de
    repeticion (mismo dia(s) de la semana, N semanas seguidas); es
    lo que permite borrar 'esta clase' vs 'esta y todas las
    futuras' de la misma serie. Las clases sueltas (no repetidas)
    tienen serie_id=None.

    profesor_reemplazo_id es un cambio PUNTUAL solo para esta fecha
    (ej. el profesor titular falto): no toca profesor_id ni afecta
    al resto de la serie. Tanto un staff como el propio profesor
    (desde su Zona de Profesores) pueden asignarlo.
    """
    __tablename__ = "clases_dictadas"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    profesor_id = Column(Integer, ForeignKey("empleados.id"), nullable=False)
    nombre_clase = Column(String, nullable=False)  # ej. "Salsa Intermedio"
    sala = Column(String, nullable=True)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(DateTime, nullable=False)
    hora_fin = Column(DateTime, nullable=True)

    dictada = Column(Boolean, default=False)  # True cuando realmente ocurrio
    cantidad_alumnos = Column(Integer, nullable=True)  # se llena al marcar dictada
    monto_pagado = Column(Float, nullable=True)  # snapshot calculado al marcar dictada

    serie_id = Column(String, nullable=True, index=True)
    profesor_reemplazo_id = Column(Integer, ForeignKey("empleados.id"), nullable=True)

    notas = Column(Text, nullable=True)
    agenda_nombre = Column(String, default="Clases")
    permite_registro = Column(Boolean, default=False)

    profesor = relationship("Empleado", foreign_keys=[profesor_id], back_populates="clases_dictadas")
    profesor_reemplazo = relationship("Empleado", foreign_keys=[profesor_reemplazo_id])


class SalaGimnasio(Base):
    __tablename__ = "salas_gimnasio"
    __table_args__ = (UniqueConstraint("gimnasio_id", "nombre", name="uq_sala_gimnasio_nombre"),)
    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    nombre = Column(String, nullable=False)
    activo = Column(Boolean, default=True)


class InscripcionClaseAlumno(Base):
    __tablename__ = "inscripciones_clase_alumno"
    __table_args__ = (UniqueConstraint("clase_id", "cliente_id", name="uq_inscripcion_clase_cliente"),)
    id = Column(Integer, primary_key=True, index=True)
    clase_id = Column(Integer, ForeignKey("clases_dictadas.id"), nullable=False, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    fecha_registro = Column(DateTime, default=ahora_lima)


class ReservaSala(Base):
    """Bloque de Agenda para un alquiler u otro uso externo de una sala."""
    __tablename__ = "reservas_sala"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    concepto_ingreso_id = Column(Integer, ForeignKey("conceptos_otro_ingreso.id"), nullable=False)
    nombre_reserva = Column(String, nullable=False)
    responsable = Column(String, nullable=True)
    sala = Column(String, nullable=True)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(DateTime, nullable=False)
    hora_fin = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)

    concepto = relationship("ConceptoOtroIngreso")


class PagoPlanilla(Base):
    """
    Registro historico de un pago de planilla realizado a un
    empleado (staff fijo o profesor de sala). Se guarda como
    snapshot de los montos ya calculados, para que un reporte de un
    mes pasado no cambie si luego se edita la tarifa/sueldo del
    empleado. Permite pagos EN PARTES: un mismo periodo (anio/mes)
    puede tener varias filas si el pago se hizo fraccionado; el
    pendiente se calcula restando la suma de estas filas al total
    calculado para ese periodo.

    Para STAFF FIJO, el concepto de un mes incluye el sueldo fijo DE
    ESE MES mas las comisiones (membresias/productos) generadas en
    el MES ANTERIOR (se pagan con un mes de arrastre). Para
    PROFESOR_DE_SALA, el monto es la suma de clases dictadas en el
    periodo elegido.
    """
    __tablename__ = "pagos_planilla"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    empleado_id = Column(Integer, ForeignKey("empleados.id"), nullable=False)
    tipo = Column(String, nullable=False)  # "staff" | "profesor"
    anio = Column(Integer, nullable=False)  # periodo que se esta pagando
    mes = Column(Integer, nullable=False)  # 1-12

    # --- STAFF ---
    monto_sueldo_fijo = Column(Float, default=0.0)
    monto_comision_membresias = Column(Float, default=0.0)  # del mes ANTERIOR
    monto_comision_productos = Column(Float, default=0.0)  # del mes ANTERIOR

    # --- PROFESOR ---
    cantidad_clases = Column(Integer, nullable=True)
    monto_clases = Column(Float, default=0.0)

    monto_total = Column(Float, nullable=False)  # lo efectivamente pagado en ESTE registro (permite pagos parciales)
    fecha_pago = Column(DateTime, default=ahora_lima)
    notas = Column(Text, nullable=True)
    usuario_registro_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # quien registro el pago
    metodo_pago = Column(String, default="efectivo")  # efectivo | cuenta

    # --- Solo PROFESOR: el periodo se identifica por el rango de
    # fechas usado en el calculo (no por mes calendario, ya que las
    # clases no siguen un ciclo mensual fijo). El pendiente de un
    # profesor se calcula comparando el total de ESE MISMO rango
    # contra la suma de pagos ya hechos para ese mismo rango.
    desde = Column(Date, nullable=True)
    hasta = Column(Date, nullable=True)

    empleado = relationship("Empleado")


# ==================================================================
# 11b. SERVICIOS / DEUDAS (Pagos > Servicios: limpieza, internet,
# agua, mantenimiento, deudas con proveedores, etc.)
# ==================================================================

class Servicio(Base):
    """
    Catalogo de servicios/proveedores recurrentes o conceptos de
    deuda del gimnasio (Personal de Limpieza, Internet, Agua,
    Mantenimiento, Deudas, etc.), gestionable desde Pagos > Servicios
    igual que el catalogo de Puestos (checklist con visibilidad).
    """
    __tablename__ = "servicios"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    nombre = Column(String, nullable=False)
    notas = Column(Text, nullable=True)
    activo = Column(Boolean, default=True)

    cargos = relationship("CargoServicio", back_populates="servicio")


class CargoServicio(Base):
    """
    Un cobro/deuda concreta de un Servicio en un periodo especifico
    (ej. 'Agua - Junio 2026' o una deuda puntual con un proveedor).
    El monto se ingresa a mano porque varia mes a mes (recibo de
    luz/agua) o es un monto unico (una deuda). Admite pagos EN
    PARTES via PagoServicio, igual que PagoPlanilla con la planilla.
    """
    __tablename__ = "cargos_servicio"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    servicio_id = Column(Integer, ForeignKey("servicios.id"), nullable=False)
    concepto = Column(String, nullable=True)  # texto libre opcional, ej. "Recibo de Junio"
    monto_total = Column(Float, nullable=False)
    anio = Column(Integer, nullable=False)
    mes = Column(Integer, nullable=False)  # 1-12, periodo al que corresponde el cargo
    fecha_vencimiento = Column(Date, nullable=True)
    fecha_registro = Column(DateTime, default=ahora_lima)
    notas = Column(Text, nullable=True)
    # --- Recurrencia (opcional): si se crea marcado como recurrente,
    # el backend genera de una vez varios CargoServicio a futuro
    # (agrupados por serie_id) en vez de uno solo. recurrente_tipo
    # queda guardado en cada fila generada solo como referencia
    # informativa (de donde vino), no dispara nada por si solo.
    recurrente_tipo = Column(String, nullable=True)  # "semanal" | "mensual" | "anual"
    recurrente_dias_semana = Column(String, nullable=True)  # csv (lun,mar,...), solo si recurrente_tipo == "semanal"
    serie_id = Column(String, nullable=True, index=True)  # agrupa los cargos generados por una misma regla de recurrencia

    servicio = relationship("Servicio", back_populates="cargos")
    pagos = relationship("PagoServicio", back_populates="cargo", cascade="all, delete-orphan")


class PagoServicio(Base):
    """Un pago (total o parcial) registrado contra un CargoServicio."""
    __tablename__ = "pagos_servicio"

    id = Column(Integer, primary_key=True, index=True)
    cargo_id = Column(Integer, ForeignKey("cargos_servicio.id"), nullable=False)
    monto = Column(Float, nullable=False)
    fecha_pago = Column(DateTime, default=ahora_lima)
    notas = Column(Text, nullable=True)
    usuario_registro_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    # Origen de fondos del gimnasio: caja fisica o cuenta bancaria/digital.
    metodo_pago = Column(String, default="efectivo")

    cargo = relationship("CargoServicio", back_populates="pagos")


# ==================================================================
# 12. CONFIGURACION GENERAL
# ==================================================================

class Configuracion(Base):
    """
    Fila unica con la configuracion general del gimnasio. Se
    espera que solo exista un registro (id=1).
    """
    __tablename__ = "configuracion"

    id = Column(Integer, primary_key=True, index=True)
    moneda = Column(String, default="S/")
    nombre_gimnasio = Column(String, default="Mi Gimnasio")
    telefono = Column(String, nullable=True)
    email = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    comision_tarjeta = Column(Float, default=3.5)
    comision_qr = Column(Float, default=2.0)
    dias_aviso_vencimiento = Column(Integer, default=7)
    comision_producto_porcentaje = Column(Float, default=0.0)  # % flat por cada venta de producto, sin relacion a metas
    tema = Column(String, default="lavanda")  # paleta de colores de la interfaz
    modo_tema = Column(String, default="claro")  # "claro" | "oscuro"
    clausulas_contrato = Column(Text, nullable=True)  # texto libre con las clausulas del contrato de matricula

    # --- Gestion > Medidas: que campos crudos y que valores calculados
    # se muestran en la tabla de Medidas de la ficha del cliente.
    # Se guardan como csv de claves (ver medidas-catalogo.js para las
    # claves validas de cada lista). Si es null/vacio, se usa un set
    # razonable por defecto (definido en el frontend).
    medidas_campos_visibles = Column(Text, nullable=True)
    medidas_valores_visibles = Column(Text, nullable=True)


# ==================================================================
# 13. METAS DE VENTAS Y COMISIONES (solo administrador)
# ==================================================================

# ==================================================================
# 14. GASTOS / EGRESOS
# ==================================================================

class CategoriaGasto(str, enum.Enum):
    COMPRA_PRODUCTO   = "compra_producto"    # reposicion de stock (enlazado a Compra)
    PAGO_STAFF        = "pago_staff"         # planilla staff fijo  (enlazado a PagoPlanilla)
    PAGO_PROFESOR     = "pago_profesor"      # planilla profesores  (enlazado a PagoPlanilla)
    OTROS             = "otros"              # alquiler, servicios, mantenimiento, etc.


class ConceptoOtroIngreso(Base):
    """Concepto reutilizable para ingresos ajenos a membresias y ventas."""
    __tablename__ = "conceptos_otro_ingreso"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    nombre = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    monto_sugerido = Column(Float, default=0.0)
    mostrar_agenda = Column(Boolean, default=False)
    sala_sugerida = Column(String, nullable=True)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=ahora_lima)


class OtroIngreso(Base):
    """Cobro registrado contra un concepto de otros ingresos."""
    __tablename__ = "otros_ingresos"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=False, index=True)
    concepto_id = Column(Integer, ForeignKey("conceptos_otro_ingreso.id"), nullable=False)
    fecha = Column(DateTime, default=ahora_lima)
    monto = Column(Float, nullable=False)
    metodo_pago = Column(String, default="efectivo")
    descripcion = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    concepto = relationship("ConceptoOtroIngreso")


class Gasto(Base):
    """
    Registro unificado de egresos del gimnasio. Los pagos de planilla
    y las compras de stock se enlazan por referencia_id para no
    duplicar datos; los gastos libres (alquiler, servicios, etc.) se
    registran directo aqui con categoria=OTROS.
    """
    __tablename__ = "gastos"

    id             = Column(Integer, primary_key=True, index=True)
    gimnasio_id    = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    fecha          = Column(DateTime, default=ahora_lima)
    categoria      = Column(Enum(CategoriaGasto), nullable=False)
    monto          = Column(Float, nullable=False)
    descripcion    = Column(Text, nullable=True)
    referencia_id  = Column(Integer, nullable=True)  # id en PagoPlanilla o Compra segun categoria
    usuario_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notas          = Column(Text, nullable=True)
    metodo_pago    = Column(String, default="efectivo")  # efectivo | cuenta


class MetaMensual(Base):
    """
    Meta de ventas esperada para un mes especifico (proyeccion
    editable a 1 anio, mes a mes). Es la base contra la que se mide
    el porcentaje de cumplimiento de cada trabajador para calcular
    su tramo de comision.
    """
    __tablename__ = "metas_mensuales"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    anio = Column(Integer, nullable=False, index=True)
    mes = Column(Integer, nullable=False)  # 1-12
    meta_membresias = Column(Float, default=0.0)
    meta_productos = Column(Float, default=0.0)
    notas = Column(Text, nullable=True)


class TramoComision(Base):
    """
    Tramo configurable de comision: a partir de que % de
    cumplimiento de la meta mensual (individual) se activa un
    porcentaje de comision sobre las ventas de ese trabajador. Se
    aplica el tramo mas alto que el trabajador alcance. Separado
    por tipo ('membresia' o 'producto') porque cada uno puede tener
    su propia escala.
    """
    __tablename__ = "tramos_comision"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    tipo = Column(String, nullable=False)  # "membresia" | "producto"
    porcentaje_meta_minimo = Column(Float, nullable=False)  # ej. 30, 50
    porcentaje_comision = Column(Float, nullable=False)  # ej. 2.0, 3.0
    activo = Column(Boolean, default=True)


# ==================================================================
# 16. MEDIDAS (toma antropometrica completa, historial por fecha)
# ==================================================================

class Medida(Base):
    """
    Una 'toma' de medidas de un cliente en una fecha especifica.
    Guarda TODOS los campos crudos posibles (el trainer solo llena
    los que aplique); cuales se muestran en la tabla del cliente y
    que valores calculados se derivan de ellos se define en
    Configuracion (medidas_campos_visibles / medidas_valores_visibles,
    ver Gestion > Medidas). Los valores calculados (IMC, BMR, TDEE,
    etc.) NO se guardan aqui: se calculan al vuelo en el frontend a
    partir de estos datos crudos (asi, si cambia la formula, no hay
    que migrar historico).
    """
    __tablename__ = "medidas"

    id = Column(Integer, primary_key=True, index=True)
    gimnasio_id = Column(Integer, ForeignKey("gimnasios.id"), nullable=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    fecha = Column(Date, default=hoy_lima, nullable=False)
    notas = Column(Text, nullable=True)

    # --- Datos base ---
    # (sexo y fecha_nacimiento NO estan aqui: se usan las de Cliente)
    estatura_cm = Column(Float, nullable=True)
    peso_kg = Column(Float, nullable=True)

    # --- Perimetros (cm) ---
    cuello_cm = Column(Float, nullable=True)
    hombros_cm = Column(Float, nullable=True)
    pecho_cm = Column(Float, nullable=True)
    brazo_derecho_relajado_cm = Column(Float, nullable=True)
    brazo_izquierdo_relajado_cm = Column(Float, nullable=True)
    brazo_derecho_contraido_cm = Column(Float, nullable=True)
    brazo_izquierdo_contraido_cm = Column(Float, nullable=True)
    antebrazo_derecho_cm = Column(Float, nullable=True)
    antebrazo_izquierdo_cm = Column(Float, nullable=True)
    cintura_cm = Column(Float, nullable=True)
    abdomen_cm = Column(Float, nullable=True)
    cadera_cm = Column(Float, nullable=True)
    muslo_derecho_cm = Column(Float, nullable=True)
    muslo_izquierdo_cm = Column(Float, nullable=True)
    pantorrilla_derecha_cm = Column(Float, nullable=True)
    pantorrilla_izquierda_cm = Column(Float, nullable=True)
    muneca_derecha_cm = Column(Float, nullable=True)
    muneca_izquierda_cm = Column(Float, nullable=True)
    tobillo_derecho_cm = Column(Float, nullable=True)
    tobillo_izquierdo_cm = Column(Float, nullable=True)

    # --- Signos vitales / composicion (de bioimpedancia si hay) ---
    presion_arterial = Column(String, nullable=True)  # texto "120/80"
    frecuencia_cardiaca_reposo = Column(Integer, nullable=True)
    saturacion_oxigeno = Column(Float, nullable=True)
    porcentaje_grasa_corporal = Column(Float, nullable=True)  # si se mide directo (bioimpedancia/plicometro)
    masa_muscular_kg = Column(Float, nullable=True)
    grasa_visceral_nivel = Column(Float, nullable=True)
    agua_corporal_pct = Column(Float, nullable=True)
    masa_osea_kg = Column(Float, nullable=True)
    edad_metabolica = Column(Integer, nullable=True)

    # --- Meta del cliente (para calcular progreso hacia la meta) ---
    peso_objetivo_kg = Column(Float, nullable=True)

    cliente = relationship("Cliente", back_populates="medidas")
