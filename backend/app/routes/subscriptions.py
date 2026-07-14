"""Endpoints para gestionar avisos futuros y bajas desde email."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter

from app.database.subscriptions_store import SubscriptionsStore
from app.services.unsubscribe_tokens import parse_unsubscribe_token


class UnsubscribeRequest(BaseModel):
    """Cuerpo de la baja de avisos futuros."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope: Literal["repo", "global"]
    token: str = Field(min_length=16, max_length=4096)


class UnsubscribeResponse(BaseModel):
    """Resultado de la operación de baja."""

    status: Literal["repo_unsubscribed", "global_unsubscribed", "already_inactive", "invalid_token"]
    message: str
    email: str | None = None
    repo_url: str | None = None


def get_subscriptions_router(limiter: Limiter) -> APIRouter:
    """Construye el router de gestión de suscripciones."""
    router = APIRouter()

    @router.post("/subscriptions/unsubscribe")
    @limiter.limit("20/minute")
    async def unsubscribe(request: Request, body: UnsubscribeRequest) -> UnsubscribeResponse:
        payload = parse_unsubscribe_token(body.token)
        if not payload or payload.get("scope") != body.scope:
            return UnsubscribeResponse(
                status="invalid_token",
                message="No se pudo validar este enlace de baja. Pide un correo nuevo y vuelve a intentarlo.",
            )

        email = payload["email"]
        store = SubscriptionsStore()

        if body.scope == "global":
            store.unsubscribe_global(email=email)
            return UnsubscribeResponse(
                status="global_unsubscribed",
                message="Hemos desactivado todos tus avisos futuros. Los análisis que pidas manualmente seguirán pudiendo enviarte un correo si lo solicitas.",
                email=email,
            )

        repo_url = payload.get("repo_url") or ""
        changed = store.unsubscribe_repo(repo_url=repo_url, email=email)
        return UnsubscribeResponse(
            status="repo_unsubscribed" if changed else "already_inactive",
            message=(
                "Ya no te avisaremos cuando aparezcan análisis nuevos de este repo."
                if changed
                else "No había una suscripción activa para este repositorio."
            ),
            email=email,
            repo_url=repo_url,
        )

    return router
