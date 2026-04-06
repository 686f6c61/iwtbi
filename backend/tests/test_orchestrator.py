"""Tests para el orquestador del pipeline de análisis."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.orchestrator import (
    Orchestrator,
    _build_biblioteca_url,
)
from app.models.job import JobStatus
from app.models.repo_context import RepoContext
from app.store.job_store import JobStore


@pytest.fixture
def store():
    return JobStore()


@pytest.fixture
def job(store):
    return store.create("https://github.com/kelseyhightower/nocode")


@pytest.mark.asyncio
async def test_orchestrator_completes_job(store, job):
    """El orquestador debe marcar el job como COMPLETE con el documento final."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})
    fake_sections = {
        "sherlock": "## Stack tecnológico\n\nSin archivos.",
        "frank": "## Arquitectura\n\nRepo vacío.",
    }

    with (
        patch.object(orchestrator._cloner, "clone", new_callable=AsyncMock, return_value=(Path("/tmp/fake"), "abc1234")),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator._reader, "read", return_value=fake_context),
        patch.object(orchestrator, "_run_agents", new_callable=AsyncMock, return_value=fake_sections),
        patch.object(orchestrator._synthesizer, "synthesize", new_callable=AsyncMock, return_value="# Documento final"),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save"),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETE
    assert updated.document == "# Documento final"


@pytest.mark.asyncio
async def test_orchestrator_handles_clone_error(store, job):
    """Un error de clonado debe marcar el job como ERROR con mensaje."""
    orchestrator = Orchestrator(store=store)

    with (
        patch.object(orchestrator._cloner, "clone", new_callable=AsyncMock, side_effect=RuntimeError("Repo no accesible")),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.ERROR
    assert "Repo no accesible" in updated.error


@pytest.mark.asyncio
async def test_orchestrator_uses_rescue_synthesis_when_full_synthesis_times_out(store, job):
    """Si falla la síntesis principal, debe intentarse la síntesis de rescate."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})
    fake_sections = {
        "sherlock": "## Stack tecnológico\n\n- Python",
        "frank": "## Arquitectura\n\n- CLI simple",
    }

    with (
        patch.object(orchestrator._cloner, "clone", new_callable=AsyncMock, return_value=(Path("/tmp/fake"), "abc1234")),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator._reader, "read", return_value=fake_context),
        patch.object(orchestrator, "_run_agents", new_callable=AsyncMock, return_value=fake_sections),
        patch.object(
            orchestrator._synthesizer,
            "synthesize",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm request timed out"),
        ),
        patch.object(
            orchestrator._synthesizer,
            "synthesize_rescue",
            new_callable=AsyncMock,
            return_value="# Documento de rescate",
        ),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save"),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETE
    assert updated.document == "# Documento de rescate"


@pytest.mark.asyncio
async def test_orchestrator_uses_deterministic_fallback_when_full_and_rescue_fail(store, job):
    """Si fallan síntesis y rescate, debe cerrarse con documento determinista."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})
    fake_sections = {
        "sherlock": "## Stack tecnológico\n\n- Python",
        "frank": "## Arquitectura\n\n- CLI simple",
    }

    with (
        patch.object(orchestrator._cloner, "clone", new_callable=AsyncMock, return_value=(Path("/tmp/fake"), "abc1234")),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator._reader, "read", return_value=fake_context),
        patch.object(orchestrator, "_run_agents", new_callable=AsyncMock, return_value=fake_sections),
        patch.object(
            orchestrator._synthesizer,
            "synthesize",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm request timed out"),
        ),
        patch.object(
            orchestrator._synthesizer,
            "synthesize_rescue",
            new_callable=AsyncMock,
            side_effect=RuntimeError("rescue also failed"),
        ),
        patch.object(
            orchestrator._synthesizer,
            "synthesize_deterministic",
            return_value="# Documento determinista",
        ),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save"),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETE
    assert updated.document == "# Documento determinista"


@pytest.mark.asyncio
async def test_orchestrator_nonexistent_job_is_safe(store):
    """Llamar a run con un job_id inexistente no debe lanzar excepción."""
    orchestrator = Orchestrator(store=store)
    await orchestrator.run("id-inexistente")  # no debe explotar


def test_build_biblioteca_url_points_to_view_route():
    assert _build_biblioteca_url("686f6c61/gitpins") == (
        "https://app.example.com/biblioteca/view?repo=686f6c61%2Fgitpins&open=1"
    )
