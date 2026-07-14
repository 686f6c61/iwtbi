"""Endpoint POST /api/preflight — mide el repo antes de lanzar el análisis."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter

from app.config import settings
from app.services.git_cloner import validate_github_url
from app.services.repo_preflight import RepoPreflightService


class PreflightRequest(BaseModel):
    """Cuerpo del endpoint de premedición."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=2048)


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
    measured_candidate_files: int | None = None
    selected_files: int
    total_candidate_chars: int
    selected_chars: int
    oversized_files: int
    budget_truncated_files: int
    candidate_file_limit: int
    measurement_limited: bool = False
    repo_size_kb: int | None = None
    repo_size_limit_mb: int | None = None


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

        try:
            result = await service.inspect(url)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="No se pudo medir el repositorio en este momento.",
            ) from exc

        return PreflightResponse(
            mode=result.mode,
            reason=result.reason,
            candidate_files=result.candidate_files,
            measured_candidate_files=result.measured_candidate_files,
            selected_files=result.selected_files,
            total_candidate_chars=result.total_candidate_chars,
            selected_chars=result.selected_chars,
            oversized_files=result.oversized_files,
            budget_truncated_files=result.budget_truncated_files,
            candidate_file_limit=settings.preflight_max_candidate_files,
            measurement_limited=result.measurement_limited,
            repo_size_kb=result.repo_size_kb,
            repo_size_limit_mb=settings.repo_size_limit_mb,
        )

    return router
