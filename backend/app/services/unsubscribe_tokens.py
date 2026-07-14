"""Generación y validación de tokens firmados para baja de avisos futuros."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Literal

from app.config import settings

UnsubscribeScope = Literal["repo", "global"]


def _get_secret() -> bytes:
    secret = settings.email_unsubscribe_secret.strip()
    if not secret or secret in {"placeholder-unsubscribe-secret", "change-me"}:
        raise RuntimeError("EMAIL_UNSUBSCRIBE_SECRET no está configurado")
    return secret.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def build_unsubscribe_token(
    *,
    scope: UnsubscribeScope,
    email: str,
    repo_url: str | None = None,
) -> str:
    """Crea un token firmado con HMAC para una baja de avisos."""
    issued_at = int(time.time())
    payload = {
        "scope": scope,
        "email": email.strip().lower(),
        "iat": issued_at,
        "exp": issued_at + settings.email_unsubscribe_token_ttl_days * 24 * 60 * 60,
    }
    if scope == "repo":
        payload["repo_url"] = (repo_url or "").rstrip("/")

    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_get_secret(), payload_bytes, hashlib.sha256).digest()
    return f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def parse_unsubscribe_token(token: str) -> dict[str, str] | None:
    """Valida el token y devuelve su payload si la firma es correcta."""
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(signature_b64)
    except Exception:
        return None

    expected_signature = hmac.new(_get_secret(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    scope = payload.get("scope")
    email = str(payload.get("email") or "").strip().lower()
    repo_url = str(payload.get("repo_url") or "").strip()
    try:
        expires_at = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return None

    if scope not in {"repo", "global"} or not email:
        return None
    if scope == "repo" and not repo_url:
        return None
    if expires_at <= int(time.time()):
        return None

    result = {"scope": scope, "email": email}
    if repo_url:
        result["repo_url"] = repo_url
    return result
