"""Health checks públicos e internos para operación."""

import secrets

from fastapi import APIRouter, HTTPException, Request, Response

from app.config import settings
from app.database.analyses_repo import AnalysesRepo

health_router = APIRouter()

_INTERNAL_TOKEN_HEADER = "x-internal-token"


def _has_real_secret(value: str) -> bool:
    """Distingue claves reales de placeholders de documentación/local."""
    stripped = value.strip()
    return bool(stripped and stripped != "placeholder" and not stripped.startswith("your_"))


def _require_internal_token(request: Request) -> None:
    expected_token = settings.internal_analyze_token.strip()
    provided_token = request.headers.get(_INTERNAL_TOKEN_HEADER, "").strip()
    if (
        not expected_token
        or not provided_token
        or not secrets.compare_digest(provided_token, expected_token)
    ):
        raise HTTPException(status_code=403, detail="Token interno inválido o no configurado.")


@health_router.get("/health")
async def health() -> dict[str, bool | str]:
    """Endpoint ligero para Docker healthcheck y proxy inverso."""
    return {
        "status": "ok",
        "email_notifications_enabled": bool(settings.resend_api_key.strip()),
    }


@health_router.get("/health/dependencies")
async def dependency_health(request: Request, response: Response) -> dict:
    """
    Healthcheck interno con dependencias críticas, sin exponer secretos.

    Devuelve 503 cuando una dependencia necesaria para biblioteca/cache no está
    disponible, pero mantiene `/health` simple para comprobar solo el proceso.
    """
    _require_internal_token(request)

    analyses_repo = AnalysesRepo()
    analyses_repo.list_page(page=1, page_size=1, sort="updated_desc")
    storage_ok = analyses_repo.last_error is None

    provider_credentials = {
        "openai_compatible": _has_real_secret(settings.openai_compatible_api_key)
        and bool(settings.openai_compatible_model.strip()),
        "nan": _has_real_secret(settings.nan_api_key),
        "zai": _has_real_secret(settings.zai_api_key),
        "ollama_cloud": _has_real_secret(settings.ollama_cloud_api_key),
    }
    active_provider_configured = provider_credentials.get(settings.provider, False)

    status = "ok" if storage_ok and active_provider_configured else "degraded"
    if status != "ok":
        response.status_code = 503

    return {
        "status": status,
        "storage": {
            "backend": settings.database_backend,
            "configured": bool(settings.database_url),
            "ok": storage_ok,
            "error": type(analyses_repo.last_error).__name__ if analyses_repo.last_error else None,
        },
        "llm": {
            "provider": settings.provider,
            "active_provider_configured": active_provider_configured,
            "providers_configured": provider_credentials,
            "models": {
                "openai_compatible": settings.openai_compatible_model,
                "nan": settings.nan_model,
                "zai": settings.zai_model,
                "ollama_cloud": settings.ollama_cloud_model,
                "ollama_cloud_fallbacks": [
                    model.strip()
                    for model in settings.ollama_cloud_fallback_models.split(",")
                    if model.strip()
                ],
            },
        },
        "jobs": {"backend": settings.job_store_backend},
    }
