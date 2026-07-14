# Changelog

Todos los cambios notables de IWTBI se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

---

## [2.1.0] — 2026-07-14

### Añadido
- Perfiles privados de IA por análisis interno, inspirados por la propuesta de @lacrimae0rerum en la PR pública #1.
- Perfiles con nombre configurados íntegramente en el servidor mediante `LLM_PROFILES_JSON`, compatibles con NaN, z.ai, Ollama Cloud y endpoints OpenAI-compatible.
- Validación al arrancar para detectar perfiles duplicados, incompletos o con URL no válida antes de aceptar tráfico.

### Modificado
- Los análisis con un perfil distinto del predeterminado generan un informe nuevo en lugar de reutilizar silenciosamente una caché creada con otro modelo.
- La selección queda restringida a la ruta interna protegida; no aparece en la web pública ni en `/health`.
- La configuración self-host permite publicar tantos perfiles como necesite cada instalación sin incluir datos ni claves de IWTBI producción.

### Corregido
- Las claves y URL privadas no pasan por el navegador, `localStorage`, los trabajos de Redis ni la Biblioteca; la ruta interna envía únicamente un identificador validado.
- API y worker resuelven el mismo perfil al ejecutar el trabajo, manteniendo la selección después de pasar por la cola Redis.
- Perfiles inexistentes, duplicados, incompletos o con URL no HTTP(S) se rechazan antes de consumir recursos de análisis.

---

## [2.0.0] — 2026-07-14

### Añadido
- Ocho agentes con identidad propia: Grace Hopper, Alan Kay, Barbara Liskov, Roy Fielding, Hedy Lamarr, Donald Knuth y Lynn Conway como especialistas, con Margaret Hamilton como integradora y validadora.
- Documento de reconstrucción autocontenido: URL y commit de origen, árbol de archivos objetivo, orden de construcción, contratos, diagramas Mermaid, tablas, criterios de aceptación, evidencias e incógnitas.
- Secciones especializadas con instrucciones concretas, rutas exactas y detalle suficiente para copiar o descargar el Markdown y entregarlo a otra IA para reconstruir el proyecto.
- Extensión 2.0 para Chrome y Firefox con permisos mínimos, iconos activo/inactivo reales, detección más estricta de repositorios, acceso directo a Biblioteca, controles accesibles y tolerancia a errores del navegador.
- Tests automatizados del detector de URLs de la extensión para rutas válidas, subrutas, páginas reservadas y entradas inválidas.
- Distribución self-host autónoma con PostgreSQL y Redis vacíos, worker dedicado, configuración de marca y URLs, proveedor OpenAI-compatible genérico y generador local de secretos.

### Modificado
- Los siete especialistas conservan íntegros sus informes y Margaret Hamilton añade un plano transversal sin resumir ni borrar sus diagramas, tablas o contratos.
- Ejecución limitada a tres llamadas de IA simultáneas en lotes `3 + 3 + 1`, seguida de la llamada de integración de Hamilton.
- Proveedor principal configurable, con soporte OpenAI-compatible genérico y perfiles de NaN, Ollama Cloud y z.ai para completar trabajos ante errores o límites del proveedor.
- Persistencia de Biblioteca migrada a PostgreSQL y almacenamiento compartido de rate limits preparado en Redis.
- Límites públicos ajustados a 10 análisis por hora, 20 preflight por minuto y 60 tickets por minuto e IP.
- Documentación pública y extensión alineadas con el objetivo real de IWTBI: producir un documento de construcción reutilizable por una IA.
- Google Analytics retirado completamente, junto con el banner de consentimiento, la mención legal y los orígenes externos de la CSP.

### Corregido
- Diagramas Mermaid con etiquetas legibles, contraste claro, tamaño estable y desplazamiento horizontal para grafos densos en análisis y Biblioteca.
- Resolución segura de IP cliente mediante proxies confiables, sin aceptar cabeceras reenviadas arbitrarias desde conexiones directas.
- Ruta interna de análisis protegida por token, enlaces de baja con caducidad y lectura de archivos limitada antes de cargar su contenido completo.
- Renderizado Markdown endurecido, dependencias vulnerables actualizadas y suite SSE reparada para que CI vuelva a validar backend, frontend y extensión.
- Estado de la extensión sincronizado con la pestaña actual y fallos de APIs del navegador controlados sin promesas rechazadas sin manejar.
- Export público endurecido para excluir bases locales, claves, artefactos de producción, migraciones internas, paquetes precompilados y cachés de desarrollo.

---

## [1.0.1] — 2026-04-07

### Añadido
- Extensión oficial de navegador para Chrome y Firefox, con banner inyectado en repos GitHub y descargas públicas desde la web.
- Suscripción opcional a avisos futuros por repositorio, con baja por repo o global desde enlaces firmados en email.
- Página pública de gestión de avisos (`/notificaciones`) y carril interno para backfills sin depender del rate limit público.

### Modificado
- Infra preparada para separar API y ejecución de análisis: cola en Redis, worker dedicado y ruta interna de administración.
- Changelog del producto actualizado en el footer y sincronizado con el changelog del repositorio.
- Sección "Cómo funciona" ampliada con la experiencia real de la extensión y su configuración visual.

### Corregido
- El envío de emails ya sigue el `repo_url` y no se pierde cuando un análisis termina correctamente en un reintento distinto.
- La pantalla de análisis renderiza mejor el documento final en vivo, incluyendo Mermaid y cierre visual más consistente con biblioteca.
- Los fallos parciales de agentes ya no muestran textos de error internos dentro del documento final guardado.

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
- Caché de análisis persistente: los resultados se guardan asociados al SHA del commit.
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
