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
          "Caché persistente en Supabase por repositorio y SHA.",
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
