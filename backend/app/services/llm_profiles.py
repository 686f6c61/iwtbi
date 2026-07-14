"""Perfiles LLM server-side seleccionables sin exponer credenciales al cliente."""

import json
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from app.config import settings

LlmProvider = Literal["openai_compatible", "nan", "zai", "ollama_cloud"]
_PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class LlmProfileDefinition(BaseModel):
    """Perfil privado cargado desde la configuración del servidor."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=80)
    provider: LlmProvider
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(default="", max_length=2048)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    api_key_required: bool = True

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _PROFILE_ID_PATTERN.fullmatch(value):
            raise ValueError("usa solo minúsculas, números, guiones y guiones bajos")
        if value == "default":
            raise ValueError("'default' está reservado")
        return value

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("debe ser una URL HTTP(S) absoluta")
        if parsed.username or parsed.password:
            raise ValueError("no puede contener credenciales")
        return value.rstrip("/")


class LlmRuntimeProfile(BaseModel):
    """Perfil resuelto que solo consume el backend o el worker."""

    id: str
    label: str
    provider: LlmProvider
    model: str
    base_url: str
    api_key: SecretStr
    api_key_required: bool

    @property
    def available(self) -> bool:
        if not self.model.strip() or not self.base_url.strip():
            return False
        if not self.api_key_required:
            return True
        key = self.api_key.get_secret_value().strip()
        return bool(key and key != "placeholder" and not key.startswith("your_"))

def _provider_settings(provider: LlmProvider) -> tuple[str, str, str]:
    if provider == "openai_compatible":
        return (
            settings.openai_compatible_model,
            settings.openai_compatible_base_url,
            settings.openai_compatible_api_key,
        )
    if provider == "nan":
        return settings.nan_model, settings.nan_base_url, settings.nan_api_key
    if provider == "zai":
        return settings.zai_model, settings.zai_base_url, settings.zai_api_key
    return (
        settings.ollama_cloud_model,
        settings.ollama_cloud_base_url,
        settings.ollama_cloud_api_key,
    )


def _default_profile() -> LlmRuntimeProfile:
    provider: LlmProvider = settings.provider
    model, base_url, api_key = _provider_settings(provider)
    return LlmRuntimeProfile(
        id="default",
        label="Predeterminado",
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=SecretStr(api_key),
        api_key_required=True,
    )


def get_llm_profiles() -> list[LlmRuntimeProfile]:
    """Carga y valida perfiles sin almacenar el JSON privado fuera del proceso."""
    raw = settings.llm_profiles_json.get_secret_value().strip() or "[]"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM_PROFILES_JSON no contiene JSON válido") from exc
    if not isinstance(payload, list):
        raise ValueError("LLM_PROFILES_JSON debe ser una lista JSON")

    profiles = [_default_profile()]
    seen = {"default"}
    for index, item in enumerate(payload):
        try:
            definition = LlmProfileDefinition.model_validate(item)
        except ValidationError as exc:
            raise ValueError(f"Perfil LLM #{index + 1} inválido: {exc}") from exc
        if definition.id in seen:
            raise ValueError(f"Perfil LLM duplicado: {definition.id}")
        seen.add(definition.id)

        default_model, default_base_url, default_api_key = _provider_settings(
            definition.provider
        )
        api_key = definition.api_key.get_secret_value() or default_api_key
        profiles.append(
            LlmRuntimeProfile(
                id=definition.id,
                label=definition.label,
                provider=definition.provider,
                model=definition.model or default_model,
                base_url=(definition.base_url or default_base_url).rstrip("/"),
                api_key=SecretStr(api_key or "not-required"),
                api_key_required=definition.api_key_required,
            )
        )
    return profiles


def get_llm_profile(profile_id: str) -> LlmRuntimeProfile:
    """Resuelve un perfil por ID y evita usar perfiles incompletos."""
    profile = next((item for item in get_llm_profiles() if item.id == profile_id), None)
    if profile is None:
        raise ValueError("El perfil de IA seleccionado no existe.")
    if not profile.available:
        raise ValueError("El perfil de IA seleccionado no está configurado.")
    return profile
