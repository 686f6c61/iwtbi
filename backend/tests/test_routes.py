"""Tests de integración para las rutas FastAPI."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.routes.analyze import get_analyze_router
from app.routes.biblioteca import get_biblioteca_router
from app.routes.health import health_router
from app.routes.preflight import get_preflight_router
from app.routes.stream import get_stream_router
from app.routes.subscriptions import get_subscriptions_router
from app.routes.ticket import get_ticket_router
from app.services.request_meta import get_client_ip
from app.services.unsubscribe_tokens import build_unsubscribe_token
from app.store.job_store import JobStore


def _issue_ticket(client: TestClient) -> str:
    response = client.get("/api/ticket", headers={"user-agent": "pytest"})
    assert response.status_code == 200
    return response.json()["ticket"]


def _internal_headers() -> dict[str, str]:
    return {
        "x-real-ip": "127.0.0.1",
        "x-internal-token": "test-internal-token",
        "user-agent": "pytest",
    }


@pytest.fixture
def client() -> TestClient:
    store = JobStore()
    limiter = Limiter(key_func=get_client_ip)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins.split(","),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "X-Ticket"],
    )
    app.include_router(get_preflight_router(limiter), prefix="/api")
    app.include_router(get_ticket_router(store, limiter), prefix="/api")
    app.include_router(get_analyze_router(store, limiter), prefix="/api")
    app.include_router(get_stream_router(store, limiter), prefix="/api")
    app.include_router(get_subscriptions_router(limiter), prefix="/api")
    app.include_router(get_biblioteca_router(limiter), prefix="/api")
    app.include_router(health_router)
    app.state.job_store = store

    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def isolate_analyze_route_side_effects():
    """Evita llamadas reales a la biblioteca o al pipeline durante tests de rutas."""
    with (
        patch("app.routes.analyze.AnalysesRepo.find_by_url", return_value=None),
        patch("app.routes.analyze.Orchestrator.run", new_callable=AsyncMock),
        patch.object(settings, "internal_analyze_token", "test-internal-token"),
        patch.object(
            settings,
            "email_unsubscribe_secret",
            "test-unsubscribe-secret-with-enough-entropy",
        ),
    ):
        yield


def test_health_endpoint(client: TestClient):
    """El endpoint de salud debe responder 200 con status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "email_notifications_enabled": bool(settings.resend_api_key.strip()),
    }


def test_dependency_health_requires_internal_token(client: TestClient):
    """La salud de dependencias no debe exponerse sin token interno."""
    response = client.get("/health/dependencies")
    assert response.status_code == 403


def test_dependency_health_reports_ok(client: TestClient):
    """El healthcheck interno debe resumir dependencias sin mostrar secretos."""
    with (
        patch("app.routes.health.AnalysesRepo") as repo_cls,
        patch.object(settings, "provider", "ollama_cloud"),
        patch.object(settings, "ollama_cloud_api_key", "ollama-key"),
        patch.object(settings, "database_backend", "postgres"),
        patch.object(settings, "database_url", "postgresql://example"),
    ):
        repo = repo_cls.return_value
        repo.last_error = None
        repo.list_page.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 1,
            "total_pages": 0,
            "sort": "updated_desc",
        }
        response = client.get("/health/dependencies", headers=_internal_headers())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["storage"]["backend"] == settings.database_backend
    assert data["storage"]["ok"] is True
    assert "api_key" not in str(data).lower()


def test_dependency_health_reports_degraded_storage(client: TestClient):
    """Si la persistencia falla, el healthcheck interno debe devolver 503."""
    with (
        patch("app.routes.health.AnalysesRepo") as repo_cls,
        patch.object(settings, "provider", "ollama_cloud"),
        patch.object(settings, "ollama_cloud_api_key", "ollama-key"),
        patch.object(settings, "database_backend", "postgres"),
        patch.object(settings, "database_url", "postgresql://example"),
    ):
        repo = repo_cls.return_value
        repo.last_error = RuntimeError("dns")
        repo.list_page.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 1,
            "total_pages": 0,
            "sort": "updated_desc",
        }
        response = client.get("/health/dependencies", headers=_internal_headers())

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["storage"]["ok"] is False
    assert data["storage"]["error"] == "RuntimeError"


def test_analyze_invalid_url_returns_422(client: TestClient):
    """Una URL de GitLab debe rechazarse con 422."""
    response = client.post(
        "/api/analyze",
        headers={"X-Ticket": _issue_ticket(client), "user-agent": "pytest"},
        json={"url": "https://gitlab.com/user/repo"},
    )
    assert response.status_code == 422


def test_preflight_invalid_url_returns_422(client: TestClient):
    """Una URL que no sea de GitHub debe rechazarse también en preflight."""
    response = client.post(
        "/api/preflight",
        json={"url": "https://gitlab.com/user/repo"},
    )
    assert response.status_code == 422


def test_preflight_returns_mode_payload(client: TestClient):
    """Preflight debe devolver el modo y las métricas medidas."""
    with patch(
        "app.routes.preflight.RepoPreflightService.inspect",
        new_callable=AsyncMock,
        return_value=type(
            "Result",
            (),
            {
                "mode": "optimized",
                "reason": "prioritized_context",
                "candidate_files": 42,
                "measured_candidate_files": 42,
                "selected_files": 16,
                "total_candidate_chars": 120000,
                "selected_chars": 80000,
                "oversized_files": 1,
                "budget_truncated_files": 1,
                "measurement_limited": False,
                "repo_size_kb": None,
            },
        )(),
    ):
        response = client.post(
            "/api/preflight",
            json={"url": "https://github.com/kelseyhightower/nocode"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "mode": "optimized",
        "reason": "prioritized_context",
        "candidate_files": 42,
        "measured_candidate_files": 42,
        "selected_files": 16,
        "total_candidate_chars": 120000,
        "selected_chars": 80000,
        "oversized_files": 1,
        "budget_truncated_files": 1,
        "candidate_file_limit": settings.preflight_max_candidate_files,
        "measurement_limited": False,
        "repo_size_kb": None,
        "repo_size_limit_mb": settings.repo_size_limit_mb,
    }


def test_preflight_clone_failure_returns_503(client: TestClient):
    """Si la medición falla de forma transitoria, la API debe responder 503 controlado."""
    with patch(
        "app.routes.preflight.RepoPreflightService.inspect",
        new_callable=AsyncMock,
        side_effect=RuntimeError("git clone falló"),
    ):
        response = client.post(
            "/api/preflight",
            json={"url": "https://github.com/VoltAgent/voltagent"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "No se pudo medir el repositorio en este momento.",
    }


def test_analyze_missing_user_repo_returns_422(client: TestClient):
    """Una URL de GitHub sin usuario/repo debe rechazarse."""
    response = client.post(
        "/api/analyze",
        headers={"X-Ticket": _issue_ticket(client), "user-agent": "pytest"},
        json={"url": "https://github.com/user"},
    )
    assert response.status_code == 422


def test_analyze_valid_url_returns_job_id(client: TestClient):
    """Una URL GitHub válida debe devolver job_id y stream_url."""
    response = client.post(
        "/api/analyze",
        headers={"X-Ticket": _issue_ticket(client), "user-agent": "pytest"},
        json={"url": "https://github.com/kelseyhightower/nocode"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert "stream_url" in data
    assert data["stream_url"].startswith("/api/stream/")

    job = client.app.state.job_store.get(data["job_id"])
    assert job is not None
    queued_event = job.queue.get_nowait()
    assert queued_event == {"type": "status", "data": {"status": "queued"}}


def test_analyze_requires_ticket(client: TestClient):
    """Sin X-Ticket el backend debe rechazar el análisis."""
    response = client.post(
        "/api/analyze",
        headers={"user-agent": "pytest"},
        json={"url": "https://github.com/kelseyhightower/nocode"},
    )
    assert response.status_code == 403


def test_internal_analyze_bypasses_public_ticket_for_loopback(client: TestClient):
    """La ruta interna debe permitir análisis desde loopback sin ticket."""
    response = client.post(
        "/api/analyze/internal",
        headers=_internal_headers(),
        json={"url": "https://github.com/kelseyhightower/nocode"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["stream_url"].startswith("/api/stream/")


def test_internal_analyze_allows_private_bridge_ip(client: TestClient):
    """La ruta interna también debe permitir peticiones desde la red privada Docker."""
    headers = _internal_headers()
    headers["x-real-ip"] = "172.19.0.1"
    response = client.post(
        "/api/analyze/internal",
        headers=headers,
        json={"url": "https://github.com/kelseyhightower/nocode"},
    )
    assert response.status_code == 200


def test_internal_analyze_rejects_missing_internal_token(client: TestClient):
    """La ruta interna debe exigir token dedicado además de IP interna."""
    response = client.post(
        "/api/analyze/internal",
        headers={"x-real-ip": "127.0.0.1", "user-agent": "pytest"},
        json={"url": "https://github.com/kelseyhightower/nocode"},
    )
    assert response.status_code == 403


def test_internal_analyze_returns_503_when_cache_lookup_fails(client: TestClient):
    """Un fallo de persistencia no debe confundirse con cache miss ni lanzar LLM."""

    class _FailingAnalysesRepo:
        last_error = RuntimeError("dns")

        def find_by_url(self, url: str):
            return None

    with patch("app.routes.analyze.AnalysesRepo", return_value=_FailingAnalysesRepo()):
        response = client.post(
            "/api/analyze/internal",
            headers=_internal_headers(),
            json={"url": "https://github.com/kelseyhightower/nocode"},
        )

    assert response.status_code == 503
    assert client.app.state.job_store._jobs == {}


def test_internal_analyze_accepts_llm_overrides(client: TestClient):
    """La ruta interna debe persistir overrides de proveedor/modelo por job."""
    response = client.post(
        "/api/analyze/internal",
        headers=_internal_headers(),
        json={
            "url": "https://github.com/kelseyhightower/nocode",
            "force_new": True,
            "provider_override": "zai",
            "model_override": "glm-5.2",
            "disable_fallback": True,
            "profile_label": "benchmark-glm-5.2",
        },
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = client.app.state.job_store.get(job_id)
    assert job is not None
    assert job.provider_override == "zai"
    assert job.model_override == "glm-5.2"
    assert job.disable_fallback is True
    assert job.profile_label == "benchmark-glm-5.2"


def test_analyze_rejects_reused_ticket(client: TestClient):
    """Un ticket consumido no puede reutilizarse."""
    ticket = _issue_ticket(client)
    headers = {"X-Ticket": ticket, "user-agent": "pytest"}

    first = client.post(
        "/api/analyze",
        headers=headers,
        json={"url": "https://github.com/kelseyhightower/nocode", "force_new": True},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/analyze",
        headers=headers,
        json={"url": "https://github.com/kelseyhightower/nocode", "force_new": True},
    )
    assert second.status_code == 403


def test_stream_nonexistent_job_returns_404(client: TestClient):
    """Un job_id que no existe debe devolver 404."""
    response = client.get("/api/stream/id-que-no-existe")
    assert response.status_code == 404


def test_biblioteca_returns_paginated_payload(client: TestClient):
    """Biblioteca debe devolver items y metadatos de paginación."""
    with patch(
        "app.routes.biblioteca.AnalysesRepo.list_page",
        return_value={
            "items": [{"id": "1", "repo_full_name": "openai/openai-quickstart-node"}],
            "total": 25,
            "page": 2,
            "page_size": 20,
            "total_pages": 2,
            "sort": "name_desc",
        },
    ) as list_page:
        response = client.get("/api/biblioteca?page=2&page_size=20&sort=name_desc")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"id": "1", "repo_full_name": "openai/openai-quickstart-node"}],
        "total": 25,
        "page": 2,
        "page_size": 20,
        "total_pages": 2,
        "sort": "name_desc",
    }
    list_page.assert_called_once_with(
        page=2,
        page_size=20,
        sort="name_desc",
        query=None,
    )


def test_biblioteca_forwards_global_search(client: TestClient):
    """La búsqueda se ejecuta en persistencia y no solo sobre la página visible."""
    with patch(
        "app.routes.biblioteca.AnalysesRepo.list_page",
        return_value={
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 21,
            "total_pages": 0,
            "sort": "updated_desc",
        },
    ) as list_page:
        response = client.get("/api/biblioteca?q=hello-world")

    assert response.status_code == 200
    list_page.assert_called_once_with(
        page=1,
        page_size=21,
        sort="updated_desc",
        query="hello-world",
    )


def test_biblioteca_rejects_invalid_repo_path(client: TestClient):
    """Los segmentos de ruta no admiten caracteres ajenos a nombres GitHub."""
    response = client.get("/api/biblioteca/octocat/hello%20world")
    assert response.status_code == 422


def test_biblioteca_returns_503_when_storage_fails(client: TestClient):
    """La biblioteca debe distinguir caída de persistencia de una página vacía."""

    class _FailingAnalysesRepo:
        last_error = RuntimeError("dns")

        def list_page(self, **kwargs):
            return {
                "items": [],
                "total": 0,
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
                "total_pages": 0,
                "sort": kwargs["sort"],
            }

    with patch("app.routes.biblioteca.AnalysesRepo", return_value=_FailingAnalysesRepo()):
        response = client.get("/api/biblioteca")

    assert response.status_code == 503


def test_biblioteca_detail_returns_503_when_storage_fails(client: TestClient):
    """El detalle también debe responder 503 si la persistencia no está disponible."""

    class _FailingAnalysesRepo:
        last_error = RuntimeError("dns")

        def find_by_full_name(self, repo_full_name: str):
            return None

    with patch("app.routes.biblioteca.AnalysesRepo", return_value=_FailingAnalysesRepo()):
        response = client.get("/api/biblioteca/octocat/Hello-World")

    assert response.status_code == 503


def test_unsubscribe_repo_route_returns_success(client: TestClient):
    """La baja por repo debe responder correctamente con un token válido."""
    token = build_unsubscribe_token(
        scope="repo",
        email="user@example.com",
        repo_url="https://github.com/example/repo",
    )

    with patch(
        "app.routes.subscriptions.SubscriptionsStore.unsubscribe_repo",
        return_value=True,
    ) as unsubscribe_repo:
        response = client.post(
            "/api/subscriptions/unsubscribe",
            json={"scope": "repo", "token": token},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "repo_unsubscribed",
        "message": "Ya no te avisaremos cuando aparezcan análisis nuevos de este repo.",
        "email": "user@example.com",
        "repo_url": "https://github.com/example/repo",
    }
    unsubscribe_repo.assert_called_once_with(
        repo_url="https://github.com/example/repo",
        email="user@example.com",
    )
