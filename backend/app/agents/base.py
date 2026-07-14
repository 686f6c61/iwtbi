"""
Agente base para todos los agentes especializados de IWTBI.

Cada agente hereda de BaseAgent y solo necesita definir su prompt de
sistema, su nombre identificador y, opcionalmente, su temperatura.
La conexión al LLM y la invocación están centralizadas aquí para
evitar duplicación de lógica.

Proveedores soportados (controlados por ``settings.provider``):

- ``openai_compatible``: usa ChatOpenAI contra el endpoint configurado.
- ``nan``: usa ChatOpenAI apuntando a NaN builders (OpenAI-compatible).
- ``zai``: usa ChatOpenAI apuntando a la API de z.ai (OpenAI-compatible).
- ``ollama_cloud``: usa ChatOllama con un AsyncClient autenticado contra
  Ollama Cloud (``https://ollama.com``). La base_url NO debe incluir
  el sufijo ``/api``; ChatOllama lo añade internamente.

Constantes compartidas:

- ``ANTI_HALLUCINATION_RULE``: bloque de instrucciones que se añade al final
  del system_prompt de cada agente para forzar extracción estricta desde
  el código fuente, sin inferencias ni completaciones inventadas.
- ``RECONSTRUCTION_SPEC_RULE``: contrato común que convierte cada análisis
  especializado en una especificación autocontenida y reconstruible.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from ollama import AsyncClient

from app.config import settings
from app.models.repo_context import RepoContext

_logger = logging.getLogger(__name__)


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

RECONSTRUCTION_SPEC_RULE = """

CONTRATO DE RECONSTRUCCIÓN — EL DOCUMENTO DEBE PODER SUSTITUIR AL REPOSITORIO:
Tu sección se entregará íntegra a otra IA que no podrá consultar el código original.

- Haz la sección autocontenida: explica el comportamiento, las relaciones y las decisiones necesarias para reconstruir tu área.
- Cita rutas reales entre backticks siempre que atribuyas una tecnología, contrato, módulo, regla, comando o configuración.
- Nombra archivos, módulos, símbolos, endpoints, campos y estados exactos cuando estén presentes en el contexto.
- Incluye tablas para conjuntos estructurados y comparables; no comprimas datos útiles en prosa.
- Incluye tantos diagramas Mermaid como sean necesarios para transmitir relaciones, flujos, estados o topologías distintas. Evita duplicar en diagramas lo que una tabla ya expresa mejor.
- Conserva contratos exactos: tipos, entradas, salidas, errores, valores por defecto, orden de operaciones e invariantes.
- Termina con `### Criterios de aceptación` y una lista verificable para reconstruir tu área.
- Termina después con `### Evidencias y desconocidos`: enumera las rutas que sustentan el análisis y marca como `No detectado en el código analizado` cualquier dato necesario que falte.
- No remitas al lector a "ver el código" ni des por supuesto que tendrá acceso al repositorio.
"""

_llm_semaphore: asyncio.Semaphore | None = None


def provider_label(provider: str | None) -> str:
    """Devuelve una etiqueta legible del proveedor para logs y mensajes."""
    if provider == "openai_compatible":
        return "OpenAI-compatible"
    if provider == "nan":
        return "NaN"
    if provider == "zai":
        return "z.ai"
    if provider == "ollama_cloud":
        return "Ollama Cloud"
    return provider or "desconocido"


def provider_model_label(provider: str | None, model: str | None = None) -> str:
    """Devuelve una etiqueta legible de proveedor y modelo para logs."""
    label = provider_label(provider)
    return f"{label} ({model})" if model else label


def _provider_has_credentials(provider: str) -> bool:
    """Comprueba si el proveedor dispone de credenciales válidas."""
    if provider == "openai_compatible":
        return bool(
            settings.openai_compatible_api_key.strip()
            and settings.openai_compatible_model.strip()
        )
    if provider == "nan":
        return bool(
            settings.nan_api_key.strip()
            and settings.nan_api_key.strip() != "placeholder"
        )
    if provider == "zai":
        return bool(
            settings.zai_api_key.strip()
            and settings.zai_api_key.strip() != "placeholder"
        )
    if provider == "ollama_cloud":
        return bool(
            settings.ollama_cloud_api_key.strip()
            and settings.ollama_cloud_api_key.strip() != "placeholder"
        )
    return False


def _provider_model(provider: str) -> str | None:
    """Devuelve el modelo configurado para un proveedor conocido."""
    if provider == "openai_compatible":
        return settings.openai_compatible_model
    if provider == "nan":
        return settings.nan_model
    if provider == "zai":
        return settings.zai_model
    if provider == "ollama_cloud":
        return settings.ollama_cloud_model
    return None


def _ollama_cloud_models() -> list[str]:
    """Devuelve los modelos Ollama Cloud configurados sin duplicados."""
    models = [settings.ollama_cloud_model]
    models.extend(
        model.strip()
        for model in settings.ollama_cloud_fallback_models.split(",")
        if model.strip()
    )

    unique_models: list[str] = []
    for model in models:
        if model and model not in unique_models:
            unique_models.append(model)
    return unique_models


def _provider_models(provider: str) -> list[str | None]:
    """Devuelve todos los modelos configurados para un proveedor fallback."""
    if provider == "ollama_cloud":
        return _ollama_cloud_models()
    return [_provider_model(provider)]


def resolve_backup_providers(
    primary_provider: str | None,
    primary_model: str | None = None,
) -> list[tuple[str, str | None]]:
    """
    Resuelve la cadena de proveedores secundarios para el primario indicado.

    La plataforma no debe rendirse si el primer backup también cae:
    Los proveedores configurados se prueban sin repetir el primario.
    """
    effective_primary = primary_provider or settings.provider
    fallback_order = {
        "openai_compatible": ["ollama_cloud", "nan", "zai"],
        "nan": ["ollama_cloud", "zai", "openai_compatible"],
        "zai": ["ollama_cloud", "nan", "openai_compatible"],
        "ollama_cloud": ["ollama_cloud", "nan", "zai", "openai_compatible"],
    }.get(effective_primary, [])

    backups: list[tuple[str, str | None]] = []
    effective_primary_model = primary_model
    if effective_primary == "ollama_cloud" and not effective_primary_model:
        effective_primary_model = settings.ollama_cloud_model

    for provider in fallback_order:
        if not _provider_has_credentials(provider):
            continue
        for model in _provider_models(provider):
            if provider == effective_primary and model == effective_primary_model:
                continue
            backups.append((provider, model))
    return backups


def resolve_backup_provider(
    primary_provider: str | None,
) -> tuple[str | None, str | None]:
    """
    Resuelve el primer proveedor secundario para código legado.

    El pipeline de agentes usa `resolve_backup_providers` para probar toda la
    cadena, pero sintetizador y recuperaciones antiguas siguen consumiendo este
    helper de primer backup.
    """
    backups = resolve_backup_providers(primary_provider)
    return backups[0] if backups else (None, None)


class _OllamaCloudDirectAdapter:
    """
    Adaptador mínimo para modelos `*:cloud` de Ollama Cloud.

    ChatOllama está devolviendo `content=''` para `glm-5.1:cloud` aunque la
    API nativa sí devuelve texto en `message.content`. Este adaptador usa el
    cliente oficial de Ollama directamente y devuelve un AIMessage compatible
    con el resto del pipeline.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = AsyncClient(
            host=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )

    async def ainvoke(self, messages):
        payload = []
        for message in messages:
            role = "user"
            if isinstance(message, SystemMessage):
                role = "system"
            elif isinstance(message, AIMessage):
                role = "assistant"
            payload.append(
                {
                    "role": role,
                    "content": str(getattr(message, "content", "") or ""),
                }
            )

        response = await self._client.chat(
            model=self._model,
            messages=payload,
            think=False,
            options={
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        )
        raw_message = getattr(response, "message", None)
        content = str(getattr(raw_message, "content", "") or "")
        thinking = getattr(raw_message, "thinking", None)
        return AIMessage(
            content=content,
            additional_kwargs={"thinking": thinking} if thinking else {},
            response_metadata={
                "model": getattr(response, "model", self._model),
                "done": getattr(response, "done", None),
                "done_reason": getattr(response, "done_reason", None),
                "total_duration": getattr(response, "total_duration", None),
                "prompt_eval_count": getattr(response, "prompt_eval_count", None),
                "eval_count": getattr(response, "eval_count", None),
                "model_provider": "ollama-direct",
            },
        )


def _get_llm_semaphore() -> asyncio.Semaphore:
    """Devuelve el semáforo global que limita la concurrencia LLM del proceso."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(min(max(settings.llm_max_concurrency, 1), 3))
    return _llm_semaphore


def _is_retryable_llm_error(exc: Exception) -> bool:
    """
    Detecta errores transitorios del proveedor que merecen reintento.

    En Ollama Cloud el caso crítico observado en producción es el 429 por
    exceso de concurrencia ("too many concurrent requests").
    """
    message = str(exc).lower()
    if "package has expired" in message:
        return False
    return (
        "too many concurrent requests" in message
        or "too many requests" in message
        or "error code: 429" in message
        or "status code: 429" in message
        or "error code: 503" in message
        or "status code: 503" in message
        or "rate limit" in message
        or "service unavailable" in message
        or "server overloaded" in message
        or "llm request timed out" in message
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


async def invoke_llm(
    llm,
    messages,
    *,
    timeout_seconds: float | None = None,
    retry_attempts: int | None = None,
    retry_base_delay_seconds: float | None = None,
):
    """
    Ejecuta una llamada LLM bajo límite global de concurrencia y con retry.

    El objetivo es evitar que múltiples análisis en paralelo saturen el
    proveedor y devuelvan 429 antes de que el sistema pueda encolar trabajo.
    """
    attempts = max(
        settings.llm_retry_attempts if retry_attempts is None else retry_attempts,
        0,
    )
    base_delay = (
        settings.llm_retry_base_delay_seconds
        if retry_base_delay_seconds is None
        else retry_base_delay_seconds
    )
    for attempt in range(attempts + 1):
        try:
            async with _get_llm_semaphore():
                response = await asyncio.wait_for(
                    llm.ainvoke(messages),
                    timeout=timeout_seconds or settings.llm_request_timeout_seconds,
                )
            if not _response_has_content(response):
                raise RuntimeError("empty llm response")
            return response
        except asyncio.TimeoutError as exc:
            if attempt >= attempts:
                raise RuntimeError("llm request timed out") from exc
            delay = base_delay * (2**attempt)
            await asyncio.sleep(delay)
        except Exception as exc:
            if attempt >= attempts or not _is_retryable_llm_error(exc):
                raise
            delay = base_delay * (2**attempt)
            await asyncio.sleep(delay)


def build_llm(
    temperature: float = 0.0,
    max_tokens: int = 32768,
    request_timeout_seconds: float | None = None,
    provider: str | None = None,
    model_override: str | None = None,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
) -> Union[ChatOpenAI, ChatOllama, _OllamaCloudDirectAdapter]:
    """
    Construye el cliente LLM según el proveedor configurado en settings.

    La temperatura y el límite de tokens se configuran por agente para
    ajustar el balance entre exactitud factual (temperature=0.0) y
    fluidez narrativa (temperature=0.05–0.1).

    Args:
        temperature: Temperatura de sampling. 0.0 para extracción factual
                     estricta (sin variabilidad); hasta 0.1 para secciones
                     más narrativas o interpretativas.
        max_tokens:  Número máximo de tokens en la respuesta. Se acota en
                     producción para evitar respuestas demasiado lentas.

    Returns:
        ``ChatOpenAI`` para proveedores OpenAI-compatible, NaN o z.ai, o
        ``ChatOllama`` con autenticación Bearer si ``provider == "ollama_cloud"``.

    Raises:
        ValueError: Si el proveedor configurado no es reconocido.
    """
    effective_provider = provider or settings.provider

    if effective_provider == "openai_compatible":
        timeout_seconds = (
            request_timeout_seconds
            if request_timeout_seconds is not None
            else settings.llm_request_timeout_seconds
        )
        return ChatOpenAI(
            api_key=api_key_override or settings.openai_compatible_api_key,
            base_url=base_url_override or settings.openai_compatible_base_url,
            model=model_override or settings.openai_compatible_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
        )

    if effective_provider == "nan":
        timeout_seconds = (
            request_timeout_seconds
            if request_timeout_seconds is not None
            else settings.llm_request_timeout_seconds
        )
        return ChatOpenAI(
            api_key=api_key_override or settings.nan_api_key,
            base_url=base_url_override or settings.nan_base_url,
            model=model_override or settings.nan_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

    if effective_provider == "zai":
        timeout_seconds = (
            request_timeout_seconds
            if request_timeout_seconds is not None
            else settings.llm_request_timeout_seconds
        )
        return ChatOpenAI(
            api_key=api_key_override or settings.zai_api_key,
            base_url=base_url_override or settings.zai_base_url,
            model=model_override or settings.zai_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
        )

    if effective_provider == "ollama_cloud":
        # ChatOllama 1.x pasa kwargs al SDK ollama subyacente mediante
        # async_client_kwargs y sync_client_kwargs. La autenticación de
        # Ollama Cloud se inyecta como cabecera Bearer en ambos clientes.
        # base_url = https://ollama.com (sin /api); el SDK añade /api/chat.
        # Ollama usa num_predict en lugar de max_tokens.
        api_key = api_key_override or settings.ollama_cloud_api_key
        base_url = base_url_override or settings.ollama_cloud_base_url
        auth_headers = {"Authorization": f"Bearer {api_key}"}
        timeout_seconds = (
            request_timeout_seconds
            if request_timeout_seconds is not None
            else settings.llm_request_timeout_seconds
        )
        effective_model = model_override or settings.ollama_cloud_model
        if effective_model.endswith(":cloud"):
            return _OllamaCloudDirectAdapter(
                model=effective_model,
                base_url=base_url,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        return ChatOllama(
            model=effective_model,
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
        f"Proveedor de LLM no reconocido: '{effective_provider}'. "
        "Valores válidos: 'openai_compatible', 'nan', 'zai', 'ollama_cloud'."
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
    max_tokens: int | None = None

    def __init__(
        self,
        *,
        provider_override: str | None = None,
        model_override: str | None = None,
        api_key_override: str | None = None,
        base_url_override: str | None = None,
        enable_fallback: bool = True,
    ) -> None:
        self._primary_provider = provider_override or settings.provider
        effective_max_tokens = self.max_tokens or settings.llm_agent_max_tokens
        self._llm = build_llm(
            temperature=self.temperature,
            max_tokens=effective_max_tokens,
            request_timeout_seconds=settings.llm_agent_request_timeout_seconds,
            provider=self._primary_provider,
            model_override=model_override,
            api_key_override=api_key_override,
            base_url_override=base_url_override,
        )
        self._fallback_llm = None
        self._fallback_provider_label = None
        self._fallback_llms = []
        if enable_fallback:
            for backup_provider, backup_model in resolve_backup_providers(
                self._primary_provider,
                model_override,
            ):
                fallback_llm = build_llm(
                    temperature=self.temperature,
                    max_tokens=effective_max_tokens,
                    request_timeout_seconds=settings.llm_agent_request_timeout_seconds,
                    provider=backup_provider,
                    model_override=backup_model,
                )
                fallback_label = provider_model_label(backup_provider, backup_model)
                self._fallback_llms.append((fallback_llm, fallback_label))
            if self._fallback_llms:
                self._fallback_llm = self._fallback_llms[0][0]
                self._fallback_provider_label = self._fallback_llms[0][1]

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
        try:
            response = await invoke_llm(
                self._llm,
                messages,
                timeout_seconds=settings.llm_agent_request_timeout_seconds,
                retry_attempts=settings.llm_agent_retry_attempts,
            )
        except Exception as primary_exc:
            if not self._fallback_llms:
                raise
            last_exc = primary_exc
            for fallback_llm, fallback_label in self._fallback_llms:
                _logger.warning(
                    "El agente '%s' falló con el proveedor primario. "
                    "Se reintentará con %s: %s",
                    self.agent_name,
                    fallback_label,
                    last_exc,
                )
                try:
                    response = await invoke_llm(
                        fallback_llm,
                        messages,
                        timeout_seconds=settings.llm_agent_request_timeout_seconds,
                        retry_attempts=settings.llm_agent_retry_attempts,
                    )
                    break
                except Exception as fallback_exc:
                    last_exc = fallback_exc
            else:
                raise last_exc from primary_exc

        content = response.content
        if not content:
            raise RuntimeError(
                f"El agente '{self.agent_name}' recibió una respuesta vacía del LLM. "
                "Puede indicar un rechazo por filtros de contenido o un error de la API."
            )
        return str(content)
