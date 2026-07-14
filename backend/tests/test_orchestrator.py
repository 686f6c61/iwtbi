"""Tests para el orquestador del pipeline de análisis."""

import asyncio
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr

from app.services.orchestrator import (
    AllAgentsFailedError,
    Orchestrator,
    _build_biblioteca_url,
    _is_transient_agent_failure,
)
from app.models.job import JobStatus
from app.models.repo_context import RepoContext
from app.store.job_store import JobStore


def _all_sections() -> dict[str, str]:
    return {
        "hopper": "## Stack tecnológico\n\n- Python",
        "kay": "## Arquitectura\n\n- CLI simple",
        "liskov": "## Base de datos\n\n- SQLite",
        "fielding": "## API y contratos\n\n- REST",
        "lamarr": "## Frontend\n\n- Astro",
        "knuth": "## Lógica de negocio\n\n- Reglas",
        "conway": "## Puesta en marcha y despliegue\n\n- Docker",
    }


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
    fake_sections = _all_sections()

    save_mock = MagicMock()

    with (
        patch.object(orchestrator._cloner, "clone", new_callable=AsyncMock, return_value=(Path("/tmp/fake"), "abc1234")),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator._reader, "read", return_value=fake_context),
        patch.object(orchestrator, "_run_agents", new_callable=AsyncMock, return_value=fake_sections),
        patch.object(
            orchestrator._synthesizer,
            "synthesize",
            new_callable=AsyncMock,
            return_value=(
                "# Documento final\n\n"
                "Stack: Python con FastAPI, Redis y Docker. "
                "Frontend con Astro."
            ),
        ),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=["observability"]),
        patch("app.services.orchestrator.AnalysesRepo.save", save_mock),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETE
    assert updated.document.startswith("# Documento final")
    save_mock.assert_called_once_with(
        repo_url="https://github.com/kelseyhightower/nocode",
        repo_full_name="kelseyhightower/nocode",
        document=updated.document,
        git_sha="abc1234",
        tags=["python", "fastapi", "astro", "docker", "redis", "observability"],
    )


@pytest.mark.asyncio
async def test_orchestrator_resolves_selected_profile_only_inside_worker(store):
    """El worker convierte el ID persistido en credenciales al ejecutar."""
    job = store.create(
        "https://github.com/kelseyhightower/nocode",
        llm_profile_id="revision",
    )
    orchestrator = Orchestrator(store=store)
    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})
    runtime_components = (
        orchestrator._reader,
        orchestrator._synthesizer,
        orchestrator._agents,
    )

    with (
        patch(
            "app.services.orchestrator.get_llm_profile",
            return_value=SimpleNamespace(
                provider="openai_compatible",
                model="profile-model",
                api_key=SecretStr("profile-key"),  # pragma: allowlist secret
                base_url="https://profile.example.test/v1",
                label="Revisión profunda",
            ),
        ),
        patch.object(
            orchestrator,
            "_build_runtime_components",
            return_value=runtime_components,
        ) as build_components,
        patch.object(
            orchestrator._cloner,
            "clone",
            new_callable=AsyncMock,
            return_value=(Path("/tmp/fake"), "abc1234"),
        ),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator._reader, "read", return_value=fake_context),
        patch.object(
            orchestrator,
            "_run_agents",
            new_callable=AsyncMock,
            return_value=_all_sections(),
        ),
        patch.object(
            orchestrator._synthesizer,
            "synthesize",
            new_callable=AsyncMock,
            return_value="# Documento final",
        ),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save"),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    build_components.assert_called_once_with(
        provider_override="openai_compatible",
        model_override="profile-model",
        api_key_override="profile-key",  # pragma: allowlist secret
        base_url_override="https://profile.example.test/v1",
        disable_fallback=False,
    )
    assert store.get(job.job_id).status == JobStatus.COMPLETE


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
async def test_orchestrator_preserves_sections_when_hamilton_times_out(store, job):
    """Si falla Hamilton, debe cerrar sin hacer otra llamada de integración."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})
    fake_sections = _all_sections()

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
            "synthesize_deterministic",
            return_value="# Documento determinista",
        ) as deterministic_mock,
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save"),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETE
    assert updated.document == "# Documento determinista"
    deterministic_mock.assert_called_once_with(
        repo_url="https://github.com/kelseyhightower/nocode",
        sections=fake_sections,
    )


@pytest.mark.asyncio
async def test_orchestrator_uses_deterministic_document_when_sections_are_incomplete(store, job):
    """Con menos de 7 secciones útiles, debe cerrarse sin pedir datos faltantes al usuario."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})
    fake_sections = {
        "lamarr": "## Frontend\n\n- Astro",
        "conway": "## Puesta en marcha y despliegue\n\n- npm run build",
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
            side_effect=AssertionError("No debería invocarse la síntesis LLM con secciones incompletas"),
        ),
        patch.object(
            orchestrator._synthesizer,
            "synthesize_deterministic",
            return_value="# Documento determinista parcial",
        ) as deterministic_mock,
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save"),
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETE
    assert updated.document == "# Documento determinista parcial"
    deterministic_mock.assert_called_once_with(
        repo_url="https://github.com/kelseyhightower/nocode",
        sections=fake_sections,
    )


@pytest.mark.asyncio
async def test_orchestrator_uses_deterministic_fallback_when_hamilton_fails(store, job):
    """Si falla la integración, debe cerrarse con documento determinista."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})
    fake_sections = _all_sections()

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
async def test_orchestrator_does_not_publish_when_all_agents_fail(store, job):
    """Un fallo total de proveedores no debe publicarse como análisis válido."""
    orchestrator = Orchestrator(store=store)

    fake_context = RepoContext(tree="└── README.md", files={"README.md": "# nocode"})

    with (
        patch.object(orchestrator._cloner, "clone", new_callable=AsyncMock, return_value=(Path("/tmp/fake"), "abc1234")),
        patch.object(orchestrator._cloner, "cleanup"),
        patch.object(orchestrator._reader, "read", return_value=fake_context),
        patch.object(
            orchestrator,
            "_run_agents",
            new_callable=AsyncMock,
            side_effect=AllAgentsFailedError("Todos los agentes fallaron."),
        ),
        patch.object(orchestrator, "_schedule_job_cleanup", new_callable=AsyncMock),
        patch("app.services.github_api.get_repo_topics", new_callable=AsyncMock, return_value=[]),
        patch("app.services.orchestrator.AnalysesRepo.save") as save_mock,
        patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]),
    ):
        await orchestrator.run(job.job_id)

    updated = store.get(job.job_id)
    assert updated.status == JobStatus.ERROR
    assert updated.document is None
    assert "proveedores de análisis" in updated.error.lower()
    save_mock.assert_not_called()


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 401 - invalid proxy token",
        "openai.AuthenticationError: unauthorized",
        "Invalid API key",
    ],
)
def test_provider_auth_failures_are_recoverable(message):
    assert _is_transient_agent_failure(RuntimeError(message)) is True


@pytest.mark.asyncio
async def test_orchestrator_nonexistent_job_is_safe(store):
    """Llamar a run con un job_id inexistente no debe lanzar excepción."""
    orchestrator = Orchestrator(store=store)
    await orchestrator.run("id-inexistente")  # no debe explotar


def test_build_biblioteca_url_points_to_view_route():
    assert _build_biblioteca_url("owner/repo") == (
        "http://localhost:3410/biblioteca/view?repo=owner%2Frepo&open=1"
    )


def test_build_biblioteca_url_uses_configured_public_url(monkeypatch):
    monkeypatch.setattr(
        "app.services.orchestrator.settings.public_app_url",
        "https://self-host.example/",
    )

    assert _build_biblioteca_url("owner/repo") == (
        "https://self-host.example/biblioteca/view?repo=owner%2Frepo&open=1"
    )


@pytest.mark.asyncio
async def test_run_agents_attempt_omits_failed_sections(store):
    """Una sección fallida no debe rellenarse con texto de error interno."""
    orchestrator = Orchestrator(store=store)
    context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})

    ok_agent = MagicMock()
    ok_agent.agent_name = "hopper"
    ok_agent.analyze = AsyncMock(return_value="## Stack tecnológico\n\n- Python")

    bad_agent = MagicMock()
    bad_agent.agent_name = "kay"
    bad_agent.analyze = AsyncMock(side_effect=RuntimeError("llm request timed out"))

    orchestrator._agents = [ok_agent, bad_agent]
    orchestrator._emit = AsyncMock()

    sections, failures = await orchestrator._run_agents_attempt(
        "job-test",
        context,
        sequential=False,
    )

    assert sections == {"hopper": "## Stack tecnológico\n\n- Python"}
    assert "kay" in failures


@pytest.mark.asyncio
async def test_run_agents_attempt_times_out_slow_agent(store, monkeypatch):
    """Un agente lento debe cortarse para no bloquear la tanda completa."""
    orchestrator = Orchestrator(store=store)
    context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})

    slow_agent = MagicMock()
    slow_agent.agent_name = "kay"

    async def _sleep_forever(_context):
        await asyncio.sleep(0.05)
        return "## Arquitectura\n\nNunca debería llegar aquí."

    slow_agent.analyze = _sleep_forever
    orchestrator._agents = [slow_agent]
    orchestrator._emit = AsyncMock()
    monkeypatch.setattr(
        "app.services.orchestrator.settings.llm_agent_wall_timeout_seconds",
        0.01,
    )

    sections, failures = await orchestrator._run_agents_attempt(
        "job-test",
        context,
        sequential=False,
    )

    assert sections == {}
    assert "kay" in failures
    assert "timed out" in str(failures["kay"]).lower()


@pytest.mark.asyncio
async def test_run_agents_attempt_dispatches_agents_in_batches(store, monkeypatch):
    """En modo paralelo, los agentes deben salir en tandas y no todos a la vez."""
    orchestrator = Orchestrator(store=store)
    context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})

    monkeypatch.setattr("app.services.orchestrator.settings.llm_agent_batch_size", 3)

    wave_started = asyncio.Event()
    release_wave = asyncio.Event()
    fourth_started = asyncio.Event()
    started_agents: list[str] = []

    def _make_agent(name: str, *, wait_for_release: bool = False):
        agent = MagicMock()
        agent.agent_name = name

        async def _analyze(_context):
            started_agents.append(name)
            if len(started_agents) >= 3:
                wave_started.set()
            if name == "fielding":
                fourth_started.set()
            if wait_for_release:
                await release_wave.wait()
            return f"## {name}\n\nok"

        agent.analyze = _analyze
        return agent

    orchestrator._agents = [
        _make_agent("hopper", wait_for_release=True),
        _make_agent("kay", wait_for_release=True),
        _make_agent("liskov", wait_for_release=True),
        _make_agent("fielding"),
    ]
    orchestrator._emit = AsyncMock()

    task = asyncio.create_task(
        orchestrator._run_agents_attempt("job-test", context, sequential=False)
    )

    await asyncio.wait_for(wave_started.wait(), timeout=0.2)
    assert started_agents == ["hopper", "kay", "liskov"]
    assert not fourth_started.is_set()

    release_wave.set()
    sections, failures = await asyncio.wait_for(task, timeout=0.2)

    assert failures == {}
    assert fourth_started.is_set()
    assert sections == {
        "hopper": "## hopper\n\nok",
        "kay": "## kay\n\nok",
        "liskov": "## liskov\n\nok",
        "fielding": "## fielding\n\nok",
    }


@pytest.mark.asyncio
async def test_run_agents_recovers_transient_failures_with_backup_provider(store, monkeypatch):
    """Los agentes con fallo transitorio deben reintentarse con el proveedor backup."""
    orchestrator = Orchestrator(store=store)
    context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})

    hopper = MagicMock()
    hopper.agent_name = "hopper"
    kay = MagicMock()
    kay.agent_name = "kay"
    orchestrator._agents = [hopper, kay]

    first_sections = {"hopper": "## Stack tecnológico\n\n- Python"}
    first_failures = {"kay": RuntimeError("agent wall-clock timed out after 180.0s")}
    recovered_sections = {"kay": "## Arquitectura\n\n- Servicio principal"}

    run_attempt = AsyncMock(return_value=(first_sections, first_failures))
    orchestrator._run_agents_attempt = run_attempt

    monkeypatch.setattr("app.services.orchestrator.settings.provider", "ollama_cloud")
    monkeypatch.setattr("app.services.orchestrator.settings.zai_api_key", "test-key")
    monkeypatch.setattr(
        "app.services.orchestrator.settings.zai_model",
        "glm-5.2",
    )

    with patch.object(
        orchestrator,
        "_recover_failed_agents_with_backup",
        new_callable=AsyncMock,
        return_value=(recovered_sections, {}),
    ) as recover:
        sections = await orchestrator._run_agents(
            "job-test",
            context,
            agents=[hopper, kay],
        )

    assert sections == {
        "hopper": "## Stack tecnológico\n\n- Python",
        "kay": "## Arquitectura\n\n- Servicio principal",
    }
    recover.assert_awaited_once()


@pytest.mark.asyncio
async def test_recover_failed_agents_uses_ollama_backup_when_primary_is_zai(store, monkeypatch):
    orchestrator = Orchestrator(store=store)
    context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})

    class _RecoverableAgent:
        created_kwargs = []

        def __init__(self, **kwargs):
            type(self).created_kwargs.append(kwargs)
            self.agent_name = "kay"

    original_agent = _RecoverableAgent()
    failures = {"kay": RuntimeError("llm request timed out")}
    orchestrator._run_agents_attempt = AsyncMock(
        return_value=({"kay": "## Arquitectura\n\n- Servicio principal"}, {})
    )

    monkeypatch.setattr("app.services.orchestrator.settings.ollama_cloud_api_key", "ollama-key")
    monkeypatch.setattr("app.services.orchestrator.settings.ollama_cloud_model", "deepseek-v4-pro:cloud")
    monkeypatch.setattr("app.services.orchestrator.settings.ollama_cloud_fallback_models", "")

    sections, recovered_failures = await orchestrator._recover_failed_agents_with_backup(
        "job-test",
        context,
        agents=[original_agent],
        failures=failures,
        enabled=True,
        primary_provider="zai",
    )

    assert sections == {"kay": "## Arquitectura\n\n- Servicio principal"}
    assert recovered_failures == {}
    assert _RecoverableAgent.created_kwargs[1]["provider_override"] == "ollama_cloud"
    assert _RecoverableAgent.created_kwargs[1]["model_override"] == "deepseek-v4-pro:cloud"
    assert _RecoverableAgent.created_kwargs[1]["enable_fallback"] is False


@pytest.mark.asyncio
async def test_recover_failed_agents_tries_second_backup_when_first_fails(store, monkeypatch):
    orchestrator = Orchestrator(store=store)
    context = RepoContext(tree="└── README.md", files={"README.md": "# demo"})

    class _RecoverableAgent:
        created_kwargs = []

        def __init__(self, **kwargs):
            type(self).created_kwargs.append(kwargs)
            self.agent_name = "kay"

    original_agent = _RecoverableAgent()
    failures = {"kay": RuntimeError("llm request timed out")}
    orchestrator._run_agents_attempt = AsyncMock(
        side_effect=[
            ({}, {"kay": RuntimeError("ollama subscription required")}),
            ({}, {"kay": RuntimeError("ollama backup failed")}),
            ({"kay": "## Arquitectura\n\n- Servicio principal"}, {}),
        ]
    )

    monkeypatch.setattr("app.services.orchestrator.settings.ollama_cloud_api_key", "ollama-key")
    monkeypatch.setattr("app.services.orchestrator.settings.ollama_cloud_model", "deepseek-v4-pro:cloud")
    monkeypatch.setattr(
        "app.services.orchestrator.settings.ollama_cloud_fallback_models",
        "kimi-k2.7-code:cloud",
    )
    monkeypatch.setattr("app.services.orchestrator.settings.zai_api_key", "zai-key")
    monkeypatch.setattr("app.services.orchestrator.settings.zai_model", "glm-5.2")

    sections, recovered_failures = await orchestrator._recover_failed_agents_with_backup(
        "job-test",
        context,
        agents=[original_agent],
        failures=failures,
        enabled=True,
        primary_provider="nan",
    )

    assert sections == {"kay": "## Arquitectura\n\n- Servicio principal"}
    assert recovered_failures == {}
    assert orchestrator._run_agents_attempt.await_count == 3
    assert _RecoverableAgent.created_kwargs[1]["provider_override"] == "ollama_cloud"
    assert _RecoverableAgent.created_kwargs[1]["model_override"] == "deepseek-v4-pro:cloud"
    assert _RecoverableAgent.created_kwargs[2]["provider_override"] == "ollama_cloud"
    assert _RecoverableAgent.created_kwargs[2]["model_override"] == "kimi-k2.7-code:cloud"
    assert _RecoverableAgent.created_kwargs[3]["provider_override"] == "zai"
    assert _RecoverableAgent.created_kwargs[3]["model_override"] == "glm-5.2"


@pytest.mark.asyncio
async def test_recover_failed_agents_uses_degraded_context_after_backups_fail(store):
    orchestrator = Orchestrator(store=store)
    context = RepoContext(
        tree="\n".join(f"├── file_{index}.py" for index in range(10)),
        files={f"file_{index}.py": "print('demo')\n" for index in range(10)},
    )

    knuth = MagicMock()
    knuth.agent_name = "knuth"
    failures = {"knuth": RuntimeError("llm request timed out")}
    seen = {}

    async def fake_run_attempt(job_id, retry_context, *, agents, sequential):
        seen["job_id"] = job_id
        seen["context"] = retry_context
        seen["agents"] = agents
        seen["sequential"] = sequential
        return {"knuth": "## Calidad\n\n- Tests relevantes"}, {}

    orchestrator._run_agents_attempt = fake_run_attempt

    sections, recovered_failures = (
        await orchestrator._recover_failed_agents_with_degraded_context(
            "job-test",
            context,
            agents=[knuth],
            failures=failures,
            enabled=True,
        )
    )

    assert sections == {"knuth": "## Calidad\n\n- Tests relevantes"}
    assert recovered_failures == {}
    assert seen["job_id"] == "job-test"
    assert seen["agents"] == [knuth]
    assert seen["sequential"] is True
    assert len(seen["context"].files) < len(context.files)


def test_send_email_notifications_uses_repo_url_and_deduplicates():
    """Debe enviar una sola vez por email aunque haya varias filas pendientes del mismo repo."""
    orchestrator = Orchestrator(store=JobStore())

    fake_notifications = [
        {
            "id": "n1",
            "job_id": "job-a",
            "repo_url": "https://github.com/ianmove/lowpoly64",
            "email": "pruebas@00b.tech",
        },
        {
            "id": "n2",
            "job_id": "job-b",
            "repo_url": "https://github.com/ianmove/lowpoly64",
            "email": "pruebas@00b.tech",
        },
        {
            "id": "n3",
            "job_id": "job-c",
            "repo_url": "https://github.com/ianmove/lowpoly64",
            "email": "otro@00b.tech",
        },
    ]

    notifications_repo = MagicMock()
    notifications_repo.find_pending_for_repo.return_value = fake_notifications

    with (
        patch("app.database.notifications_repo.NotificationsRepo", return_value=notifications_repo),
        patch("app.services.email_service.send_analysis_ready", return_value=True) as send_email,
    ):
        orchestrator._send_email_notifications(
            job_id="job-final",
            repo_url="https://github.com/ianmove/lowpoly64",
            repo_full_name="ianmove/lowpoly64",
        )

    assert notifications_repo.find_pending_for_repo.call_count == 1
    notifications_repo.find_pending_for_repo.assert_called_once_with(
        "https://github.com/ianmove/lowpoly64"
    )
    assert send_email.call_count == 2
    notifications_repo.mark_sent.assert_any_call("n1")
    notifications_repo.mark_sent.assert_any_call("n2")
    notifications_repo.mark_sent.assert_any_call("n3")
