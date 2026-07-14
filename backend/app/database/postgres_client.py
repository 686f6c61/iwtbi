"""Cliente PostgreSQL interno de la biblioteca."""

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.config import settings


@contextmanager
def connect() -> Iterator[Connection]:
    """
    Abre una conexión PostgreSQL con filas tipo dict.

    Se usa una conexión corta por operación porque las llamadas actuales son
    síncronas y de baja frecuencia. Si el tráfico crece, este módulo es el
    punto natural para introducir un pool.
    """
    if not settings.database_url.strip():
        raise ValueError("DATABASE_URL es obligatoria para la biblioteca PostgreSQL.")

    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
