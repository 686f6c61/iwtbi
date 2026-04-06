"""
Repositorio de notificaciones por email asociadas a análisis en curso.

Cada registro conecta un job con un email de usuario que quiere ser
notificado cuando el análisis termine. Un mismo job puede tener varios
registros (múltiples usuarios pueden solicitar notificación del mismo análisis).

La tabla ``repo_notifications`` usa RLS con solo service_role para evitar
que los usuarios consulten o modifiquen suscripciones de otros.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import Client

from app.database.supabase_client import get_client

_logger = logging.getLogger(__name__)


class NotificationsRepo:
    """
    Repositorio de notificaciones pendientes de envío.

    Permite guardar el email de un usuario para un job en curso y
    recuperar todos los emails asociados a un job al completar.
    """

    def __init__(self, client: Client | None = None) -> None:
        self._client = client

    def _get_client(self) -> Client:
        """Devuelve el cliente, inicializándolo la primera vez que se necesita."""
        if self._client is None:
            self._client = get_client()
        return self._client

    def save(self, job_id: str, repo_url: str, email: str) -> dict | None:
        """
        Registra que un usuario quiere ser notificado cuando el job termine.

        Args:
            job_id: Identificador del job de análisis en curso.
            repo_url: URL del repositorio que se está analizando.
            email: Dirección de correo del usuario.

        Returns:
            Diccionario con la fila insertada, o None si la inserción falla.
        """
        try:
            result = (
                self._get_client().table("repo_notifications")
                .insert({
                    "job_id": job_id,
                    "repo_url": repo_url,
                    "email": email,
                })
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as exc:
            _logger.error(
                "Error al guardar notificación para job '%s', email '%s': %s",
                job_id,
                email,
                exc,
            )
            return None

    def find_by_job(self, job_id: str) -> list[dict]:
        """
        Devuelve todas las notificaciones pendientes para un job.

        Se usa al completar el análisis para hacer el fanout de emails.

        Args:
            job_id: Identificador del job completado.

        Returns:
            Lista de dicts con id, job_id, repo_url, email, sent_at, created_at.
            Lista vacía si no hay suscriptores o si Supabase falla.
        """
        try:
            result = (
                self._get_client().table("repo_notifications")
                .select("*")
                .eq("job_id", job_id)
                .is_("sent_at", "null")
                .execute()
            )
            return result.data or []
        except Exception as exc:
            _logger.error(
                "Error al buscar notificaciones para job '%s': %s",
                job_id,
                exc,
            )
            return []

    def mark_sent(self, notification_id: str) -> None:
        """
        Marca una notificación como enviada con la marca temporal actual.

        Args:
            notification_id: UUID de la fila en ``repo_notifications``.
        """
        try:
            (
                self._get_client().table("repo_notifications")
                .update({"sent_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", notification_id)
                .execute()
            )
        except Exception as exc:
            _logger.error(
                "Error al marcar notificación '%s' como enviada: %s",
                notification_id,
                exc,
            )
