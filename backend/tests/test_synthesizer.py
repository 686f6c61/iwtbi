"""Tests del plano de Hamilton y del ensamblado sin pérdida de detalle."""

from unittest.mock import AsyncMock

import pytest

from app.agents.synthesizer import (
    Synthesizer,
    _assemble_document,
    _join_sections,
)


def _all_sections() -> dict[str, str]:
    return {
        "hopper": "## Stack tecnológico\n\n| Paquete | Versión |\n|---|---|\n| FastAPI | 1 |",
        "kay": "## Arquitectura\n\n```mermaid\ngraph TD\n  API --> Store\n```",
        "liskov": "## Base de datos\n\nNo detectado en el código analizado",
        "fielding": "## API y contratos\n\n`POST /api/analyze`",
        "lamarr": "## Frontend\n\nAstro",
        "knuth": "## Lógica de negocio\n\nValidar la URL",
        "conway": "## Puesta en marcha y despliegue\n\n`docker compose up`",
    }


def _integration() -> str:
    return """## Plano de reconstrucción

### Qué construir

Un analizador de repositorios.

### Árbol objetivo

```text
backend/
frontend/
```

### Orden de construcción

1. Crear el backend.
2. Crear el frontend.

### Criterios de aceptación globales

- El análisis termina.

### Desconocidos que no deben inventarse

- Ninguno adicional.
"""


def test_join_sections_uses_historical_internal_names_and_ignores_placeholders():
    sections = {
        "hopper": "## Stack tecnológico\n\n- Vite",
        "kay": "_Esta sección no pudo generarse debido a un error interno._",
    }

    joined = _join_sections(sections, ["hopper", "kay"])

    assert "agente=hopper" in joined
    assert "error interno" not in joined
    assert "agente=kay" not in joined


def test_assemble_document_preserves_mermaid_tables_and_exact_repo_url():
    sections = _all_sections()
    document = _assemble_document(
        "https://github.com/example/project",
        _integration(),
        sections,
    )

    assert "**Repositorio:** https://github.com/example/project" in document
    assert sections["hopper"] in document
    assert sections["kay"] in document
    assert document.index("## Plano de reconstrucción") < document.index(
        "# Especificaciones detalladas"
    )


@pytest.mark.asyncio
async def test_hamilton_makes_one_normal_call_and_keeps_all_specialist_outputs(monkeypatch):
    llm = object()

    class _Response:
        content = _integration()

    monkeypatch.setattr("app.agents.synthesizer.build_llm", lambda **_: llm)
    invoke = AsyncMock(return_value=_Response())
    monkeypatch.setattr(
        "app.agents.synthesizer.Synthesizer._invoke_with_retries", invoke
    )
    synth = Synthesizer(enable_fallback=False)
    sections = _all_sections()

    result = await synth.synthesize("https://github.com/example/project", sections)

    assert invoke.await_count == 1
    assert invoke.await_args.args[0] is llm
    for section in sections.values():
        assert section in result


@pytest.mark.asyncio
async def test_hamilton_uses_configured_backup_when_primary_fails(monkeypatch):
    primary_llm = object()
    fallback_llm = object()
    built = []

    class _Response:
        content = _integration()

    def fake_build_llm(**kwargs):
        built.append(kwargs)
        return primary_llm if len(built) == 1 else fallback_llm

    monkeypatch.setattr("app.agents.synthesizer.build_llm", fake_build_llm)
    monkeypatch.setattr(
        "app.agents.synthesizer.resolve_backup_providers",
        lambda *_: [("nan", "qwen3.6")],
    )
    invoke = AsyncMock(
        side_effect=[RuntimeError("llm request timed out"), _Response()]
    )
    monkeypatch.setattr(
        "app.agents.synthesizer.Synthesizer._invoke_with_retries", invoke
    )
    synth = Synthesizer()

    result = await synth.synthesize(
        "https://github.com/example/project", _all_sections()
    )

    assert "## Plano de reconstrucción" in result
    assert invoke.await_count == 2
    assert invoke.await_args_list[0].args[0] is primary_llm
    assert invoke.await_args_list[1].args[0] is fallback_llm


def test_deterministic_document_keeps_full_shape_and_marks_missing_sections():
    synth = Synthesizer(enable_fallback=False)
    document = synth.synthesize_deterministic(
        "https://github.com/example/project",
        {
            "lamarr": "## Frontend\n\n- Astro",
            "conway": "## Puesta en marcha y despliegue\n\n- npm run build",
        },
    )

    assert "## Plano de reconstrucción" in document
    assert "## Frontend" in document
    assert "## Puesta en marcha y despliegue" in document
    assert "## Stack tecnológico" in document
    assert "Sección no disponible en esta pasada" in document


def test_complete_section_set_requires_the_seven_historical_agent_ids():
    synth = Synthesizer(enable_fallback=False)

    assert synth.agent_name == "hamilton"
    assert synth.has_complete_section_set(_all_sections())
    assert not synth.has_complete_section_set(
        {"lamarr": "## Frontend\n\nAstro", "conway": "## DevOps\n\nDocker"}
    )
