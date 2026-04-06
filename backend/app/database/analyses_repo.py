"""
Repositorio de análisis cacheados en Supabase.

Encapsula todas las operaciones sobre la tabla ``public.analyses``.
Los errores de red o Supabase se registran y devuelven None / lista vacía
para que el pipeline pueda continuar sin bloqueos.
"""

import logging

from supabase import Client

from app.database.supabase_client import get_client

_logger = logging.getLogger(__name__)

# Columnas devueltas en el listado (sin 'document' para aligerar la respuesta).
# Se incluye 'tags' (jsonb) para mostrar chips de tecnología en las cards.
_LIST_COLUMNS = "id,repo_url,repo_full_name,git_sha,tags,created_at,updated_at"

_SORT_MAPPING: dict[str, tuple[str, bool]] = {
    "updated_desc": ("updated_at", True),
    "updated_asc": ("updated_at", False),
    "name_asc": ("repo_full_name", False),
    "name_desc": ("repo_full_name", True),
}


class AnalysesRepo:
    """
    Repositorio de análisis cacheados.

    Los métodos son síncronos porque supabase-py expone una API síncrona.
    Las operaciones son rápidas (caché, no pipeline LLM) así que no
    es necesario correrlas en un executor.

    El cliente Supabase se inicializa de forma lazy: la primera llamada a un
    método lo obtiene del singleton. Esto permite instanciar el repositorio
    aunque Supabase no esté configurado, lo que evita errores en entornos
    de test sin credenciales reales.
    """

    def __init__(self, client: Client | None = None) -> None:
        self._client = client

    def _get_client(self) -> Client:
        """Devuelve el cliente, inicializándolo la primera vez que se necesita."""
        if self._client is None:
            self._client = get_client()
        return self._client

    def find_by_url(self, repo_url: str) -> dict | None:
        """
        Busca el análisis cacheado para la URL indicada.

        Args:
            repo_url: URL completa del repositorio GitHub.

        Returns:
            Diccionario con todos los campos del análisis, o None si no existe.
        """
        try:
            result = (
                self._get_client().table("analyses")
                .select("*")
                .eq("repo_url", repo_url)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            _logger.error("Error al buscar análisis para '%s': %s", repo_url, exc)
            return None

    def find_by_full_name(self, repo_full_name: str) -> dict | None:
        """
        Busca el análisis cacheado por nombre completo del repo (owner/repo).

        Args:
            repo_full_name: Nombre en formato «owner/repo», ej. «686f6c61/GoTrash».

        Returns:
            Diccionario con todos los campos del análisis, o None si no existe.
        """
        try:
            result = (
                self._get_client().table("analyses")
                .select("*")
                .eq("repo_full_name", repo_full_name)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            _logger.error("Error al buscar análisis para '%s': %s", repo_full_name, exc)
            return None

    def save(
        self,
        repo_url: str,
        repo_full_name: str,
        document: str,
        git_sha: str,
        tags: list[str] | None = None,
    ) -> dict | None:
        """
        Guarda o actualiza el análisis en Supabase (upsert por repo_url).

        Solo el análisis más reciente persiste para cada repo. Si ya existe
        una entrada para ``repo_url``, la sobreescribe completamente.

        Args:
            repo_url: URL completa del repositorio.
            repo_full_name: Nombre «owner/repo» del repositorio.
            document: Documento Markdown completo generado por el sintetizador.
            git_sha: SHA del HEAD en el momento del análisis.
            tags: Lista de topics del repositorio en GitHub (ej. ["python", "fastapi"]).
                  Si es None o lista vacía, se guarda como array JSON vacío.

        Returns:
            Diccionario con la fila guardada, o None si el guardado falla.
        """
        try:
            result = (
                self._get_client().table("analyses")
                .upsert(
                    {
                        "repo_url": repo_url,
                        "repo_full_name": repo_full_name,
                        "document": document,
                        "git_sha": git_sha,
                        "tags": tags or [],
                    },
                    on_conflict="repo_url",
                )
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            _logger.error("Error al guardar análisis para '%s': %s", repo_url, exc)
            return None

    def list_all(self) -> list[dict]:
        """
        Devuelve todos los análisis guardados, ordenados por fecha de actualización.

        El campo ``document`` se excluye para aligerar la respuesta.

        Returns:
            Lista de dicts con: id, repo_url, repo_full_name, git_sha,
            created_at, updated_at. Lista vacía si hay error.
        """
        try:
            result = (
                self._get_client().table("analyses")
                .select(_LIST_COLUMNS)
                .order("updated_at", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            _logger.error("Error al listar análisis: %s", exc)
            return []

    def list_page(
        self,
        page: int = 1,
        page_size: int = 21,
        sort: str = "updated_desc",
    ) -> dict:
        """
        Devuelve una página de análisis guardados con metadatos de paginación.

        Args:
            page: Página 1-based solicitada.
            page_size: Número de elementos por página.
            sort: Clave de orden permitida.

        Returns:
            Dict con items, total, page, page_size, total_pages y sort.
            Si hay error, devuelve una página vacía coherente.
        """
        column, desc = _SORT_MAPPING.get(sort, _SORT_MAPPING["updated_desc"])
        start = (page - 1) * page_size
        end = start + page_size - 1

        try:
            result = (
                self._get_client().table("analyses")
                .select(_LIST_COLUMNS, count="exact")
                .order(column, desc=desc)
                .range(start, end)
                .execute()
            )
            total = result.count or 0
            total_pages = max((total + page_size - 1) // page_size, 1) if total else 0
            return {
                "items": result.data or [],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "sort": sort if sort in _SORT_MAPPING else "updated_desc",
            }
        except Exception as exc:
            _logger.error(
                "Error al listar análisis paginados (page=%s, page_size=%s, sort=%s): %s",
                page,
                page_size,
                sort,
                exc,
            )
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0,
                "sort": sort if sort in _SORT_MAPPING else "updated_desc",
            }
