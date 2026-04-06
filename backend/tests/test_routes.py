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
from app.routes.biblioteca import biblioteca_router
from app.routes.preflight import get_preflight_router
from app.routes.stream import get_stream_router
from app.routes.ticket import get_ticket_router
from app.services.request_meta import get_client_ip
from app.store.job_store import JobStore


def _issue_ticket(client: TestClient) -> str:
    response = client.get("/api/ticket", headers={"user-agent": "pytest"})
    assert response.status_code == 200
    return response.json()["ticket"]


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
    app.include_router(biblioteca_router, prefix="/api")

    @app.get("/health")
    async def health() -> dict[str, bool | str]:
        return {
            "status": "ok",
            "email_notifications_enabled": bool(settings.resend_api_key.strip()),
        }

    return TestClient(app)


@pytest.fixture(autouse=True)
def isolate_analyze_route_side_effects():
    """Evita llamadas reales a Supabase o al pipeline durante tests de rutas."""
    with (
        patch("app.routes.analyze.AnalysesRepo.find_by_url", return_value=None),
        patch("app.routes.analyze.Orchestrator.run", new_callable=AsyncMock),
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
                "selected_files": 16,
                "total_candidate_chars": 120000,
                "selected_chars": 80000,
                "oversized_files": 1,
                "budget_truncated_files": 1,
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
        "selected_files": 16,
        "total_candidate_chars": 120000,
        "selected_chars": 80000,
        "oversized_files": 1,
        "budget_truncated_files": 1,
        "candidate_file_limit": settings.preflight_max_candidate_files,
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


def test_analyze_requires_ticket(client: TestClient):
    """Sin X-Ticket el backend debe rechazar el análisis."""
    response = client.post(
        "/api/analyze",
        headers={"user-agent": "pytest"},
        json={"url": "https://github.com/kelseyhightower/nocode"},
    )
    assert response.status_code == 403


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
    list_page.assert_called_once_with(page=2, page_size=20, sort="name_desc")
