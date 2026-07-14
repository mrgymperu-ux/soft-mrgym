# 🚀 Guía de Despliegue - Soft-Gym
> Costo total: **$0/mes** (Supabase BD gratis permanente + Render web gratis)

## Paso 1: Crear la base de datos en Supabase (gratis, permanente)

1. Ir a **https://supabase.com** → crear cuenta (con GitHub)
2. Click **"New Project"**
   - Name: `soft-mrgym`
   - Database Password: generar una segura y **guardarla**
   - Region: **South America (São Paulo)** (más cerca a Perú)
3. Esperar ~2 min a que se cree
4. Ir a **Settings → Database → Connection string → URI**
5. Copiar la URI, se ve así:
   ```
   postgresql://postgres.[ref]:[PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:6543/postgres
   ```
6. Reemplazar `[PASSWORD]` con la contraseña que guardaste
7. **Importante:** cambiar el puerto de `6543` a `5432` y agregar `?sslmode=require` al final:
   ```
   postgresql://postgres.[ref]:TU_PASSWORD@aws-0-sa-east-1.pooler.supabase.com:5432/postgres?sslmode=require
   ```

Esa es tu `DATABASE_URL`. Guárdala.

## Paso 2: Subir el código a GitHub

```bash
cd D:\Soft-MrGym
git init
git add .
git commit -m "Soft-Gym ready for deployment"
```

Crear repositorio en github.com (puede ser privado), luego:
```bash
git remote add origin https://github.com/TU-USUARIO/soft-mrgym.git
git push -u origin main
```

## Paso 3: Crear el web service en Render.com

1. Ir a **https://render.com** → crear cuenta (con GitHub)
2. Click **"New +"** → **"Blueprint"**
3. Conectar tu repositorio `soft-mrgym`
4. Render detecta `render.yaml` y muestra el servicio a crear
5. Configurar la variable **DATABASE_URL**: pegar la URI de Supabase del Paso 1
6. Click **"Apply"** → esperar ~5 min al primer build

## Paso 4: Acceder

Render te asigna una URL como:
```
https://soft-mrgym.onrender.com
```

| Portal | URL |
|--------|-----|
| Panel Staff | `https://soft-mrgym.onrender.com/login.html` |
| Portal Alumno | `https://soft-mrgym.onrender.com/alumno/login.html` |
| Zona Profesores | `https://soft-mrgym.onrender.com/profesor/login.html` |
| API Docs | `https://soft-mrgym.onrender.com/docs` |

## Paso 5: Crear el primer usuario

La BD está vacía. El sistema siembra automáticamente los catálogos (ejercicios, alimentos, etc.) al arrancar. Para crear tu gimnasio y admin, entra a:

```
https://soft-mrgym.onrender.com/registro.html
```

---

## ¿Por qué Supabase + Render?

| | Render PostgreSQL | Supabase |
|---|---|---|
| Gratis | ✅ pero **expira a los 90 días** | ✅ **permanente** |
| Almacenamiento | 1 GB | 500 MB (~50 gyms) |
| Dashboard | Solo connection string | UI completa, editor SQL, backups |
| Región | US/EU | **São Paulo** (más cerca a Lima) |

---

## Migrar datos desde SQLite local

Para llevar tus 1662 clientes a Supabase:

**Opción A: pgloader (recomendada)**
```bash
# En WSL o Linux
pgloader sqlite:///ruta/a/sql_app.db "postgresql://postgres.[ref]:PASS@host:5432/postgres?sslmode=require"
```

**Opción B: Exportar/importar CSV**
Usar los endpoints existentes `/clientes/importar`, `/membresias/importar`, etc.

---

## Costos si escalas

| Nivel | Gyms | Hosting/mes | Se paga con... |
|-------|------|-------------|----------------|
| Gratis | 1-50 | $0 | Nada |
| Starter | 50-200 | ~$12 (Render $7 + Supabase Pro $25 si necesitas más espacio) | 1 gym Pro ($49) |
| Growth | 200+ | ~$50 | 2 gyms Pro |

---

## Variables de entorno (resumen)

| Variable | Dónde | Valor |
|----------|-------|-------|
| `DATABASE_URL` | Render dashboard | URI de Supabase (ver Paso 1) |
| `SECRET_KEY` | Render genera automáticamente | — |
| `CORS_ORIGINS` | render.yaml | `*` (o dominio específico) |

---

## Notas técnicas

- El web service de Render **se duerme** tras 15 min sin uso (tarda ~30s en despertar). Con múltiples gyms activos, rara vez duerme.
- La BD en Supabase **nunca se apaga** — siempre disponible.
- Las fotos subidas (clientes/productos) se pierden al redesplegar (el filesystem de Render es efímero). Para producción real, migrar uploads a Supabase Storage o Cloudflare R2.
