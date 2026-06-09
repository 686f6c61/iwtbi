"""
Agente base para todos los agentes especializados de IWTBI.

Cada agente hereda de BaseAgent y solo necesita definir su prompt de
sistema, su nombre identificador y, opcionalmente, su temperatura.
La conexión al LLM y la invocación están centralizadas aquí para
evitar duplicación de lógica.

Proveedores soportados (controlados por ``settings.provider``):

- ``zai``: usa ChatOpenAI apuntando a la API de z.ai (OpenAI-compatible).
- ``ollama_cloud``: usa ChatOllama con un AsyncClient autenticado contra
  Ollama Cloud (``https://ollama.com``). La base_url NO debe incluir
  el sufijo ``/api``; ChatOllama lo añade internamente.

Constante compartida:

- ``ANTI_HALLUCINATION_RULE``: bloque de instrucciones que se añade al final
  del system_prompt de cada agente para forzar extracción estricta desde
  el código fuente, sin inferencias ni completaciones inventadas.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Union

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import settings
from app.models.job import LlmConfig, LlmProvider
from app.models.repo_context import RepoContext


# ---------------------------------------------------------------------------
# Regla anti-alucinación compartida por todos los agentes.
#
# Se importa en cada agente y se concatena al system_prompt para garantizar
# que el modelo trabaje exclusivamente con lo que está en el código analizado.
# Centralizar la regla aquí evita divergencias entre agentes y facilita
# futuras actualizaciones.
# ---------------------------------------------------------------------------
ANTI_HALLUCINATION_RULE = """

REGLA ABSOLUTA — SOLO LO QUE ESTÁ EN EL CÓDIGO:
No inventes, no infieras, no completes con conocimiento general del lenguaje o framework.

- Versiones: extrae solo las que aparecen literalmente en los archivos de dependencias \
(package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml u equivalentes). \
Si no están presentes en ningún archivo, escribe "no especificada".
- Endpoints, funciones, campos: si no aparecen en el código analizado, no los incluyas.
- Componentes ausentes: si el proyecto no tiene base de datos, frontend, API o CI/CD, \
escribe "No detectado en el código analizado" — no inventes alternativas ni valores típicos.
- Incertidumbre: cuando la información no esté en el código, escribe exactamente \
"No detectado en el código analizado".
- Prohibido usar: "probablemente", "típicamente", "suele ser", "se asume que", \
"es probable que", "parece ser", "generalmente" o cualquier frase que no afirme \
un hecho observado directamente en el código fuente."""

_llm_semaphore: asyncio.Semaphore | None = None
_ZAI_OFFICIAL_BASE_URL = "https://api.z.ai/api/paas/v4/"
_LEGACY_ZAI_BASE_URLS = {"https://api.z.ai/v1", "https://api.z.ai/v1/"}
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OLLAMA_CLOUD_BASE_URL = "https://ollama.com"
_OLLAMA_LOCAL_BASE_URL = "http://host.docker.internal:11434"


def _get_llm_semaphore() -> asyncio.Semaphore:
    """Devuelve el semáforo global que limita la concurrencia LLM del proceso."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    return _llm_semaphore


def _has_real_secret(value: str) -> bool:
    """Detecta placeholders habituales para evitar llamadas LLM inútiles."""
    stripped = value.strip()
    return bool(stripped) and stripped != "placeholder" and not stripped.startswith("your_")


def _setting_provider() -> LlmProvider:
    return settings.provider


def _effective_provider(llm_config: LlmConfig | None) -> LlmProvider:
    return llm_config.provider if llm_config else _setting_provider()


def _effective_model(llm_config: LlmConfig | None) -> str:
    if llm_config:
        return llm_config.model.strip()
    if settings.provider == "zai":
        return settings.zai_model
    return settings.ollama_cloud_model


def _effective_api_key(llm_config: LlmConfig | None, provider: LlmProvider) -> str:
    if llm_config:
        return (llm_config.api_key or "").strip()
    if provider == "zai":
        return settings.zai_api_key
    if provider == "ollama_cloud":
        return settings.ollama_cloud_api_key
    return ""


def _effective_base_url(llm_config: LlmConfig | None, provider: LlmProvider) -> str | None:
    configured = (llm_config.base_url or "").strip() if llm_config else ""
    if configured:
        return configured
    if not llm_config and provider == "zai":
        return settings.zai_base_url
    if not llm_config and provider == "ollama_cloud":
        return settings.ollama_cloud_base_url
    if provider == "openrouter":
        return _OPENROUTER_BASE_URL
    if provider == "zai":
        return _ZAI_OFFICIAL_BASE_URL
    if provider == "ollama_cloud":
        return _OLLAMA_CLOUD_BASE_URL
    if provider == "ollama_local":
        return _OLLAMA_LOCAL_BASE_URL
    return None


def validate_llm_settings(llm_config: LlmConfig | None = None) -> None:
    """
    Valida la configuración LLM antes de arrancar un análisis costoso.

    Raises:
        ValueError: Si falta la credencial del proveedor activo o si Z.AI
                    apunta al endpoint OpenAI-compatible antiguo.
    """
    provider = _effective_provider(llm_config)
    model = _effective_model(llm_config)
    api_key = _effective_api_key(llm_config, provider)
    base_url = _effective_base_url(llm_config, provider)

    if not model:
        raise ValueError("Falta configurar el modelo LLM para el análisis.")

    if provider in {"zai", "openai", "openrouter", "anthropic", "ollama_cloud"}:
        if not _has_real_secret(api_key):
            raise ValueError(
                f"Falta configurar una API key real para el proveedor {provider}."
            )

    if provider == "zai":
        if (base_url or "").strip().rstrip("/") in {
            url.rstrip("/") for url in _LEGACY_ZAI_BASE_URLS
        }:
            raise ValueError(
                "ZAI_BASE_URL apunta al endpoint antiguo. Usa "
                f"{_ZAI_OFFICIAL_BASE_URL}"
            )

    if provider in {"zai", "openrouter", "ollama_cloud", "ollama_local"}:
        if not base_url:
            raise ValueError(f"Falta configurar la URL base para el proveedor {provider}.")
        return


def _is_retryable_llm_error(exc: Exception) -> bool:
    """
    Detecta errores transitorios del proveedor que merecen reintento.

    En Ollama Cloud el caso crítico observado en producción es el 429 por
    exceso de concurrencia ("too many concurrent requests").
    """
    message = str(exc).lower()
    return (
        "too many concurrent requests" in message
        or "status code: 429" in message
        or "rate limit" in message
        or "empty llm response" in message
    )


def _response_has_content(response) -> bool:
    """
    Determina si la respuesta del proveedor contiene contenido utilizable.

    Algunos proveedores devuelven respuestas 200 con content vacío bajo carga
    o filtros internos. En esos casos merece la pena reintentar igual que en
    un 429, porque suele ser un fallo transitorio del proveedor.
    """
    content = getattr(response, "content", None)
    if content is None:
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return len(content) > 0
    return True


async def invoke_llm(llm, messages):
    """
    Ejecuta una llamada LLM bajo límite global de concurrencia y con retry.

    El objetivo es evitar que múltiples análisis en paralelo saturen el
    proveedor y devuelvan 429 antes de que el sistema pueda encolar trabajo.
    """
    attempts = max(settings.llm_retry_attempts, 0)
    for attempt in range(attempts + 1):
        try:
            async with _get_llm_semaphore():
                response = await asyncio.wait_for(
                    llm.ainvoke(messages),
                    timeout=settings.llm_request_timeout_seconds,
                )
            if not _response_has_content(response):
                raise RuntimeError("empty llm response")
            return response
        except asyncio.TimeoutError as exc:
            raise RuntimeError("llm request timed out") from exc
        except Exception as exc:
            if attempt >= attempts or not _is_retryable_llm_error(exc):
                raise
            delay = settings.llm_retry_base_delay_seconds * (2**attempt)
            await asyncio.sleep(delay)


def build_llm(
    temperature: float = 0.0,
    max_tokens: int = 32768,
    request_timeout_seconds: float | None = None,
    llm_config: LlmConfig | None = None,
) -> Union[ChatOpenAI, ChatOllama, ChatAnthropic]:
    """
    Construye el cliente LLM según el proveedor configurado en settings.

    La temperatura y el límite de tokens se configuran por agente para
    ajustar el balance entre exactitud factual (temperature=0.0) y
    fluidez narrativa (temperature=0.05–0.1).

    Args:
        temperature: Temperatura de sampling. 0.0 para extracción factual
                     estricta (sin variabilidad); hasta 0.1 para secciones
                     más narrativas o interpretativas.
        max_tokens:  Número máximo de tokens en la respuesta. 32 768 por
                     defecto para garantizar secciones completas sin truncar.

    Returns:
        ``ChatOpenAI`` si ``provider == "zai"``, o
        ``ChatOllama`` con autenticación Bearer si ``provider == "ollama_cloud"``.

    Raises:
        ValueError: Si el proveedor configurado no es reconocido.
    """
    provider = _effective_provider(llm_config)
    model = _effective_model(llm_config)
    api_key = _effective_api_key(llm_config, provider)
    base_url = _effective_base_url(llm_config, provider)
    timeout_seconds = (
        request_timeout_seconds
        if request_timeout_seconds is not None
        else settings.llm_request_timeout_seconds
    )

    if provider in {"zai", "openai", "openrouter"}:
        kwargs = {
            "api_key": api_key,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout_seconds,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        return ChatAnthropic(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
        )

    if provider in {"ollama_cloud", "ollama_local"}:
        # ChatOllama 1.x pasa kwargs al SDK ollama subyacente mediante
        # async_client_kwargs y sync_client_kwargs. La autenticación de
        # Ollama Cloud se inyecta como cabecera Bearer en ambos clientes.
        # base_url = https://ollama.com (sin /api); el SDK añade /api/chat.
        # Ollama usa num_predict en lugar de max_tokens.
        auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return ChatOllama(
            model=model,
            base_url=base_url,
            async_client_kwargs={
                "headers": auth_headers,
                "timeout": timeout_seconds,
            },
            sync_client_kwargs={
                "headers": auth_headers,
                "timeout": timeout_seconds,
            },
            temperature=temperature,
            num_predict=max_tokens,
        )

    raise ValueError(
        f"Proveedor de LLM no reconocido: '{provider}'."
    )


class BaseAgent(ABC):
    """
    Contrato base para los agentes especializados de IWTBI.

    Cada agente recibe el RepoContext completo y devuelve una sección
    Markdown con la información de su dominio específico.

    Para implementar un agente nuevo, basta con heredar de esta clase
    y definir ``system_prompt``, ``agent_name`` y, opcionalmente,
    sobreescribir ``temperature``.

    Atributos de clase:
        temperature: Temperatura de sampling. Las subclases la sobreescriben
                     según el tipo de análisis:
                     - 0.0 para extracción factual (stack, BD, API, DevOps).
                     - 0.05 para secciones más narrativas (arquitectura, frontend).
                     - 0.1 para análisis interpretativos (lógica de negocio).
        max_tokens:  Límite de tokens de salida. 32 768 por defecto para
                     garantizar secciones completas sin truncar.
    """

    temperature: float = 0.0
    max_tokens: int = 32768

    def __init__(self, llm_config: LlmConfig | None = None) -> None:
        self._llm = build_llm(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            llm_config=llm_config,
        )

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Prompt de sistema que define la especialidad del agente."""
        ...

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Nombre identificador del agente (usado en eventos SSE)."""
        ...

    async def analyze(self, context: RepoContext) -> str:
        """
        Analiza el repositorio y devuelve su sección Markdown.

        Args:
            context: Contexto completo del repositorio (árbol + archivos).

        Returns:
            Sección Markdown generada por el agente para su dominio.

        Raises:
            RuntimeError: Si el LLM devuelve una respuesta vacía o nula.
        """
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context.as_text),
        ]
        response = await invoke_llm(self._llm, messages)

        content = response.content
        if not content:
            raise RuntimeError(
                f"El agente '{self.agent_name}' recibió una respuesta vacía del LLM. "
                "Puede indicar un rechazo por filtros de contenido o un error de la API."
            )
        return str(content)
