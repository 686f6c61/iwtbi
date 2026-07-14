"""
Endpoints de la Biblioteca — listado y consulta de análisis cacheados.

La biblioteca expone dos endpoints de solo lectura:
- GET /api/biblioteca: lista todos los análisis (sin el campo document).
- GET /api/biblioteca/{owner}/{repo}: devuelve un análisis individual completo.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from slowapi import Limiter

from app.config import settings
from app.database.analyses_repo import AnalysesRepo

_logger = logging.getLogger(__name__)

def get_biblioteca_router(limiter: Limiter) -> APIRouter:
    """Construye las rutas públicas de biblioteca con límite por IP."""
    router = APIRouter()

    @router.get("/biblioteca")
    @limiter.limit(settings.biblioteca_rate_limit)
    async def list_analyses(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(21, ge=1, le=100),
        sort: Literal["updated_desc", "updated_asc", "name_asc", "name_desc"] = Query(
            "updated_desc"
        ),
        q: str | None = Query(default=None, min_length=1, max_length=100),
    ) -> dict:
        """Devuelve una página sin documentos, ordenada y filtrada por repositorio."""
        del request
        analyses_repo = AnalysesRepo()
        page_data = analyses_repo.list_page(
            page=page,
            page_size=page_size,
            sort=sort,
            query=q,
        )
        if analyses_repo.last_error:
            raise HTTPException(
                status_code=503,
                detail="La biblioteca no está disponible temporalmente.",
            )
        return page_data

    @router.get(
        "/biblioteca/{owner}/{repo}",
        responses={404: {"description": "Análisis no encontrado para el repositorio indicado"}},
    )
    @limiter.limit(settings.biblioteca_rate_limit)
    async def get_analysis(
        request: Request,
        owner: str = Path(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$"),
        repo: str = Path(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$"),
    ) -> dict:
        """Devuelve el análisis completo de un repositorio concreto."""
        del request
        repo_full_name = f"{owner}/{repo}"
        analyses_repo = AnalysesRepo()
        entry = analyses_repo.find_by_full_name(repo_full_name)
        if analyses_repo.last_error:
            raise HTTPException(
                status_code=503,
                detail="La biblioteca no está disponible temporalmente.",
            )
        if entry is None:
            _logger.info("Análisis no encontrado para '%s'.", repo_full_name)
            raise HTTPException(
                status_code=404,
                detail=f"No hay análisis guardado para {repo_full_name}.",
            )
        return entry

    return router
