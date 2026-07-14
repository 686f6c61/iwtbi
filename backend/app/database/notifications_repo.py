"""Repositorio PostgreSQL de notificaciones por email asociadas a análisis."""

import logging
from datetime import datetime, timezone

from app.database import postgres_client

_logger = logging.getLogger(__name__)


class NotificationsRepo:
    """Persistencia de avisos directos cuando un análisis termina."""

    def save(self, job_id: str, repo_url: str, email: str) -> dict | None:
        try:
            with postgres_client.connect() as conn:
                row = conn.execute(
                    """
                    INSERT INTO repo_notifications (job_id, repo_url, email)
                    VALUES (%s, %s, %s)
                    RETURNING *
                    """,
                    (job_id, repo_url, email),
                ).fetchone()
                return dict(row) if row else None
        except Exception as exc:
            _logger.error(
                "Error al guardar notificación para job '%s', email '%s': %s",
                job_id,
                email,
                exc,
            )
            return None

    def find_by_job(self, job_id: str) -> list[dict]:
        try:
            with postgres_client.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM repo_notifications
                    WHERE job_id = %s AND sent_at IS NULL
                    ORDER BY created_at ASC
                    """,
                    (job_id,),
                ).fetchall()
                return [dict(row) for row in rows]
        except Exception as exc:
            _logger.error(
                "Error al buscar notificaciones para job '%s': %s",
                job_id,
                exc,
            )
            return []

    def find_pending_for_repo(self, repo_url: str) -> list[dict]:
        try:
            with postgres_client.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM repo_notifications
                    WHERE repo_url = %s AND sent_at IS NULL
                    ORDER BY created_at ASC
                    """,
                    (repo_url,),
                ).fetchall()
                return [dict(row) for row in rows]
        except Exception as exc:
            _logger.error(
                "Error al buscar notificaciones pendientes para repo '%s': %s",
                repo_url,
                exc,
            )
            return []

    def mark_sent(self, notification_id: str) -> None:
        try:
            sent_at = datetime.now(timezone.utc)
            with postgres_client.connect() as conn:
                conn.execute(
                    """
                    UPDATE repo_notifications
                    SET sent_at = %s
                    WHERE id = %s
                    """,
                    (sent_at, notification_id),
                )
        except Exception as exc:
            _logger.error(
                "Error al marcar notificación '%s' como enviada: %s",
                notification_id,
                exc,
            )
