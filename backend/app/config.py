"""
Configuración centralizada de la aplicación vía variables de entorno.

Usa pydantic-settings para validar y tipar la configuración en tiempo
de arranque. Los valores por defecto permiten ejecutar sin .env en local.

Proveedores de LLM disponibles:
- ``openai_compatible``: cualquier API compatible con OpenAI
- ``nan``: API de NaN builders (OpenAI-compatible, Qwen por defecto)
- ``zai``: API de z.ai (OpenAI-compatible, GLM por defecto)
- ``ollama_cloud``: Ollama Cloud (API nativa Ollama, base_url sin ``/api``)
"""

from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_MAX_FILES = 2500


class Settings(BaseSettings):
    """
    Configuración global cargada desde variables de entorno o archivo .env.

    Los valores se validan al arrancar la aplicación; un fallo de validación
    detiene el proceso con un mensaje claro antes de procesar cualquier request.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Selección de proveedor ───────────────────────────────────────────────
    # Elige qué LLM usa el pipeline. Cambia solo esta variable en .env para
    # alternar entre una API OpenAI-compatible, NaN, z.ai y Ollama Cloud.
    provider: Literal["openai_compatible", "nan", "zai", "ollama_cloud"] = "nan"
    job_store_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_storage_uri: str = "memory://"
    api_docs_enabled: bool = False
    allowed_hosts: str = "localhost,127.0.0.1,testserver"

    # ── Proveedor OpenAI-compatible genérico ────────────────────────────────
    # Permite usar OpenAI, OpenRouter, Groq, LocalAI, vLLM u otro endpoint que
    # implemente la API de chat compatible con OpenAI.
    openai_compatible_api_key: str = ""
    openai_compatible_base_url: str = "https://api.openai.com/v1"
    openai_compatible_model: str = ""
    # Perfiles privados para análisis internos. Puede contener credenciales y
    # por eso se mantiene como SecretStr y nunca se devuelve al cliente.
    llm_profiles_json: SecretStr = SecretStr("[]")

    # ── Proveedor NaN builders (OpenAI-compatible / principal) ───────────────
    nan_api_key: str = "placeholder"
    nan_base_url: str = "https://api.nan.builders/v1"
    nan_model: str = "qwen3.6"

    # ── Proveedor z.ai (API de coding / fallback) ────────────────────────────
    zai_api_key: str = "placeholder"
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    zai_model: str = "glm-5.2"

    # ── Proveedor Ollama Cloud ────────────────────────────────────────────────
    # IMPORTANTE: la base_url NO debe terminar en /api.
    # ChatOllama construye la ruta como {base_url}/api/chat; si se añade /api
    # el resultado sería /api/api/chat → 404.
    ollama_cloud_api_key: str = "placeholder"
    ollama_cloud_base_url: str = "https://ollama.com"
    ollama_cloud_model: str = "deepseek-v4-pro:cloud"
    # Modelos Ollama Cloud adicionales, separados por coma, probados en orden.
    ollama_cloud_fallback_models: str = "kimi-k2.7-code:cloud"

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Lista de orígenes permitidos separados por coma.
    # En producción, restringir al dominio del frontend (p. ej. http://localhost:3410).
    # El valor por defecto solo permite el entorno de desarrollo local.
    cors_origins: str = "http://localhost:3410,http://localhost:4321"  # NOSONAR — URLs de desarrollo local; http es correcto en entorno local
    # Solo se aceptan cabeceras de proxy cuando el peer inmediato pertenece a
    # estas redes. Evita que clientes directos falseen IPs para rate limits o
    # rutas internas.
    trusted_proxy_cidrs: str = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    # Activar solo si el dominio pasa realmente por Cloudflare o si el proxy
    # frontal limpia esas cabeceras antes de reenviar al backend.
    trust_cloudflare_client_headers: bool = False
    analyze_rate_limit: str = "10/hour"
    ticket_rate_limit: str = "60/minute"
    preflight_rate_limit: str = "20/minute"
    biblioteca_rate_limit: str = "60/minute"
    # Los agentes se despachan por tandas para evitar que todos los wall-timeouts
    # empiecen a contar a la vez mientras esperan cola en el proveedor.
    # Con 7 agentes y tandas de 3, el pipeline progresa 3 -> 3 -> 1.
    # Ambos límites tienen un techo de 3 para proteger NaN y Ollama incluso
    # si una variable de entorno se configura por error con un valor mayor.
    llm_agent_batch_size: int = Field(default=3, ge=1, le=3)
    llm_max_concurrency: int = Field(default=3, ge=1, le=3)
    llm_retry_attempts: int = 3
    llm_retry_base_delay_seconds: float = 1.5
    llm_request_timeout_seconds: float = 60.0
    # En producción no queremos agotar varios minutos en el mismo modelo:
    # una llamada lenta o un 503 debe pasar rápido al siguiente proveedor.
    llm_agent_request_timeout_seconds: float = 60.0
    llm_agent_retry_attempts: int = 0
    llm_agent_max_tokens: int = 8000
    # Este límite cubre el tiempo total del agente, incluida la espera
    # en la cola del semáforo global de concurrencia. Con tandas de 3 agentes,
    # los últimos arrancan más tarde sin que el proveedor esté realmente caído.
    llm_agent_wall_timeout_seconds: float = 180.0
    llm_synth_request_timeout_seconds: float = 60.0
    llm_synth_retry_attempts: int = 0
    llm_synth_retry_base_delay_seconds: float = 4.0

    # ── Límites para repos grandes ────────────────────────────────────────────
    # Evitan colapsar el contexto del LLM con repos muy voluminosos.
    repo_size_limit_mb: int = 100
    file_size_limit_kb: int = 500
    max_files: int = _DEFAULT_MAX_FILES
    preflight_max_candidate_files: int = _DEFAULT_MAX_FILES
    # Techo de caracteres del contexto total enviado a cada agente.
    # 90 000 chars ≈ 22 500 tokens: suficiente para repos medianos y más seguro
    # cuando varios agentes analizan el mismo repo en tandas controladas.
    # Los archivos se incluyen en orden de prioridad (README, configs, código)
    # hasta agotar el presupuesto.
    max_context_chars: int = 90_000

    # ── Persistencia ─────────────────────────────────────────────────────────
    # La aplicación usa PostgreSQL como almacén canónico.
    database_backend: Literal["postgres"] = "postgres"
    database_url: str = ""

    # ── Resend (notificaciones por email) ────────────────────────────────────
    # La clave es obligatoria solo si se usa el servicio de email.
    # Si está vacía, el envío de email se omite silenciosamente.
    resend_api_key: str = ""
    resend_from: str = ""
    public_app_url: str = "http://localhost:3410"
    email_unsubscribe_secret: str = ""
    email_unsubscribe_token_ttl_days: int = 180
    internal_analyze_token: str = ""

    @field_validator("preflight_max_candidate_files", mode="before")
    @classmethod
    def _coerce_blank_preflight_limit(cls, value: Any) -> Any:
        """
        Algunos sistemas de despliegue dejan variables opcionales vacías.

        Si ``PREFLIGHT_MAX_CANDIDATE_FILES`` llega vacío, reutilizamos el
        límite por defecto en lugar de abortar el arranque del backend.
        """
        if value in (None, ""):
            return _DEFAULT_MAX_FILES
        return value

    @model_validator(mode="after")
    def _align_preflight_limit_with_ingest_cap(self) -> "Settings":
        """
        El límite visible no debe prometer más archivos de los que medimos.

        ``max_files`` protege el coste del lector y el tiempo de preflight.
        Si ``preflight_max_candidate_files`` fuese mayor, la UI podría decir
        "aceptamos hasta 2500" aunque el backend deje de medir en 2000.
        """
        if self.preflight_max_candidate_files > self.max_files:
            self.preflight_max_candidate_files = self.max_files
        return self


# Instancia singleton: se importa desde cualquier módulo como `from app.config import settings`
settings = Settings()
