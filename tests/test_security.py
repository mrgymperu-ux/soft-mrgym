import pytest
import io
from pydantic import ValidationError
from fastapi import HTTPException
from PIL import Image

from backend import auth, schemas
from backend.main import _validar_y_optimizar_foto


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
