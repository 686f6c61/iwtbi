"""Tests del bootstrap idempotente del esquema PostgreSQL."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from app.config import settings
from app.database.schema import ensure_schema


def test_ensure_schema_skips_without_database_url(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    assert ensure_schema() is False


def test_ensure_schema_executes_schema(monkeypatch):
    connection = MagicMock()

    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr(settings, "database_url", "postgresql://example")
    monkeypatch.setattr("app.database.schema.postgres_client.connect", fake_connect)

    assert ensure_schema() is True
    query = connection.execute.call_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS analyses" in query
    assert "CREATE TABLE IF NOT EXISTS repo_subscriptions" in query


def test_ensure_schema_accepts_existing_tables_when_reapply_fails(monkeypatch):
    first_connection = MagicMock()
    first_connection.execute.side_effect = RuntimeError("must be owner of function")
    second_connection = MagicMock()
    second_connection.execute.return_value.fetchall.return_value = [
        {"table_name": "analyses"},
        {"table_name": "repo_notifications"},
        {"table_name": "repo_subscriptions"},
        {"table_name": "email_preferences"},
    ]

    connections = iter([first_connection, second_connection])

    @contextmanager
    def fake_connect():
        yield next(connections)

    monkeypatch.setattr(settings, "database_url", "postgresql://example")
    monkeypatch.setattr("app.database.schema.postgres_client.connect", fake_connect)

    assert ensure_schema() is True
