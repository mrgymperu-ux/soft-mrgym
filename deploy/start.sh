#!/bin/bash
# start.sh - Inicia backend (gunicorn) + nginx en un solo contenedor
# Render/Railway asignan $PORT; nginx escucha ahí y proxea al backend en 8000.

set -e

PORT=${PORT:-10000}

# Reemplazar el puerto en la config de nginx
sed -i "s/LISTEN_PORT/$PORT/g" /etc/nginx/nginx.conf

# Inyectar la URL del backend en los frontends (reemplaza localhost:8000)
# El backend corre internamente en :8000, pero desde el browser la URL
# es la misma del dominio (nginx hace proxy), así que API_BASE = ""
DOMAIN_URL=${RENDER_EXTERNAL_URL:-""}

# frontend-staff usa API_BASE_URL, los otros usan API_BASE
sed -i "s|http://localhost:8000|${DOMAIN_URL}|g" /app/frontend-staff/js/api.js
sed -i "s|http://localhost:8000|${DOMAIN_URL}|g" /app/frontend-alumno/js/api.js
sed -i "s|http://localhost:8000|${DOMAIN_URL}|g" /app/frontend-profesor/js/api.js

# Iniciar backend con gunicorn (mejor que uvicorn solo para producción)
cd /app
gunicorn backend.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 2 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - &

# Esperar a que el backend arranque
sleep 3

# Iniciar nginx en foreground (PID 1 para que Docker lo maneje)
nginx -g "daemon off;"
