"""Endpoint GET /api/ticket — emite tickets efímeros para iniciar análisis."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from slowapi import Limiter

from app.config import settings
from app.services.request_meta import get_client_ip, get_user_agent
from app.store.job_store import JobStore


class TicketResponse(BaseModel):
    """Respuesta JSON del endpoint de emisión de tickets."""

    ticket: str


def get_ticket_router(store: JobStore, limiter: Limiter) -> APIRouter:
    """Construye el router de tickets con store y limiter inyectados."""
    router = APIRouter()

    @router.get("/ticket")
    @limiter.limit(settings.ticket_rate_limit)
    async def issue_ticket(request: Request) -> TicketResponse:
        ticket = store.issue_ticket(
            client_ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return TicketResponse(ticket=ticket)

    return router
