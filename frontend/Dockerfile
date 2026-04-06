# frontend/Dockerfile
# Construcción multi-etapa:
# - Etapa builder: instala dependencias y genera el sitio estático con Astro.
# - Etapa final: nginx-unprivileged + los archivos estáticos generados.
# El resultado es una imagen mínima sin Node.js en producción.
#
# Seguridad: se usa nginxinc/nginx-unprivileged que arranca en puerto 8080
# sin necesitar root en ningún momento del ciclo de vida del contenedor.

FROM node:22-slim AS builder

WORKDIR /app

ARG PUBLIC_BACKEND_URL=http://localhost:8410
ENV PUBLIC_BACKEND_URL=${PUBLIC_BACKEND_URL}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- Etapa final: nginx-unprivileged sirve los archivos estáticos ---
# nginx-unprivileged no requiere root: escucha en puerto 8080 por defecto
# y el proceso worker nunca eleva privilegios.
FROM nginxinc/nginx-unprivileged:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
