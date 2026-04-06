# backend/Dockerfile
# Imagen mínima de Python 3.12 con git instalado para el clonado de repos.
# Se usa python:3.12-slim (no 3.14) para compatibilidad completa con LangChain.
#
# Seguridad: el proceso uvicorn se ejecuta como usuario no privilegiado «app»
# para limitar el radio de explosión si un repo clonado explotara una vulnerabilidad.

FROM python:3.12-slim

# git es necesario para el clonado de repositorios en el servicio GitCloner
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
# Stub mínimo del paquete: hatchling necesita que el directorio app/ exista
# para resolver los metadatos del wheel. El stub vacío satisface esa condición
# y permite cachear la capa de dependencias independientemente del código fuente.
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir .

# Sobreescribe el stub con el código fuente real.
# Esta capa se invalida solo cuando cambia app/, sin reinstalar dependencias.
COPY app/ ./app/

# Crear usuario no privilegiado antes de arrancar el proceso.
# En producción el backend usa el /tmp interno del contenedor para clonar
# repositorios temporales, evitando depender de permisos del host.
RUN addgroup --system app && adduser --system --ingroup app app
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
