"""Endpoint POST /api/preflight — mide el repo antes de lanzar el análisis."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter

from app.config import settings
from app.services.git_cloner import validate_github_url
from app.services.repo_preflight import RepoPreflightService


class PreflightRequest(BaseModel):
    """Cuerpo del endpoint de premedición."""

    url: str


class PreflightResponse(BaseModel):
    """Respuesta estructurada para el frontend de análisis."""

    mode: Literal["normal", "optimized", "too_large"]
    reason: Literal[
        "fits_context",
        "prioritized_context",
        "context_budget_exceeded",
        "file_count_limit",
        "repo_size_limit",
    ]
    candidate_files: int
    selected_files: int
    total_candidate_chars: int
    selected_chars: int
    oversized_files: int
    budget_truncated_files: int
    candidate_file_limit: int


def get_preflight_router(limiter: Limiter) -> APIRouter:
    """Construye la ruta de premedición con rate limit propio."""
    router = APIRouter()
    service = RepoPreflightService()

    @router.post(
        "/preflight",
        responses={422: {"description": "URL de GitHub no válida"}},
    )
    @limiter.limit(settings.preflight_rate_limit)
    async def preflight(
        request: Request,
        body: PreflightRequest,
    ) -> PreflightResponse:
        del request  # requerido por slowapi; el limiter lee la request aunque no se use

        url = body.url.rstrip("/")
        if not validate_github_url(url):
            raise HTTPException(
                status_code=422,
                detail=(
                    "La URL debe ser un repositorio GitHub público válido: "
                    "https://github.com/usuario/repositorio"
                ),
            )

        result = await service.inspect(url)
        return PreflightResponse(
            mode=result.mode,
            reason=result.reason,
            candidate_files=result.candidate_files,
            selected_files=result.selected_files,
            total_candidate_chars=result.total_candidate_chars,
            selected_chars=result.selected_chars,
            oversized_files=result.oversized_files,
            budget_truncated_files=result.budget_truncated_files,
            candidate_file_limit=settings.preflight_max_candidate_files,
        )

    return router
