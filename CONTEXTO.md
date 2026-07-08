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
║  nueva gasta miles de tokens re-explorando 258KB de main.py.     ║
╚══════════════════════════════════════════════════════════════════╝
-->

# CONTEXTO — Soft-MrGym
> Última actualización: 2026-07-08 (v3 - PWA + QR)
> main.py: ~265KB, ~5550 líneas | models.py: ~800 líneas | schemas.py: ~610 líneas

## Qué es
Sistema de gestión de gimnasio multi-tenant (SaaS). Un superadmin administra gimnasios; cada gimnasio tiene su staff, clientes, productos, etc. completamente aislados.

## Stack
- **Backend:** FastAPI + SQLAlchemy + SQLite (dev) / PostgreSQL (prod)
- **Frontends:** HTML/CSS/JS vanilla (sin framework), 3 portales separados
- **PDF:** reportlab (recibos, contratos, boletas)
- **Auth:** JWT (python-jose) + bcrypt (passlib)
- **Dev:** Windows, D:\Soft-MrGym, uvicorn --reload en :8000, frontends con http.server

## Reglas técnicas para trabajar
- `bash_tool` NO accede a D:\ → usar siempre `filesystem:*` (MCP)
- `filesystem:edit_file` requiere `oldText` único → verificar antes de editar
- main.py NO cabe en contexto → leer por bloques con head/tail
- Tras editar .py, uvicorn recarga solo (~2-3s)
- El navegador cachea → Ctrl+Shift+R

---

## Mapa de archivos

```
D:\Soft-MrGym\
├── backend\
│   ├── __init__.py              (vacío, hace que sea un paquete)
│   ├── database.py              (Engine, SessionLocal, get_db; lee DATABASE_URL del env)
│   ├── models.py                (~800 lín) Tablas ORM — ver sección "Modelo de datos"
│   ├── schemas.py               (~600 lín) Pydantic schemas (Base/Create/Update/Response)
│   ├── auth.py                  (~200 lín) JWT, bcrypt, dependencies de permisos
│   ├── main.py                  (~5400 lín) TODOS los endpoints — ver sección "Endpoints"
│   ├── pdf_generator.py         (~300 lín) Genera PDFs con reportlab
│   ├── requirements.txt         (fastapi, uvicorn, sqlalchemy, pydantic, jose, passlib, etc.)
│   ├── .env                     (SECRET_KEY local, NO commitear)
│   └── uploads\                 (fotos de clientes, productos, ejercicios)
│
├── frontend-staff\              Panel principal del gimnasio
│   ├── js\api.js                API_BASE_URL = "http://localhost:8000" (se reescribe en deploy)
│   ├── js\sidebar.js            Menú lateral, enlace Super Admin (solo superadmins)
│   ├── js\tema.js               Temas (lavanda, océano, etc.) y modo claro/oscuro
│   ├── js\flujo-cliente.js      Búsqueda inteligente + venta rápida del panel principal
│   ├── js\logo.js               Logo dinámico en sidebar
│   ├── js\personal.js           Lógica de empleados y puestos
│   ├── js\medidas-catalogo.js   Campos de medidas configurables
│   ├── css\styles.css           Único archivo CSS (sidebar + flujo-cliente + todo)
│   ├── styles.css               (¡OJO! hay otro en raíz de frontend-staff)
│   ├── login.html, registro.html, principal.html
│   ├── clientes.html, membresias.html, productos.html, ventas.html
│   ├── venta-rapida.html, asistencias.html, vencimientos.html
│   ├── entrenamientos.html (catálogo ejercicios), progreso.html
│   ├── nutricion.html, mi-nutricion.html, mi-rutina.html, mi-progreso.html
│   ├── usuarios-staff.html, usuarios-profesores.html
│   ├── planilla-staff.html, planilla-profesores.html, agenda.html
│   ├── pagos.html (servicios/deudas), ingresos.html, egresos.html
│   ├── movimientos.html, resumen.html (dashboard financiero)
│   ├── metas.html (comisiones), reportes.html, configuracion.html
│   ├── gestion-medidas.html, retos.html
│   └── superadmin.html          Panel SaaS (planes, gimnasios, stats globales)
│
├── frontend-alumno\             Portal del alumno (solo lectura)
│   ├── js\api.js                API_BASE = "http://localhost:8000"
│   ├── login.html, mi-perfil.html, mi-rutina.html
│   ├── mi-nutricion.html, mi-progreso.html, retos.html
│
├── frontend-profesor\           Zona de profesores (agenda propia, reemplazos)
│   ├── js\api.js                API_BASE = "http://localhost:8000"
│   ├── login.html, agenda.html
│
├── deploy\                      Archivos de despliegue en nube
│   ├── nginx.conf               Proxy: / → staff, /alumno/ → alumno, /profesor/ → profesor, API → :8000
│   ├── start.sh                 Arranca gunicorn + nginx, inyecta URL real en api.js
│   └── .env.example
│
├── Dockerfile                   Python 3.12-slim + nginx, todo en un contenedor
├── render.yaml                  Blueprint para Render.com (solo web service, BD en Supabase)
├── .dockerignore, .gitignore
├── start.bat                    Desarrollo local (Windows)
├── DEPLOY.md                    Guía paso a paso para desplegar
├── CONTEXTO.md                  ← ESTE ARCHIVO
└── sql_app.db                   Base SQLite local (~1662 clientes reales)
```

---

## Modelo de datos (models.py)

### Tablas GLOBALES (sin gimnasio_id)
| Tabla | Descripción |
|-------|-------------|
| `planes_saas` | Catálogo de planes SaaS (Free, Pro). Campos: max_clientes, max_productos, max_rutinas, max_usuarios_staff, nutricion_habilitada, reportes_avanzados, dominio_propio |
| `gimnasios` | Cada tenant. Tiene plan_id, slug, config (moneda, comisiones, tema, clausulas) |
| `configuracion` | Tabla legacy (id=1), aún usada por _get_o_crear_configuracion() |

### Tablas con gimnasio_id (25 tablas raíz)
| Tabla | Clave | Relaciones |
|-------|-------|-----------|
| `usuarios` | username + password_hash | → gimnasio, → empleado (opcional). Campos: rol (STAFF/PROFESOR), es_administrador, es_superadmin, puede_eliminar, puede_exportar, zonas_permitidas |
| `clientes` | nombre, apellidos, dni, etc. | → gimnasio. Campos: foto_url, genero, fecha_renovacion/vencimiento, membresia_texto (legacy), asistencias_legado |
| `clientes_historicos` | importados de sistema anterior | num_carnet, migrado, cliente_nuevo_id |
| `membresias` | catálogo de tarifas | precio, duracion_dias/meses, incluye_nutricion, horarios, congelamiento |
| `cliente_membresias` | asignación cliente↔membresía | fecha_inicio/fin, monto_pagado, vendido_por_id, metodo_pago |
| `productos` | inventario | precio_compra/venta, stock, stock_minimo, foto_url |
| `ventas` | registro de ventas | → detalles. total, metodo_pago, es_venta_rapida, costo_comision_gym |
| `detalles_venta` | items de una venta | producto_id, cantidad, precio_unitario |
| `compras` | reposición de stock | producto_id, cantidad, costo_unitario (alimenta Egresos) |
| `asistencias` | entrada/salida de clientes | cliente_id, fecha_hora_entrada/salida |
| `asistencias_empleado` | entrada/salida de staff | empleado_id, fecha_hora_entrada/salida |
| `progresos` | registro simple peso/medidas | cliente_id, fecha, peso_kg, grasa_pct, notas |
| `medidas` | toma antropométrica completa | ~40 campos (perímetros, signos vitales, composición corporal) |
| `tipos_ejercicio` | catálogo de ejercicios | categoria, equipamiento, nivel, genero_recomendado, objetivo (76 precargados) |
| `rutinas` → `rutina_dias` → `rutina_ejercicios` | rutina por cliente | nombre, días, ejercicios con series/reps/peso |
| `alimentos` | catálogo nutricional | 82+ alimentos peruanos, macro/micronutrientes por 100g |
| `paquetes_nutricion` → `paquete_alimentos` | plantillas desayuno/almuerzo/cena | por propósito (bajar peso, ganar masa, etc.) × 3 tamaños |
| `planes_nutricion` → `comidas_plan` | plan asignado a cliente | generado automáticamente según IMC/BMR/TDEE o manual |
| `retos` | desafíos para alumnos | titulo, descripcion, fecha_inicio/fin |
| `empleados` | personal del gym | nombre, tipo (STAFF_FIJO/PROFESOR_DE_SALA), sueldo, tarifas, DNI |
| `puestos` | catálogo de cargos | nombre, tipo. Precargados: Counter, Entrenador, Baile, etc. |
| `clases_dictadas` | agenda de clases | profesor_id, fecha, hora_inicio/fin, sala, serie_id (recurrentes) |
| `pagos_planilla` | pagos a staff/profesores | tipo (staff/profesor), monto_total, mes/año, desde/hasta |
| `servicios` | catálogo (agua, luz, alquiler) | nombre, notas |
| `cargos_servicio` → `pagos_servicio` | deudas/cobros | monto_total, recurrente (semanal/mensual/anual), serie_id |
| `gastos` | egresos generales | categoria, monto, descripcion |
| `metas_mensuales` | meta de ventas por mes | meta_membresias, meta_productos |
| `tramos_comision` | escalas de comisión | tipo (membresia/producto), porcentaje_meta_minimo, porcentaje_comision |

### Enums
- `RolUsuario`: STAFF, PROFESOR
- `MetodoPago`: EFECTIVO, TARJETA, QR
- `TipoComida`: DESAYUNO, COMIDA, CENA, APERITIVO
- `TipoEmpleado`: STAFF_FIJO, PROFESOR_DE_SALA
- `CategoriaAlimento`: PROTEINA, CARBOHIDRATO, GRASA, VEGETAL, FRUTA, LACTEO, LEGUMBRE, OTRO
- `PropositoNutricion`: BAJAR_PESO, GANAR_MASA, MANTENIMIENTO, DEFINICION
- `CategoriaGasto`: COMPRA_PRODUCTO, PAGO_STAFF, PAGO_PROFESOR, PAGO_SERVICIO, OTROS

---

## Helpers críticos (main.py, primeras ~110 líneas)

| Helper | Línea aprox | Qué hace |
|--------|-------------|----------|
| `get_gid(usuario)` | ~42 | Extrae gimnasio_id del usuario autenticado |
| `q(db, Model, usuario)` | ~46 | Query filtrada por gimnasio_id (shorthand) |
| `_validar_limite_plan(db, usuario, recurso)` | ~54 | Valida max_clientes/productos/rutinas/staff del plan. HTTP 403 si excede. 0=ilimitado |
| `_validar_nutricion_habilitada(db, usuario)` | ~96 | HTTP 403 si plan no incluye nutrición |
| `_detectar_delimitador(primera_linea)` | ~115 | Auto-detecta separador CSV (tab > ; > ,) |
| `_migrar_columnas_nuevas()` | ~183 | ALTER TABLE idempotente, soporta SQLite + PostgreSQL |
| `_sembrar_gimnasio_default()` | ~350 | Crea gym id=1 (template), planes Free/Pro, asigna data NULL |
| `_get_o_crear_configuracion(db)` | ~3400 | Singleton de Configuración (id=1) |

---

## Endpoints por módulo (main.py)

### Auth (~línea 1020)
- `_resolver_gimnasio_id_por_slug(db, slug)` — Helper: convierte slug a gimnasio_id, 404 si no existe
- `GET /gym/{slug}` — Info pública del gym (nombre, logo, tema). Sin auth. Para personalizar login/PWA
- `GET /gym-actual/` — Info del gimnasio del usuario autenticado (slug, nombre, logo, tema). Resuelve el problema de obtener el slug sin tenerlo en sessionStorage
- `POST /gym-actual/logo` — Sube/reemplaza el logo del gimnasio (solo admin). Guarda en uploads/logos/
- `GET /gym/{slug}/manifest.json?portal=alumno|profesor|staff` — Web App Manifest dinámico por gym (nombre, colores, ícono)
- `GET /gym/{slug}/icon.svg` — Ícono SVG generado con inicial del gym y color del tema (fallback si no hay logo_url)
- `GET /gym/{slug}/sw.js` — Service Worker mínimo (hace la app instalable como PWA)
- `GET /gym/{slug}/qr.svg?portal=alumno|profesor` — Código QR como SVG con la URL del portal (usa lib qrcode)
- `POST /auth/login` — Staff/profesor, devuelve JWT con gimnasio_id + gimnasio_slug
- `POST /auth/login-alumno` — Cliente con DNI + código + slug (opcional). **Filtra por gimnasio_id si viene slug**
- `POST /auth/login-profesor` — Profesor con DNI + código + slug (opcional). **Filtra por gimnasio_id si viene slug**
- `POST /auth/registro-gimnasio` — Registro público, crea gym (Free) + admin + seeders

### Usuarios (~línea 1025)
- CRUD `/usuarios/` — Solo admin crea. `_validar_limite_plan("usuarios_staff")` en POST
- `GET /usuarios/me` — Datos del usuario logueado

### Dashboard + Finanzas (~línea 1130)
- `GET /dashboard/stats` — Tarjetas del panel principal
- `GET /ingresos/` — Membresías + ventas con comisiones
- `GET /egresos/` — Compras + planilla + servicios + comisiones pasarela
- CRUD `/gastos/` — Egresos manuales

### Clientes (~línea 1560)
- `GET /clientes/listado-completo` — Vista de tabla con deuda, vencimiento, %asistencia
- `GET /clientes/` — Paginado con búsqueda server-side
- `POST /clientes/` — `_validar_limite_plan("clientes")` en POST
- `POST /clientes/importar` — CSV masivo, con validación de límite
- `POST /clientes/{id}/foto` — Upload JPEG/PNG/WEBP ≤5MB
- `GET /clientes/{id}/ficha` — Resumen rápido para búsqueda inteligente

### Clientes Históricos (~línea 2300)
- `GET /clientes-historicos/` — Búsqueda en base legacy
- `POST /clientes-historicos/importar` — CSV del sistema anterior
- `POST /clientes-historicos/{id}/reingresar` — Migra a cliente activo, con validación de límite

### Reportes (~línea 1900)
- `GET /reportes/clientes` + `/exportar` — JSON o CSV
- `GET /reportes/ventas` + `/exportar`
- `GET /reportes/productos` + `/exportar`

### Membresías (~línea 2500)
- CRUD `/membresias/` — Catálogo de tarifas
- `POST /clientes/{id}/membresias` — Asignar membresía (recalcula fechas del cliente)
- `PUT/DELETE /cliente-membresias/{id}` — Corrección administrativa
- `GET /membresias/por-vencer` — Alertas
- PDFs: `GET /clientes/{id}/membresias/{cm_id}/recibo.pdf` y `/contrato.pdf`
- Exportar/importar CSV de tarifas

### Productos (~línea 2950)
- CRUD `/productos/` — `_validar_limite_plan("productos")` en POST
- `GET /productos/mas-vendidos` — Para Venta Rápida
- `POST /productos/{id}/foto` — Upload
- CRUD `/compras/` — Reposición de stock (alimenta Egresos)

### Ventas (~línea 3200)
- CRUD `/ventas/` — Descuenta stock, calcula comisión pasarela
- `GET /ventas/{id}/boleta.pdf`

### Asistencias (~línea 3400)
- CRUD `/asistencias/` — Entrada/salida de clientes
- CRUD `/asistencias-empleado/` — Entrada/salida de staff

### Entrenamientos (~línea 3480)
- CRUD `/tipos-ejercicio/` — Catálogo (76 precargados)
- CRUD `/rutinas/` — `_validar_limite_plan("rutinas")` en POST
- CRUD `/rutina-dias/{id}/ejercicios`

### Nutrición (~línea 3600)
- CRUD `/alimentos/` — Catálogo (82+ items)
- CRUD `/paquetes-nutricion/` — Plantillas por propósito × tamaño
- CRUD `/nutricion/` — Planes de cliente. `_validar_nutricion_habilitada` en POST
- `POST /nutricion/generar-automatico/{id}` — Calcula BMR/TDEE/IMC → elige paquetes
- `POST /nutricion/generar-automatico-masivo` — Para todos los clientes elegibles

### Personal (~línea 4100)
- CRUD `/empleados/`, `/puestos/`
- Agenda: CRUD `/clases/` — Series recurrentes con serie_id
- `PUT /clases/{id}/marcar-dictada` — Calcula pago por hora
- Planilla: `GET /planilla/profesor/{id}`, `GET /planilla/staff/{id}`
- CRUD `/pagos-planilla/` — Con validación de saldo pendiente
- PDF: `GET /pagos-planilla/{id}/recibo.pdf`

### Servicios/Deudas (~línea 4500)
- CRUD `/servicios/` — Catálogo
- CRUD `/cargos-servicio/` — Cobros con recurrencia (semanal/mensual/anual)
- CRUD `/pagos-servicio/` — Pagos parciales contra cargos

### Medidas (~línea 4750)
- CRUD `/medidas/` — ~40 campos antropométricos
- Tras registrar/editar: dispara `_intentar_generar_plan_automatico`

### Configuración (~línea 4830)
- GET/PUT `/configuracion/` — Moneda, comisiones, tema, clausulas

### Metas y Comisiones (~línea 4860)
- CRUD `/metas/`, `/comisiones/tramos`
- `GET /comisiones/resumen` — Calcula comisiones de todo el staff

### SaaS / Super Admin (~línea 5050)
- CRUD `/saas/planes`, `/saas/gimnasios`
- `DELETE /saas/gimnasios/{id}` — Cascada total (protege gym template id=1)
- `GET /saas/dashboard` — Stats globales

### Portal Alumno (~línea 5250)
- Solo lectura: mi-perfil, mi-rutina, mi-nutricion, mi-progreso, retos
- `POST /portal-alumno/mi-foto` — Solo si no tiene deuda

### Portal Profesor (~línea 2100 en main.py)
- `GET /portal-profesor/mi-agenda` — Clases propias
- `PUT /portal-profesor/clases/{id}/reemplazo` — Asignar reemplazo
- `GET /portal-profesor/ocupado` — Calendario de ocupación

---

## Auth y permisos (auth.py)

| Dependency | Quién puede |
|------------|------------|
| `get_usuario_actual` | Cualquier usuario con JWT válido |
| `requiere_staff` | Solo rol STAFF |
| `requiere_staff_o_profesor` | STAFF o PROFESOR |
| `requiere_administrador` | STAFF + es_administrador=True |
| `requiere_superadmin` | STAFF + es_superadmin=True |
| `requiere_permiso_eliminar` | STAFF + (es_administrador OR puede_eliminar) |
| `requiere_permiso_exportar` | STAFF + (es_administrador OR puede_exportar) |
| `get_cliente_actual` | Token tipo "alumno" |
| `get_profesor_actual` | Token tipo "profesor" → devuelve Empleado |

JWT incluye: sub (id), tipo (usuario/alumno/profesor), rol, gimnasio_id.
Expira en 12 horas.

---

## Multi-tenant — cómo funciona

1. **Toda query** usa `q(db, Model, usuario)` que filtra por `gimnasio_id`
2. **Todo POST** asigna `gimnasio_id=get_gid(usuario)` al crear
3. **JWT** incluye `gimnasio_id` → se propaga automáticamente
4. **Seeders** al registrar un gym nuevo: copia ejercicios, alimentos, paquetes, puestos, servicios del gym template (id=1)
5. **Límites** por plan: `_validar_limite_plan()` en POST de clientes, productos, rutinas, usuarios
6. **Login por slug**: alumno/profesor envían `?gym=slug` en la URL → el frontend lo lee y lo envía como campo `slug` en el request de login → el backend filtra por `gimnasio_id` → no hay conflicto de DNIs entre gyms
7. **`GET /gym/{slug}`**: endpoint público que devuelve nombre, logo, tema del gym para personalizar la pantalla de login

---

## Flujo de URLs por gym (slug)

- **Staff**: `https://dominio.com/` (login con username, el gimnasio_id ya va en el JWT)
- **Alumno**: `https://dominio.com/alumno/login.html?gym=mi-gimnasio` → personaliza login con nombre del gym, envía slug
- **Profesor**: `https://dominio.com/profesor/login.html?gym=mi-gimnasio` → idem
- **Info pública**: `GET /gym/{slug}` → nombre, logo_url, tema, modo_tema

---

## Despliegue

- **Local:** `start.bat` → uvicorn :8000, http.server :3000/:3001/:3002
- **Nube:** Dockerfile (Python+nginx en un contenedor), `render.yaml` para Render.com (solo web service)
- **BD prod:** PostgreSQL en Supabase (free permanente, 500MB, región São Paulo)
- **Variables env:** DATABASE_URL, SECRET_KEY, CORS_ORIGINS
- **nginx:** proxy reverso, / → staff, /alumno/ → alumno, /profesor/ → profesor, APIs → :8000

---

## Estado actual y pendientes

### ✅ Completado
- Sistema base completo (todas las pantallas funcionando)
- Multi-tenant (7 pasos completados)
- Límites por plan (validación en 8 endpoints)
- Nutrición automática (BMR/TDEE/IMC → paquetes)
- Despliegue preparado (Dockerfile, nginx, render.yaml, Supabase)
- Migración SQLite↔PostgreSQL compatible
- Login multi-tenant por slug (fix: DNI ya no colisiona entre gyms)
- Endpoint público `GET /gym/{slug}` para personalizar login
- Frontends alumno/profesor personalizan login con nombre del gym
- PWA dinámica: manifest.json, icon.svg y service worker generados por gym
- QR en panel de configuración para compartir portal con socios
- TokenResponse incluye gimnasio_slug; staff frontend lo guarda en sessionStorage
- Dependencia qrcode==7.4.2 agregada a requirements.txt

### 🔲 Pendiente
- Subir a la nube (GitHub → Render + Supabase)
- Pasarela de pagos para suscripciones SaaS (Stripe/MercadoPago)
- Notificaciones (WhatsApp/email a clientes por vencimiento)
- Dashboard analytics avanzado para superadmin

---

## Base de datos real
- Gimnasio principal (id=1, plan Pro): ~1662 clientes activos
- Gimnasio de prueba (id=2, plan Free): 0 clientes (para testing)
- 2 planes: Free (50 clientes, 20 productos, 10 rutinas, 1 staff) y Pro (ilimitado, $49/mes)
