"""Margaret Hamilton integra las siete especificaciones en el documento final."""

import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base import (
    _is_retryable_llm_error,
    build_llm,
    invoke_llm,
    provider_model_label,
    resolve_backup_providers,
)
from app.config import settings

_logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Eres Margaret Hamilton, ingeniera responsable de integrar siete especificaciones especializadas de un repositorio.

El documento se entregará a otra IA para reconstruir un proyecto funcionalmente equivalente sin consultar el repositorio original. Tu trabajo es producir SOLO el plano transversal de construcción. El programa añadirá después, sin modificarlas, las siete especificaciones detalladas con sus tablas, contratos y diagramas Mermaid.

REGLA ABSOLUTA — SOLO LAS ESPECIFICACIONES RECIBIDAS:
- No inventes archivos, directorios, tecnologías, versiones, comandos, endpoints, campos, reglas ni comportamientos.
- Resuelve contradicciones citando entre backticks la ruta o la sección que tenga evidencia más concreta. Si no pueden resolverse, decláralas como desconocidas.
- No resumas hasta borrar detalles importantes y no repitas las siete especificaciones.
- No incluyas un título H1 ni una línea de repositorio: el programa los añade de forma determinista.
- No uses bloques Mermaid en este plano salvo que una dependencia transversal no esté ya representada en las especificaciones.

Devuelve únicamente Markdown con esta estructura exacta:

## Plano de reconstrucción

### Qué construir

[Descripción precisa del producto, sus usuarios, comportamiento observable y límites. Incluye la tecnología principal solo si está documentada.]

### Árbol objetivo

```text
[Árbol de archivos y directorios que la IA debe crear. Incluye solo rutas documentadas. Si no hay evidencia suficiente, escribe dentro del bloque: No detectado en el código analizado]
```

### Orden de construcción

1. [Paso accionable con rutas, símbolos, contratos o comandos documentados.]

[Entre 8 y 16 pasos. Ordena dependencias antes que consumidores y termina con pruebas y despliegue cuando estén documentados.]

### Criterios de aceptación globales

- [Resultado verificable desde fuera o mediante una prueba documentada.]

### Desconocidos que no deben inventarse

- [Dato necesario ausente, contradicción o límite del análisis. Si no hay ninguno, indica que no se detectaron desconocidos adicionales.]
"""

_SECTION_ORDER = [
    "hopper",
    "kay",
    "liskov",
    "fielding",
    "lamarr",
    "knuth",
    "conway",
]

_SECTION_TITLES = {
    "hopper": "Stack tecnológico",
    "kay": "Arquitectura",
    "liskov": "Base de datos",
    "fielding": "API y contratos",
    "lamarr": "Frontend",
    "knuth": "Lógica de negocio",
    "conway": "Puesta en marcha y despliegue",
}
_PLACEHOLDER_PREFIX = "_Esta sección"
_MISSING_SECTION_NOTE = (
    "_Sección no disponible en esta pasada. El documento conserva el resto del "
    "análisis sin inventar contenido._"
)
_CONTEXT_TREE_LINE_LIMIT = 140
_CONTEXT_FILE_LIMIT = 6
_CONTEXT_FILE_CHAR_LIMIT = 1600
_REQUIRED_INTEGRATION_HEADINGS = (
    "## Plano de reconstrucción",
    "### Qué construir",
    "### Árbol objetivo",
    "### Orden de construcción",
    "### Criterios de aceptación globales",
    "### Desconocidos que no deben inventarse",
)


def _is_usable_section(section: str) -> bool:
    content = section.strip()
    return bool(content) and not content.startswith(_PLACEHOLDER_PREFIX)


def _usable_sections(sections: dict[str, str]) -> dict[str, str]:
    return {
        name: section
        for name, section in sections.items()
        if _is_usable_section(section)
    }


def _join_sections(sections: dict[str, str], order: list[str] | None = None) -> str:
    """Concatena las especificaciones en orden estable para Margaret Hamilton."""
    keys = order or _SECTION_ORDER
    return "\n\n---\n\n".join(
        f"[Especificación de {_SECTION_TITLES.get(name, name)}; agente={name}]\n"
        f"{sections[name]}"
        for name in keys
        if name in sections and _is_usable_section(sections[name])
    )


def _format_project_title(repo_url: str) -> str:
    repo_name = repo_url.rstrip("/").split("/")[-1]
    words = [part for part in re.split(r"[-_]+", repo_name) if part]
    if not words:
        return repo_name or "Proyecto"
    return " ".join(word.upper() if len(word) <= 3 else word.capitalize() for word in words)


def _render_section(agent_name: str, sections: dict[str, str]) -> str:
    """Inserta la salida del especialista sin reescribir su contenido."""
    section = sections.get(agent_name)
    if section is not None and _is_usable_section(section):
        return section
    return f"## {_SECTION_TITLES[agent_name]}\n\n{_MISSING_SECTION_NOTE}"


def _assemble_document(
    repo_url: str,
    integration_markdown: str,
    sections: dict[str, str],
) -> str:
    """Monta cabecera, plano de Hamilton y especificaciones especializadas."""
    project_title = _format_project_title(repo_url)
    ordered_sections = "\n\n---\n\n".join(
        _render_section(name, sections) for name in _SECTION_ORDER
    )
    return (
        f"# {project_title}\n\n"
        f"**Repositorio:** {repo_url}\n\n"
        f"{integration_markdown.strip()}\n\n"
        "---\n\n"
        "# Especificaciones detalladas\n\n"
        f"{ordered_sections}\n"
    )


def _validate_integration(content: str) -> str:
    integration = content.strip()
    if not integration:
        raise RuntimeError("Margaret Hamilton devolvió un plano de reconstrucción vacío.")
    missing = [heading for heading in _REQUIRED_INTEGRATION_HEADINGS if heading not in integration]
    if missing:
        raise RuntimeError(
            "El plano de reconstrucción está incompleto; faltan: " + ", ".join(missing)
        )
    return integration


def _build_deterministic_integration(sections: dict[str, str]) -> str:
    """Crea un plano conservador cuando Hamilton o sus proveedores fallan."""
    available = [
        key for key in _SECTION_ORDER if key in sections and _is_usable_section(sections[key])
    ]
    steps = [
        "1. Preparar el proyecto con el stack y las versiones documentadas en `## Stack tecnológico`.",
    ]
    templates = {
        "kay": "Crear la estructura y los límites de módulos descritos en `## Arquitectura`.",
        "liskov": "Implementar la persistencia y sus restricciones según `## Base de datos`.",
        "fielding": "Implementar los contratos, validaciones y errores de `## API y contratos`.",
        "lamarr": "Construir las vistas, componentes y estados descritos en `## Frontend`.",
        "knuth": "Implementar las reglas, estados y flujos de `## Lógica de negocio`.",
        "conway": "Configurar pruebas, ejecución y despliegue según `## Puesta en marcha y despliegue`.",
    }
    for key in _SECTION_ORDER:
        if key in available and key in templates:
            steps.append(f"{len(steps) + 1}. {templates[key]}")
    steps.append(
        f"{len(steps) + 1}. Verificar de forma cruzada todos los criterios de aceptación de las especificaciones detalladas."
    )
    missing_titles = [
        _SECTION_TITLES[key] for key in _SECTION_ORDER if key not in available
    ]
    unknowns = (
        "- Secciones no disponibles en esta pasada: " + ", ".join(missing_titles) + "."
        if missing_titles
        else "- No se detectaron desconocidos adicionales; prevalecen los indicados en cada especificación."
    )
    return (
        "## Plano de reconstrucción\n\n"
        "### Qué construir\n\n"
        "Reconstruye un proyecto funcionalmente equivalente usando las especificaciones "
        "detalladas como única fuente de verdad. No añadas componentes, comportamientos ni "
        "tecnologías que no estén documentados.\n\n"
        "### Árbol objetivo\n\n"
        "```text\nConsultar las rutas exactas documentadas en Arquitectura y en las demás especificaciones.\n```\n\n"
        "### Orden de construcción\n\n"
        + "\n".join(steps)
        + "\n\n### Criterios de aceptación globales\n\n"
        "- Se satisfacen los criterios de aceptación de cada una de las siete áreas.\n"
        "- Ningún contrato, regla, ruta o comando contradice las especificaciones detalladas.\n"
        "- Los componentes ausentes no se sustituyen por alternativas inventadas.\n\n"
        "### Desconocidos que no deben inventarse\n\n"
        f"{unknowns}"
    )


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[... extracto truncado ...]"


class Synthesizer:
    """Ejecuta a Hamilton una vez y ensambla sus conclusiones sin tocar las secciones."""

    agent_name = "hamilton"

    def __init__(
        self,
        *,
        provider_override: str | None = None,
        model_override: str | None = None,
        enable_fallback: bool = True,
    ) -> None:
        effective_provider = provider_override or settings.provider
        self._llm = build_llm(
            temperature=0.05,
            max_tokens=6000,
            request_timeout_seconds=settings.llm_synth_request_timeout_seconds,
            provider=effective_provider,
            model_override=model_override,
        )
        self._fallback_llms = []
        if enable_fallback:
            for backup_provider, backup_model in resolve_backup_providers(
                effective_provider, model_override
            ):
                self._fallback_llms.append(
                    (
                        build_llm(
                            temperature=0.05,
                            max_tokens=6000,
                            request_timeout_seconds=settings.llm_synth_request_timeout_seconds,
                            provider=backup_provider,
                            model_override=backup_model,
                        ),
                        provider_model_label(backup_provider, backup_model),
                    )
                )

    def usable_section_count(self, sections: dict[str, str]) -> int:
        return len(_usable_sections(sections))

    def has_complete_section_set(self, sections: dict[str, str]) -> bool:
        return self.usable_section_count(sections) == len(_SECTION_ORDER)

    async def _invoke_with_retries(self, llm, messages):
        attempts = max(settings.llm_synth_retry_attempts, 0)
        last_exc: Exception | None = None
        for attempt in range(attempts + 1):
            try:
                return await invoke_llm(
                    llm,
                    messages,
                    timeout_seconds=settings.llm_synth_request_timeout_seconds,
                    retry_attempts=0,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts or not _is_retryable_llm_error(exc):
                    raise
                _logger.warning(
                    "Hamilton agotó el intento %d/%d: %s",
                    attempt + 1,
                    attempts + 1,
                    exc,
                )
                await asyncio.sleep(settings.llm_synth_retry_base_delay_seconds * (2**attempt))
        raise last_exc or RuntimeError("Hamilton agotó los intentos sin respuesta")

    async def synthesize(self, repo_url: str, sections: dict[str, str]) -> str:
        """Genera un plano con una llamada de Hamilton y conserva las siete salidas."""
        if not sections:
            raise ValueError("Hamilton no puede integrar un análisis sin secciones.")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=f"Repositorio exacto: {repo_url}\n\n{_join_sections(sections)}"
            ),
        ]
        try:
            response = await self._invoke_with_retries(self._llm, messages)
        except Exception as primary_exc:
            response = await self._invoke_synth_fallbacks(
                messages, primary_exc=primary_exc
            )
        integration = _validate_integration(str(response.content or ""))
        return _assemble_document(repo_url, integration, sections)

    async def _invoke_synth_fallbacks(self, messages, *, primary_exc: Exception):
        if not self._fallback_llms:
            raise primary_exc
        last_exc = primary_exc
        for fallback_llm, fallback_label in self._fallback_llms:
            _logger.warning(
                "Hamilton falló. Se reintentará con %s: %s", fallback_label, last_exc
            )
            try:
                return await self._invoke_with_retries(fallback_llm, messages)
            except Exception as fallback_exc:
                last_exc = fallback_exc
        raise last_exc from primary_exc

    def synthesize_deterministic(self, repo_url: str, sections: dict[str, str]) -> str:
        """Ensambla el documento sin otra llamada si Hamilton no está disponible."""
        usable = _usable_sections(sections)
        if not usable:
            raise RuntimeError("No hay secciones válidas para construir el documento.")
        return _assemble_document(
            repo_url,
            _build_deterministic_integration(usable),
            usable,
        )

    def synthesize_from_context_deterministic(self, repo_url: str, context) -> str:
        """Red de seguridad cuando ningún especialista completa su llamada."""
        repo_full_name = "/".join(repo_url.rstrip("/").split("/")[-2:])
        project_title = _format_project_title(repo_url)
        tree_lines = context.tree.splitlines()
        tree_excerpt = "\n".join(tree_lines[:_CONTEXT_TREE_LINE_LIMIT]).strip()
        if len(tree_lines) > _CONTEXT_TREE_LINE_LIMIT:
            tree_excerpt += "\n..."
        selected_items = list(context.files.items())[:_CONTEXT_FILE_LIMIT]
        file_rows = "\n".join(
            f"| `{path}` | Incluido en el contexto priorizado del análisis |"
            for path, _ in selected_items
        )
        excerpts = "\n\n".join(
            f"### `{path}`\n\n```\n{_truncate_text(content, _CONTEXT_FILE_CHAR_LIMIT)}\n```"
            for path, content in selected_items
        )
        return (
            f"# {project_title}\n\n"
            f"> Documento técnico de respaldo del repositorio {repo_full_name}.\n\n"
            f"**Repositorio:** {repo_url}\n\n"
            "## Estructura detectada\n\n"
            f"```text\n{tree_excerpt}\n```\n\n"
            "## Archivos clave incluidos en el contexto\n\n"
            "| Archivo | Papel observado |\n|---------|----------------|\n"
            f"{file_rows}\n\n"
            "## Extractos de referencia\n\n"
            f"{excerpts}\n"
        )
