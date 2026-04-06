"""
Configuración centralizada de la aplicación vía variables de entorno.

Usa pydantic-settings para validar y tipar la configuración en tiempo
de arranque. Los valores por defecto permiten ejecutar sin .env en local.

Proveedores de LLM disponibles:
- ``zai``: API de z.ai (OpenAI-compatible, GLM por defecto)
- ``ollama_cloud``: Ollama Cloud (API nativa Ollama, base_url sin ``/api``)
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # alternar entre z.ai y Ollama Cloud sin tocar código.
    provider: Literal["zai", "ollama_cloud"] = "zai"

    # ── Proveedor z.ai (API OpenAI-compatible) ───────────────────────────────
    zai_api_key: str = "placeholder"
    zai_base_url: str = "https://api.z.ai/v1"
    zai_model: str = "glm-z1-flash"

    # ── Proveedor Ollama Cloud ────────────────────────────────────────────────
    # IMPORTANTE: la base_url NO debe terminar en /api.
    # ChatOllama construye la ruta como {base_url}/api/chat; si se añade /api
    # el resultado sería /api/api/chat → 404.
    ollama_cloud_api_key: str = "placeholder"
    ollama_cloud_base_url: str = "https://ollama.com"
    ollama_cloud_model: str = "qwen3.5"

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Lista de orígenes permitidos separados por coma.
    # En producción, restringir al dominio del frontend (p. ej. https://app.example.com).
    # El valor por defecto solo permite el entorno de desarrollo local.
    cors_origins: str = "http://localhost:3410,http://localhost:4321"  # NOSONAR — URLs de desarrollo local; http es correcto en entorno local
    analyze_rate_limit: str = "5/hour"
    ticket_rate_limit: str = "30/minute"
    preflight_rate_limit: str = "12/minute"
    llm_max_concurrency: int = 4
    llm_retry_attempts: int = 3
    llm_retry_base_delay_seconds: float = 1.5
    llm_request_timeout_seconds: float = 60.0
    llm_synth_request_timeout_seconds: float = 120.0
    llm_synth_retry_attempts: int = 2
    llm_synth_retry_base_delay_seconds: float = 4.0

    # ── Límites para repos grandes ────────────────────────────────────────────
    # Evitan colapsar el contexto del LLM con repos muy voluminosos.
    repo_size_limit_mb: int = 100
    file_size_limit_kb: int = 500
    max_files: int = 2000
    preflight_max_candidate_files: int = 750
    # Techo de caracteres del contexto total enviado a cada agente.
    # 80 000 chars ≈ 20 000 tokens: suficiente para repos medianos y seguro para
    # modelos con ventana de 32K tokens (deja margen para system prompt y output).
    # Los archivos se incluyen en orden de prioridad (README, configs, código)
    # hasta agotar el presupuesto.
    max_context_chars: int = 80_000

    # ── Supabase ──────────────────────────────────────────────────────────────
    # Solo el backend accede a Supabase con la clave service_role.
    # El frontend NO accede directamente a Supabase.
    supabase_url: str = ""
    supabase_service_key: str = ""

    # ── Resend (notificaciones por email) ────────────────────────────────────
    # La clave es obligatoria solo si se usa el servicio de email.
    # Si está vacía, el envío de email se omite silenciosamente.
    resend_api_key: str = ""
    resend_from: str = "hola@app.example.com"


# Instancia singleton: se importa desde cualquier módulo como `from app.config import settings`
settings = Settings()
