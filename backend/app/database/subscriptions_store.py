"""Repositorio PostgreSQL de suscripciones a avisos futuros por repositorio."""

from __future__ import annotations

from datetime import datetime, timezone

from app.database import postgres_client


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class SubscriptionsStore:
    """Almacén PostgreSQL para suscripciones y preferencias de avisos futuros."""

    def upsert_repo_subscription(
        self,
        *,
        repo_url: str,
        email: str,
        last_notified_git_sha: str | None = None,
    ) -> None:
        """Activa o crea la suscripción de un email para un repo."""
        email = _normalize_email(email)
        now = _now()

        with postgres_client.connect() as conn:
            conn.execute(
                """
                INSERT INTO email_preferences (
                    email, future_updates_enabled, created_at, updated_at, unsubscribed_at
                )
                VALUES (%s, TRUE, %s, %s, NULL)
                ON CONFLICT (email) DO UPDATE SET
                    future_updates_enabled = TRUE,
                    updated_at = EXCLUDED.updated_at,
                    unsubscribed_at = NULL
                """,
                (email, now, now),
            )

            conn.execute(
                """
                INSERT INTO repo_subscriptions (
                    repo_url, email, active, last_notified_git_sha, created_at, updated_at, unsubscribed_at
                )
                VALUES (%s, %s, TRUE, %s, %s, %s, NULL)
                ON CONFLICT (repo_url, email) DO UPDATE SET
                    active = TRUE,
                    updated_at = EXCLUDED.updated_at,
                    unsubscribed_at = NULL,
                    last_notified_git_sha = COALESCE(
                        EXCLUDED.last_notified_git_sha,
                        repo_subscriptions.last_notified_git_sha
                    )
                """,
                (repo_url, email, last_notified_git_sha, now, now),
            )

    def seed_repo_subscriptions(self, *, repo_url: str, git_sha: str) -> None:
        """
        Inicializa suscripciones nuevas con el SHA actual.

        Evita que quien acaba de suscribirse reciba un correo duplicado por el
        mismo análisis que ha solicitado manualmente.
        """
        with postgres_client.connect() as conn:
            conn.execute(
                """
                UPDATE repo_subscriptions
                SET last_notified_git_sha = %s, updated_at = %s
                WHERE repo_url = %s
                  AND active = TRUE
                  AND (last_notified_git_sha IS NULL OR last_notified_git_sha = '')
                """,
                (git_sha, _now(), repo_url),
            )

    def list_pending_repo_updates(self, *, repo_url: str, git_sha: str) -> list[dict]:
        """Devuelve suscripciones activas pendientes de aviso para un nuevo SHA."""
        with postgres_client.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.repo_url,
                    s.email,
                    s.last_notified_git_sha
                FROM repo_subscriptions s
                LEFT JOIN email_preferences p
                  ON p.email = s.email
                WHERE s.repo_url = %s
                  AND s.active = TRUE
                  AND COALESCE(p.future_updates_enabled, TRUE) = TRUE
                  AND s.last_notified_git_sha IS NOT NULL
                  AND s.last_notified_git_sha <> %s
                ORDER BY s.updated_at ASC
                """,
                (repo_url, git_sha),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_repo_notified(self, *, repo_url: str, email: str, git_sha: str) -> None:
        """Marca el último SHA notificado para una suscripción de repo."""
        with postgres_client.connect() as conn:
            conn.execute(
                """
                UPDATE repo_subscriptions
                SET last_notified_git_sha = %s, updated_at = %s
                WHERE repo_url = %s AND email = %s
                """,
                (git_sha, _now(), repo_url, _normalize_email(email)),
            )

    def unsubscribe_repo(self, *, repo_url: str, email: str) -> bool:
        """Desactiva la suscripción futura a un repo concreto."""
        now = _now()
        with postgres_client.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE repo_subscriptions
                SET active = FALSE, updated_at = %s, unsubscribed_at = %s
                WHERE repo_url = %s AND email = %s AND active = TRUE
                """,
                (now, now, repo_url, _normalize_email(email)),
            )
            return cursor.rowcount > 0

    def unsubscribe_global(self, *, email: str) -> bool:
        """Desactiva todos los avisos futuros para un email."""
        email = _normalize_email(email)
        now = _now()
        with postgres_client.connect() as conn:
            conn.execute(
                """
                INSERT INTO email_preferences (
                    email, future_updates_enabled, created_at, updated_at, unsubscribed_at
                )
                VALUES (%s, FALSE, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    future_updates_enabled = FALSE,
                    updated_at = EXCLUDED.updated_at,
                    unsubscribed_at = EXCLUDED.unsubscribed_at
                """,
                (email, now, now, now),
            )
        return True
