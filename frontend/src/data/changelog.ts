/**
 * Datos del changelog de IWTBI.
 *
 * Fuente de verdad para el popup de changelog en el footer.
 * Sincronizar manualmente con /CHANGELOG.md al publicar una nueva versión.
 *
 * Las categorías siguen la convención de Keep a Changelog:
 * «added» | «changed» | «fixed»
 */

export type CategoryType = "added" | "changed" | "fixed";

export interface ChangelogSection {
  type: CategoryType;
  items: string[];
}

export interface ChangelogEntry {
  version: string;
  date: string;
  sections: ChangelogSection[];
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "2.1.1",
    date: "14 jul 2026",
    sections: [
      {
        type: "fixed",
        items: [
          "El icono de la extensión en Chrome y Firefox usa ahora el favicon oficial de IWTBI en todos sus estados y tamaños.",
          "El empaquetado parte de una única imagen de marca y una prueba comprueba que ambos manifiestos apuntan al icono correcto.",
        ],
      },
    ],
  },
  {
    version: "2.1.0",
    date: "14 jul 2026",
    sections: [
      {
        type: "added",
        items: [
          "Perfiles privados de IA por análisis interno, inspirados por la propuesta de @lacrimae0rerum en la PR pública #1.",
          "Perfiles con nombre configurados en el servidor para NaN, z.ai, Ollama Cloud y endpoints OpenAI-compatible.",
        ],
      },
      {
        type: "changed",
        items: [
          "Elegir un perfil distinto del predeterminado desde la ruta interna crea un informe nuevo para respetar el modelo seleccionado.",
          "La selección queda restringida al servidor y no aparece en la interfaz pública ni en el estado de salud.",
          "Cada instalación self-host puede definir sus propios perfiles internos sin heredar datos ni claves de producción.",
        ],
      },
      {
        type: "fixed",
        items: [
          "Redis maneja únicamente el identificador del perfil; las claves y URL privadas se resuelven dentro de la API y el worker.",
          "Los perfiles desconocidos, incompletos, duplicados o con URL no válida se rechazan antes de iniciar el análisis.",
        ],
      },
    ],
  },
  {
    version: "2.0.0",
    date: "14 jul 2026",
    sections: [
      {
        type: "added",
        items: [
          "Ocho agentes con identidad propia: Grace Hopper, Alan Kay, Barbara Liskov, Roy Fielding, Hedy Lamarr, Donald Knuth y Lynn Conway como especialistas, con Margaret Hamilton como integradora y validadora.",
          "Documento de reconstrucción autocontenido: URL y commit de origen, árbol objetivo, orden de construcción, contratos, diagramas Mermaid, tablas, criterios de aceptación, evidencias e incógnitas.",
          "Extensión 2.0 para Chrome y Firefox con permisos mínimos, iconos de estado reales, detección más estricta de repositorios, acceso a Biblioteca, controles accesibles y tolerancia a errores del navegador.",
          "Distribución self-host autónoma con PostgreSQL y Redis vacíos, worker dedicado, proveedor OpenAI-compatible genérico, marca configurable y generación local de secretos.",
        ],
      },
      {
        type: "changed",
        items: [
          "Los siete especialistas conservan íntegros sus informes y Margaret Hamilton añade un plano transversal sin resumir ni borrar el detalle necesario para construir.",
          "Ejecución limitada a tres llamadas de IA simultáneas en lotes 3 + 3 + 1, seguida de la integración; el proveedor principal y sus respaldos son configurables.",
          "Migración de persistencia a PostgreSQL y límites públicos ajustados a 10 análisis por hora, 20 preflight y 60 tickets por minuto e IP.",
          "Se retiró Google Analytics, incluido el consentimiento, el texto legal y sus permisos de red.",
        ],
      },
      {
        type: "fixed",
        items: [
          "Mermaid mantiene etiquetas legibles, contraste claro y desplazamiento horizontal en diagramas densos, tanto en análisis en vivo como en Biblioteca.",
          "Seguridad reforzada con proxies confiables, token para análisis internos, bajas con caducidad, lectura de archivos acotada, sanitización Markdown, Redis para rate limits y dependencias actualizadas.",
          "Suite y CI recuperadas con pruebas del backend, frontend y extensión, incluyendo el detector de URLs de GitHub.",
          "Export público protegido contra bases locales, secretos, artefactos de producción, migraciones internas, paquetes precompilados y cachés de desarrollo.",
        ],
      },
    ],
  },
  {
    version: "1.0.1",
    date: "7 abr 2026",
    sections: [
      {
        type: "added",
        items: [
          "Extensión oficial para Chrome y Firefox, con detección de repos GitHub, banner inyectado y descargas públicas desde la web.",
          "Suscripción opcional a futuros análisis del mismo repo, con enlaces de baja por repo o global desde el correo.",
          "Página de preferencias de avisos y carril interno para backfills administrativos sin depender del rate limit público.",
        ],
      },
      {
        type: "changed",
        items: [
          "Infra preparada para separar API y ejecución: Redis como cola de jobs, worker dedicado y ruta interna de administración.",
          "Sección Cómo funciona ampliada con la experiencia real de la extensión y su configuración dentro de GitHub.",
          "Changelog del footer sincronizado con el repositorio para reflejar esta nueva versión 1.0.1.",
        ],
      },
      {
        type: "fixed",
        items: [
          "Los correos pendientes ya siguen el repo correcto aunque el análisis cierre en un reintento distinto al job original.",
          "La pantalla de análisis renderiza mejor el documento final en vivo, incluyendo Mermaid y cierre visual consistente con biblioteca.",
          "Los errores parciales de agentes ya no aparecen incrustados como texto interno dentro del documento final.",
        ],
      },
    ],
  },
  {
    version: "1.0.0",
    date: "6 abr 2026",
    sections: [
      {
        type: "added",
        items: [
          "Premedición del repositorio antes del análisis, con modos normal, optimizado y bloqueo por tamaño en el plan gratuito.",
          "Protección de la API con ticket one-shot, rate limits por endpoint y validación de origen en endpoints de escritura.",
          "Biblioteca pública completa: listado paginado, ordenación, vista individual y reanálisis forzado.",
          "Notificaciones por email que permiten cerrar la pestaña sin perder el análisis cuando se registra correo.",
          "Documentación pública completa para self-hosting y copia saneada del proyecto lista para liberar a la comunidad.",
        ],
      },
      {
        type: "changed",
        items: [
          "Pipeline más resistente: reintentos al proveedor LLM, síntesis de rescate y fallback determinista para no perder análisis válidos.",
          "Frontend responsive pulido en home, pantalla de análisis y biblioteca, con mejores estados de espera y mensajes de producto.",
          "Footer unificado y enlazado al repositorio público oficial en GitHub.",
        ],
      },
      {
        type: "fixed",
        items: [
          "Correcciones de enrutado y assets para evitar pérdidas de CSS y redirecciones incorrectas en rutas internas.",
          "Correcciones en el cierre del análisis para renderizar correctamente el documento final también fuera de la biblioteca.",
          "Ajustes de caché, SHA y flujo de ver análisis para abrir siempre el documento correcto guardado.",
        ],
      },
    ],
  },
  {
    version: "0.1.0",
    date: "4 abr 2026",
    sections: [
      {
        type: "added",
        items: [
          "Biblioteca pública de análisis con listado y vista individual.",
          "Caché persistente por repositorio y SHA.",
          "Popup previo al análisis con email opcional y soporte de reanálisis.",
          "Notificaciones por email cuando el análisis termina.",
        ],
      },
    ],
  },
  {
    version: "0.0.1",
    date: "7 mar 2026",
    sections: [
      {
        type: "added",
        items: [
          "Implementación inicial del pipeline: clonar → leer → 7 agentes → sintetizar.",
          "Siete agentes especializados: Stack, Architecture, Database, API, Frontend, Logic, DevOps.",
          "Streaming de eventos SSE del backend al frontend.",
          "Documento Markdown final unificado por el sintetizador.",
        ],
      },
    ],
  },
];
