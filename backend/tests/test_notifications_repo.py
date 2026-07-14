"""Tests del repositorio de notificaciones."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from app.database.notifications_repo import NotificationsRepo


def test_notifications_postgres_save(monkeypatch):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "job_id": "job-1",
        "email": "user@example.com",
    }

    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr("app.database.notifications_repo.postgres_client.connect", fake_connect)

    result = NotificationsRepo().save(
        job_id="job-1",
        repo_url="https://github.com/user/repo",
        email="user@example.com",
    )

    assert result["job_id"] == "job-1"
    assert "INSERT INTO repo_notifications" in connection.execute.call_args.args[0]


def test_notifications_postgres_find_pending_for_repo(monkeypatch):
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = [
        {"id": "n1", "email": "user@example.com"}
    ]

    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr("app.database.notifications_repo.postgres_client.connect", fake_connect)

    result = NotificationsRepo().find_pending_for_repo("https://github.com/user/repo")

    assert result == [{"id": "n1", "email": "user@example.com"}]
    assert "sent_at IS NULL" in connection.execute.call_args.args[0]
