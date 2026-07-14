"""Repositorio PostgreSQL de análisis cacheados."""

import logging

from psycopg import sql
from psycopg.types.json import Jsonb

from app.database import postgres_client

_logger = logging.getLogger(__name__)

_LIST_COLUMNS = "id,repo_url,repo_full_name,git_sha,tags,created_at,updated_at"
_LIST_COLUMN_NAMES = _LIST_COLUMNS.split(",")

_SORT_MAPPING: dict[str, tuple[str, bool]] = {
    "updated_desc": ("updated_at", True),
    "updated_asc": ("updated_at", False),
    "name_asc": ("repo_full_name", False),
    "name_desc": ("repo_full_name", True),
}


def _page_payload(
    *,
    items: list[dict],
    total: int,
    page: int,
    page_size: int,
    sort: str,
) -> dict:
    total_pages = max((total + page_size - 1) // page_size, 1) if total else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "sort": sort if sort in _SORT_MAPPING else "updated_desc",
    }


class AnalysesRepo:
    """Persistencia de análisis cacheados en PostgreSQL interno."""

    def __init__(self) -> None:
        self.last_error: Exception | None = None

    def find_by_url(self, repo_url: str) -> dict | None:
        try:
            self.last_error = None
            with postgres_client.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM analyses WHERE repo_url = %s",
                    (repo_url,),
                ).fetchone()
                return dict(row) if row else None
        except Exception as exc:
            self.last_error = exc
            _logger.error("Error al buscar análisis para '%s': %s", repo_url, exc)
            return None

    def find_by_full_name(self, repo_full_name: str) -> dict | None:
        try:
            self.last_error = None
            with postgres_client.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM analyses WHERE repo_full_name = %s",
                    (repo_full_name,),
                ).fetchone()
                return dict(row) if row else None
        except Exception as exc:
            self.last_error = exc
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
        try:
            self.last_error = None
            with postgres_client.connect() as conn:
                row = conn.execute(
                    """
                    INSERT INTO analyses (
                        repo_url, repo_full_name, document, git_sha, tags
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (repo_url) DO UPDATE SET
                        repo_full_name = EXCLUDED.repo_full_name,
                        document = EXCLUDED.document,
                        git_sha = EXCLUDED.git_sha,
                        tags = EXCLUDED.tags,
                        updated_at = now()
                    RETURNING *
                    """,
                    (repo_url, repo_full_name, document, git_sha, Jsonb(tags or [])),
                ).fetchone()
                return dict(row) if row else None
        except Exception as exc:
            self.last_error = exc
            _logger.error("Error al guardar análisis para '%s': %s", repo_url, exc)
            return None

    def list_all(self) -> list[dict]:
        try:
            self.last_error = None
            with postgres_client.connect() as conn:
                rows = conn.execute(
                    sql.SQL("SELECT {columns} FROM analyses ORDER BY updated_at DESC").format(
                        columns=sql.SQL(", ").join(
                            sql.Identifier(name) for name in _LIST_COLUMN_NAMES
                        )
                    )
                ).fetchall()
                return [dict(row) for row in rows]
        except Exception as exc:
            self.last_error = exc
            _logger.error("Error al listar análisis: %s", exc)
            return []

    def list_page(
        self,
        page: int = 1,
        page_size: int = 21,
        sort: str = "updated_desc",
        query: str | None = None,
    ) -> dict:
        column, desc = _SORT_MAPPING.get(sort, _SORT_MAPPING["updated_desc"])
        start = (page - 1) * page_size
        direction = "DESC" if desc else "ASC"
        normalized_query = (query or "").strip()
        where_clause = (
            sql.SQL("WHERE strpos(lower(repo_full_name), lower(%s)) > 0")
            if normalized_query
            else sql.SQL("")
        )
        filter_params: tuple[object, ...] = (
            (normalized_query,) if normalized_query else ()
        )

        try:
            self.last_error = None
            with postgres_client.connect() as conn:
                total = conn.execute(
                    sql.SQL("SELECT count(*) AS count FROM analyses {where}").format(
                        where=where_clause
                    ),
                    filter_params,
                ).fetchone()
                rows = conn.execute(
                    sql.SQL(
                        """
                    SELECT {columns}
                    FROM analyses
                    {where}
                    ORDER BY {column} {direction}
                    LIMIT %s OFFSET %s
                    """
                    ).format(
                        columns=sql.SQL(", ").join(
                            sql.Identifier(name) for name in _LIST_COLUMN_NAMES
                        ),
                        where=where_clause,
                        column=sql.Identifier(column),
                        direction=sql.SQL(direction),
                    ),
                    (*filter_params, page_size, start),
                ).fetchall()
                return _page_payload(
                    items=[dict(row) for row in rows],
                    total=int((total or {}).get("count") or 0),
                    page=page,
                    page_size=page_size,
                    sort=sort,
                )
        except Exception as exc:
            self.last_error = exc
            _logger.error(
                "Error al listar análisis paginados (page=%s, page_size=%s, sort=%s): %s",
                page,
                page_size,
                sort,
                exc,
            )
            return _page_payload(items=[], total=0, page=page, page_size=page_size, sort=sort)
