"""Tests del almacén PostgreSQL de suscripciones a avisos futuros."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from app.database.subscriptions_store import SubscriptionsStore


def _patch_connect(monkeypatch, connection):
    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr("app.database.subscriptions_store.postgres_client.connect", fake_connect)


def test_upsert_repo_subscription_normalizes_email_and_writes_preferences(monkeypatch):
    connection = MagicMock()
    _patch_connect(monkeypatch, connection)

    SubscriptionsStore().upsert_repo_subscription(
        repo_url="https://github.com/ianmove/lowpoly64",
        email="Pruebas@00b.tech",
    )

    assert connection.execute.call_count == 2
    preference_params = connection.execute.call_args_list[0].args[1]
    subscription_params = connection.execute.call_args_list[1].args[1]
    assert preference_params[0] == "pruebas@00b.tech"
    assert subscription_params[1] == "pruebas@00b.tech"
    assert "ON CONFLICT (repo_url, email)" in connection.execute.call_args_list[1].args[0]


def test_list_pending_repo_updates_filters_by_repo_and_sha(monkeypatch):
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = [{
        "repo_url": "https://github.com/ianmove/lowpoly64",
        "email": "pruebas@00b.tech",
        "last_notified_git_sha": "sha-old",
    }]
    _patch_connect(monkeypatch, connection)

    pending = SubscriptionsStore().list_pending_repo_updates(
        repo_url="https://github.com/ianmove/lowpoly64",
        git_sha="sha-new",
    )

    assert pending == [{
        "repo_url": "https://github.com/ianmove/lowpoly64",
        "email": "pruebas@00b.tech",
        "last_notified_git_sha": "sha-old",
    }]
    query, params = connection.execute.call_args.args
    assert "COALESCE(p.future_updates_enabled, TRUE) = TRUE" in query
    assert params == ("https://github.com/ianmove/lowpoly64", "sha-new")


def test_mark_repo_notified_updates_normalized_email(monkeypatch):
    connection = MagicMock()
    _patch_connect(monkeypatch, connection)

    SubscriptionsStore().mark_repo_notified(
        repo_url="https://github.com/ianmove/lowpoly64",
        email="Pruebas@00b.tech",
        git_sha="sha-new",
    )

    params = connection.execute.call_args.args[1]
    assert params[2:] == ("https://github.com/ianmove/lowpoly64", "pruebas@00b.tech")


def test_unsubscribe_repo_reports_if_active_row_changed(monkeypatch):
    cursor = MagicMock(rowcount=1)
    connection = MagicMock()
    connection.execute.return_value = cursor
    _patch_connect(monkeypatch, connection)

    changed = SubscriptionsStore().unsubscribe_repo(
        repo_url="https://github.com/ianmove/lowpoly64",
        email="Pruebas@00b.tech",
    )

    assert changed is True
    params = connection.execute.call_args.args[1]
    assert params[2:] == ("https://github.com/ianmove/lowpoly64", "pruebas@00b.tech")


def test_global_unsubscribe_disables_future_updates(monkeypatch):
    connection = MagicMock()
    _patch_connect(monkeypatch, connection)

    assert SubscriptionsStore().unsubscribe_global(email="User@Example.com") is True

    query, params = connection.execute.call_args.args
    assert "future_updates_enabled = FALSE" in query
    assert params[0] == "user@example.com"
