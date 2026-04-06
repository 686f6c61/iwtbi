"""
Agente Tim Berners-Lee — ensambla las siete secciones en el documento final.

Recibe las salidas de los siete agentes especializados y produce un
documento Markdown cohesionado con una sección final de instrucciones
de construcción para IAs. Está separado de los agentes especializados
porque su entrada es diferente: recibe Markdown, no código fuente.

Temperatura 0.1: necesita redacción narrativa coherente para el resumen
y las instrucciones paso a paso, pero debe mantenerse anclado en las
secciones recibidas sin añadir información nueva.
"""

import asyncio
import re

from app.agents.base import build_llm, invoke_llm
from app.config import settings
from langchain_core.messages import HumanMessage, SystemMessage

_SYSTEM_PROMPT = """Eres un sintetizador técnico experto. Recibirás siete secciones Markdown generadas por agentes especializados que analizaron un repositorio de software.

Tu tarea es producir el documento final de reconstrucción. El criterio de calidad es uno: ¿podría una IA leer este documento y reconstruir el proyecto desde cero, sin ver el repositorio original?

REGLA ABSOLUTA — SOLO LO QUE ESTÁ EN LAS SECCIONES RECIBIDAS:
- El "Resumen para reconstrucción con IA" y las "Instrucciones de construcción paso a paso" deben construirse EXCLUSIVAMENTE a partir de la información de las siete secciones recibidas.
- No añadas ningún detalle tecnológico, versión, comando o patrón que no esté documentado en las secciones.
- Si una sección indica "No detectado en el código analizado", no inventes alternativas para ese componente.
- Los comandos de las instrucciones paso a paso deben ser exactamente los que aparecen en la sección "Puesta en marcha y despliegue" o "Stack tecnológico". Si un paso requiere un comando no documentado en las secciones, escríbelo como: "Comando no documentado — usar el estándar del framework ([npm install] / [pip install] / [go build] / etc.)".

ESTRUCTURA OBLIGATORIA DEL DOCUMENTO:

---

# [Nombre del proyecto]

> [Una sola frase que describe qué hace este software y para quién.]

**Repositorio:** [URL si está disponible]  **Tecnología principal:** [lenguaje + framework extraídos de la sección Stack]

## ¿Qué es este proyecto?

[Párrafo narrativo de 4-6 frases. Describe el problema que resuelve, el tipo de aplicación que es, el contexto de uso y qué lo hace distinto o relevante. Basa este párrafo exclusivamente en lo que dicen las secciones de Lógica de negocio y Stack tecnológico.]

## Resumen para reconstrucción con IA

[Escríbelo como si fuera el prompt que darías a una IA para que construya este proyecto desde cero. Debe ser denso, preciso y autocontenido: menciona el lenguaje, el framework, el patrón arquitectónico, la persistencia, la API, el frontend si lo hay, las dependencias clave y el mecanismo de despliegue. Entre 100 y 200 palabras. Sin listas: párrafo continuo. SOLO información que esté documentada en las secciones recibidas.]

---

## Stack tecnológico

[Contenido de la sección correspondiente, editado para eliminar redundancias con las demás.]

## Arquitectura

[Contenido de la sección correspondiente.]

## Base de datos

[Contenido de la sección correspondiente.]

## API y contratos

[Contenido de la sección correspondiente.]

## Frontend

[Contenido de la sección correspondiente.]

## Lógica de negocio

[Contenido de la sección correspondiente.]

## Puesta en marcha y despliegue

[Contenido de la sección correspondiente.]

---

## Instrucciones de construcción paso a paso

[Guía numerada para que una IA construya el proyecto desde cero. Mínimo 12 pasos. Empieza desde "crear el repositorio e inicializar el proyecto" y termina en "verificar que el sistema funciona en producción".

Cada paso debe ser accionable: nombra el archivo a crear o modificar, el comando a ejecutar o la decisión de diseño concreta. No hay pasos vagos como "implementar la lógica de negocio" sin especificar qué archivo y qué función.

Los comandos deben extraerse de las secciones Stack tecnológico y Puesta en marcha y despliegue. Si un comando no está documentado en las secciones, escribe: "Comando no documentado — usar el estándar del framework".

Ejemplo de formato de paso correcto:
"3. Crear el archivo `src/routes/analyze.py` con el endpoint `POST /api/analyze`. Este endpoint valida la URL de entrada con [validación específica documentada en la sección API], crea un Job en memoria y lanza el pipeline de análisis como tarea asíncrona."]

---

NORMAS DE EDICIÓN:
- Elimina redundancias entre secciones sin perder información. Si un dato aparece en dos secciones, déjalo solo en la más relevante.
- Los diagramas Mermaid de las secciones deben conservarse intactos.
- El documento debe funcionar sin el repositorio original: cualquier referencia a "ver el código" es un fallo.
- Usa tablas cuando presentes información comparativa o tabulada (variables de entorno, endpoints, reglas de negocio).
- El tono es técnico pero directo: sin adornos, sin frases de relleno."""

_OVERVIEW_PROMPT = """Eres un editor técnico. Recibirás secciones Markdown de análisis de un repositorio.

Tu tarea es redactar SOLO la cabecera narrativa del documento final.

REGLAS:
- Usa EXCLUSIVAMENTE información presente en las secciones recibidas.
- No inventes tecnologías, comandos, endpoints ni componentes ausentes.
- Si falta un dato, omítelo en lugar de inventarlo.
- Devuelve SOLO Markdown válido con esta estructura exacta:

# [Nombre del proyecto]

> [Una sola frase que describe qué hace el software y para quién.]

**Repositorio:** [URL del repositorio]

## ¿Qué es este proyecto?

[Párrafo de 4-6 frases.]

## Resumen para reconstrucción con IA

[Párrafo denso, preciso y autocontenido, entre 100 y 180 palabras.]
"""

_BUILD_STEPS_PROMPT = """Eres un arquitecto de software. Recibirás secciones Markdown de análisis de un repositorio.

Tu tarea es redactar SOLO la guía final de construcción paso a paso.

REGLAS:
- Usa EXCLUSIVAMENTE información presente en las secciones recibidas.
- Los comandos deben salir de las secciones. Si no están documentados, escribe:
  "Comando no documentado — usar el estándar del framework".
- Cada paso debe ser accionable y concreto.
- Devuelve SOLO Markdown válido con este encabezado exacto:

## Instrucciones de construcción paso a paso

1. ...
2. ...

- Genera entre 10 y 14 pasos.
"""

_SECTION_ORDER = [
    "sherlock",
    "frank",
    "oracle",
    "hermes",
    "picasso",
    "turing",
    "macgyver",
]

_RESCUE_OVERVIEW_KEYS = ["sherlock", "frank", "oracle", "hermes", "picasso", "turing"]
_RESCUE_STEPS_KEYS = ["sherlock", "oracle", "hermes", "picasso", "turing", "macgyver"]
_SECTION_TITLES = {
    "sherlock": "Stack tecnológico",
    "frank": "Arquitectura",
    "oracle": "Base de datos",
    "hermes": "API y contratos",
    "picasso": "Frontend",
    "turing": "Lógica de negocio",
    "macgyver": "Puesta en marcha y despliegue",
}
_PLACEHOLDER_PREFIX = "_Esta sección"


def _join_sections(sections: dict[str, str], order: list[str] | None = None) -> str:
    """Concatena las secciones en un orden estable para pasarlas al LLM."""
    keys = order or list(sections.keys())
    return "\n\n---\n\n".join(
        f"[Sección de {name}]\n{sections[name]}"
        for name in keys
        if name in sections and sections[name].strip()
    )


def _assemble_rescue_document(
    overview_markdown: str,
    sections: dict[str, str],
    steps_markdown: str,
) -> str:
    """Monta un documento completo usando cabecera y pasos generados por separado."""
    ordered_sections = "\n\n---\n\n".join(
        sections[name].strip()
        for name in _SECTION_ORDER
        if name in sections and sections[name].strip()
    )
    return (
        f"{overview_markdown.strip()}\n\n---\n\n"
        f"{ordered_sections}\n\n---\n\n"
        f"{steps_markdown.strip()}\n"
    )


def _is_usable_section(section: str) -> bool:
    """Indica si la sección contiene información reutilizable."""
    content = section.strip()
    return bool(content) and not content.startswith(_PLACEHOLDER_PREFIX)


def _format_project_title(repo_url: str) -> str:
    """Deriva un título legible a partir del nombre del repositorio."""
    repo_name = repo_url.rstrip("/").split("/")[-1]
    words = [part for part in re.split(r"[-_]+", repo_name) if part]
    if not words:
        return repo_name or "Proyecto"
    return " ".join(word.upper() if len(word) <= 3 else word.capitalize() for word in words)


def _build_deterministic_steps(sections: dict[str, str]) -> str:
    """Genera una checklist final sin depender de una síntesis adicional."""
    available_keys = [
        key
        for key in _SECTION_ORDER
        if key in sections and _is_usable_section(sections[key])
    ]
    step_templates = {
        "sherlock": "Definir el stack inicial usando exclusivamente la información documentada en `## Stack tecnológico`.",
        "frank": "Reproducir la estructura del proyecto siguiendo `## Arquitectura`, respetando módulos, capas y límites entre componentes.",
        "oracle": "Configurar la persistencia y los modelos a partir de `## Base de datos`, sin añadir tablas o colecciones no documentadas.",
        "hermes": "Implementar endpoints, contratos y validaciones según `## API y contratos`.",
        "picasso": "Construir la interfaz y el flujo visual descritos en `## Frontend`.",
        "turing": "Trasladar reglas, casos de uso y comportamiento principal desde `## Lógica de negocio`.",
        "macgyver": "Preparar ejecución local y despliegue replicando `## Puesta en marcha y despliegue`.",
    }

    steps = [
        "1. Crear un repositorio limpio y preparar el entorno base únicamente con la información documentada en este análisis.",
    ]
    for key in available_keys:
        steps.append(f"{len(steps) + 1}. {step_templates[key]}")
    steps.extend(
        [
            f"{len(steps) + 1}. Revisar de forma cruzada las secciones anteriores y completar solo las piezas explícitamente documentadas.",
            f"{len(steps) + 1}. Verificar el sistema en local y contrastar el resultado con la sección de despliegue antes de publicarlo.",
        ]
    )
    return "## Instrucciones de construcción paso a paso\n\n" + "\n".join(steps)


class Synthesizer:
    """
    Ensambla las secciones de los agentes en el documento Markdown final.

    Se ejecuta después de que todos los agentes han completado su trabajo,
    recibiendo sus salidas completas para garantizar coherencia global.
    El sintetizador tiene acceso a todas las secciones simultáneamente,
    lo que le permite detectar y eliminar redundancias entre ellas.

    Usa temperature=0.1 para permitir redacción narrativa coherente en el
    resumen y las instrucciones, manteniendo el ancla en las secciones recibidas.
    """

    def __init__(self) -> None:
        self._llm = build_llm(
            temperature=0.1,
            max_tokens=32768,
            request_timeout_seconds=settings.llm_synth_request_timeout_seconds,
        )
        self._overview_llm = build_llm(
            temperature=0.05,
            max_tokens=4096,
            request_timeout_seconds=settings.llm_synth_request_timeout_seconds,
        )
        self._steps_llm = build_llm(
            temperature=0.05,
            max_tokens=8192,
            request_timeout_seconds=settings.llm_synth_request_timeout_seconds,
        )

    async def _invoke_with_retries(self, llm, messages):
        """Reintenta la síntesis cuando el proveedor agota tiempo o responde vacío."""
        attempts = max(settings.llm_synth_retry_attempts, 0)
        last_exc: Exception | None = None
        for attempt in range(attempts + 1):
            try:
                return await invoke_llm(llm, messages)
            except Exception as exc:
                last_exc = exc
                message = str(exc).lower()
                retryable = (
                    "timed out" in message
                    or "429" in message
                    or "rate limit" in message
                    or "too many concurrent requests" in message
                    or "empty llm response" in message
                )
                if attempt >= attempts or not retryable:
                    raise
                await asyncio.sleep(
                    settings.llm_synth_retry_base_delay_seconds * (2**attempt)
                )
        assert last_exc is not None
        raise last_exc

    async def synthesize(self, sections: dict[str, str]) -> str:
        """
        Genera el documento final a partir de las secciones de los agentes.

        Args:
            sections: Diccionario {nombre_agente: sección_markdown}.
                      Las claves son los agent_name de cada BaseAgent.

        Returns:
            Documento Markdown completo, cohesionado y listo para el usuario.

        Raises:
            ValueError: Si el diccionario de secciones está vacío.
            RuntimeError: Si el LLM devuelve una respuesta vacía o nula.
        """
        if not sections:
            raise ValueError(
                "El sintetizador no puede operar: no hay secciones de agentes disponibles."
            )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_join_sections(sections)),
        ]
        response = await self._invoke_with_retries(self._llm, messages)

        content = response.content
        if not content:
            raise RuntimeError(
                "El sintetizador recibió una respuesta vacía del LLM. "
                "Puede indicar un error de la API o un rechazo por filtros de contenido."
            )
        return str(content)

    async def synthesize_rescue(self, repo_url: str, sections: dict[str, str]) -> str:
        """
        Genera un documento completo en dos pasos más ligeros.

        Este camino existe para los casos donde la síntesis monolítica agota
        tiempo. En lugar de guardar un parcial, se generan por separado:
        - cabecera narrativa
        - instrucciones de construcción

        y luego se ensamblan de forma determinista con las secciones originales.
        """
        if not sections:
            raise ValueError(
                "La síntesis de rescate no puede operar: no hay secciones disponibles."
            )

        overview_messages = [
            SystemMessage(content=_OVERVIEW_PROMPT),
            HumanMessage(
                content=(
                    f"Repositorio: {repo_url}\n\n"
                    f"{_join_sections(sections, _RESCUE_OVERVIEW_KEYS)}"
                )
            ),
        ]
        overview_response = await self._invoke_with_retries(
            self._overview_llm,
            overview_messages,
        )
        overview = str(overview_response.content or "").strip()
        if not overview:
            raise RuntimeError("La cabecera de rescate del documento salió vacía.")

        steps_messages = [
            SystemMessage(content=_BUILD_STEPS_PROMPT),
            HumanMessage(content=_join_sections(sections, _RESCUE_STEPS_KEYS)),
        ]
        steps_response = await self._invoke_with_retries(
            self._steps_llm,
            steps_messages,
        )
        steps = str(steps_response.content or "").strip()
        if not steps:
            raise RuntimeError("Las instrucciones de rescate salieron vacías.")

        return _assemble_rescue_document(overview, sections, steps)

    def synthesize_deterministic(self, repo_url: str, sections: dict[str, str]) -> str:
        """
        Cierra el documento sin LLM cuando incluso la síntesis de rescate falla.

        No añade información nueva: monta una cabecera neutra y una checklist
        basada en las secciones válidas ya generadas por los agentes.
        """
        usable_sections = {
            name: section
            for name, section in sections.items()
            if _is_usable_section(section)
        }
        if not usable_sections:
            raise RuntimeError(
                "No hay secciones válidas para construir el documento determinista."
            )

        repo_full_name = "/".join(repo_url.rstrip("/").split("/")[-2:])
        project_title = _format_project_title(repo_url)
        ordered_sections = "\n\n---\n\n".join(
            usable_sections[name].strip()
            for name in _SECTION_ORDER
            if name in usable_sections
        )
        intro = (
            f"# {project_title}\n\n"
            f"> Documento técnico de reconstrucción del repositorio {repo_full_name}.\n\n"
            f"**Repositorio:** {repo_url}\n\n"
            "## ¿Qué es este proyecto?\n\n"
            "Este documento reúne las observaciones extraídas directamente del código analizado "
            "para facilitar la reconstrucción del proyecto. Las secciones siguientes conservan "
            "el detalle detectado por los agentes sobre stack, arquitectura, persistencia, API, "
            "frontend, lógica de negocio y despliegue.\n\n"
            "## Resumen para reconstrucción con IA\n\n"
            "Reconstruye este proyecto usando únicamente la información documentada en las "
            "secciones siguientes. Prioriza primero el stack, la arquitectura, la API, la "
            "persistencia, la lógica y el despliegue tal y como aparecen en el análisis.\n"
        )
        steps = _build_deterministic_steps(usable_sections)
        return f"{intro}\n---\n\n{ordered_sections}\n\n---\n\n{steps}\n"
