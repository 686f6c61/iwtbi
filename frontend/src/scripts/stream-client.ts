/**
 * Cliente SSE para consumir el stream de eventos del análisis IWTBI.
 *
 * Gestiona la conexión con el backend, despacha eventos mediante callbacks
 * y cierra automáticamente el stream al recibir 'complete' o 'analysis_error'.
 * También maneja las respuestas cacheadas (sin abrir SSE).
 *
 * Separar este cliente en su propio módulo permite testearlo de forma
 * aislada y reutilizarlo en cualquier página que necesite streaming.
 */

/** URL base del backend. En Docker, el frontend accede al backend por nombre de servicio. */
const BACKEND_URL =
  (import.meta as unknown as { env: Record<string, string> }).env
    ?.PUBLIC_BACKEND_URL ?? "http://localhost:8410";

/**
 * Margen antes de considerar fatal un `EventSource.onerror`.
 *
 * El backend emite comentarios SSE `: ping` cada 15s para mantener vivo el
 * stream, pero los comentarios no llegan como eventos al navegador. Detrás de
 * proxies/CDNs es normal recibir `onerror` transitorios durante un reconnect.
 * Damos margen suficiente para que EventSource recupere la conexión antes de
 * declarar el análisis como interrumpido.
 */
const STREAM_ERROR_GRACE_MS = 25_000;

/** Datos del evento emitido cuando un agente completa su sección. */
export interface AgentEventData {
  /** Nombre identificador del agente (hopper, kay, liskov, etc.). */
  agent: string;
  /** Sección Markdown generada por el agente. */
  section: string;
}

/** Datos emitidos cuando un agente no puede completar su sección. */
export interface AgentErrorEventData {
  /** Nombre identificador del agente (hopper, kay, liskov, etc.). */
  agent: string;
  /** Mensaje legible asociado al fallo del agente. */
  message: string;
}

/** Datos de una respuesta cacheada del backend. */
export interface CachedAnalysisData {
  /** Documento Markdown completo del análisis cacheado. */
  document: string;
  /** Nombre «owner/repo» del repositorio. */
  repo_full_name: string;
  /** Fecha de la última actualización del análisis. */
  updated_at: string;
  /** Si el SHA actual difiere del cacheado (posibles cambios en el repo). */
  has_changes: boolean;
}

/** Capacidades expuestas por el backend para adaptar la UI del frontend. */
export interface BackendCapabilities {
  /** Si true, el backend está listo para enviar avisos por email. */
  emailNotificationsEnabled: boolean;
}

/** Resultado de la premedición del repositorio antes del análisis. */
export interface RepoPreflightData {
  /** Modo de análisis previsto según el tamaño útil del repo. */
  mode: "normal" | "optimized" | "too_large";
  /** Motivo estructurado de la decisión. */
  reason:
    | "fits_context"
    | "prioritized_context"
    | "context_budget_exceeded"
    | "file_count_limit"
    | "repo_size_limit";
  /** Archivos de texto legibles considerados. */
  candidate_files: number;
  /** Archivos cuyo contenido se midió en detalle tras priorización interna. */
  measured_candidate_files?: number | null;
  /** Archivos que entrarían al contexto actual. */
  selected_files: number;
  /** Total de caracteres útiles detectados. */
  total_candidate_chars: number;
  /** Caracteres que caben en el contexto actual. */
  selected_chars: number;
  /** Archivos truncados por el límite por archivo. */
  oversized_files: number;
  /** Archivos truncados por el límite global restante. */
  budget_truncated_files: number;
  /** Límite gratuito actual de archivos candidatos permitidos. */
  candidate_file_limit: number;
  /** Si true, el backend detectó más texto del que midió en detalle. */
  measurement_limited?: boolean;
  /** Tamaño bruto estimado del repositorio según GitHub, si el bloqueo vino por MB. */
  repo_size_kb?: number | null;
  /** Límite bruto de MB permitido por la plataforma. */
  repo_size_limit_mb?: number | null;
}

/** Opciones opcionales para el inicio del análisis. */
export interface StartAnalysisOptions {
  /** Si true, fuerza un análisis nuevo ignorando el caché. */
  forceNew?: boolean;
  /** Email para notificación cuando el análisis termine (permite cerrar la pestaña). */
  email?: string;
  /** Si true, el email queda suscrito a avisos futuros del repo cuando cambie el SHA. */
  subscribeUpdates?: boolean;
  /** Ticket efímero emitido por el backend para autorizar el análisis. */
  ticket?: string;
}

/** Resultado inmediato del alta del análisis en el backend. */
export interface StartAnalysisResult {
  /** Si true, el backend aceptó la petición y el análisis ya existe. */
  accepted: boolean;
  /** Si true, el backend devolvió una respuesta cacheada y no abrió SSE. */
  cached: boolean;
  /** Función para cerrar el stream SSE cuando exista. */
  cancel: () => void;
}

/** Callbacks para cada tipo de evento SSE. */
export interface StreamCallbacks {
  /** Llamado cuando cambia el estado global del análisis (cloning, analyzing, synthesizing). */
  onStatus: (status: string) => void;
  /** Llamado cuando un agente completa su sección. */
  onAgent: (data: AgentEventData) => void;
  /** Llamado cuando un agente falla pero el pipeline continúa. */
  onAgentError?: (data: AgentErrorEventData) => void;
  /** Llamado cuando el sintetizador produce el documento final completo. */
  onComplete: (document: string) => void;
  /** Llamado si el análisis falla en cualquier fase. */
  onError: (message: string) => void;
  /** Llamado si el backend devuelve un análisis cacheado (sin SSE). */
  onCached?: (data: CachedAnalysisData) => void;
}

/**
 * Parsea de forma segura el campo `data` de un MessageEvent SSE.
 *
 * @param e - Evento SSE recibido.
 * @returns El objeto parseado, o null si el JSON es inválido.
 */
function parseEventData(e: Event): Record<string, unknown> | null {
  try {
    return JSON.parse((e as MessageEvent).data);
  } catch {
    return null;
  }
}

/**
 * Convierte respuestas de error heterogéneas del backend (string, array de
 * validación, objetos anidados) en un mensaje corto y legible para la UI.
 */
function normalizeErrorMessage(input: unknown, fallback: string): string {
  if (typeof input === "string") {
    const text = input.trim();
    return text || fallback;
  }

  if (input instanceof Error) {
    return normalizeErrorMessage(input.message, fallback);
  }

  if (typeof input === "number" || typeof input === "boolean") {
    return String(input);
  }

  if (Array.isArray(input)) {
    const messages = input
      .map((item) => normalizeValidationMessage(item))
      .filter((value): value is string => Boolean(value));
    return messages[0] ?? fallback;
  }

  if (input && typeof input === "object") {
    const record = input as Record<string, unknown>;
    const nestedMessage =
      pickNormalizedMessage(record.detail) ??
      pickNormalizedMessage(record.message) ??
      pickNormalizedMessage(record.error);
    return normalizeValidationMessage(record) ?? nestedMessage ?? fallback;
  }

  return fallback;
}

function normalizeValidationMessage(input: unknown): string | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return null;
  }

  const record = input as Record<string, unknown>;
  const rawMessage =
    typeof record.msg === "string"
      ? record.msg
      : typeof record.message === "string"
        ? record.message
        : null;

  if (!rawMessage?.trim()) {
    return null;
  }

  const location = Array.isArray(record.loc)
    ? record.loc
        .filter((part): part is string | number => typeof part === "string" || typeof part === "number")
        .join(" > ")
    : "";

  const normalizedMessage = rawMessage.trim();
  if (location.endsWith("email")) {
    return "El email no es válido. Revísalo e inténtalo de nuevo.";
  }

  if (location.endsWith("url")) {
    return "La URL del repositorio no es válida. Usa un repositorio público de GitHub.";
  }

  if (/field required/i.test(normalizedMessage)) {
    return "Falta un dato obligatorio para iniciar el análisis.";
  }

  return normalizedMessage;
}

function pickNormalizedMessage(input: unknown): string | null {
  const message = normalizeErrorMessage(input, "");
  return message.trim() ? message : null;
}

/**
 * Solicita un ticket efímero para autorizar el siguiente POST /api/analyze.
 *
 * El ticket se pide justo antes del análisis para evitar que caduque mientras
 * el usuario sigue leyendo el popup o escribiendo su email.
 */
export async function getAnalysisTicket(): Promise<string> {
  const response = await fetch(`${BACKEND_URL}/api/ticket`);
  if (!response.ok) {
    throw new Error("No se pudo obtener el ticket de análisis");
  }

  const data = (await response.json()) as { ticket?: string };
  if (!data.ticket) {
    throw new Error("La respuesta del ticket es inválida");
  }

  return data.ticket;
}

/**
 * Consulta la salud del backend y las capacidades públicas relevantes para la UI.
 */
export async function getBackendCapabilities(): Promise<BackendCapabilities> {
  const response = await fetch(`${BACKEND_URL}/health`);
  if (!response.ok) {
    throw new Error("No se pudo obtener el estado del backend");
  }

  const data = (await response.json()) as {
    email_notifications_enabled?: boolean;
  };

  return {
    emailNotificationsEnabled: Boolean(data.email_notifications_enabled),
  };
}

/**
 * Mide el tamaño útil del repo para decidir si el análisis puede ser normal,
 * optimizado o si conviene bloquearlo por tamaño.
 */
export async function measureRepositoryContext(
  repoUrl: string,
): Promise<RepoPreflightData> {
  const response = await fetch(`${BACKEND_URL}/api/preflight`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url: repoUrl }),
  });

  if (!response.ok) {
    const err = await response
      .json()
      .catch(() => ({ detail: "No se pudo medir el repositorio" }));
    throw new Error(normalizeErrorMessage(err, "No se pudo medir el repositorio"));
  }

  return (await response.json()) as RepoPreflightData;
}

/**
 * Inicia el análisis de un repositorio y abre el stream SSE de eventos.
 *
 * Primero hace POST /api/analyze para crear el job u obtener el caché.
 * - Si la respuesta tiene `cached: true`, llama a `onCached` (sin SSE).
 * - Si la respuesta tiene `cached: false`, abre EventSource y despacha eventos.
 *
 * @param repoUrl - URL del repositorio GitHub a analizar.
 * @param callbacks - Manejadores para cada tipo de evento SSE.
 * @param options - Opciones adicionales: forceNew y email.
 * @returns Función para cancelar el stream (cierra el EventSource si está abierto).
 *
 * @example
 * const cancel = await startAnalysis("https://github.com/user/repo", {
 *   onStatus: (s) => console.log("Estado:", s),
 *   onAgent: (d) => console.log("Agente", d.agent, "completado"),
 *   onComplete: (doc) => console.log("Documento listo", doc.length, "chars"),
 *   onError: (msg) => console.error("Error:", msg),
 *   onCached: (data) => console.log("Caché", data.has_changes ? "(cambios)" : ""),
 * }, { email: "user@example.com" });
 */
export async function startAnalysis(
  repoUrl: string,
  callbacks: StreamCallbacks,
  options: StartAnalysisOptions = {},
): Promise<StartAnalysisResult> {
  const ticket = options.ticket;
  if (!ticket) {
    callbacks.onError(
      "No se pudo validar la solicitud. Recarga la página y vuelve a intentarlo.",
    );
    return { accepted: false, cached: false, cancel: () => {} };
  }

  // Paso 1: Crear el job o consultar caché en el backend
  let responseData: Record<string, unknown>;
  try {
    const response = await fetch(`${BACKEND_URL}/api/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Ticket": ticket,
      },
      body: JSON.stringify({
        url: repoUrl,
        force_new: options.forceNew ?? false,
        email: options.email ?? null,
        subscribe_updates: options.subscribeUpdates ?? false,
      }),
    });

    if (!response.ok) {
      const err = await response
        .json()
        .catch(() => ({ detail: "Error desconocido" }));
      callbacks.onError(normalizeErrorMessage(err, "Error al iniciar el análisis"));
      return { accepted: false, cached: false, cancel: () => {} };
    }

    responseData = await response.json();
  } catch {
    callbacks.onError("No se pudo conectar con el servidor de análisis");
    return { accepted: false, cached: false, cancel: () => {} };
  }

  // Paso 2a: Respuesta cacheada — no se abre SSE
  if (responseData.cached === true) {
    if (callbacks.onCached) {
      callbacks.onCached({
        document: responseData.document as string,
        repo_full_name: responseData.repo_full_name as string,
        updated_at: responseData.updated_at as string,
        has_changes: responseData.has_changes as boolean,
      });
    } else {
      // Fallback si no se proporcionó onCached: tratar como onComplete
      callbacks.onComplete(responseData.document as string);
    }
    return { accepted: true, cached: true, cancel: () => {} };
  }

  // Paso 2b: Análisis nuevo — abrir el stream SSE
  const streamUrl = `${BACKEND_URL}${responseData.stream_url as string}`;
  const source = new EventSource(streamUrl);
  let settled = false;
  let reconnectErrorTimer: number | null = null;

  function clearReconnectErrorTimer() {
    if (reconnectErrorTimer === null) {
      return;
    }
    window.clearTimeout(reconnectErrorTimer);
    reconnectErrorTimer = null;
  }

  function markStreamHealthy() {
    clearReconnectErrorTimer();
  }

  function failInterruptedConnection() {
    if (settled) {
      return;
    }
    settled = true;
    clearReconnectErrorTimer();
    callbacks.onError("Conexión interrumpida con el servidor");
    source.close();
  }

  source.addEventListener("status", (e: Event) => {
    const data = parseEventData(e);
    if (!data) {
      settled = true;
      clearReconnectErrorTimer();
      callbacks.onError("Respuesta inesperada del servidor (status)");
      source.close();
      return;
    }
    markStreamHealthy();
    callbacks.onStatus(data.status as string);
  });

  source.addEventListener("agent", (e: Event) => {
    const data = parseEventData(e);
    if (!data) {
      // Un agente con JSON malformado no debe romper el análisis completo
      console.error("[stream-client] JSON inválido en evento 'agent'");
      return;
    }
    markStreamHealthy();
    callbacks.onAgent(data as unknown as AgentEventData);
  });

  source.addEventListener("agent_error", (e: Event) => {
    const data = parseEventData(e);
    if (!data) {
      console.error("[stream-client] JSON inválido en evento 'agent_error'");
      return;
    }
    markStreamHealthy();
    callbacks.onAgentError?.(data as unknown as AgentErrorEventData);
  });

  source.addEventListener("complete", (e: Event) => {
    const data = parseEventData(e);
    if (!data) {
      settled = true;
      clearReconnectErrorTimer();
      callbacks.onError("Respuesta inesperada del servidor (complete)");
      source.close();
      return;
    }
    settled = true;
    clearReconnectErrorTimer();
    callbacks.onComplete(data.document as string);
    source.close();
  });

  // "analysis_error": evento de error semántico emitido por el backend.
  // Renombrado desde "error" para evitar colisión con el evento nativo
  // de EventSource, que se dispara ante fallos de conexión de red.
  source.addEventListener("analysis_error", (e: Event) => {
    const data = parseEventData(e);
    settled = true;
    clearReconnectErrorTimer();
    callbacks.onError(
      normalizeErrorMessage(data?.message ?? data, "Error durante el análisis")
    );
    source.close();
  });

  // Errores de red / conexión perdida (evento nativo de EventSource)
  source.onerror = () => {
    if (settled) {
      return;
    }

    // EventSource reintenta automáticamente. Solo cerramos si no ha
    // conseguido volver a OPEN tras un margen prudente.
    if (reconnectErrorTimer !== null) {
      return;
    }

    reconnectErrorTimer = window.setTimeout(() => {
      reconnectErrorTimer = null;
      if (settled) {
        return;
      }
      if (source.readyState === EventSource.OPEN) {
        return;
      }
      if (source.readyState === EventSource.CONNECTING) {
        failInterruptedConnection();
        return;
      }
      failInterruptedConnection();
    }, STREAM_ERROR_GRACE_MS);
  };

  return {
    accepted: true,
    cached: false,
    cancel: () => {
      settled = true;
      clearReconnectErrorTimer();
      source.close();
    },
  };
}
