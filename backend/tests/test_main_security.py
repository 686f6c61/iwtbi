"""Regresiones de configuración de seguridad de la aplicación principal."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.main import app


def test_production_defaults_disable_interactive_api_docs():
    """La documentación pública debe requerir una activación explícita."""
    assert Settings.model_fields["api_docs_enabled"].default is False
    expected_openapi_url = "/openapi.json" if settings.api_docs_enabled else None
    assert app.openapi_url == expected_openapi_url


def test_main_app_sets_security_headers_and_rejects_untrusted_hosts():
    """Las respuestas de la app incluyen cabeceras y validan el host recibido."""
    with patch("app.main.ensure_schema"), TestClient(app) as client:
        response = client.get("/health")
        rejected = client.get("/health", headers={"host": "attacker.example"})

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert rejected.status_code == 400
