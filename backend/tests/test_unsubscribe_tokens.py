"""Tests de tokens firmados para baja de avisos futuros."""

import pytest

from app.services.unsubscribe_tokens import (
    build_unsubscribe_token,
    parse_unsubscribe_token,
)


@pytest.fixture(autouse=True)
def unsubscribe_secret(monkeypatch):
    monkeypatch.setattr(
        "app.services.unsubscribe_tokens.settings.email_unsubscribe_secret",
        "test-unsubscribe-secret-with-enough-entropy",
    )


def test_repo_unsubscribe_token_roundtrip():
    token = build_unsubscribe_token(
        scope="repo",
        email="USER@example.com",
        repo_url="https://github.com/ianmove/lowpoly64",
    )

    payload = parse_unsubscribe_token(token)

    assert payload == {
        "scope": "repo",
        "email": "user@example.com",
        "repo_url": "https://github.com/ianmove/lowpoly64",
    }


def test_invalid_unsubscribe_token_returns_none():
    assert parse_unsubscribe_token("bad.token") is None


def test_build_token_requires_dedicated_secret(monkeypatch):
    monkeypatch.setattr(
        "app.services.unsubscribe_tokens.settings.email_unsubscribe_secret",
        "",
    )
    with pytest.raises(RuntimeError, match="EMAIL_UNSUBSCRIBE_SECRET"):
        build_unsubscribe_token(scope="global", email="user@example.com")


def test_expired_unsubscribe_token_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.services.unsubscribe_tokens.settings.email_unsubscribe_token_ttl_days",
        -1,
    )
    token = build_unsubscribe_token(
        scope="global",
        email="user@example.com",
    )

    assert parse_unsubscribe_token(token) is None
