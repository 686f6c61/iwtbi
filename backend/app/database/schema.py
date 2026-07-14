"""Bootstrap idempotente del esquema PostgreSQL."""

from __future__ import annotations

import logging
from pathlib import Path

from psycopg import sql

from app.config import settings
from app.database import postgres_client

_logger = logging.getLogger(__name__)
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "postgres" / "schema.sql"
_REQUIRED_TABLES = {
    "analyses",
    "repo_notifications",
    "repo_subscriptions",
    "email_preferences",
}


def _required_tables_exist() -> bool:
    placeholders = sql.SQL(", ").join(
        sql.Placeholder() for _ in _REQUIRED_TABLES
    )
    query = sql.SQL(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ({placeholders})
    """
    ).format(placeholders=placeholders)
    try:
        with postgres_client.connect() as conn:
            rows = conn.execute(query, tuple(sorted(_REQUIRED_TABLES))).fetchall()
    except Exception:
        return False

    table_names = {
        row["table_name"] if isinstance(row, dict) else row[0]
        for row in rows
    }
    return _REQUIRED_TABLES.issubset(table_names)


def ensure_schema() -> bool:
    """
    Aplica el esquema PostgreSQL si hay `DATABASE_URL`.

    Los contenedores Postgres ejecutan `backend/postgres/schema.sql` solo en el
    primer arranque del volumen. Esta función cubre despliegues ya existentes
    donde se añade una tabla nueva después.
    """
    if not settings.database_url.strip():
        _logger.warning("DATABASE_URL no configurada; se omite bootstrap de esquema.")
        return False

    try:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with postgres_client.connect() as conn:
            conn.execute(sql)
    except Exception as exc:
        if _required_tables_exist():
            _logger.warning(
                "No se pudo reaplicar el esquema PostgreSQL, pero las tablas "
                "requeridas ya existen: %s",
                exc,
            )
            return True
        _logger.error("No se pudo aplicar el esquema PostgreSQL: %s", exc)
        return False
    return True
