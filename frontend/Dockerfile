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
ARG PUBLIC_APP_URL=http://localhost:3410
ARG PUBLIC_AUTHOR_URL=
ARG PUBLIC_AUTHOR_LABEL=
ARG PUBLIC_SOURCE_URL=
ARG PUBLIC_SOCIAL_HANDLE=
ARG PUBLIC_LINKEDIN_URL=
ARG PUBLIC_EXTENSION_DOWNLOADS_ENABLED=false
ENV PUBLIC_BACKEND_URL=${PUBLIC_BACKEND_URL}
ENV PUBLIC_APP_URL=${PUBLIC_APP_URL}
ENV PUBLIC_AUTHOR_URL=${PUBLIC_AUTHOR_URL}
ENV PUBLIC_AUTHOR_LABEL=${PUBLIC_AUTHOR_LABEL}
ENV PUBLIC_SOURCE_URL=${PUBLIC_SOURCE_URL}
ENV PUBLIC_SOCIAL_HANDLE=${PUBLIC_SOCIAL_HANDLE}
ENV PUBLIC_LINKEDIN_URL=${PUBLIC_LINKEDIN_URL}
ENV PUBLIC_EXTENSION_DOWNLOADS_ENABLED=${PUBLIC_EXTENSION_DOWNLOADS_ENABLED}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build
RUN node -e "const fs=require('node:fs'); const u=new URL(process.env.PUBLIC_BACKEND_URL); let c=fs.readFileSync('nginx-spa.conf','utf8').replaceAll('__PUBLIC_BACKEND_ORIGIN__',u.origin).replaceAll('__CSP_UPGRADE__',process.env.PUBLIC_APP_URL.startsWith('https://')?'upgrade-insecure-requests;':''); fs.writeFileSync('nginx-spa.generated.conf',c)"

# --- Etapa final: nginx-unprivileged sirve los archivos estáticos ---
# nginx-unprivileged no requiere root: escucha en puerto 8080 por defecto
# y el proceso worker nunca eleva privilegios.
FROM nginxinc/nginx-unprivileged:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY --from=builder /app/nginx-spa.generated.conf /etc/nginx/conf.d/default.conf

USER 101:101

EXPOSE 8080
