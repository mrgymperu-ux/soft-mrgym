# Dockerfile para Soft-MrGym (backend + frontends en un solo contenedor)
# Usa Python slim + nginx para servir todo desde un solo servicio gratis.

FROM python:3.12-slim

# Instalar nginx para servir los frontends estáticos
RUN apt-get update && apt-get install -y --no-install-recommends nginx && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias Python
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt gunicorn

# Copiar backend
COPY backend/ /app/backend/

# Copiar frontends
COPY frontend-staff/ /app/frontend-staff/
COPY frontend-alumno/ /app/frontend-alumno/
COPY frontend-profesor/ /app/frontend-profesor/

# Crear directorio de uploads (persistente si se monta volumen)
RUN mkdir -p /app/backend/uploads/clientes /app/backend/uploads/productos /app/backend/uploads/ejercicios /app/backend/uploads/logos

# Configuración de nginx
COPY deploy/nginx.conf /etc/nginx/nginx.conf

# Script de inicio
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Puerto único (Render/Railway asignan $PORT)
EXPOSE ${PORT:-10000}

CMD ["/app/start.sh"]
