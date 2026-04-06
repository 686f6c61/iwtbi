"""Tests del endpoint GET /api/ticket."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.routes.ticket import get_ticket_router
from app.services.request_meta import get_client_ip
from app.store.job_store import JobStore


def build_client() -> tuple[TestClient, JobStore]:
    store = JobStore()
    limiter = Limiter(key_func=get_client_ip)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(get_ticket_router(store, limiter), prefix="/api")
    return TestClient(app), store


def test_get_ticket_returns_uuid():
    client, _ = build_client()
    response = client.get("/api/ticket")
    assert response.status_code == 200
    data = response.json()
    assert "ticket" in data
    assert len(data["ticket"]) == 36
    assert data["ticket"].count("-") == 4


def test_get_ticket_each_call_is_unique():
    client, _ = build_client()
    r1 = client.get("/api/ticket")
    r2 = client.get("/api/ticket")
    assert r1.json()["ticket"] != r2.json()["ticket"]


def test_get_ticket_issues_consumable_ticket():
    client, store = build_client()
    response = client.get("/api/ticket", headers={"user-agent": "pytest"})
    ticket = response.json()["ticket"]

    assert store.consume_ticket(
        ticket,
        client_ip="testclient",
        user_agent="pytest",
    )
