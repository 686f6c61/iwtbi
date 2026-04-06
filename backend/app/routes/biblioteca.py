"""
Endpoints de la Biblioteca — listado y consulta de análisis cacheados.

La biblioteca expone dos endpoints de solo lectura:
- GET /api/biblioteca: lista todos los análisis (sin el campo document).
- GET /api/biblioteca/{owner}/{repo}: devuelve un análisis individual completo.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.database.analyses_repo import AnalysesRepo

_logger = logging.getLogger(__name__)

biblioteca_router = APIRouter()


@biblioteca_router.get("/biblioteca")
async def list_analyses(
    page: int = Query(1, ge=1),
    page_size: int = Query(21, ge=1, le=100),
    sort: Literal["updated_desc", "updated_asc", "name_asc", "name_desc"] = Query(
        "updated_desc"
    ),
) -> dict:
    """
    Devuelve una página de análisis guardados con orden configurable.

    El campo ``document`` se excluye para aligerar la respuesta.
    La página /biblioteca usa este endpoint para renderizar las cards y la paginación.

    Returns:
        Dict con ``items`` y metadatos de paginación.
    """
    return AnalysesRepo().list_page(page=page, page_size=page_size, sort=sort)


@biblioteca_router.get(
    "/biblioteca/{owner}/{repo}",
    responses={404: {"description": "Análisis no encontrado para el repositorio indicado"}},
)
async def get_analysis(owner: str, repo: str) -> dict:
    """
    Devuelve el análisis completo de un repositorio, incluido el documento Markdown.

    La URL del parámetro se construye como «owner/repo», lo que coincide con
    el campo ``repo_full_name`` de la tabla ``analyses``.

    Args:
        owner: Propietario del repositorio (usuario u organización GitHub).
        repo: Nombre del repositorio.

    Returns:
        Diccionario completo del análisis incluyendo el campo ``document``.

    Raises:
        HTTPException 404: Si no existe análisis para el repositorio indicado.
    """
    repo_full_name = f"{owner}/{repo}"
    entry = AnalysesRepo().find_by_full_name(repo_full_name)
    if entry is None:
        _logger.info("Análisis no encontrado para '%s'.", repo_full_name)
        raise HTTPException(
            status_code=404,
            detail=f"No hay análisis guardado para {repo_full_name}.",
        )
    return entry
