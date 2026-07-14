# IWTBI Browser Extension

Extensión 2.0 compartida para Chrome y Firefox con estética IWTBI.

Qué hace:

- Se activa solo cuando la pestaña actual tiene una URL válida de repositorio de GitHub.
- Distingue repositorios de páginas de producto como Settings, Copilot o Marketplace.
- Abre tu instancia de IWTBI con la URL del repo ya preparada para crear el documento.
- Inyecta un acceso directo configurable en modo destacado, compacto u oculto.
- Muestra iconos distintos para los estados activo e inactivo.
- Incluye acceso directo a la biblioteca de tu instancia.
- Solicita únicamente almacenamiento local y acceso al host `github.com`.

## Build

```bash
npm install
npm test
IWTBI_APP_URL=https://iwtbi.example npm run build
```

Salida:

- `dist/chrome`
- `dist/firefox`

`IWTBI_APP_URL` es obligatorio en una distribución self-host: el valor queda
integrado en la extensión. Para conservar una identidad estable en Firefox,
define también `IWTBI_FIREFOX_EXTENSION_ID` antes de compilar.

## Cargar en Chrome

1. Abre `chrome://extensions`
2. Activa `Developer mode`
3. Pulsa `Load unpacked`
4. Selecciona la carpeta `extension/dist/chrome`

## Cargar en Firefox

1. Abre `about:debugging#/runtime/this-firefox`
2. Pulsa `Load Temporary Add-on`
3. Selecciona `extension/dist/firefox/manifest.json`

## Notas

- El popup funciona como acceso al servicio; el análisis se ejecuta en IWTBI.
- La franja inline usa un selector robusto y sigue los cambios de navegación interna de GitHub.
- Los iconos activo/inactivo y los paquetes de Chrome y Firefox se generan desde las fuentes compartidas.
