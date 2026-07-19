import pytest
import io
from pathlib import Path
from pydantic import ValidationError
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import auth, models, schemas
from backend.main import (
    _total_pagado_membresia,
    _validar_archivo_documento,
    _validar_y_optimizar_foto,
    listar_egresos,
    listar_ingresos,
)


def test_codigo_acceso_se_guarda_como_hash_y_se_verifica():
    guardado = auth.hash_codigo_acceso("638291")
    assert guardado != "638291"
    assert auth.verificar_codigo_acceso("638291", guardado)
    assert not auth.verificar_codigo_acceso("000000", guardado)


def test_codigos_antiguos_siguen_funcionando_para_migracion_gradual():
    assert auth.verificar_codigo_acceso("638291", "638291")
    assert auth.codigo_necesita_rehash("638291")


def test_password_staff_exige_longitud_minima():
    with pytest.raises(ValidationError):
        schemas.UsuarioCreate(
            nombre_completo="Prueba",
            username="prueba",
            rol="STAFF",
            password="corta1",
        )


def test_password_staff_es_opcional_para_flujo_counter():
    usuario = schemas.UsuarioCreate(
        nombre_completo="Recepcion Counter",
        username="recepcion-counter",
        rol="staff",
    )
    assert usuario.password is None


def test_password_segura_exige_letras_y_numeros():
    with pytest.raises(ValueError):
        auth.validar_password_segura("sololetrasseguras")
    with pytest.raises(ValueError):
        auth.validar_password_segura("123456789012")
    auth.validar_password_segura("ClaveSegura2026")


def test_rate_limit_bloquea_despues_del_quinto_fallo():
    limiter = auth.LoginRateLimiter(max_intentos=5, ventana_segundos=900)
    clave = "staff:ip:gym:usuario"
    for _ in range(5):
        assert limiter.comprobar(clave) is None
        limiter.registrar_fallo(clave)
    assert limiter.comprobar(clave) is not None
    limiter.limpiar(clave)
    assert limiter.comprobar(clave) is None


def test_rate_limit_persistente_sobrevive_reinicio_y_oculta_identidad():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    clave = "alumno:192.0.2.10:mi-gym:87654321"
    try:
        for _ in range(5):
            auth.registrar_fallo_login(db, clave)
        # Simula un reinicio: la memoria se vacia, la BD debe seguir bloqueando.
        auth.login_rate_limiter.limpiar(clave)
        with pytest.raises(HTTPException) as error:
            auth.exigir_intentos_disponibles(clave, db)
        assert error.value.status_code == 429
        registro = db.query(models.IntentoAcceso).one()
        assert registro.clave_hash != clave
        assert "87654321" not in registro.clave_hash
        auth.limpiar_fallos_login(db, clave)
        auth.exigir_intentos_disponibles(clave, db)
    finally:
        auth.login_rate_limiter.limpiar(clave)
        db.close()


def test_archivo_disfrazado_de_imagen_es_rechazado():
    with pytest.raises(HTTPException):
        _validar_y_optimizar_foto(b"<script>alert(1)</script>", "image/png")


def test_imagen_de_tipo_distinto_al_declarado_es_rechazada():
    salida = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(salida, format="PNG")
    with pytest.raises(HTTPException):
        _validar_y_optimizar_foto(salida.getvalue(), "image/jpeg")


def test_imagen_valida_puede_convertirse_a_webp():
    salida = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(salida, format="PNG")
    contenido, mime = _validar_y_optimizar_foto(salida.getvalue(), "image/png", optimizar=True)
    assert mime == "image/webp"
    assert contenido.startswith(b"RIFF")


def test_sustento_disfrazado_de_pdf_es_rechazado():
    with pytest.raises(HTTPException):
        _validar_archivo_documento("factura.pdf", b"<script>alert(1)</script>")


def test_xml_contable_debe_estar_bien_formado():
    with pytest.raises(HTTPException):
        _validar_archivo_documento("factura.xml", b"<factura><total>10</factura>")
    mime, extension = _validar_archivo_documento("factura.xml", b"<factura><total>10</total></factura>")
    assert (mime, extension) == ("application/xml", ".xml")


def test_total_membresia_proviene_de_pagos_validos_y_no_del_cache():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        gym = models.Gimnasio(nombre="Gym", slug="gym-finanzas", activo=True)
        db.add(gym); db.flush()
        cliente = models.Cliente(gimnasio_id=gym.id, nombre="Socio")
        plan = models.Membresia(gimnasio_id=gym.id, nombre="Plan", precio=100, duracion_dias=30)
        db.add_all([cliente, plan]); db.flush()
        cm = models.ClienteMembresia(cliente=cliente, membresia=plan, monto_pagado=999)
        db.add(cm); db.flush()
        db.add_all([
            models.PagoMembresia(cliente_membresia_id=cm.id, monto=40, anulada=False),
            models.PagoMembresia(cliente_membresia_id=cm.id, monto=50, anulada=True),
        ])
        db.commit()
        assert _total_pagado_membresia(db, cm.id) == 40
    finally:
        db.close()


def test_libro_financiero_registra_comision_de_otro_ingreso():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        gym = models.Gimnasio(nombre="Gym", slug="gym-comision", activo=True, comision_tarjeta=4, comision_qr=2)
        db.add(gym); db.flush()
        admin = models.Usuario(gimnasio_id=gym.id, nombre_completo="Admin", username="admin-fin", password_hash="x", rol=models.RolUsuario.STAFF, es_administrador=True)
        concepto = models.ConceptoOtroIngreso(gimnasio_id=gym.id, nombre="Alquiler")
        db.add_all([admin, concepto]); db.flush()
        ingreso = models.OtroIngreso(gimnasio_id=gym.id, concepto=concepto, monto=100, metodo_pago="tarjeta")
        db.add(ingreso); db.commit()
        fecha = ingreso.fecha.date()
        libro_ingresos = listar_ingresos(desde=fecha, hasta=fecha, db=db, usuario=admin)
        libro_egresos = listar_egresos(desde=fecha, hasta=fecha, db=db, usuario=admin)
        assert libro_ingresos["total"] == 100
        assert libro_ingresos["detalle"][0]["comision_gym"] == 4
        assert libro_egresos["comisiones"] == 4
    finally:
        db.close()


def test_frontends_produccion_usan_canal_api_estable():
    raiz = Path(__file__).resolve().parents[1]
    nginx = (raiz / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    assert "location /api/" in nginx
    assert "proxy_pass http://127.0.0.1:8000/;" in nginx
    for ruta in (
        "frontend-staff/js/api.js",
        "frontend-alumno/js/api.js",
        "frontend-profesor/js/api.js",
    ):
        contenido = (raiz / ruta).read_text(encoding="utf-8")
        assert "${window.location.origin}/api" in contenido
