// astro.config.mjs
// Modo estático: genera HTML/CSS/JS puro, servido por nginx.
// Sin SSR ni adaptador: el análisis ocurre completamente en el frontend
// vía EventSource conectado al backend FastAPI.
//
// Sitemap: @astrojs/sitemap genera automáticamente /sitemap-index.xml
// y /sitemap-0.xml en build time a partir de las rutas estáticas detectadas.
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: process.env.PUBLIC_APP_URL || 'http://localhost:3410',
  output: 'static',
  integrations: [
    sitemap(),
  ],
});
