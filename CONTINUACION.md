# Contexto: Continuación de desarrollo — Soft-Gym

Estoy desarrollando **Soft-Gym**, un sistema de gestión de gimnasio, en `D:\Soft-MrGym` (Windows, acceso vía MCP filesystem). Ya tengo mucho avanzado en una conversación anterior con Claude que se hizo demasiado larga. Continúa el trabajo desde aquí.

## Stack y estructura
- **Backend**: FastAPI + SQLAlchemy + SQLite (`D:\Soft-MrGym\backend\`) — `main.py` (rutas), `models.py`, `schemas.py`, `auth.py`, `pdf_generator.py` (reportlab), `database.py`.
- **Frontends** (HTML/CSS/JS vanilla, sin framework): `frontend-staff\` (panel de administración/recepción), `frontend-alumno\` (portal del alumno), `frontend-profesor\` (Zona de Profesores).
- Se corre todo con `D:\Soft-MrGym\start.bat` (backend en :8000 con `uvicorn --reload`, frontend-staff en :3000, etc). El backend se reinicia solo al detectar cambios en archivos `.py`.
- Tengo Claude en Chrome conectado y MCP filesystem apuntando a `D:\Soft-MrGym`.
- Base real de producción: **~1664 clientes** (mayoría importados de un sistema anterior, sin `ClienteMembresia` propiamente asignada — ver nota importante más abajo).

## Ya implementado (sesiones anteriores, no repetir)
- Sistema de temas, Reportes (Clientes/Ventas/Productos) con export CSV, Planilla Staff/Profesores, Agenda semanal, Boletas A5, Catálogo de Puestos editable, permisos admin en ventas, campos de Cliente (género/fechas/% asistencia calculado), sidebar acordeón, flujo "Nuevo Cliente → Asignar Membresía → Cobro y Contrato" (`frontend-staff/js/flujo-cliente.js`), Configuración → Modelo de Contrato.
- **Corregido bug de hora (5h de adelanto)**: todo el backend usaba `datetime.utcnow()` pero el servidor corre en hora de Perú; se cambió a `datetime.now()` en `main.py` y `models.py` (excepto la expiración de JWT en `auth.py`, que es correcto dejarla en UTC/epoch).
- **Módulo Pagos completo** (`pagos.html`, sidebar → Principal): 3 pestañas.
  - **Staff / Profesores**: ahora con **búsqueda inteligente** (campo de texto + dropdown, no `<select>`) para elegir trabajador/profesor, ver su detalle del mes/periodo (sueldo, comisiones, clases, pagado, deuda) y registrar pagos (reusa `/pagos-planilla/`).
  - **Servicios**: catálogo editable de servicios/deudas (`Servicio`, `CargoServicio`, `PagoServicio` en `models.py`), con cargos por periodo, pagos parciales, y deuda total visible. Endpoints `/servicios/`, `/cargos-servicio/`, `/pagos-servicio/`. Conectado a `/egresos/` (categoría `pago_servicio`).
  - Zona de permisos nueva: `"pagos"` (en `auth.py` `ZONAS_DISPONIBLES` y en `personal.js`).
- **Nutrición con asignación automática**:
  - Catálogo de **Alimentos** ampliado a **82 items** peruanos/Lima (proteínas, verduras, frutas, carbohidratos, grasas, bebidas — incluye toda la lista que pasó el gimnasio). Sembrado vía funciones idempotentes en `main.py` (`_sembrar_alimentos_expansion_lima`, `_sembrar_alimentos_expansion_lima_2`), corren en cada arranque sin duplicar.
  - Catálogo de **Paquetes** (desayuno/almuerzo/cena × 4 propósitos × 4 porciones × 2 variantes de receta) = **96 paquetes**. Sembrado vía `_sembrar_paquetes_nutricion_iniciales` + `_sembrar_paquetes_nutricion_variantes`.
  - En Nutrición → Paquetes: **ya NO existe "aplicar a cliente"**; solo Crear, **Editar** (✏️) y **Duplicar** (📋, prellena con "(copia)" para ajustar y guardar como nuevo).
  - **Cálculo automático**: `_computar_perfil_nutricional()` calcula BMR (Mifflin-St Jeor, distinto hombre/mujer), TDEE (actividad moderada fija), IMC → determina propósito (bajar_peso/mantenimiento/definición/ganar_masa) y reparte calorías desayuno 28% / almuerzo 42% / cena 30%, eligiendo el paquete más cercano en calorías.
  - **Disparo automático**: al registrar/editar una `Medida` (peso/estatura) de un cliente con `Membresia.incluye_nutricion=True` en su membresía vigente, se regenera su plan solo (`_intentar_generar_plan_automatico`, no rompe si faltan datos).
  - Botón manual `POST /nutricion/generar-automatico/{cliente_id}` (en la ficha del cliente) y botón masivo `POST /nutricion/generar-automatico-masivo` (solo admin, en Nutrición → Planes).
  - En la ficha del cliente (pestaña Plan Nutrición): botón **"✏️ Adaptar"** por plan → editor de alimentos/cantidades (autocalcula kcal) → al guardar **crea un plan nuevo** (`POST /nutricion/`) y desactiva el anterior (`PUT /nutricion/{id} {activo:false}`), sin borrar histórico.
  - ⚠️ **Importante**: de los clientes reales revisados, **ninguno tenía `fecha_nacimiento` cargada** — sin eso el cálculo automático no puede correr. Antes de usar el botón masivo, conviene completar esa fecha al menos para los inscritos en nutrición.
- **Sidebar reorganizado**:
  - Principal: Panel de Control (antes "Panel"), Clientes (subido desde Gestión), Pagos, Asistencias.
  - Sistema: Resumen, Ingresos, Egresos (bajados desde Principal), Reportes, Metas y Comisiones, Configuración.
- **Filtro "Activos" de Clientes corregido**: antes solo miraba `Cliente.activo` (no eliminado). Ahora exige membresía vigente usando `Cliente.fecha_vencimiento >= hoy` (NO se usa JOIN a `ClienteMembresia` porque los clientes importados históricamente nunca tienen filas ahí; `fecha_vencimiento` se mantiene sincronizado en ambos casos — legacy y asignación desde la app). Con esto pasó de mostrar 1664 a **84 clientes realmente vigentes**. Se rellenó también el fallback de columna Vencimiento/Plan con los campos legacy del Cliente cuando no hay `ClienteMembresia`.
  - Pendiente de decidir: el filtro "Activos" de **Reportes → Clientes** (`_query_reporte_clientes`) se dejó **sin tocar** (sigue siendo solo `Cliente.activo`) — preguntar si debe unificarse con el mismo criterio.

## Cosas importantes para trabajar bien en este proyecto
- **`bash_tool` (contenedor sandbox) NO tiene acceso a `D:\`** — para todo archivo del proyecto usa siempre las herramientas `filesystem:*` (MCP): `filesystem:read_file`, `filesystem:write_file`, `filesystem:edit_file`, `filesystem:directory_tree`, `filesystem:search_files`, `filesystem:get_file_info`. Nunca `bash_tool`/`view`/`str_replace`/`create_file` del contenedor para estos archivos (esas SÍ sirven para verificar sintaxis en el sandbox: copiar el texto a un `.py` local y correr `python3 -m py_compile`).
- **`filesystem:edit_file` requiere que `oldText` sea único en el archivo** — si hay bloques repetidos (como varias funciones `_sembrar_*` con el mismo patrón `if agregados: db.commit() ... db.close()`), incluye suficiente contexto único (la línea siguiente, ej. el `def` de la función que sigue) para no reemplazar el lugar equivocado. **Ya pasó dos veces en esta sesión** que el reemplazo se comió accidentalmente la línea `def nombre_funcion():` de la función siguiente — siempre verificar con `python3 -m py_compile` después de cada edit_file en `main.py`.
- `main.py` es muy grande (>190KB): `filesystem:read_file` completo no cabe en el contexto y lo guarda en un `.json` en `/mnt/user-data/tool_results/`; para revisarlo usa `bash_tool` + `grep`/`sed` sobre ese `.json` extraído a texto plano (`python3 -c "import json; ..."`).
- **`create_file` a veces falla con un error falso** ("path: Field required") — si pasa, usa `filesystem:write_file` en su lugar (sobrescribe sin problema).
- El backend usa `uvicorn --reload`: tras editar `.py` del backend, espera ~2-3 segundos antes de probar (se reinicia solo). Si algo no responde, pedir al usuario una captura de la ventana negra "Soft-Gym Backend" para ver el traceback real.
- El navegador cachea agresivamente HTML y `js/*.js` — **usar `Ctrl+Shift+R`** (recarga dura) después de cualquier cambio de frontend, tanto si lo prueba el usuario como si lo verifica Claude en Chrome (`computer` con `action:"key", text:"ctrl+shift+r"`). Ya pasó en esta sesión que un cambio parecía "no aplicado" y solo era caché.
- Para verificar cambios, usar Claude en Chrome: `javascript_tool` (ejecutar JS/fetch directo contra `apiFetch(...)` en la pestaña real) es más confiable y rápido que capturas de pantalla para validar datos; `read_console_messages` con `onlyErrors:true` para chequear errores JS después de cada cambio.
- **Nunca dejar datos de prueba en la base real**: si hace falta crear un cliente/medida/pago de prueba para verificar un flujo end-to-end, limpiarlo inmediatamente después (soft-delete de Cliente vía `DELETE /clientes/{id}`, hard-delete de Medida/Pago vía sus endpoints DELETE). Esta sesión lo hizo varias veces (ej. cliente "ZZ_PRUEBA_BORRAR").
- Todo el copy es en español, sin tildes en el código (variables/comentarios en el backend), pero SÍ con tildes en texto visible para el usuario en el frontend.
- Sigue el patrón de diseño ya establecido: `.form-row`/`.form-group` para formularios, paletas de tema vía CSS variables (`--color-primario`, `--color-blanco`, `--color-fondo`, etc. — nunca colores fijos), componentes compartidos inyectados por JS (`flujo-cliente.js`, `personal.js`), modales con `.modal`/`.modal-content`/`.modal-header` + `classList.add("active")`, y funciones seed idempotentes (`_sembrar_x_iniciales` revisa tabla vacía; `_sembrar_x_expansion` revisa por nombre exacto) para poder ampliar catálogos sin duplicar en cada reinicio.

## Empieza preguntando qué sigue
No hay una tarea pendiente puntual asignada todavía — pregunta al usuario qué quiere trabajar ahora (o revisa si mencionó algo al abrir esta conversación).
