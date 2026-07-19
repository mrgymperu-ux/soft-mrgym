# Operación segura de Soft-Gym

## Antes de habilitar producción

1. Usar un servicio web que no entre en reposo y configurar `ENVIRONMENT=production`.
2. Configurar `SECRET_KEY`, `DATABASE_URL`, `APP_BASE_URL`, `RESEND_API_KEY` y `EMAIL_FROM` como secretos.
3. En **Configuracion > Preparacion para produccion**, enviar el correo de prueba. Solo despues de recibirlo, cambiar `REQUIRE_EMAIL_VERIFICATION=true`.
4. En GitHub Actions, crear el secreto `PRODUCTION_DATABASE_URL` con acceso exclusivamente a la base de producción.
5. Ejecutar manualmente el flujo **Respaldo diario de producción** y descargar el artefacto generado.
6. Configurar un monitor externo sobre `GET /health/ready`; alertar cuando no responda 200.

## Respaldo y restauración

- El respaldo diario se ejecuta a las 03:17 de Lima y se conserva 30 días.
- Cada archivo incluye un manifiesto SHA-256 y recuento de tablas/filas.
- Una vez al mes debe restaurarse el último respaldo en una base PostgreSQL vacía y separada.
- Nunca usar la base de producción como destino de una prueba de restauración.

```powershell
$env:RESTORE_DATABASE_URL="postgresql://...base-vacia..."
python scripts/restore_database.py backups/archivo.json.gz --confirm RESTORE_EMPTY_DATABASE
```

## Incidentes financieros

- No borrar filas directamente en PostgreSQL.
- Las ventas, compras y pagos de membresía se corrigen desde la interfaz mediante **Anular** y con motivo obligatorio.
- Ante diferencias de stock o caja, conservar evidencia, registrar el incidente y realizar un contramovimiento.
- Antes de cada despliegue con migraciones, comprobar que el último respaldo diario terminó correctamente.

## Operacion diaria de caja

1. Abrir **Sistema > Caja** al comenzar el turno y registrar el efectivo contado.
2. Registrar cada cobro o egreso desde su modulo; la caja se actualiza desde esos documentos, no mediante ajustes manuales.
3. Al finalizar, contar el efectivo y cerrar la caja. Toda diferencia mayor a un centimo exige una explicacion.
4. No editar documentos de un turno ya cerrado para cuadrar una diferencia: anular con motivo y registrar la operacion correcta.

## Contingencia del counter

Si el sistema no está disponible, registrar temporalmente en una hoja numerada: hora, alumno, operación, monto, método y responsable. Al restablecerse, cargar las operaciones indicando en notas el número de contingencia y conciliarlas antes del cierre de caja.
