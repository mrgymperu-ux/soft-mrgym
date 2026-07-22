"""Pruebas de regresion para las fronteras multi-tenant criticas."""

import io
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend import auth, models, schemas
from backend.main import (
    EJERCICIOS_GENERABLES_EQUIPO,
    EQUIPAMIENTO_GIMNASIO,
    _CAMPOS_CLIENTE_EXPORTABLES,
    _cliente_membresia_del_gym,
    _cerrar_asistencias_vencidas,
    _configuracion_del_gym,
    _del_gym,
    _estado_suscripcion,
    _limitar_gramos_proteina,
    _porcion_cliente_facil,
    _validar_y_optimizar_foto,
    _sembrar_datos_gimnasio_nuevo,
    asignar_paquete_rutina,
    asignar_membresia_a_cliente,
    abrir_caja,
    actualizar_tipo_ejercicio,
    actualizar_whatsapp_configuracion,
    crear_equipamiento_personalizado,
    crear_concepto_ingreso,
    crear_ajuste_caja,
    crear_documento_financiero,
    crear_empleado,
    crear_paquete_rutina,
    crear_reserva_sala,
    crear_tipo_ejercicio,
    crear_usuario,
    crear_venta,
    cerrar_caja,
    actualizar_empleado,
    caja_actual,
    consultar_auditoria,
    contenido_foto_cliente,
    eliminar_compra,
    eliminar_pago_membresia,
    eliminar_venta,
    emitir_documento_financiero,
    eliminar_biometria_facial,
    anular_deuda_cliente_membresia,
    estado_biometria_facial,
    generar_rutinas_por_equipamiento,
    guardar_biometria_facial,
    obtener_equipamiento_gimnasio,
    registrar_compra,
    registrar_entrada,
    registrar_salida,
    reprogramar_cliente_membresia,
    registrar_otro_ingreso,
    resumen_documentos_financieros,
    resumen_comercial_staff,
    recomendar_paquetes_rutina_cliente,
    renovar_suscripcion_saas,
    guardar_recomendacion_rutina,
    listar_whatsapp_mensajes,
    listar_descriptores_faciales,
    listado_completo_clientes,
    listar_usuarios_counter,
    login_counter,
    obtener_whatsapp_configuracion,
    configurar_pin_counter,
    vincular_dispositivo_counter,
)


def _request(path: str, method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": [], "query_string": b""})


class MultiTenantTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.plan_saas = models.PlanSaas(nombre="Pro Test", precio_mensual=49, activo=True)
        self.db.add(self.plan_saas)
        self.db.flush()
        self.gym1 = models.Gimnasio(nombre="Gym Uno", slug="gym-uno", activo=True, moneda="S/", plan_id=self.plan_saas.id, reconocimiento_facial_modo="movil")
        self.gym2 = models.Gimnasio(nombre="Gym Dos", slug="gym-dos", activo=True, moneda="USD")
        self.db.add_all([self.gym1, self.gym2])
        self.db.flush()

        self.admin1 = models.Usuario(
            gimnasio_id=self.gym1.id,
            nombre_completo="Admin Uno",
            username="admin-uno",
            password_hash="test",
            rol=models.RolUsuario.STAFF,
            es_administrador=True,
        )
        self.staff1 = models.Usuario(
            gimnasio_id=self.gym1.id,
            nombre_completo="Staff Uno",
            username="staff-uno",
            password_hash="test",
            rol=models.RolUsuario.STAFF,
            es_administrador=False,
            zonas_permitidas="clientes",
        )
        self.cliente1 = models.Cliente(gimnasio_id=self.gym1.id, nombre="Cliente Uno")
        self.cliente2 = models.Cliente(gimnasio_id=self.gym2.id, nombre="Cliente Dos")
        self.plan2 = models.Membresia(gimnasio_id=self.gym2.id, nombre="Plan Dos", precio=50, duracion_dias=30)
        self.db.add_all([self.admin1, self.staff1, self.cliente1, self.cliente2, self.plan2])
        self.db.flush()
        self.cm2 = models.ClienteMembresia(cliente_id=self.cliente2.id, membresia_id=self.plan2.id, monto_pagado=0)
        self.db.add(self.cm2)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_entidades_de_otro_gimnasio_no_se_resuelven(self):
        self.assertIsNone(_del_gym(self.db, models.Cliente, self.cliente2.id, self.admin1))
        self.assertIsNone(_cliente_membresia_del_gym(self.db, self.cm2.id, self.admin1))

    def test_horario_staff_se_guarda_actualiza_y_valida(self):
        empleado = crear_empleado(
            schemas.EmpleadoCreate(
                nombre_completo="Recepcion Test",
                tipo=models.TipoEmpleado.STAFF_FIJO,
                horario_semanal=[
                    {"dias": [0, 1, 2, 3, 4], "hora_inicio": "08:00", "hora_fin": "17:00"},
                    {"dias": [5], "hora_inicio": "09:00", "hora_fin": "13:00"},
                ],
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.assertEqual(empleado.gimnasio_id, self.gym1.id)
        self.assertEqual(empleado.horario_semanal[0]["dias"], [0, 1, 2, 3, 4])

        actualizado = actualizar_empleado(
            empleado.id,
            schemas.EmpleadoUpdate(
                horario_semanal=[{"dias": [0, 2, 4], "hora_inicio": "07:30", "hora_fin": "15:30"}]
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.assertEqual(actualizado.horario_semanal[0]["hora_inicio"], "07:30")

        with self.assertRaises(ValueError):
            schemas.EmpleadoUpdate(horario_semanal=[
                {"dias": [0, 1], "hora_inicio": "08:00", "hora_fin": "17:00"},
                {"dias": [1, 2], "hora_inicio": "18:00", "hora_fin": "22:00"},
            ])
        with self.assertRaises(ValueError):
            schemas.EmpleadoUpdate(horario_semanal=[
                {"dias": [6], "hora_inicio": "17:00", "hora_fin": "08:00"},
            ])

    def test_exportacion_no_incluye_credenciales_de_alumnos(self):
        self.assertNotIn("codigo_acceso", _CAMPOS_CLIENTE_EXPORTABLES)

    def test_optimizacion_de_logo_conserva_transparencia(self):
        origen = Image.new("RGBA", (4, 4), (20, 120, 220, 0))
        origen.putpixel((1, 1), (20, 120, 220, 255))
        archivo = io.BytesIO()
        origen.save(archivo, format="PNG")

        contenido, tipo = _validar_y_optimizar_foto(archivo.getvalue(), "image/png", optimizar=True)
        resultado = Image.open(io.BytesIO(contenido)).convert("RGBA")

        self.assertEqual(tipo, "image/webp")
        self.assertEqual(resultado.getpixel((0, 0))[3], 0)
        self.assertEqual(resultado.getpixel((1, 1))[3], 255)

    def test_biometria_facial_se_cifra_y_respeta_el_gimnasio(self):
        descriptor = [((i % 17) - 8) / 100 for i in range(1024)]
        guardado = guardar_biometria_facial(
            self.cliente1.id,
            schemas.BiometriaFacialGuardar(
                descriptor=descriptor,
                consentimiento=True,
                version_modelo="human-3.3.6-faceres",
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.assertTrue(guardado["registrada"])

        registro = self.db.query(models.BiometriaFacial).filter_by(cliente_id=self.cliente1.id).one()
        self.assertNotIn(str(descriptor[:3]), registro.descriptor_cifrado)
        self.assertGreater(len(registro.descriptor_cifrado), 100)

        disponibles = listar_descriptores_faciales(db=self.db, usuario=self.admin1)
        self.assertEqual([item["cliente_id"] for item in disponibles], [self.cliente1.id])
        self.assertEqual(len(disponibles[0]["descriptor"]), 1024)
        self.assertAlmostEqual(disponibles[0]["descriptor"][9], descriptor[9])
        self.assertTrue(estado_biometria_facial(self.cliente1.id, db=self.db, usuario=self.admin1)["registrada"])

        with self.assertRaises(HTTPException) as otro_gimnasio:
            estado_biometria_facial(self.cliente2.id, db=self.db, usuario=self.admin1)
        self.assertEqual(otro_gimnasio.exception.status_code, 404)

        eliminar_biometria_facial(self.cliente1.id, db=self.db, usuario=self.admin1)
        self.assertFalse(estado_biometria_facial(self.cliente1.id, db=self.db, usuario=self.admin1)["registrada"])

    def test_biometria_facial_exige_consentimiento(self):
        with self.assertRaises(HTTPException) as sin_consentimiento:
            guardar_biometria_facial(
                self.cliente1.id,
                schemas.BiometriaFacialGuardar(descriptor=[0.0] * 1024, consentimiento=False),
                db=self.db,
                usuario=self.admin1,
            )
        self.assertEqual(sin_consentimiento.exception.status_code, 400)

    def test_foto_alumno_exige_token_opaco_correcto(self):
        token = "token-opaco-de-prueba-1234567890"
        self.cliente1.foto_datos = b"imagen"
        self.cliente1.foto_tipo = "image/webp"
        self.cliente1.foto_url = f"/clientes/{self.cliente1.id}/foto-contenido?token={token}"
        self.db.commit()

        respuesta = contenido_foto_cliente(self.cliente1.id, token=token, db=self.db)
        self.assertEqual(respuesta.body, b"imagen")
        with self.assertRaises(HTTPException):
            contenido_foto_cliente(self.cliente1.id, token="token-incorrecto-de-largo-suficiente", db=self.db)

    def test_configuracion_es_por_gimnasio(self):
        config = _configuracion_del_gym(self.db, self.admin1)
        self.assertEqual(config.id, self.gym1.id)
        self.assertEqual(config.moneda, "S/")
        config.nombre_gimnasio = "Nuevo nombre"
        config.email = "gym@example.com"
        self.assertEqual(config.nombre, "Nuevo nombre")
        self.assertEqual(config.email_contacto, "gym@example.com")

    def test_whatsapp_configuracion_y_mensajes_estan_aislados_por_gimnasio(self):
        config = obtener_whatsapp_configuracion(db=self.db, usuario=self.admin1)
        self.assertEqual(config.gimnasio_id, self.gym1.id)
        actualizar_whatsapp_configuracion(
            schemas.WhatsAppConfiguracionUpdate(
                consentimiento_confirmado=True,
                vencimientos_automaticos=True,
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.db.add_all([
            models.WhatsAppMensaje(gimnasio_id=self.gym1.id, categoria="utilidad", direccion="saliente"),
            models.WhatsAppMensaje(gimnasio_id=self.gym2.id, categoria="marketing", direccion="saliente"),
        ])
        self.db.commit()
        mensajes = listar_whatsapp_mensajes(limite=100, db=self.db, usuario=self.admin1)
        self.assertEqual(len(mensajes), 1)
        self.assertEqual(mensajes[0].gimnasio_id, self.gym1.id)

    def test_counter_vinculado_solo_lista_y_autentica_usuarios_del_gimnasio(self):
        configurar_pin_counter(
            self.staff1.id, schemas.CounterPinRequest(pin="123456"),
            db=self.db, admin=self.admin1,
        )
        otro = models.Usuario(
            gimnasio_id=self.gym2.id, nombre_completo="Staff Dos", username="staff-dos",
            password_hash="test", pin_counter_hash=auth.hash_codigo_acceso("123456"),
            rol=models.RolUsuario.STAFF, es_administrador=False,
        )
        self.db.add(otro)
        self.db.commit()
        vinculo = vincular_dispositivo_counter(
            schemas.CounterVincularRequest(nombre="Counter prueba"), db=self.db, admin=self.admin1,
        )
        usuarios = listar_usuarios_counter(vinculo.dispositivo_token, db=self.db)
        self.assertEqual([u.id for u in usuarios], [self.staff1.id])
        sesion = login_counter(
            schemas.CounterLoginRequest(
                dispositivo_token=vinculo.dispositivo_token, usuario_id=self.staff1.id, pin="123456",
            ),
            _request("/counter/login"), self.db,
        )
        self.assertEqual(sesion.nombre, self.staff1.nombre_completo)
        with self.assertRaises(HTTPException):
            login_counter(
                schemas.CounterLoginRequest(
                    dispositivo_token=vinculo.dispositivo_token, usuario_id=otro.id, pin="123456",
                ),
                _request("/counter/login"), self.db,
            )

    def test_crear_staff_counter_no_requiere_password_visible(self):
        self.plan_saas.max_usuarios_staff = 0
        self.db.commit()
        nuevo = crear_usuario(
            schemas.UsuarioCreate(
                nombre_completo="Recepcion Counter",
                username="recepcion-counter",
                rol="staff",
                es_administrador=False,
                zonas_permitidas="clientes,sistema",
            ),
            db=self.db,
            usuario_admin=self.admin1,
        )
        self.assertTrue(nuevo.password_hash)
        self.assertNotEqual(nuevo.password_hash, "")
        self.assertEqual(nuevo.zonas_permitidas, "clientes,sistema")

    def test_auditoria_no_expone_eventos_de_otro_gimnasio(self):
        self.db.add_all([
            models.EventoAuditoria(gimnasio_id=self.gym1.id, usuario_id=self.admin1.id, accion="POST", ruta="/clientes"),
            models.EventoAuditoria(gimnasio_id=self.gym2.id, accion="DELETE", ruta="/clientes/99"),
        ])
        self.db.commit()
        eventos = consultar_auditoria(accion=None, desde=None, hasta=None, skip=0, limit=100, db=self.db, admin=self.admin1)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["ruta"], "/clientes")

    def test_asistencia_abierta_se_cierra_exactamente_a_las_tres_horas(self):
        ahora = datetime(2026, 7, 13, 18, 30)
        antigua = models.Asistencia(
            gimnasio_id=self.gym1.id,
            cliente_id=self.cliente1.id,
            fecha_hora_entrada=ahora - timedelta(hours=4),
        )
        reciente = models.Asistencia(
            gimnasio_id=self.gym1.id,
            cliente_id=self.cliente1.id,
            fecha_hora_entrada=ahora - timedelta(hours=2),
        )
        otro_gym = models.Asistencia(
            gimnasio_id=self.gym2.id,
            cliente_id=self.cliente2.id,
            fecha_hora_entrada=ahora - timedelta(hours=5),
        )
        self.db.add_all([antigua, reciente, otro_gym])
        self.db.commit()

        cerradas = _cerrar_asistencias_vencidas(self.db, self.gym1.id, ahora)

        self.assertEqual(cerradas, 1)
        self.assertEqual(antigua.fecha_hora_salida, antigua.fecha_hora_entrada + timedelta(hours=3))
        self.assertIsNone(reciente.fecha_hora_salida)
        self.assertIsNone(otro_gym.fecha_hora_salida)

    def test_entrada_y_salida_guardan_hora_operativa_de_lima(self):
        entrada_lima = datetime(2026, 7, 13, 22, 15)
        salida_lima = datetime(2026, 7, 13, 23, 5)
        with patch("backend.main.ahora_lima", return_value=entrada_lima):
            asistencia = registrar_entrada(
                schemas.AsistenciaCreate(cliente_id=self.cliente1.id),
                db=self.db,
                usuario=self.admin1,
            )
        self.assertEqual(asistencia.fecha_hora_entrada, entrada_lima)

        with patch("backend.main.ahora_lima", return_value=salida_lima):
            actualizada = registrar_salida(
                schemas.RegistrarSalidaRequest(asistencia_id=asistencia.id),
                db=self.db,
                usuario=self.admin1,
            )
        self.assertEqual(actualizada.fecha_hora_salida, salida_lima)

    def test_porciones_nutricion_son_faciles_para_el_cliente(self):
        casos = [
            ("Huevo cocido", models.CategoriaAlimento.PROTEINA, 200, "4 huevos"),
            ("Atun en agua", models.CategoriaAlimento.PROTEINA, 150, "1 lata"),
            ("Arroz blanco cocido", models.CategoriaAlimento.CARBOHIDRATO, 100, "1/2 taza"),
            ("Palta (aguacate)", models.CategoriaAlimento.GRASA, 100, "1/2 palta"),
        ]
        for nombre, categoria, gramos, esperado in casos:
            alimento = models.Alimento(
                nombre=nombre,
                categoria=categoria,
                porcion_gramos=100,
                calorias=100,
            )
            self.assertEqual(_porcion_cliente_facil(alimento, gramos), esperado)

    def test_porciones_de_proteina_tienen_limites_razonables(self):
        pollo = models.Alimento(
            nombre="Pechuga de pollo a la plancha",
            categoria=models.CategoriaAlimento.PROTEINA,
            porcion_gramos=100,
            calorias=165,
        )
        atun = models.Alimento(
            nombre="Atun en agua",
            categoria=models.CategoriaAlimento.PROTEINA,
            porcion_gramos=100,
            calorias=116,
        )
        huevo = models.Alimento(
            nombre="Huevo",
            categoria=models.CategoriaAlimento.PROTEINA,
            porcion_gramos=100,
            calorias=155,
        )
        self.assertEqual(_limitar_gramos_proteina(pollo, 333), 200)
        self.assertEqual(_porcion_cliente_facil(pollo, 200), "1 filete mediano")
        self.assertEqual(_limitar_gramos_proteina(atun, 278), 150)
        self.assertEqual(_limitar_gramos_proteina(huevo, 278), 200)

    def test_zonas_se_validan_en_backend(self):
        self.assertIs(auth.requiere_staff(_request("/clientes/"), self.staff1), self.staff1)
        with self.assertRaises(HTTPException) as error:
            auth.requiere_staff(_request("/ventas/"), self.staff1)
        self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as error_equipo:
            auth.requiere_staff(_request("/equipamiento-gimnasio"), self.staff1)
        self.assertEqual(error_equipo.exception.status_code, 403)

        self.staff1.zonas_permitidas = "agenda"
        self.assertIs(auth.requiere_staff(_request("/agenda/profesores"), self.staff1), self.staff1)
        self.assertIs(auth.requiere_staff(_request("/agenda/conceptos-ingreso"), self.staff1), self.staff1)
        self.assertIs(auth.requiere_staff(_request("/salas/"), self.staff1), self.staff1)
        with self.assertRaises(HTTPException) as error_empleados:
            auth.requiere_staff(_request("/empleados/"), self.staff1)
        self.assertEqual(error_empleados.exception.status_code, 403)

        self.staff1.zonas_permitidas = "planilla"
        self.assertIs(auth.requiere_staff(_request("/empleados/"), self.staff1), self.staff1)

    def test_matricula_permite_elegir_vendedor_del_staff(self):
        plan = models.Membresia(gimnasio_id=self.gym1.id, nombre="Mensual", precio=100, duracion_dias=30)
        self.db.add(plan); self.db.commit()
        cm = asignar_membresia_a_cliente(
            self.cliente1.id,
            schemas.ClienteMembresiaCreate(
                cliente_id=self.cliente1.id, membresia_id=plan.id,
                monto_pagado=40, fecha_pago_saldo=date.today() + timedelta(days=7),
                vendido_por_id=self.staff1.id,
            ),
            idempotency_key=None, db=self.db, usuario_actual=self.admin1,
        )
        self.assertEqual(cm.vendido_por_id, self.staff1.id)

    def test_reprogramar_matricula_solo_sin_asistencias(self):
        plan = models.Membresia(gimnasio_id=self.gym1.id, nombre="Mensual", precio=100, duracion_dias=30)
        self.db.add(plan); self.db.flush()
        inicio = date.today()
        cm = models.ClienteMembresia(
            cliente_id=self.cliente1.id, membresia_id=plan.id,
            fecha_inicio=inicio, fecha_fin=inicio + timedelta(days=30), activo=True,
        )
        self.db.add(cm); self.db.commit()
        movida = reprogramar_cliente_membresia(
            cm.id, schemas.ReprogramarMembresiaRequest(fecha_inicio=inicio + timedelta(days=5)),
            db=self.db, usuario=self.staff1,
        )
        self.assertEqual(movida.fecha_fin, inicio + timedelta(days=35))
        self.db.add(models.Asistencia(
            cliente_id=self.cliente1.id, gimnasio_id=self.gym1.id,
            fecha_hora_entrada=datetime.combine(movida.fecha_inicio, datetime.min.time()) + timedelta(hours=10),
        ))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            reprogramar_cliente_membresia(
                cm.id, schemas.ReprogramarMembresiaRequest(fecha_inicio=inicio + timedelta(days=6)),
                db=self.db, usuario=self.staff1,
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_anular_deuda_conserva_el_pago_realizado(self):
        plan = models.Membresia(gimnasio_id=self.gym1.id, nombre="Mensual", precio=100, duracion_dias=30)
        self.db.add(plan); self.db.flush()
        cm = models.ClienteMembresia(
            cliente_id=self.cliente1.id, membresia_id=plan.id,
            fecha_inicio=date.today(), fecha_fin=date.today() + timedelta(days=30), monto_pagado=30, activo=True,
        )
        self.db.add(cm); self.db.flush()
        pago = models.PagoMembresia(cliente_membresia_id=cm.id, monto=30, metodo_pago="efectivo", registrado_por_id=self.admin1.id)
        self.db.add(pago); self.db.commit()
        resultado = anular_deuda_cliente_membresia(
            cm.id, schemas.AnulacionOperacionRequest(motivo="Nueva matrícula"), db=self.db, usuario=self.admin1,
        )
        self.db.refresh(cm); self.db.refresh(pago)
        self.assertEqual(resultado["saldo_anulado"], 70)
        self.assertTrue(cm.anulada)
        self.assertFalse(pago.anulada)

    def test_resumen_comercial_separa_ventas_comisiones_pagos_y_saldo(self):
        empleado = models.Empleado(
            gimnasio_id=self.gym1.id, nombre_completo="Staff Uno",
            tipo=models.TipoEmpleado.STAFF_FIJO, sueldo_fijo_mensual=0,
        )
        self.db.add(empleado); self.db.flush()
        self.staff1.empleado_id = empleado.id
        self.gym1.comision_producto_porcentaje = 10
        plan = models.Membresia(gimnasio_id=self.gym1.id, nombre="Mensual", precio=100, duracion_dias=30)
        meta = models.MetaMensual(gimnasio_id=self.gym1.id, anio=2026, mes=1, meta_membresias=100)
        tramo = models.TramoComision(
            gimnasio_id=self.gym1.id, tipo="membresia", porcentaje_meta_minimo=100,
            porcentaje_comision=5, activo=True,
        )
        self.db.add_all([plan, meta, tramo]); self.db.flush()
        cm = models.ClienteMembresia(
            cliente_id=self.cliente1.id, membresia_id=plan.id, vendido_por_id=self.staff1.id,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31), monto_pagado=100,
        )
        self.db.add(cm); self.db.flush()
        self.db.add_all([
            models.PagoMembresia(
                cliente_membresia_id=cm.id, monto=100, metodo_pago="efectivo",
                fecha_pago=datetime(2026, 1, 10), registrado_por_id=self.admin1.id,
            ),
            models.Venta(
                gimnasio_id=self.gym1.id, usuario_id=self.staff1.id, total=50,
                metodo_pago=models.MetodoPago.EFECTIVO, es_venta_rapida=True,
                fecha_venta=datetime(2026, 1, 12),
            ),
            models.PagoPlanilla(
                gimnasio_id=self.gym1.id, empleado_id=empleado.id, tipo="staff",
                anio=2026, mes=2, monto_sueldo_fijo=0, monto_comision_membresias=5,
                monto_comision_productos=5, monto_total=5, metodo_pago="efectivo",
            ),
        ])
        self.db.commit()
        resumen = resumen_comercial_staff(2026, 1, db=self.db, usuario=self.admin1)
        fila = next(f for f in resumen["filas"] if f["usuario_id"] == self.staff1.id)
        self.assertEqual(fila["ventas_membresias"], 100)
        self.assertEqual(fila["venta_rapida"], 50)
        self.assertEqual(fila["comision_total"], 10)
        self.assertEqual(fila["pagado"], 5)
        self.assertEqual(fila["saldo"], 5)
        febrero = resumen_comercial_staff(2026, 2, db=self.db, usuario=self.admin1)
        fila_febrero = next(f for f in febrero["filas"] if f["usuario_id"] == self.staff1.id)
        self.assertEqual(fila_febrero["planilla_total"], 10)
        self.assertEqual(fila_febrero["planilla_pagado"], 5)
        self.assertEqual(fila_febrero["planilla_saldo"], 5)

    def test_clientes_todos_incluye_inscritos_y_no_inscritos_historicos(self):
        historico = models.ClienteHistorico(
            gimnasio_id=self.gym1.id, nombre_completo="Persona No Inscrita",
            nombres="Persona", apellidos="No Inscrita", migrado=False,
        )
        self.db.add(historico); self.db.commit()
        filas = listado_completo_clientes(
            filtro="todos", dias_vencimiento=30, desde=None, hasta=None,
            orden=None, buscar=None, db=self.db, _=self.admin1,
        )
        self.assertTrue(any(f.id == self.cliente1.id and not f.es_historico for f in filas))
        self.assertTrue(any(f.historico_id == historico.id and f.es_historico for f in filas))

    def test_staff_puede_leer_configuracion_pero_no_modificarla(self):
        self.assertIs(auth.requiere_staff(_request("/configuracion/"), self.staff1), self.staff1)
        with self.assertRaises(HTTPException) as error:
            auth.requiere_staff(_request("/configuracion/", method="PUT"), self.staff1)
        self.assertEqual(error.exception.status_code, 403)

    def test_reintento_de_venta_no_duplica_cobro_ni_descuenta_stock_dos_veces(self):
        producto = models.Producto(gimnasio_id=self.gym1.id, nombre="Agua", precio_venta=5, stock=10)
        self.db.add(producto); self.db.commit()
        datos = schemas.VentaCreate(
            metodo_pago="efectivo",
            detalles=[schemas.DetalleVentaCreate(producto_id=producto.id, cantidad=2, precio_unitario=5)],
        )
        clave = "operacion-venta-prueba-0001"
        primera = crear_venta(datos, idempotency_key=clave, db=self.db, usuario_actual=self.admin1)
        segunda = crear_venta(datos, idempotency_key=clave, db=self.db, usuario_actual=self.admin1)
        self.db.refresh(producto)
        self.assertEqual(primera.id, segunda.id)
        self.assertEqual(producto.stock, 8)
        self.assertEqual(self.db.query(models.Venta).count(), 1)

    def test_cierre_de_caja_exige_explicar_diferencia_y_conserva_snapshot(self):
        abrir_caja(schemas.AperturaCajaRequest(monto_apertura=100), idempotency_key="apertura-caja-prueba-0001", db=self.db, usuario=self.admin1)
        producto = models.Producto(gimnasio_id=self.gym1.id, nombre="Agua", precio_venta=10, stock=2)
        self.db.add(producto); self.db.commit()
        crear_venta(
            schemas.VentaCreate(metodo_pago="efectivo", detalles=[schemas.DetalleVentaCreate(producto_id=producto.id, cantidad=1, precio_unitario=10)]),
            idempotency_key="venta-caja-prueba-0001", db=self.db, usuario_actual=self.admin1,
        )
        actual = caja_actual(db=self.db, usuario=self.admin1)
        self.assertEqual(actual["monto_esperado"], 110.0)
        with self.assertRaises(HTTPException):
            cerrar_caja(schemas.CierreCajaRequest(monto_contado=105), idempotency_key="cierre-caja-prueba-0001", db=self.db, usuario=self.admin1)
        cierre = cerrar_caja(schemas.CierreCajaRequest(monto_contado=105, nota="Faltante pendiente de revision"), idempotency_key="cierre-caja-prueba-0002", db=self.db, usuario=self.admin1)
        self.assertEqual(cierre["diferencia"], -5.0)
        self.assertEqual(self.db.query(models.TurnoCaja).one().estado, "cerrada")

    def test_caja_cerrada_no_se_reescribe_y_la_correccion_es_un_ajuste(self):
        abrir_caja(schemas.AperturaCajaRequest(monto_apertura=100), idempotency_key="apertura-bloqueo-0001", db=self.db, usuario=self.admin1)
        producto = models.Producto(gimnasio_id=self.gym1.id, nombre="Agua", precio_venta=10, stock=2)
        self.db.add(producto); self.db.commit()
        venta = crear_venta(
            schemas.VentaCreate(metodo_pago="efectivo", detalles=[schemas.DetalleVentaCreate(producto_id=producto.id, cantidad=1, precio_unitario=10)]),
            idempotency_key="venta-bloqueo-0001", db=self.db, usuario_actual=self.admin1,
        )
        cerrar_caja(schemas.CierreCajaRequest(monto_contado=110), idempotency_key="cierre-bloqueo-0001", db=self.db, usuario=self.admin1)

        with self.assertRaises(HTTPException) as error:
            eliminar_venta(venta.id, schemas.AnulacionOperacionRequest(motivo="Correccion posterior"), db=self.db, usuario=self.admin1)
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(venta.anulada)

        abrir_caja(schemas.AperturaCajaRequest(monto_apertura=110), idempotency_key="apertura-bloqueo-0002", db=self.db, usuario=self.admin1)
        datos = schemas.AjusteCajaCreate(tipo="egreso", monto=10, motivo="Correccion de la venta anterior", referencia=f"Venta #{venta.id}")
        primero = crear_ajuste_caja(datos, idempotency_key="ajuste-bloqueo-0001", db=self.db, usuario=self.admin1)
        segundo = crear_ajuste_caja(datos, idempotency_key="ajuste-bloqueo-0001", db=self.db, usuario=self.admin1)
        self.assertEqual(primero["id"], segundo["id"])
        self.assertEqual(self.db.query(models.AjusteCaja).count(), 1)
        self.assertEqual(caja_actual(db=self.db, usuario=self.admin1)["monto_esperado"], 100.0)

    def test_documentos_reservan_correlativo_y_no_duplican_el_origen(self):
        self.gym1.ruc = "20123456789"; self.gym1.razon_social = "Gimnasio Prueba SAC"
        producto = models.Producto(gimnasio_id=self.gym1.id, nombre="Agua", precio_venta=10, stock=3)
        self.db.add(producto); self.db.commit()
        venta = crear_venta(
            schemas.VentaCreate(metodo_pago="efectivo", detalles=[schemas.DetalleVentaCreate(producto_id=producto.id, cantidad=1, precio_unitario=10)]),
            idempotency_key="venta-documento-prueba-0001", db=self.db, usuario_actual=self.admin1,
        )
        datos = schemas.DocumentoFinancieroCreate(
            direccion="ingreso", tipo="boleta", fecha_emision=date.today(), igv=1.53,
            fuente_tipo="venta", fuente_id=venta.id, receptor_nombre="Consumidor final",
        )
        documento = crear_documento_financiero(datos, idempotency_key="documento-prueba-0001", db=self.db, usuario=self.admin1)
        emitido = emitir_documento_financiero(documento.id, db=self.db, usuario=self.admin1)
        self.assertEqual((emitido.serie, emitido.numero, emitido.estado), ("B001", 1, "emitido"))
        self.assertEqual(emitido.total, 10.0)

        duplicado = crear_documento_financiero(datos, idempotency_key="documento-prueba-0002", db=self.db, usuario=self.admin1)
        with self.assertRaises(HTTPException) as error:
            emitir_documento_financiero(duplicado.id, db=self.db, usuario=self.admin1)
        self.assertEqual(error.exception.status_code, 409)

        resumen = resumen_documentos_financieros(date.today().year, date.today().month, db=self.db, usuario=self.admin1)
        self.assertEqual(resumen["documentos_emitidos"], 1)
        self.assertEqual(resumen["ingresos_total"], 10.0)
        self.assertEqual(resumen["ingresos_igv"], 1.53)
        self.assertEqual(resumen["movimientos_documentados"], 1)
        self.assertEqual(resumen["movimientos_pendientes"], 0)

    def test_documento_no_admite_origen_de_otro_gimnasio(self):
        producto = models.Producto(gimnasio_id=self.gym2.id, nombre="Ajeno", precio_venta=15, stock=1)
        venta = models.Venta(gimnasio_id=self.gym2.id, total=15, metodo_pago=models.MetodoPago.EFECTIVO)
        self.db.add_all([producto, venta]); self.db.commit()
        with self.assertRaises(HTTPException) as error:
            crear_documento_financiero(
                schemas.DocumentoFinancieroCreate(direccion="ingreso", tipo="recibo", fuente_tipo="venta", fuente_id=venta.id),
                idempotency_key="documento-ajeno-prueba-0001", db=self.db, usuario=self.admin1,
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_venta_usa_precio_del_servidor(self):
        producto = models.Producto(
            gimnasio_id=self.gym1.id,
            nombre="Bebida",
            precio_venta=12.0,
            stock=5,
        )
        self.db.add(producto)
        self.db.commit()
        venta = crear_venta(
            schemas.VentaCreate(
                metodo_pago=models.MetodoPago.EFECTIVO,
                detalles=[schemas.DetalleVentaCreate(producto_id=producto.id, cantidad=2, precio_unitario=0.01)],
            ),
            db=self.db,
            usuario_actual=self.admin1,
        )
        self.assertEqual(venta.total, 24.0)
        self.assertEqual(venta.detalles[0].precio_unitario, 12.0)
        self.assertEqual(producto.stock, 3)

    def test_suscripcion_vencida_bloquea_acceso(self):
        suscripcion = models.SuscripcionSaas(
            gimnasio_id=self.gym1.id,
            plan_id=self.plan_saas.id,
            estado="activa",
            fecha_inicio=date.today() - timedelta(days=40),
            fecha_fin_periodo=date.today() - timedelta(days=6),
            fecha_fin_gracia=date.today() - timedelta(days=1),
            dias_gracia=5,
        )
        self.db.add(suscripcion)
        self.db.commit()
        self.assertEqual(_estado_suscripcion(suscripcion), "vencida")
        self.assertFalse(auth._suscripcion_permite_acceso(self.db, self.gym1.id))

    def test_renovacion_saas_registra_pago_y_periodo(self):
        resultado = renovar_suscripcion_saas(
            self.gym1.id,
            schemas.RenovacionSaasRequest(
                plan_id=self.plan_saas.id,
                meses=1,
                monto=49,
                metodo_pago="transferencia",
                referencia="TEST-001",
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.assertEqual(resultado["estado"], "activa")
        self.assertEqual(len(resultado["pagos"]), 1)
        self.assertEqual(resultado["pagos"][0].monto, 49)
        self.assertTrue(auth._suscripcion_permite_acceso(self.db, self.gym1.id))

    def test_anular_pago_conserva_evidencia_y_recalcula_saldo(self):
        plan = models.Membresia(gimnasio_id=self.gym1.id, nombre="Mensual", precio=50, duracion_dias=30)
        self.db.add(plan)
        self.db.flush()
        asignacion = models.ClienteMembresia(
            cliente_id=self.cliente1.id,
            membresia_id=plan.id,
            monto_pagado=20,
        )
        self.db.add(asignacion)
        self.db.flush()
        pago = models.PagoMembresia(
            cliente_membresia_id=asignacion.id,
            monto=20,
            metodo_pago="efectivo",
        )
        self.db.add(pago)
        self.db.commit()

        pago_id = pago.id
        asignacion_id = asignacion.id
        eliminar_pago_membresia(
            pago_id,
            schemas.AnulacionOperacionRequest(motivo="Registro duplicado"),
            db=self.db,
            usuario=self.admin1,
        )

        pago_anulado = self.db.query(models.PagoMembresia).filter_by(id=pago_id).one()
        self.assertTrue(pago_anulado.anulada)
        self.assertEqual(pago_anulado.motivo_anulacion, "Registro duplicado")
        self.assertEqual(pago_anulado.anulada_por_id, self.admin1.id)
        asignacion_actual = self.db.query(models.ClienteMembresia).filter_by(id=asignacion_id).first()
        self.assertIsNotNone(asignacion_actual)
        self.assertEqual(asignacion_actual.monto_pagado, 0)

    def test_anular_venta_restaura_stock_sin_borrar_historial(self):
        producto = models.Producto(gimnasio_id=self.gym1.id, nombre="Bebida", precio_venta=8, stock=3)
        self.db.add(producto)
        self.db.commit()
        venta = crear_venta(
            schemas.VentaCreate(
                metodo_pago="efectivo",
                detalles=[schemas.DetalleVentaCreate(producto_id=producto.id, cantidad=2, precio_unitario=8)],
            ),
            db=self.db,
            usuario_actual=self.admin1,
        )
        self.assertEqual(producto.stock, 1)

        eliminar_venta(
            venta.id,
            schemas.AnulacionOperacionRequest(motivo="Venta ingresada dos veces"),
            db=self.db,
            usuario=self.admin1,
        )

        self.db.refresh(venta)
        self.db.refresh(producto)
        self.assertTrue(venta.anulada)
        self.assertEqual(producto.stock, 3)
        self.assertEqual(len(venta.detalles), 1)

    def test_anular_compra_exige_stock_disponible_y_conserva_registro(self):
        producto = models.Producto(gimnasio_id=self.gym1.id, nombre="Proteina", precio_venta=90, stock=0)
        self.db.add(producto)
        self.db.commit()
        compra = registrar_compra(
            schemas.CompraCreate(producto_id=producto.id, cantidad=4, costo_unitario=50),
            db=self.db,
            usuario_actual=self.admin1,
        )

        eliminar_compra(
            compra.id,
            schemas.AnulacionOperacionRequest(motivo="Factura de proveedor incorrecta"),
            db=self.db,
            usuario=self.admin1,
        )

        self.db.refresh(compra)
        self.db.refresh(producto)
        self.assertTrue(compra.anulada)
        self.assertEqual(producto.stock, 0)

    def test_egresos_solo_aceptan_efectivo_o_cuenta(self):
        for esquema, datos in (
            (schemas.CompraCreate, {"producto_id": 1, "cantidad": 1, "costo_unitario": 5}),
            (schemas.PagoPlanillaCreate, {"empleado_id": 1, "tipo": "staff", "anio": 2026, "mes": 7, "monto_total": 5}),
            (schemas.PagoServicioCreate, {"cargo_id": 1, "monto": 5}),
            (schemas.GastoCreate, {"categoria": "otros", "monto": 5}),
        ):
            self.assertEqual(esquema(**datos, metodo_pago="cuenta").metodo_pago, "cuenta")
            with self.assertRaises(ValueError):
                esquema(**datos, metodo_pago="tarjeta")

    def test_compra_guarda_origen_y_gimnasio(self):
        producto = models.Producto(
            gimnasio_id=self.gym1.id,
            nombre="Proteina",
            precio_venta=20,
            stock=2,
        )
        self.db.add(producto)
        self.db.commit()

        compra = registrar_compra(
            schemas.CompraCreate(
                producto_id=producto.id,
                cantidad=3,
                costo_unitario=8,
                metodo_pago="cuenta",
            ),
            db=self.db,
            usuario_actual=self.admin1,
        )

        self.assertEqual(compra.metodo_pago, "cuenta")
        self.assertEqual(compra.gimnasio_id, self.gym1.id)
        self.assertEqual(producto.stock, 5)

    def test_paquete_de_rutina_se_copia_al_cliente(self):
        paquete = crear_paquete_rutina(
            schemas.PaqueteRutinaCreate(
                nombre="Basico - bajar de peso",
                nivel="basico",
                objetivo="bajar_peso",
                etapa="inicio",
                dias=[schemas.PaqueteRutinaDiaCreate(
                    nombre="Dia 1",
                    ejercicios=[schemas.PaqueteRutinaEjercicioCreate(
                        nombre="Sentadilla",
                        series=3,
                        repeticiones="12",
                    )],
                )],
            ),
            db=self.db,
            usuario=self.admin1,
        )
        rutina = asignar_paquete_rutina(
            paquete.id,
            schemas.AsignarPaqueteRutina(cliente_id=self.cliente1.id),
            db=self.db,
            usuario=self.admin1,
        )

        self.assertEqual(paquete.gimnasio_id, self.gym1.id)
        self.assertEqual(rutina.cliente_id, self.cliente1.id)
        self.assertEqual(rutina.dias[0].ejercicios[0].nombre, "Sentadilla")
        paquete.dias[0].ejercicios[0].nombre = "Modificado"
        self.assertEqual(rutina.dias[0].ejercicios[0].nombre, "Sentadilla")

    def test_equipamiento_nuevo_genera_paquete_una_sola_vez(self):
        self.gym1.equipamiento_disponible = "saco_boxeo"
        self.db.commit()

        primera = generar_rutinas_por_equipamiento(db=self.db, usuario=self.admin1)
        segunda = generar_rutinas_por_equipamiento(db=self.db, usuario=self.admin1)

        self.assertEqual(primera["paquetes_creados"], 1)
        self.assertEqual(segunda["paquetes_creados"], 0)
        paquete = self.db.query(models.PaqueteRutina).filter_by(
            gimnasio_id=self.gym1.id,
            equipamiento_origen="saco_boxeo",
        ).one()
        self.assertTrue(paquete.dias[0].ejercicios)
        self.assertTrue(all(e.tipo_ejercicio.equipamiento == "saco_boxeo" for e in paquete.dias[0].ejercicios))

    def test_equipamiento_personalizado_es_privado_y_admite_ejercicios(self):
        respuesta = crear_equipamiento_personalizado(
            schemas.EquipamientoPersonalizadoCreate(
                nombre="Maquina exclusiva Uno",
                categoria="Maquinas especiales",
                grupos_musculares=["Gluteos", "Piernas"],
            ),
            db=self.db,
            usuario=self.admin1,
        )
        codigo = respuesta["creado"]["codigo"]

        self.assertIn(codigo, respuesta["seleccionados"])
        self.assertTrue(respuesta["creado"]["personalizado"])
        catalogo_otro_gym = obtener_equipamiento_gimnasio(db=self.db, usuario=models.Usuario(gimnasio_id=self.gym2.id))
        self.assertNotIn(codigo, {item["codigo"] for item in catalogo_otro_gym["catalogo"]})

        ejercicio = crear_tipo_ejercicio(
            schemas.TipoEjercicioCreate(
                nombre="Patada en maquina exclusiva",
                grupo_muscular="Gluteos",
                equipamiento=codigo,
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.assertEqual(ejercicio.gimnasio_id, self.gym1.id)
        self.assertEqual(ejercicio.equipamiento, codigo)

    def test_asignar_paquete_adapta_ejercicio_a_variante_sin_equipo(self):
        original = models.TipoEjercicio(
            gimnasio_id=self.gym1.id,
            nombre="Press de pecho en maquina",
            grupo_muscular="Pecho",
            categoria="fuerza",
            equipamiento="press_pecho_maquina",
            nivel="principiante",
            objetivo="tonificar",
            activo=True,
        )
        alternativa = models.TipoEjercicio(
            gimnasio_id=self.gym1.id,
            nombre="Flexiones de pecho",
            grupo_muscular="Pecho",
            categoria="fuerza",
            equipamiento="sin_equipo",
            nivel="principiante",
            objetivo="tonificar",
            activo=True,
        )
        self.db.add_all([original, alternativa])
        self.db.flush()
        paquete = models.PaqueteRutina(
            gimnasio_id=self.gym1.id,
            nombre="Pecho adaptable",
            dias=[models.PaqueteRutinaDia(
                nombre="Dia 1",
                ejercicios=[models.PaqueteRutinaEjercicio(
                    tipo_ejercicio_id=original.id,
                    nombre=original.nombre,
                    series=3,
                    repeticiones="12",
                )],
            )],
        )
        self.db.add(paquete)
        self.gym1.equipamiento_disponible = ""
        self.db.commit()

        rutina = asignar_paquete_rutina(
            paquete.id,
            schemas.AsignarPaqueteRutina(cliente_id=self.cliente1.id),
            db=self.db,
            usuario=self.admin1,
        )

        ejercicio_asignado = rutina.dias[0].ejercicios[0]
        self.assertEqual(ejercicio_asignado.tipo_ejercicio_id, alternativa.id)
        self.assertEqual(ejercicio_asignado.nombre, alternativa.nombre)
        self.assertIn(original.nombre, ejercicio_asignado.notas)
        self.assertEqual(paquete.dias[0].ejercicios[0].tipo_ejercicio_id, original.id)

    def test_todas_las_maquinas_tienen_ejercicios_generables(self):
        maquinas = {
            codigo for codigo, _nombre, categoria in EQUIPAMIENTO_GIMNASIO
            if categoria.startswith("Máquinas") or categoria == "Cardio"
        }

        self.assertFalse(maquinas - set(EJERCICIOS_GENERABLES_EQUIPO))

    def test_renombrar_catalogo_actualiza_rutinas_y_paquetes_enlazados(self):
        catalogo = models.TipoEjercicio(
            gimnasio_id=self.gym1.id,
            nombre="Sentadilla antigua",
            activo=True,
        )
        self.db.add(catalogo)
        self.db.flush()
        rutina = models.Rutina(
            gimnasio_id=self.gym1.id,
            cliente_id=self.cliente1.id,
            nombre="Rutina enlazada",
            dias=[models.RutinaDia(
                nombre="Dia 1",
                ejercicios=[
                    models.RutinaEjercicio(
                        tipo_ejercicio_id=catalogo.id,
                        nombre="Sentadilla antigua",
                    ),
                    models.RutinaEjercicio(nombre="Ejercicio libre"),
                ],
            )],
        )
        paquete = models.PaqueteRutina(
            gimnasio_id=self.gym1.id,
            nombre="Paquete enlazado",
            dias=[models.PaqueteRutinaDia(
                nombre="Dia 1",
                ejercicios=[models.PaqueteRutinaEjercicio(
                    tipo_ejercicio_id=catalogo.id,
                    nombre="Sentadilla antigua",
                )],
            )],
        )
        self.db.add_all([rutina, paquete])
        self.db.commit()

        actualizar_tipo_ejercicio(
            catalogo.id,
            schemas.TipoEjercicioUpdate(nombre="Sentadilla goblet"),
            db=self.db,
            usuario=self.admin1,
        )

        self.db.refresh(rutina.dias[0].ejercicios[0])
        self.db.refresh(rutina.dias[0].ejercicios[1])
        self.db.refresh(paquete.dias[0].ejercicios[0])
        self.assertEqual(rutina.dias[0].ejercicios[0].nombre, "Sentadilla goblet")
        self.assertEqual(paquete.dias[0].ejercicios[0].nombre, "Sentadilla goblet")
        self.assertEqual(rutina.dias[0].ejercicios[1].nombre, "Ejercicio libre")

    def test_gimnasio_nuevo_recibe_paquetes_de_rutinas_enlazados(self):
        catalogo = models.TipoEjercicio(
            gimnasio_id=self.gym1.id,
            nombre="Plancha de prueba",
            activo=True,
        )
        self.db.add(catalogo)
        self.db.flush()
        paquete = models.PaqueteRutina(
            gimnasio_id=self.gym1.id,
            nombre="Paquete inicial de prueba",
            nivel="basico",
            objetivo="inicio",
            genero_recomendado="todos",
            dias=[models.PaqueteRutinaDia(
                nombre="Dia 1",
                ejercicios=[models.PaqueteRutinaEjercicio(
                    tipo_ejercicio_id=catalogo.id,
                    nombre=catalogo.nombre,
                    series=3,
                    repeticiones="12",
                )],
            )],
        )
        gimnasio_nuevo = models.Gimnasio(nombre="Gym Nuevo", slug="gym-nuevo", activo=True)
        self.db.add_all([paquete, gimnasio_nuevo])
        self.db.commit()

        _sembrar_datos_gimnasio_nuevo(self.db, gimnasio_nuevo.id)
        paquete_nuevo = self.db.query(models.PaqueteRutina).filter_by(
            gimnasio_id=gimnasio_nuevo.id,
            nombre=paquete.nombre,
        ).one()

        ejercicio_nuevo = paquete_nuevo.dias[0].ejercicios[0]
        self.assertEqual(ejercicio_nuevo.nombre, catalogo.nombre)
        self.assertNotEqual(ejercicio_nuevo.tipo_ejercicio_id, catalogo.id)
        self.assertEqual(ejercicio_nuevo.tipo_ejercicio.gimnasio_id, gimnasio_nuevo.id)

    def test_recomendador_usa_perfil_y_obliga_guardar_paquete_nuevo(self):
        self.cliente1.genero = "Femenino"
        self.cliente1.fecha_nacimiento = date(1995, 1, 1)
        ejercicio = models.TipoEjercicio(
            gimnasio_id=self.gym1.id,
            nombre="Sentadilla recomendada",
            activo=True,
        )
        self.db.add(ejercicio)
        self.db.flush()
        paquete = models.PaqueteRutina(
            gimnasio_id=self.gym1.id,
            nombre="Bajar peso femenino base",
            nivel="basico",
            objetivo="bajar_peso",
            genero_recomendado="femenino",
            dias=[models.PaqueteRutinaDia(
                nombre="Dia 1",
                ejercicios=[models.PaqueteRutinaEjercicio(
                    tipo_ejercicio_id=ejercicio.id,
                    nombre=ejercicio.nombre,
                    series=3,
                    repeticiones="12",
                )],
            )],
        )
        self.db.add_all([
            paquete,
            models.Medida(
                gimnasio_id=self.gym1.id,
                cliente_id=self.cliente1.id,
                fecha=date.today(),
                peso_kg=80,
                estatura_cm=160,
                peso_objetivo_kg=65,
            ),
        ])
        self.db.commit()

        recomendacion = recomendar_paquetes_rutina_cliente(
            self.cliente1.id,
            objetivo=None,
            nivel=None,
            db=self.db,
            usuario=self.admin1,
        )
        self.assertEqual(recomendacion["perfil"]["objetivo_sugerido"], "bajar_peso")
        self.assertEqual(recomendacion["perfil"]["genero"], "femenino")
        self.assertEqual(recomendacion["opciones"][0]["paquete"].id, paquete.id)
        schemas.RecomendacionRutina.model_validate(recomendacion)

        paquete_editado = schemas.PaqueteRutinaCreate(
            nombre="Plan personalizado de Ana",
            nivel="basico",
            objetivo="bajar_peso",
            genero_recomendado="femenino",
            dias=[schemas.PaqueteRutinaDiaCreate(
                nombre="Dia personalizado",
                ejercicios=[schemas.PaqueteRutinaEjercicioCreate(
                    tipo_ejercicio_id=ejercicio.id,
                    nombre=ejercicio.nombre,
                    series=4,
                    repeticiones="10",
                )],
            )],
        )
        guardado = guardar_recomendacion_rutina(
            schemas.GuardarRecomendacionRutinaRequest(
                cliente_id=self.cliente1.id,
                paquete_origen_id=paquete.id,
                paquete=paquete_editado,
            ),
            db=self.db,
            usuario=self.admin1,
        )
        self.assertEqual(guardado["paquete"].nombre, "Plan personalizado de Ana")
        self.assertEqual(guardado["rutina"].cliente_id, self.cliente1.id)
        self.assertEqual(guardado["rutina"].dias[0].ejercicios[0].series, 4)
        schemas.GuardarRecomendacionRutinaResponse.model_validate(guardado)

        with self.assertRaises(HTTPException) as error:
            guardar_recomendacion_rutina(
                schemas.GuardarRecomendacionRutinaRequest(
                    cliente_id=self.cliente1.id,
                    paquete_origen_id=paquete.id,
                    paquete=paquete_editado.model_copy(update={"nombre": paquete.nombre}),
                ),
                db=self.db,
                usuario=self.admin1,
            )
        self.assertEqual(error.exception.status_code, 400)

    def test_otro_ingreso_y_reserva_quedan_en_el_gimnasio(self):
        concepto = crear_concepto_ingreso(
            schemas.ConceptoOtroIngresoCreate(
                nombre="Alquiler de sala de baile",
                monto_sugerido=80,
                mostrar_agenda=True,
                sala_sugerida="Sala B",
            ),
            db=self.db,
            usuario=self.admin1,
        )
        ingreso = registrar_otro_ingreso(
            schemas.OtroIngresoCreate(
                concepto_id=concepto.id,
                fecha=datetime(2026, 7, 13, 12, 0),
                monto=80,
                metodo_pago="efectivo",
            ),
            db=self.db,
            usuario=self.admin1,
        )
        reserva = crear_reserva_sala(
            schemas.ReservaSalaCreate(
                concepto_ingreso_id=concepto.id,
                nombre_reserva="Ensayo externo",
                responsable="Academia Test",
                sala="Sala B",
                fecha=date(2026, 7, 13),
                hora_inicio=datetime(2026, 7, 13, 18, 0),
                hora_fin=datetime(2026, 7, 13, 20, 0),
            ),
            db=self.db,
            usuario=self.admin1,
        )

        self.assertEqual(concepto.gimnasio_id, self.gym1.id)
        self.assertEqual(ingreso.gimnasio_id, self.gym1.id)
        self.assertEqual(reserva.gimnasio_id, self.gym1.id)
        self.assertEqual(reserva.concepto_ingreso_id, concepto.id)
        with self.assertRaises(HTTPException) as conflicto:
            crear_reserva_sala(
                schemas.ReservaSalaCreate(
                    concepto_ingreso_id=concepto.id,
                    nombre_reserva="Reserva superpuesta",
                    sala="Sala B",
                    fecha=date(2026, 7, 13),
                    hora_inicio=datetime(2026, 7, 13, 19, 0),
                    hora_fin=datetime(2026, 7, 13, 21, 0),
                ),
                db=self.db,
                usuario=self.admin1,
            )
        self.assertEqual(conflicto.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
