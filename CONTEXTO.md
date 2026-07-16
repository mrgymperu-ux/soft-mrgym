<!--
╔══════════════════════════════════════════════════════════════════╗
║  INSTRUCCIÓN PARA CLAUDE (o cualquier IA que trabaje aquí):     ║
║                                                                  ║
║  1. LEE ESTE ARCHIVO COMPLETO antes de tocar cualquier código.   ║
║  2. Después de CADA cambio que hagas, ACTUALIZA este archivo     ║
║     reflejando lo que cambió: archivos nuevos, endpoints nuevos, ║
║     tablas nuevas, decisiones de diseño, bugs corregidos, etc.   ║
║  3. Si agregas un archivo, agrégalo al mapa.                     ║
║  4. Si modificas un endpoint, actualiza su entrada.              ║
║  5. Si cambias una tabla, actualiza el modelo.                   ║
║  6. Mantén las líneas de referencia (ej. "~línea 52") actuales.  ║
║                                                                  ║
║  Este archivo ES la memoria del proyecto. Sin él, cada sesión    ║
║  nueva gasta miles de tokens re-explorando 265KB de main.py.     ║
╚══════════════════════════════════════════════════════════════════╝
-->

# CONTEXTO — Soft-Gym
> Última actualización: 2026-07-16 (v7 - Endurecimiento inicial de autenticación)
> main.py: ~296KB, ~6530 líneas | models.py: ~1225 líneas | schemas.py: ~1470 líneas | auth.py: ~490 líneas

## Qué es
Sistema de gestión de gimnasio multi-tenant (SaaS). Un superadmin administra gimnasios; cada gimnasio tiene su staff, clientes, productos, etc. completamente aislados.

## Seguridad v7 (2026-07-16)
- Contraseñas de propietarios y staff: mínimo 10 caracteres, con letras y números.
- Registro público exige email válido (la verificación por correo queda para el siguiente bloque).
- Login de staff, alumnos y profesores limitado a 5 fallos por IP+identificador durante 15 minutos.
- Códigos de alumnos y profesores nuevos se guardan con bcrypt; los antiguos migran automáticamente al iniciar sesión correctamente.
- Los códigos de profesores ya no se devuelven en respuestas de la API.
- Primer acceso del alumno usa un token de configuración de 15 minutos que solo permite crear contraseña; luego se emite una sesión normal.
- En producción, el backend rechaza la clave JWT predeterminada cuando `ENVIRONMENT=production`.
- Suite: 25 pruebas (`tests/test_multitenant.py` + `tests/test_security.py`).
- Correo transaccional preparado para Resend mediante `RESEND_API_KEY` y `EMAIL_FROM`; sin esas variables no intenta enviar.
- Verificación de correo con token de un solo uso válido por 24 horas.
- Recuperación de contraseña con respuesta anti-enumeración y enlace válido por 30 minutos.
- Los tokens de correo se guardan únicamente como hash SHA-256 y quedan inutilizados después de consumirse.
- `sesion_version` permite cerrar todas las sesiones anteriores al restablecer contraseña o solicitar cierre global.
- Páginas nuevas: `recuperar.html`, `restablecer.html`, `verificar-email.html`.
- `REQUIRE_EMAIL_VERIFICATION=false` mantiene compatibilidad hasta configurar dominio/remitente; cambiar a `true` después de validar Resend.
- Invitaciones de trabajadores: enlace de un solo uso válido por 72 horas, revocable y asociado al gimnasio; el trabajador crea su propio usuario y contraseña.
- Si Resend no está configurado, el administrador puede copiar el enlace de invitación durante el piloto.
- Cada login de staff crea una sesión identificada (`jti`) con IP, navegador, creación y última actividad.
- API de sesiones: `GET /auth/sesiones`, `DELETE /auth/sesiones/{id}` y cierre global con invalidación de tokens anteriores.
- Cabeceras defensivas globales: CSP, anti-iframe, `nosniff`, referrer policy, permisos de cámara/ubicación y HSTS en HTTPS.
- Imágenes limitadas a 10 MB y 25 megapíxeles; Pillow verifica el contenido real y que coincida con JPEG/PNG/WEBP antes de guardar.
- Helper `escapeHTML` disponible en los tres portales; primera limpieza aplicada a inicio administrativo, rutina y perfil del alumno.
- Auditoría transversal: toda operación POST/PUT/PATCH/DELETE y toda descarga con adjunto registra gimnasio, usuario, acción, ruta, estado, IP, dispositivo y fecha sin guardar el cuerpo del formulario.
- Inicio de sesión exitoso registrado como `INICIO_SESION`.
- Consulta aislada por tenant en `GET /auditoria`, visible solo para administradores, con filtros y paginación.
- Nueva pantalla `auditoria.html` en la sección Sistema.
- Alembic incorporado (`alembic.ini`, `migrations/`) y ejecutado antes de Gunicorn en cada despliegue; revisión base + revisión de seguridad/medios persistentes.
- Logotipos e imágenes nuevas de ejercicios se almacenan como binarios optimizados en PostgreSQL, no en el disco efímero de Render.
- Respaldo portable verificable en `scripts/backup_database.py`, con recuento de tablas/filas y manifiesto SHA-256.
- Restauración segura en `scripts/restore_database.py`: exige variable separada, confirmación explícita y base destino vacía.
- Ensayo backup→restore realizado correctamente incluyendo un logotipo binario.
- `scripts/migrate_legacy_media.py` rescata medios `/uploads/` desde el contenedor activo; simula por defecto y revierte toda la operación si alguna descarga falla.

## URLs en producción
- **Panel Staff:** https://soft-mrgym.onrender.com/
- **Portal Alumno:** https://soft-mrgym.onrender.com/alumno/login.html?gym={slug}
- **Zona Profesores:** https://soft-mrgym.onrender.com/profesor/login.html?gym={slug}
- **API Docs:** https://soft-mrgym.onrender.com/docs
- **Repo GitHub:** https://github.com/mrgymperu-ux/soft-mrgym (privado)
- **Marca comercial oficial:** `Soft-Gym`. La URL de Render, el repositorio y la carpeta local conservan `soft-mrgym`/`Soft-MrGym` como identificadores técnicos heredados para no romper el despliegue existente.

## Stack
- **Backend:** FastAPI + SQLAlchemy + SQLite (dev) / PostgreSQL (prod, Supabase free permanente)
- **Frontends:** HTML/CSS/JS vanilla (sin framework), 3 portales separados
- **PDF:** reportlab (recibos, contratos, boletas)
- **QR:** qrcode==7.4.2 (genera QR SVG para compartir portal alumno)
- **Auth:** JWT (python-jose) + bcrypt==4.0.1 (passlib)
- **Hosting:** Render.com free tier (Docker: Python+nginx en un contenedor)
- **BD prod:** Supabase PostgreSQL (free permanente, 500MB, región São Paulo)
- **Dev:** Windows, `D:\Soft-MrGym - CODEX test`, uvicorn --reload en :8000, frontends con http.server

## Reglas técnicas para trabajar
- `bash_tool` NO accede a D:\ → usar siempre `filesystem:*` (MCP)
- `filesystem:edit_file` requiere `oldText` único → verificar antes de editar
- main.py NO cabe en contexto → leer por bloques con head/tail
- Tras editar .py, uvicorn recarga solo (~2-3s)
- El navegador cachea → Ctrl+Shift+R
- Para desplegar: `git add . && git commit -m "msg" && git push` → Render redesplega en ~3 min

---

## Mapa de archivos

```
D:\Soft-MrGym - CODEX test\
├── backend\
│   ├── __init__.py              (vacío, hace que sea un paquete)
│   ├── database.py              (Engine, SessionLocal, get_db; lee DATABASE_URL del env)
│   ├── models.py                (~1225 lín) Tablas ORM — ver sección "Modelo de datos"
│   ├── schemas.py               (~1470 lín) Pydantic schemas (Base/Create/Update/Response)
│   ├── auth.py                  (~490 lín) JWT, bcrypt, permisos y bloqueo SaaS
│   ├── main.py                  (~6500 lín) TODOS los endpoints — ver sección "Endpoints"
│   ├── pdf_generator.py         (~300 lín) Genera PDFs con reportlab
│   ├── requirements.txt         (fastapi, uvicorn, sqlalchemy, pydantic, jose, passlib, bcrypt==4.0.1, qrcode, etc.)
│   ├── .env                     (SECRET_KEY local, NO commitear)
│   └── uploads\                 (fotos de clientes, productos, ejercicios, logos)
│
├── frontend-staff\              Panel principal del gimnasio
│   ├── js\api.js                API_BASE_URL (localhost en dev, "" en prod via start.sh). Guarda gimnasio_slug en sessionStorage al login
│   ├── js\sidebar.js            Menú lateral en PC; header + navegación horizontal en móvil
│   ├── js\tema.js               Temas (lavanda, océano, etc.) y modo claro/oscuro
│   ├── js\flujo-cliente.js      Búsqueda inteligente + venta rápida + asignación membresía + cobro
│   ├── js\logo.js               Logo dinámico en sidebar
│   ├── js\personal.js           Lógica de empleados y puestos
│   ├── js\medidas-catalogo.js   Campos de medidas configurables
│   ├── css\styles.css           Único archivo CSS (sidebar + flujo-cliente + todo)
│   ├── styles.css               (¡OJO! hay otro en raíz de frontend-staff)
│   ├── login.html, registro.html, principal.html
│   ├── clientes.html            Ficha completa con pestañas: Datos, Membresías, Medidas, Rutinas, Progreso, Nutrición, Retos
│   ├── membresias.html, productos.html, ventas.html
│   ├── venta-rapida.html, asistencias.html, vencimientos.html
│   ├── entrenamientos.html, progreso.html
│   ├── nutricion.html, mi-nutricion.html, mi-rutina.html, mi-progreso.html
│   ├── usuarios-staff.html, usuarios-profesores.html
│   ├── planilla-staff.html, planilla-profesores.html, agenda.html
│   ├── pagos.html, ingresos.html, egresos.html
│   ├── movimientos.html, resumen.html
│   ├── metas.html, reportes.html
│   ├── configuracion.html       Datos gym, suscripción SaaS, logo, QR, moneda, comisiones, temas, cláusulas, medidas, contraseña
│   ├── gestion-medidas.html, retos.html
│   └── superadmin.html          Panel SaaS: gimnasios, planes, períodos, pagos, suspensión y renovación
│
├── frontend-alumno\             Portal del alumno (solo lectura)
│   ├── js\api.js                API_BASE, getSlug(), fetchInfoGym(), loginAlumno() envía slug
│   ├── login.html               Personaliza nombre del gym + PWA (manifest, SW, ícono)
│   ├── mi-perfil.html, mi-rutina.html
│   ├── mi-nutricion.html, mi-progreso.html, retos.html
│
├── frontend-profesor\           Zona de profesores
│   ├── js\api.js                API_BASE, getSlug(), fetchInfoGym(), loginProfesor() envía slug
│   ├── login.html               Personaliza nombre del gym + PWA
│   ├── agenda.html
│
├── deploy\                      Archivos de despliegue en nube
│   ├── nginx.conf               Proxy: / → staff, /alumno/ → alumno, /profesor/ → profesor, API (gym|gym-actual|auth|...) → :8000
│   ├── start.sh                 1 worker gunicorn + nginx, inyecta RENDER_EXTERNAL_URL en api.js
│   └── .env.example
│
├── Dockerfile                   Python 3.12-slim + nginx, todo en un contenedor
├── render.yaml                  Blueprint para Render.com (solo web service, BD en Supabase)
├── tests\
│   └── test_multitenant.py      Pruebas de aislamiento, configuración, permisos, cobros SaaS, ventas y corrección de pagos
├── .dockerignore, .gitignore
├── start.bat                    Desarrollo local (Windows)
├── DEPLOY.md                    Guía paso a paso para desplegar
├── CONTEXTO.md                  ← ESTE ARCHIVO
└── sql_app.db                   Base SQLite local (~1665 clientes reales, NO se sube)
```

---

## Modelo de datos (models.py)

### Tablas GLOBALES (sin gimnasio_id)
| Tabla | Descripción |
|-------|-------------|
| `planes_saas` | Catálogo de planes SaaS (Free, Pro). Campos: max_clientes, max_productos, max_rutinas, max_usuarios_staff, nutricion_habilitada, reportes_avanzados, dominio_propio |
| `gimnasios` | Cada tenant. Tiene plan_id, slug, logo_url, config (moneda, comisiones, tema, clausulas) |
| `configuracion` | Tabla legacy conservada por compatibilidad; la API operativa usa la configuración de cada `gimnasio` |

### Facturación SaaS de cada gimnasio
| Tabla | Descripción |
|-------|-------------|
| `suscripciones_saas` | Una por gimnasio. Plan, estado, inicio/fin de período, fin de gracia, auto-renovación, suspensión y notas |
| `pagos_saas` | Historial inmutable de cobros de la plataforma: monto, moneda, método, referencia, fecha y período cubierto |

### Tablas con gimnasio_id (25 tablas raíz)
| Tabla | Clave | Relaciones |
|-------|-------|-----------|
| `usuarios` | username + password_hash | → gimnasio, → empleado. Campos: rol (STAFF/PROFESOR), es_administrador, es_superadmin, puede_eliminar, puede_exportar, zonas_permitidas |
| `clientes` | nombre, apellidos, dni, etc. | → gimnasio. Campos: foto_url, genero, fecha_renovacion/vencimiento, membresia_texto (legacy) |
| `clientes_historicos` | importados de sistema anterior | num_carnet, migrado, cliente_nuevo_id |
| `membresias` | catálogo de tarifas | precio, duracion_dias/meses, incluye_nutricion, horarios, congelamiento |
| `cliente_membresias` | asignación cliente↔membresía | fecha_inicio/fin, monto_pagado, vendido_por_id, metodo_pago, fecha_pago_saldo |
| `pagos_membresia` | historial de pagos individuales | cliente_membresia_id, monto, metodo_pago, fecha_pago, registrado_por_id, notas |
| `productos` | inventario | precio_compra/venta, stock, stock_minimo, foto_url |
| `ventas` → `detalles_venta` | registro de ventas | total, metodo_pago, es_venta_rapida, costo_comision_gym |
| `compras` | reposición de stock | producto_id, cantidad, costo_unitario |
| `asistencias` | entrada/salida de clientes | cliente_id, fecha_hora_entrada/salida |
| `asistencias_empleado` | entrada/salida de staff | empleado_id |
| `progresos` | registro simple peso/medidas | cliente_id, fecha, peso_kg, grasa_pct |
| `medidas` | toma antropométrica completa | ~40 campos |
| `tipos_ejercicio` | catálogo de ejercicios | 76 precargados con categoria, equipamiento, nivel, genero, objetivo |
| `paquetes_rutina` → `paquete_rutina_dias` → `paquete_rutina_ejercicios` | plantillas reutilizables por perfil, nivel, objetivo y etapa |
| `rutinas` → `rutina_dias` → `rutina_ejercicios` | copia de un paquete asignada a un cliente |
| `alimentos` | catálogo nutricional | 82+ alimentos peruanos |
| `paquetes_nutricion` → `paquete_alimentos` | plantillas por propósito × tamaño |
| `planes_nutricion` → `comidas_plan` | plan asignado a cliente |
| `retos` | desafíos para alumnos |
| `empleados` | personal del gym | tipo (STAFF_FIJO/PROFESOR_DE_SALA), sueldo, tarifas |
| `puestos` | catálogo de cargos |
| `clases_dictadas` | agenda de clases | serie_id (recurrentes) |
| `pagos_planilla` | pagos a staff/profesores |
| `servicios` | catálogo (agua, luz, alquiler) |
| `cargos_servicio` → `pagos_servicio` | deudas/cobros recurrentes |
| `gastos` | egresos generales |
| `metas_mensuales` | meta de ventas por mes |
| `tramos_comision` | escalas de comisión |

---

## Helpers críticos (main.py, primeras ~120 líneas)

| Helper | Qué hace |
|--------|----------|
| `get_gid(usuario)` | Extrae gimnasio_id del usuario autenticado |
| `q(db, Model, usuario)` | Query filtrada por gimnasio_id |
| `_del_gym(db, Model, id, usuario)` | Busca una entidad raíz por id y gimnasio; responde 404 si pertenece a otro tenant |
| `_cliente_membresia_del_gym(...)` y helpers análogos | Protegen entidades hijas mediante JOIN con su entidad raíz y gimnasio |
| `_configuracion_del_gym(db, usuario)` | Devuelve el propio `Gimnasio` como configuración aislada del tenant |
| `_validar_limite_plan(db, usuario, recurso)` | Valida max del plan. HTTP 403 si excede. 0=ilimitado |
| `_validar_nutricion_habilitada(db, usuario)` | HTTP 403 si plan no incluye nutrición |
| `_detectar_delimitador(primera_linea)` | Auto-detecta separador CSV |
| `_migrar_columnas_nuevas()` | ALTER TABLE idempotente, SQLite + PostgreSQL |
| `_sembrar_gimnasio_default()` | Crea gym default, planes Free/Pro. Busca por id=1 O slug="mi-gimnasio" (PostgreSQL compatible) |

---

## Endpoints por módulo (main.py)

### PWA + Info Gym (~línea 1030)
- `GET /gym/{slug}` — Info pública del gym (nombre, logo, tema). Sin auth
- `POST /gym-actual/logo` — Sube logo del gym (solo admin). Guarda en uploads/logos/
- `GET /gym-actual/` — Info del gym del usuario autenticado (slug, nombre, logo, tema)
- `GET /gym/{slug}/manifest.json?portal=alumno|profesor|staff` — Manifest dinámico
- `GET /gym/{slug}/icon.svg` — Ícono SVG generado (inicial + color tema)
- `GET /gym/{slug}/sw.js` — Service Worker mínimo
- `GET /gym/{slug}/qr.svg?portal=alumno|profesor` — QR como SVG

### Auth (~línea 1190)
- `POST /auth/login` — Staff/profesor, devuelve JWT con gimnasio_id + gimnasio_slug
- `POST /auth/login-alumno` — DNI + código + slug → filtra por gimnasio_id
- `POST /auth/login-profesor` — DNI + código + slug → filtra por gimnasio_id
- `POST /auth/registro-gimnasio` — Registro público, crea gym (Free) + admin + seeders

### Usuarios (~línea 1230)
- CRUD `/usuarios/` — Solo admin crea. `_validar_limite_plan("usuarios_staff")`
- `GET /usuarios/me`

### Dashboard + Finanzas (~línea 1340)
- `GET /dashboard/stats`, `GET /ingresos/`, `GET /egresos/`, CRUD `/gastos/`

### Clientes (~línea 1750)
- `GET /clientes/listado-completo` — Con deuda, vencimiento, %asistencia
- CRUD `/clientes/`, importar CSV, subir foto, ficha rápida

### Clientes Históricos (~línea 2500)
- Búsqueda, importar CSV, reingresar a activo

### Reportes (~línea 2100)
- Clientes, ventas, productos (JSON + CSV)

### Membresías (~línea 2700)
- CRUD `/membresias/` — Catálogo de tarifas
- `POST /clientes/{id}/membresias` — Asignar membresía
- `PUT/DELETE /cliente-membresias/{id}` — Corrección administrativa (solo admin)
- `PUT /cliente-membresias/{id}/pagar-saldo` — Pago rápido de saldo pendiente (cualquier staff). Recibe {monto, metodo_pago}, suma al monto_pagado, limpia fecha_pago_saldo si saldo llega a 0
- `DELETE /pagos-membresia/{id}` — Corrección administrativa: elimina solo el pago individual y descuenta su monto de la membresía asignada
- PDFs: recibo y contrato
- Exportar/importar CSV

### Productos (~línea 3150)
- CRUD `/productos/`, fotos, compras (reposición stock)

### Ventas (~línea 3400)
- CRUD `/ventas/`, boleta PDF

### Asistencias (~línea 3600)
- Clientes y staff

### Entrenamientos (~línea 3700)
- Constructor de paquetes de rutinas por perfil y asignación de copias independientes a clientes

### Nutrición (~línea 3900)
- Alimentos, paquetes, planes, generación automática (BMR/TDEE/IMC)

### Personal (~línea 4300)
- Empleados, puestos, agenda, planilla staff/profesor, pagos

### Servicios/Deudas (~línea 4700)
- Servicios, cargos recurrentes, pagos parciales

### Medidas (~línea 4950)
- CRUD, ~40 campos, dispara plan nutrición automático

### Configuración (~línea 5030)
- GET/PUT moneda, comisiones, tema, clausulas

### Metas/Comisiones (~línea 5060)
- Metas mensuales, tramos, resumen comisiones

### SaaS / Super Admin (~línea 6045)
- CRUD planes y gimnasios, dashboard con estados e ingresos SaaS del mes, DELETE cascada
- `GET /saas/gimnasios/{id}/suscripcion` — detalle e historial de pagos
- `PUT /saas/gimnasios/{id}/suscripcion` — plan, estado, vencimiento, gracia y suspensión manual
- `POST /saas/gimnasios/{id}/suscripcion/renovar` — registra pago y extiende el período de 1 a 24 meses
- `GET /suscripcion/mi-plan` — el administrador del gimnasio consulta plan, vencimiento y últimos pagos

### Portal Alumno (~línea 5450)
- Solo lectura: perfil, rutina, nutrición, progreso, retos, subir foto

### Portal Profesor (~línea 2300)
- Mi agenda, reemplazo, calendario ocupación

---

## Auth y permisos (auth.py)

| Dependency | Quién puede |
|------------|------------|
| `get_usuario_actual` | Usuario con JWT válido, gimnasio activo y suscripción vigente (superadmin y rutas de consulta/renovación exentas) |
| `requiere_staff` | Solo STAFF; además valida `zonas_permitidas` contra la ruta solicitada |
| `requiere_staff_o_profesor` | STAFF o PROFESOR; para STAFF aplica `zonas_permitidas` en backend |
| `requiere_administrador` | STAFF + es_administrador=True |
| `requiere_superadmin` | STAFF + es_superadmin=True |
| `requiere_permiso_eliminar` | STAFF + (admin OR puede_eliminar) |
| `requiere_permiso_exportar` | STAFF + (admin OR puede_exportar) |
| `get_cliente_actual` | Token tipo "alumno" |
| `get_profesor_actual` | Token tipo "profesor" → Empleado |

JWT incluye: sub (id), tipo, rol, gimnasio_id. Expira 12h.
`autenticar_alumno` y `autenticar_profesor` requieren un slug válido para resolver el gimnasio. Un gimnasio inactivo bloquea todas sus sesiones; una suscripción vencida devuelve HTTP 402 y permite al dueño entrar únicamente a Configuración para consultar su plan.

---

## Multi-tenant — cómo funciona

1. Toda query raíz usa `q(db, Model, usuario)` o `_del_gym()` → filtra por gimnasio_id
2. Todo POST asigna `gimnasio_id=get_gid(usuario)`
3. JWT incluye gimnasio_id
4. Seeders al registrar gym: copia ejercicios, alimentos, paquetes, puestos, servicios del template (gym default)
5. Límites por plan: `_validar_limite_plan()` en POST de clientes, productos, rutinas, usuarios
6. Login por slug: `?gym=slug` → frontend envía slug → backend filtra por gimnasio_id
7. `GET /gym/{slug}`: info pública para personalizar login/PWA
8. Entidades hijas (pagos, membresías asignadas, rutinas, agenda y servicios) se validan mediante JOIN hasta el gimnasio
9. Configuración, moneda, comisiones y PDFs leen el registro `Gimnasio` del tenant, no el id global 1

---

## Flujo de URLs por gym (slug)

- **Staff**: `https://soft-mrgym.onrender.com/` (login con username, gimnasio_id en JWT)
- **Alumno**: `.../alumno/login.html?gym=mi-gimnasio` → personaliza login, envía slug
- **Profesor**: `.../profesor/login.html?gym=mi-gimnasio` → idem
- **Info pública**: `GET /gym/{slug}` → nombre, logo_url, tema, modo_tema

---

## PWA (Progressive Web App)

- `GET /gym/{slug}/manifest.json` genera manifest dinámico con nombre, colores e ícono del gym
- `GET /gym/{slug}/icon.svg` genera ícono SVG con inicial del gym + color del tema
- `GET /gym/{slug}/sw.js` service worker mínimo (hace la app instalable)
- login.html de alumno y profesor inyectan manifest + registran SW dinámicamente
- Meta tags apple-mobile-web-app-capable para iOS

---

## Despliegue

- **Local:** `start.bat` → uvicorn :8000, http.server :3000/:3001/:3002
- **Nube:** Dockerfile (Python 3.12-slim + nginx), 1 worker gunicorn
- **BD prod:** PostgreSQL en Supabase (free permanente, São Paulo)
- **Variables env:** DATABASE_URL (Supabase URI), SECRET_KEY, CORS_ORIGINS
- **nginx:** / → staff, /alumno/ → alumno, /profesor/ → profesor, API → :8000
- **Deploy flow:** `git push` → Render auto-redeploy ~3 min

### Problemas resueltos en deploy
- ENUMs de PostgreSQL: se pre-crean con CREATE TYPE antes de create_all (evita race condition entre workers)
- bcrypt: fijado a ==4.0.1 (passlib incompatible con versiones nuevas)
- _sembrar_gimnasio_default: busca por id=1 O slug="mi-gimnasio" (PostgreSQL no garantiza id=1)
- Tabla configuracion: try/except si no existe en BD nueva
- gunicorn: 1 worker (evita race condition de ENUMs)

---

## Estado actual y pendientes

### ✅ Completado
- Sistema base completo (todas las pantallas funcionando)
- Multi-tenant (7 pasos completados)
- Límites por plan (validación en 8 endpoints)
- Nutrición automática (BMR/TDEE/IMC → paquetes)
- Despliegue en producción (Render + Supabase) — FUNCIONANDO
- Migración SQLite↔PostgreSQL compatible
- Login multi-tenant por slug (DNI no colisiona entre gyms)
- PWA dinámica: manifest.json, icon.svg, service worker por gym
- QR en configuración para compartir portal con socios
- Upload de logo del gimnasio
- TokenResponse incluye gimnasio_slug
- Registro público de gimnasios con seeders automáticos

### ✅ Pago rápido de saldo pendiente (implementado)
- Tabla `pagos_membresia` (modelo PagoMembresia): historial individual de cada pago contra una membresía asignada
- Schema `PagoMembresiaOut` + `PagoSaldoRequest` (con fecha_proximo_pago)
- `ClienteMembresia` response ahora incluye `pagos: List[PagoMembresiaOut]`
- Endpoint `PUT /cliente-membresias/{cm_id}/pagar-saldo` (staff): crea registro PagoMembresia, suma al monto_pagado, limpia fecha_pago_saldo si saldo=0, acepta fecha_proximo_pago
- Al asignar membresía (POST /clientes/{id}/membresias) también registra el pago inicial en pagos_membresia
- `ClienteListadoRow` ahora incluye `fecha_pago_saldo` y `ultimo_cm_id`
- clientes.html: pestaña Membresías muestra historial de pagos como sub-filas (└ Pago) debajo de cada membresía
- clientes.html: botón "💳 Pagar saldo" en línea separada debajo de acciones
- clientes.html: modal con campo dinámico "Fecha próximo pago" que aparece al hacer pago parcial
- Moneda (S/) solo en cabeceras de tablas, celdas muestran solo números
- principal.html: búsqueda inteligente muestra fecha de pago (rojo si vencida), monto pendiente, ícono 💳
- principal.html: modal pago con campo dinámico fecha próximo pago + usa endpoint `/pagar-saldo`

### ✅ Keep-alive inteligente + pantalla de carga (implementado)
- Backend: background task `_keep_alive_loop()` se auto-pinga via URL externa solo si inactivo >13min Y en horario activo
- Horario: Lun-Sab 6am-11pm | Dom 6am-1pm (hora Lima, UTC-5)
- Middleware `track_last_request` actualiza `_ultimo_request_ts` en cada request
- Endpoint `GET /ping` (sin auth) retorna `{status, hora_lima}` — agregado a nginx.conf
- En dev local se desactiva automaticamente (sin RENDER_EXTERNAL_URL)
- Frontend alumno: `apiFetch()` ahora muestra overlay blanco "Conectando..." si la API tarda >3s
- Reintentos automaticos (hasta 3) con espera progresiva (2s, 4s) en errores de red (cold start)
- Ahorro: ~7 horas/dia sin pings (11pm-6am) = ~210 horas/mes ahorradas del limite de 750h

### ✅ Rediseño ficha del cliente - Pestaña Pagos (implementado)
- Tab "Membresías" renombrada a "Pagos"
- Foto del cliente 20% más grande (67px → 80px)
- Header de ficha: Nombre, Celular con link WhatsApp ("Hola + nombre"), Cumpleaños
- Barra de info del plan activo debajo del header: Plan | Inicio | Fin | Costo
- Tabla de pagos rediseñada: cada plan como card con cabecera, tabla interna con columnas FECHA | PAGADO | SALDO | F.PROX PAGO | MÉTODO | NOTAS
- Cada pago en línea separada con saldo progresivo calculado
- Botón "Pagar saldo" visible si hay deuda pendiente
- Backend: endpoint `/ingresos/` ahora usa PagoMembresia (pagos individuales) en vez de ClienteMembresia acumulado
- Cada pago (inicial o a cuenta) aparece como línea separada en Movimientos/Ingresos con su fecha, monto y método reales

### ✅ Endurecimiento multi-tenant, permisos y cobros (2026-07-13)
- Se corrigieron consultas sin filtro de gimnasio en usuarios, gastos, clientes históricos, membresías asignadas, pagos, rutinas, nutrición, agenda, planilla, servicios, medidas y ventas
- Se agregaron helpers para validar entidades raíz e hijas contra el gimnasio autenticado; un id válido de otro tenant devuelve 404
- La configuración operativa ahora vive en cada registro `Gimnasio`: moneda, comisiones, tema, cláusulas, datos de contacto y PDFs quedan aislados por tenant
- La tabla global `configuracion` permanece solo como compatibilidad legacy y ya no se consulta desde los endpoints operativos
- Un gimnasio inactivo bloquea nuevas autenticaciones y también invalida las sesiones existentes de staff, alumnos y profesores
- `zonas_permitidas` dejó de ser una restricción solo visual: el backend la aplica por prefijo de ruta para usuarios STAFF no administradores
- Los portales de alumno y profesor exigen slug; no se permite buscar un DNI globalmente si falta el gimnasio
- DNI de cliente pasa a ser único por `(gimnasio_id, dni)` en instalaciones nuevas y PostgreSQL; la SQLite local conserva su índice histórico hasta una migración controlada
- Ventas validan cantidad positiva y toman siempre el precio actual del producto desde el servidor; el precio enviado por el navegador se ignora
- Se añadieron validaciones de montos, cantidades, stock, precios y fechas; una corrección de `monto_pagado` crea un ajuste positivo o negativo en `pagos_membresia`
- Pagos de planilla y planes nutricionales automáticos ahora guardan `gimnasio_id`; cálculos de comisiones y egresos filtran por tenant
- CORS quedó restringido a los frontends locales por defecto y al dominio de producción en `render.yaml`
- Pruebas automáticas en `tests/test_multitenant.py`: aislamiento entre gimnasios, configuración por tenant, permisos backend y precio autoritativo de venta
- Verificación 2026-07-13: compilación correcta, 4/4 pruebas aprobadas y arranque local validado con `/ping`, `/gym/mi-gimnasio` y `/openapi.json`
- `start.bat` usa su propia ubicación (`%~dp0`) para arrancar backend y frontends; las copias del proyecto ya no apuntan accidentalmente a `D:\Soft-MrGym`
- La base local tiene un descuadre histórico de S/ 89 entre `ClienteMembresia.monto_pagado` y el detalle de `PagoMembresia`; no se corrigió automáticamente porque no existe una fecha fiable para reconstruir ese pago

### ✅ Suscripción recurrente SaaS por gimnasio (2026-07-13)
- Nuevos modelos `SuscripcionSaas` y `PagoSaas`; el pago que realiza el gimnasio por Soft-Gym queda separado de las membresías y pagos de sus alumnos
- Estados derivados: `prueba`, `activa`, `gracia`, `vencida`, `suspendida`, `cancelada` y `sin_configurar`
- Nuevos gimnasios reciben 14 días de prueba más 5 días de gracia; gimnasios legacy sin registro siguen accesibles hasta que el superadmin configure su primera renovación
- Renovar registra monto, moneda, método, referencia y período cubierto; permite acumular de 1 a 24 meses sin perder días ya pagados
- Al terminar la gracia, staff, alumnos y profesores quedan bloqueados. El dueño aún puede iniciar sesión y entrar a Configuración para consultar su suscripción
- `superadmin.html` muestra estado y vencimiento, ingresos SaaS del mes, suscripciones vencidas y modal responsive para cobrar, renovar, suspender o reactivar
- `configuracion.html` muestra al administrador del gimnasio su plan, período, gracia y últimos tres pagos
- La migración automática creó `suscripciones_saas` y `pagos_saas` en la SQLite local sin modificar los datos de clientes

### ✅ Navegación responsive móvil (2026-07-13)
- En anchos de hasta 768px el sidebar pasa a ser un header fijo: logo/nombre del gimnasio arriba y accesos debajo con scroll horizontal táctil
- Las secciones del menú se aplanan en móvil para que todas las acciones autorizadas estén disponibles sin ocupar una columna lateral
- Se ocultan subtítulos y columnas marcadas como secundarias; tarjetas, formularios, pestañas, tablas y modales usan tamaños compactos
- `superadmin.html` oculta clientes/usuarios/estado operativo secundarios en celular, manteniendo plan, suscripción, vencimiento y acciones
- Se corrigió el login móvil: la tarjeta ocupa 362px en viewport de 390px, sin desbordamiento, y el enlace de registro permanece dentro de la tarjeta
- El sidebar carga el logo y nombre reales del gimnasio; si no están disponibles conserva la marca de respaldo
- Verificación 2026-07-13: backend compila, JavaScript modificado pasa validación sintáctica, servidor local responde y 6/6 pruebas automáticas pasan

### ✅ Detalle financiero unificado y tablas tematizadas (2026-07-13)
- `movimientos.html` (Principal → Movimientos) y `resumen.html` (Sistema → Resumen) usan el mismo diseño de detalle financiero
- Fecha en dos líneas: fecha arriba y hora local debajo en formato de 24 horas `HH:mm`; cuando el origen no tiene hora se muestra `00:00`
- Tipo y método de pago se muestran como texto, sin iconos; los montos del detalle usan un decimal y la moneda permanece en la cabecera
- Ingresos usan verde medio oscuro `#187A5B` y egresos vino tinto `#7A2438`, ambos con peso de fuente normal
- Se eliminó el botón y texto global “Borrar último”; cada fila muestra corrección únicamente a administradores
- Corregido el borrado de ingresos de membresía: ahora `DELETE /pagos-membresia/{id}` elimina el pago individual y ajusta `monto_pagado`, sin borrar por error toda la membresía asignada
- Los borrados de pagos de planilla y servicios ahora también requieren administrador, igual que ventas, compras y gastos
- Se cerraron filtros multi-tenant faltantes en el cálculo de comisiones de ventas y membresías dentro de `/egresos/`
- Todas las tablas del panel staff tienen cabecera fija, fondo con `--color-primario` del tema, texto blanco y peso normal; Nutrición y Superadmin recibieron sus ajustes específicos
- `deploy/nginx.conf` enruta los nuevos prefijos `/pagos-membresia` y `/suscripcion` al backend
- Verificación: compilación correcta, JavaScript de ambas vistas válido y 7/7 pruebas automáticas aprobadas

### ✅ Origen de fondos en pagos del gimnasio (2026-07-13)
- Todos los egresos operativos permiten indicar si el dinero salió de `Efectivo` o `Cuenta`: compras de productos, gastos generales, pagos de staff, pagos de profesores y pagos de servicios
- `Cuenta` agrupa banco, tarjeta, Yape, Plin y QR; esta simplificación se aplica solo a pagos que realiza el gimnasio
- Los cobros a clientes mantienen `Efectivo`, `Tarjeta` y `QR`, porque tarjeta y QR conservan sus comisiones configurables
- Los modelos `Compra`, `PagoPlanilla`, `PagoServicio` y `Gasto` guardan `metodo_pago`; la migración automática añade las columnas faltantes en instalaciones existentes
- El backend solo acepta `efectivo` o `cuenta` en nuevos egresos y en correcciones administrativas; los registros históricos `tarjeta`/`qr` se presentan como `Cuenta` cuando son egresos
- Principal → Movimientos, Sistema → Resumen y la pantalla Egresos muestran el origen del pago; las comisiones de pasarela se identifican como salidas de `Cuenta`
- Se corrigió además el registro de compras para guardar siempre `gimnasio_id`, y la edición de planilla combinada conserva el tipo antes de cerrar el modal
- Verificación: backend compilado, OpenAPI local actualizado, JavaScript de 7 pantallas válido y 9/9 pruebas automáticas aprobadas

### ✅ Seguimiento, Agenda semanal y paquetes de rutinas (2026-07-13)
- Se quitó `Progreso` del menú Seguimiento y también de las zonas configurables para nuevos permisos de staff; sus datos y endpoints se conservan por compatibilidad y para los portales/fichas que aún los usan
- Agenda muestra la semana completa de lunes a domingo; la grilla, el rango consultado y la repetición semanal aceptan domingo (`weekday=6`)
- El acceso `Ejercicios` se renombró `Rutinas`; `entrenamientos.html` ya no muestra las pestañas “Rutinas de alumnos” ni “Catálogo de ejercicios”
- Nueva pantalla responsive `Paquetes de rutinas`: búsqueda, filtros por nivel y objetivo, tarjetas resumidas, edición, desactivación y asignación
- Cada paquete define nombre, descripción, nivel (`básico`, `intermedio`, `avanzado`, `competencia`), objetivo, etapa, perfil recomendado, rango de edad, duración, días y ejercicios
- Rutinas tiene dos vistas coordinadas: `Paquetes de rutinas` y `Catálogo de ejercicios`; el catálogo es la fuente del selector del constructor y también admite ejercicios con texto libre
- Nuevas tablas `paquetes_rutina`, `paquete_rutina_dias` y `paquete_rutina_ejercicios`, aisladas por `gimnasio_id`
- Nuevos endpoints CRUD `/paquetes-rutina/` y `POST /paquetes-rutina/{id}/asignar`; asignar crea una copia independiente en las tablas de rutina del cliente
- Las rutinas ya asignadas no cambian al editar o desactivar el paquete original y continúan visibles en la ficha/portal del alumno
- Al renombrar un ejercicio del catálogo, el nombre se propaga a las rutinas de alumnos y paquetes que conservan `tipo_ejercicio_id`; los ejercicios de texto libre no cambian y la actualización queda limitada al gimnasio autenticado
- Al iniciar el backend también se sincronizan referencias antiguas que hayan quedado con un nombre anterior; la base local ya fue corregida y la regresión queda cubierta por 14/14 pruebas automáticas
- Catálogo inicial de 18 paquetes de rutinas por gimnasio: inicio, bajar de peso, ganar masa, tonificación, definición y rendimiento
- Los paquetes cubren perfiles mixtos, femeninos y masculinos en niveles básico, intermedio y avanzado, con programas de 3 a 5 días y duración sugerida de 4 a 10 semanas
- Cada paquete contiene ejercicios reales enlazados al catálogo, series, repeticiones, orden diario e indicaciones de técnica/carga; todos siguen siendo editables antes de asignarlos
- La pantalla de paquetes incorpora filtro por perfil (`Mixto`, `Femenino`, `Masculino`) además de nivel, objetivo y búsqueda
- La siembra es idempotente: completa paquetes faltantes sin duplicar los existentes; los gimnasios nuevos reciben también una copia independiente con referencias a su propio catálogo
- Verificación: 18 paquetes en cada gimnasio local, todos con días/ejercicios, JavaScript válido y 15/15 pruebas automáticas aprobadas
- En `Clientes → Rutinas`, el generador aleatorio fue reemplazado por un recomendador que ordena los paquetes existentes según objetivo, último peso, estatura/IMC, peso objetivo, género, edad, nivel e historial de rutinas del cliente
- El recomendador propone hasta cinco paquetes y explica las coincidencias; el entrenador puede cambiar manualmente el objetivo y el nivel antes de elegir
- El botón `Usar` asigna inmediatamente una copia independiente del paquete elegido al cliente, cierra el recomendador y actualiza la pestaña para mostrar la nueva rutina
- La rutina cargada puede editarse desde la propia ficha del cliente; el paquete original permanece sin cambios
- Se conserva el flujo opcional del editor de paquetes y `POST /paquetes-rutina/guardar-y-asignar` para crear una adaptación con nombre nuevo y asignarla en una sola transacción
- Verificación del recomendador: backend compilado y 16/16 pruebas automáticas aprobadas, incluyendo perfil, ranking, edición, nombre obligatorio, guardado y asignación
- `deploy/nginx.conf` enruta `/paquetes-rutina` al backend
- Verificación inicial: backend compilado, JavaScript de navegación/Agenda/Rutinas válido, OpenAPI y tablas locales disponibles

### ✅ Catálogo visible, otros ingresos y alquiler de salas (2026-07-13)
- La sección Rutinas vuelve a mostrar el `Catálogo de ejercicios` junto a `Paquetes de rutinas`; permite crear, editar, desactivar y subir imagen demostrativa
- El constructor de paquetes selecciona directamente ejercicios del catálogo, conservando la opción de texto libre
- Principal incorpora una cuarta tarjeta `Otros ingresos`, con accesos a `Conceptos` y `+ Registrar`
- Los conceptos reutilizables guardan nombre, descripción, monto sugerido, sala sugerida y la opción `Mostrar este concepto al agendar una sala alquilada`
- El registro de otro ingreso solicita fecha, concepto, monto, método (`efectivo`, `tarjeta`, `qr`) y descripción opcional
- Nuevas tablas multi-tenant `conceptos_otro_ingreso`, `otros_ingresos` y `reservas_sala`
- Nuevos endpoints `/conceptos-ingreso/`, `/otros-ingresos/` y `/reservas-sala/`, protegidos por las zonas Pagos y Agenda
- Otros ingresos se integran en `/ingresos/`, Principal → Movimientos, Sistema → Resumen, pantalla Ingresos y balances diarios de efectivo/cuenta
- Agenda permite elegir `Clase del gimnasio` o `Sala alquilada`; el alquiler usa uno de los conceptos habilitados, no exige profesor y no afecta planilla
- Las reservas aparecen también en el calendario de ocupación de profesores y el backend impide superponer clases/alquileres en la misma sala y horario (HTTP 409)
- `deploy/nginx.conf` enruta los tres nuevos prefijos al backend
- Verificación: compilación correcta, JavaScript de 6 pantallas válido, OpenAPI y tablas locales disponibles, y 11/11 pruebas automáticas aprobadas

### ✅ Agenda compacta y creación desde la cuadrícula (2026-07-13)
- La grilla semanal calcula su tamaño según la ocupación: un día sin clases ni reservas usa `0.5fr` frente al ancho `1fr` de un día ocupado
- Cada hora sin eventos en toda la semana mide 26px, exactamente el 50% de las horas ocupadas (52px)
- Los eventos conservan su posición y duración aunque atraviesen filas de distinta altura; el cálculo usa offsets acumulados por segmento horario
- Cada cruce de día y hora incluye un botón circular `+`, visible también en móvil
- Al tocar `+`, el modal `Agendar` recibe automáticamente la fecha, la hora de inicio y una hora de fin sugerida; dentro se elige `Clase del gimnasio` o `Sala alquilada`
- El botón general de cabecera se simplificó a `+ Agendar`
- Verificación: JavaScript válido y 11/11 pruebas automáticas aprobadas

### ✅ Porciones de nutrición fáciles para el cliente (2026-07-13)
- Los alimentos de paquetes y planes guardan ahora `porcion_cliente`, separada de `cantidad_gramos`; los gramos permanecen únicamente para calcular calorías y macronutrientes
- Los paquetes siempre muestran y solicitan una medida doméstica fácil, editable por el staff: `4 huevos`, `1 lata`, `1/2 taza`, `3/4 taza` o `1/2 palta`
- Huevos y alimentos expresados en unidades se redondean a números enteros; el atún usa latas de 150 g; arroz, choclo, arvejas y granos usan cuartos de taza; la palta usa medias unidades
- Los paquetes iniciales, paquetes existentes y planes antiguos se normalizan automáticamente al arrancar, sin perder sus valores nutricionales internos
- Al aplicar un paquete o generar un plan automático, el nombre visible ya no incorpora gramos; el alumno ve el alimento y debajo su porción sencilla
- El constructor manual de planes y el editor de paquetes sugieren la porción al cambiar el alimento o el gramaje, pero permiten que el nutricionista la ajuste
- El editor se reorganiza de forma responsive para que alimento, porción y cálculo interno sean operables desde celular
- Se reforzó el aislamiento multi-tenant al validar que cada alimento agregado a un paquete pertenezca al gimnasio autenticado
- La ficha del cliente muestra debajo de cada alimento su cantidad doméstica; las calorías se rotulan como `Energía` para evitar confundirlas con gramos
- Los paquetes y planes automáticos limitan proteínas a porciones razonables: carnes y pescados hasta 200 g, atún hasta una lata de 150 g y huevos hasta 4 unidades
- Los paquetes existentes y planes automáticos ya generados se corrigen y recalculan automáticamente al iniciar el backend
- Las cabeceras de los planes usan un degradado más intenso basado en la paleta del gimnasio; se aplica tanto en Nutrición como en la ficha del cliente
- En modo oscuro, tarjetas, indicadores y bloques de desayuno/almuerzo/cena mezclan sus acentos con las superficies oscuras del tema, manteniendo texto, bordes y porciones legibles
- Las franjas `Desayuno`, `Almuerzo`, `Aperitivo` y `Cena` usan una versión intensa del mismo color de su tarjeta, con título y calorías en blanco; en modo oscuro el tono se profundiza sin perder su identidad
- Verificación: backend compilado, JavaScript válido y 13/13 pruebas automáticas aprobadas, incluyendo porciones y límites de proteínas

### ✅ Uniformidad visual, tablas responsive y marca ampliada (2026-07-13)
- La interfaz compartida de staff define una escala tipográfica única: etiquetas de 12 px, texto auxiliar de 13 px, texto operativo/tablas/botones de 14 px, cabeceras de 16 px y títulos principales de 20 px
- Las tablas usan peso normal, altura de línea y espaciado coherentes; sus cabeceras continúan fijas y toman el color primario del tema
- `Movimientos` y `Resumen` comparten los mismos estilos de fecha/hora, tipo, método, monto y descripción; ingresos usan verde oscuro y egresos vino en claro, con variantes de mayor contraste en modo oscuro
- En ventanas estrechas, la columna Descripción admite hasta dos líneas y mantiene el resto de columnas compactas y operativas
- Las cabeceras de planes y comidas de nutrición comparten tamaños, intensidad, contraste y colores entre Nutrición, ficha del cliente y portal del alumno; las descripciones largas se limitan a dos líneas en celular
- El logo del menú lateral aumenta de 30 px a 90 px (300%); el nombre editable de `Configuración` aparece debajo en letra pequeña y, si está vacío, el logo crece a 108 px para usar ese espacio
- En menú colapsado y celular el logo usa medidas adaptadas para no romper la navegación horizontal ni ocultar acciones
- La escala tipográfica base también queda declarada en los portales de alumno y profesor
- Verificación: JavaScript válido en 7 archivos/pantallas, backend compilado y 16/16 pruebas automáticas aprobadas

### ✅ Aforo actual y salida automática (2026-07-13)
- Principal reemplaza la lista única de asistencias por dos vistas operativas con contadores: `Ingresos de hoy (XX)` conserva el historial diario y `En sala (XX)` muestra únicamente entradas sin salida
- La vista inicial es `En sala`; al registrar la salida de un cliente desaparece inmediatamente de esa lista, pero permanece en `Ingresos de hoy` con su hora de salida
- Toda asistencia abierta se cierra automáticamente al cumplir tres horas y guarda como salida la hora exacta `entrada + 3 horas`
- El cierre automático se ejecuta al consultar Dashboard, historial o asistencias del día; Principal refresca la lista cada minuto, por lo que el aforo visible se corrige sin intervención del staff
- La corrección está aislada por `gimnasio_id`: nunca cierra asistencias de otro gimnasio
- Verificación: JavaScript válido, backend compilado y 17/17 pruebas automáticas aprobadas, incluida la salida exacta a las tres horas y el aislamiento multi-tenant

### ✅ Marca oficial Soft-Gym (2026-07-13)
- La marca comercial y visible del proyecto cambia de `Soft-MrGym` a `Soft-Gym` en panel staff, portal del alumno, zona de profesores, pantallas auxiliares, API, mensajes de suscripción, PWA y scripts locales
- Producción continúa funcionando en `https://soft-mrgym.onrender.com` con PostgreSQL en Supabase; la URL de Render, el repositorio y las rutas locales no se renombran para evitar romper el despliegue
- La futura integración Izipay usará el origen público HTTPS ya existente en Render; las rutas previstas son `/pagos/izipay/notificacion` para IPN y una pantalla propia de resultado para el retorno del comprador

### ✅ Actualización preparada para producción (2026-07-13)
- Se consolidan para GitHub y Render todos los cambios funcionales, responsive, multi-tenant y de marca documentados en esta sesión
- El despliegue conserva el servicio técnico `soft-mrgym`, la URL `https://soft-mrgym.onrender.com` y la base PostgreSQL existente en Supabase
- La carpeta local de asistencia `.continue/` queda excluida del repositorio y no forma parte de la aplicación
- Validación previa: backend compilado e importado correctamente, JavaScript externo válido, revisión de diferencias sin errores y 17/17 pruebas automáticas aprobadas

### ✅ Migración de MrGym a Supabase (2026-07-13)
- El gimnasio principal local fue migrado a producción reutilizando el tenant técnico vacío `id=1`, ahora llamado `MrGym`; conserva el slug técnico `mi-gimnasio`
- El gimnasio `prueba gym` (`id=4`) y todos sus conteos permanecieron intactos
- Se migraron 1,665 clientes (1,662 activos y 3 inactivos), 4 usuarios del tenant principal, 5 empleados, membresías, pagos, productos, ventas, asistencias, rutinas, nutrición, agenda, servicios, planilla, metas y medidas
- Todos los IDs y llaves foráneas se reasignaron dentro de una sola transacción PostgreSQL; la validación posterior confirmó los mismos conteos que SQLite en cada tabla migrada
- El usuario y contraseña administrativos configurados localmente fueron probados contra `https://soft-mrgym.onrender.com/auth/login`: acceso correcto al gimnasio `MrGym` y al Dashboard
- Antes de modificar Supabase se creó el respaldo local comprimido `backups/supabase-antes-mrgym-20260713-222833.json.gz`; `backups/` está excluido de Git
- La herramienta reutilizable y protegida quedó en `scripts/migrate_gym_to_production.py`; aborta ante colisiones o datos operativos inesperados y nunca borra otros gimnasios
- El usuario local `MrGym` pertenecía a un tercer tenant local (`id=3`) y no formaba parte de la primera copia del tenant principal; se añadió después como quinto usuario administrador de MrGym en producción, conservando exactamente su hash de contraseña local. Antes se generó el respaldo adicional `backups/supabase-antes-mrgym-20260713-224558.json.gz`
- `scripts/copy_user_to_production.py` permite repetir de forma segura este ajuste para un usuario concreto: valida colisiones, crea respaldo y nunca copia privilegios de superadmin entre tenants
- Las 10 imágenes locales de clientes, productos y logo no se copiaron a Render para no publicar datos personales en GitHub; siguen pendientes de Supabase Storage o Cloudflare R2

### 🔲 Pendiente (próxima sesión)
- Reconciliar manualmente el descuadre histórico de S/ 89 de la base SQLite antes de usar el libro de pagos como fuente contable definitiva
- Bloquear secciones del menú según plan (frontend)
- Flujo para que el dueño del gym upgrade su plan
- Integrar Izipay Online para suscripciones SaaS: primera etapa con Link de Pago/IPN y renovación confirmada por webhook; automatizar cobro con token solo después de que Izipay habilite y confirme recurrencia/MIT para la cuenta. El POS físico se mantiene como cobro presencial con renovación registrada por superadmin
- Notificaciones (WhatsApp/email a clientes por vencimiento)
- Dashboard analytics avanzado para superadmin
- Fotos persistentes (actualmente se pierden al redesplegar; migrar a Supabase Storage o Cloudflare R2)

---

## Base de datos
- **Producción (Supabase):** gym de prueba creado via registro.html
- **Local (SQLite):** Gimnasio principal (~1665 clientes), gym de prueba (0 clientes)
- 2 planes: Free (50 clientes, 20 productos, 10 rutinas, 1 staff) y Pro (ilimitado, $49/mes)
