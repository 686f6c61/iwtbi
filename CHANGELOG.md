# Changelog

Todos los cambios notables de IWTBI se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

---

## [1.0.0] — 2026-04-06

### Añadido
- Premedición del repositorio antes del análisis, con clasificación `normal`, `optimized` y `too_large`.
- Ticket one-shot para iniciar análisis y protección multicapa de la API con límites por endpoint.
- Biblioteca pública completa con paginación, ordenación, vista individual y reanálisis forzado.
- Notificaciones por email que permiten cerrar la pestaña sin perder el análisis cuando se registra correo.
- Documentación pública exhaustiva para self-hosting, esquema SQL canónico y copia saneada lista para publicar.

### Modificado
- Pipeline reforzado con reintentos frente a timeouts del proveedor LLM, síntesis de rescate y fallback determinista.
- UX responsive pulida en home, análisis y biblioteca, con mejores mensajes de espera y medición previa del repo.
- Footer unificado apuntando al repositorio público oficial del proyecto.

### Corregido
- Rutas y assets del frontend para evitar pantallas sin CSS y redirecciones incorrectas a `:8080` o a flujos de análisis nuevos.
- Cierre del flujo de análisis para renderizar el documento persistido igual que en biblioteca.
- Apertura de análisis guardados desde biblioteca y manejo del caché por SHA.

---

## [0.1.0] — 2026-04-04

### Añadido
- Biblioteca pública de análisis: listado paginado de todos los repositorios analizados.
- Vista individual de análisis (`/biblioteca/view?repo=owner/repo`) con documento completo.
- Caché de análisis en Supabase: los resultados se guardan asociados al SHA del commit.
- Invalidación automática del caché por SHA: banner de aviso si el repositorio ha cambiado.
- Popup modal antes del análisis: permite añadir email para notificación y forzar reanálisis.
- Notificaciones por email al completar el análisis (integración con Resend).
- Cancelación del pipeline de análisis si el cliente se desconecta sin email registrado.
- Fanout de emails: múltiples usuarios pueden suscribirse al mismo análisis en curso.
- `stream-client.ts` tipado con soporte de respuesta cacheada (`onCached`).
- Opción `force_new` en la API para ignorar el caché y lanzar un análisis fresco.

### Modificado
- `git_cloner` devuelve ahora `(path, sha)` en lugar de solo `path`.
- El orquestador desempaqueta el SHA y lo persiste junto con el documento.
- `analyze.astro` rediseñado con gestión de estado del popup y flujo cacheado.

---

## [0.0.4] — 2026-03-28

### Corregido
- Auditoría de resiliencia: manejo explícito de errores en todos los límites del sistema.
- Seguridad: eliminadas dependencias con versiones pinadas inseguras; se usan siempre las últimas.
- `ChatOllama` usa `async_client_kwargs` en lugar de `async_client` (compatibilidad con la versión actual del SDK).
- Mejoras de fiabilidad en el manejo de `asyncio.CancelledError` en el orquestador.

---

## [0.0.3] — 2026-03-21

### Añadido
- Soporte dual de proveedores LLM: **z.ai** (principal) y **Ollama Cloud** (alternativa).
- Configuración por variable de entorno para seleccionar el proveedor activo.

---

## [0.0.2] — 2026-03-14

### Añadido
- Frontend fiel al diseño Pencil: páginas Principal, Resultado, Cómo funciona.
- Componentes visuales neobrutalist: bordes negros, sombras desplazadas, coral de acento.
- Visualización en tiempo real del progreso de los 7 agentes mediante SSE.

---

## [0.0.1] — 2026-03-07

### Añadido
- Implementación inicial completa de IWTBI.
- Pipeline de análisis: clonar → leer → 7 agentes en paralelo → sintetizar.
- Agentes: Stack, Architecture, Database, API, Frontend, Logic, DevOps.
- Streaming de eventos SSE desde el backend al frontend.
- Documento Markdown final con las secciones de los 7 agentes.
- Documentación de diseño y arquitectura del sistema.
