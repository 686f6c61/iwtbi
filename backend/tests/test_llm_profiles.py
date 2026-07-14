"""Pruebas de los perfiles LLM privados configurados en el servidor."""

import pytest
from pydantic import SecretStr

from app.config import settings
from app.services.llm_profiles import get_llm_profile, get_llm_profiles


def test_profile_inherits_provider_credentials_without_exposing_them(monkeypatch):
    monkeypatch.setattr(settings, "nan_api_key", "configured-for-tests")
    monkeypatch.setattr(settings, "nan_base_url", "https://llm.example.test/v1")
    monkeypatch.setattr(
        settings,
        "llm_profiles_json",
        SecretStr(
            '[{"id":"revision","label":"Revisión profunda",'
            '"provider":"nan","model":"qwen-test"}]'
        ),
    )

    profile = get_llm_profile("revision")

    assert profile.api_key.get_secret_value() == "configured-for-tests"
    assert profile.base_url == "https://llm.example.test/v1"
    assert profile.available is True


def test_profile_can_be_keyless_for_a_private_compatible_endpoint(monkeypatch):
    monkeypatch.setattr(
        settings,
        "llm_profiles_json",
        SecretStr(
            '[{"id":"local","label":"Modelo local",'
            '"provider":"openai_compatible","model":"local-model",'
            '"base_url":"http://llm:11434/v1","api_key_required":false}]'
        ),
    )

    profile = get_llm_profile("local")

    assert profile.available is True
    assert profile.base_url == "http://llm:11434/v1"


@pytest.mark.parametrize(
    "payload, message",
    [
        ("{}", "debe ser una lista"),
        (
            '[{"id":"one","label":"Uno","provider":"nan","model":"m"},'
            '{"id":"one","label":"Dos","provider":"nan","model":"m"}]',
            "duplicado",
        ),
        (
            '[{"id":"unsafe","label":"Inseguro","provider":"nan",'
            '"model":"m","base_url":"file:///etc/passwd"}]',
            r"HTTP\(S\)",
        ),
    ],
)
def test_invalid_profile_configuration_is_rejected(monkeypatch, payload, message):
    monkeypatch.setattr(settings, "llm_profiles_json", SecretStr(payload))

    with pytest.raises(ValueError, match=message):
        get_llm_profiles()
