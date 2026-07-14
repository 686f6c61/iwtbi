"""
Orquestador del pipeline de análisis de repositorios.

Coordina el ciclo completo: clonar → leer → 7 agentes en lotes acotados →
integrar → emitir eventos SSE. Gestiona errores y limpieza de temporales.

El orquestador se ejecuta como background task de FastAPI: no bloquea
la respuesta HTTP y emite eventos SSE conforme avanza el análisis.
"""

import asyncio
import logging
import time
from urllib.parse import quote

from app.agents.api_agent import ApiAgent
from app.agents.architecture import ArchitectureAgent
from app.agents.base import BaseAgent, provider_model_label, resolve_backup_providers
from app.agents.database import DatabaseAgent
from app.agents.devops import DevOpsAgent
from app.agents.frontend_agent import FrontendAgent
from app.agents.logic import LogicAgent
from app.agents.stack import StackAgent
from app.agents.synthesizer import Synthesizer
from app.database.analyses_repo import AnalysesRepo
from app.models.job import JobStatus
from app.models.repo_context import RepoContext
from app.config import settings
from app.services.analysis_tags import derive_analysis_tags, merge_tags
from app.services.file_reader import FileReader
from app.services.git_cloner import GitCloner
from app.store.job_store import JobStore

_logger = logging.getLogger(__name__)

# Segundos que un job completado permanece en memoria antes de ser eliminado.
# El retardo permite que el cliente descargue el documento sin carreras.
_JOB_RETENTION_SECONDS = 1800  # 30 minutos
_DEGRADED_CONTEXT_MAX_FILES = 6
_DEGRADED_CONTEXT_MAX_CHARS = 60_000


def _chunk_agents(agents: list[BaseAgent], batch_size: int) -> list[list[BaseAgent]]:
    """Divide la lista de agentes en tandas estables de tamaño `batch_size`."""
    safe_batch_size = min(max(batch_size, 1), settings.llm_max_concurrency, 3)
    return [
        agents[index:index + safe_batch_size]
        for index in range(0, len(agents), safe_batch_size)
    ]


class AllAgentsFailedError(RuntimeError):
    """Señala que ningún agente consiguió producir una sección utilizable."""


class AnalysisCancelledError(asyncio.CancelledError):
    """Cancelación explícita solicitada por el cliente."""


def _is_transient_agent_failure(exc: BaseException) -> bool:
    """Detecta fallos del proveedor que permiten continuar con un backup."""
    message = str(exc).lower()
    return (
        "timed out" in message
        or "429" in message
        or "rate limit" in message
        or "too many concurrent requests" in message
        or "empty llm response" in message
        or "401" in message
        or "authenticationerror" in message
        or "authentication error" in message
        or "invalid api key" in message
        or "invalid proxy token" in message
        or "unauthorized" in message
    )


def _build_biblioteca_url(repo_full_name: str) -> str:
    """Construye la URL pública correcta al análisis guardado en la biblioteca."""
    encoded_repo = quote(repo_full_name, safe="")
    base_url = settings.public_app_url.rstrip("/")
    return f"{base_url}/biblioteca/view?repo={encoded_repo}&open=1"


def _model_name_for_provider(provider: str | None, model_override: str | None) -> str:
    """Devuelve el modelo efectivo para logs internos sin duplicar ternarios."""
    if model_override:
        return model_override
    if provider == "openai_compatible":
        return settings.openai_compatible_model
    if provider == "nan":
        return settings.nan_model
    if provider == "zai":
        return settings.zai_model
    if provider == "ollama_cloud":
        return settings.ollama_cloud_model
    return "desconocido"


class Orchestrator:
    """
    Gestiona el pipeline completo de análisis de un repositorio.

    Cada llamada a run() es independiente: crea sus propios agentes,
    clona el repo en su directorio temporal y limpia todo al finalizar,
    tanto si el análisis tiene éxito como si falla.
    """

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self._cloner = GitCloner()
        self._reader = FileReader(
            max_files=settings.max_files,
            file_size_limit_kb=settings.file_size_limit_kb,
            max_context_chars=settings.max_context_chars,
        )
        self._synthesizer = Synthesizer()
        self._agents: list[BaseAgent] = [
            StackAgent(enable_fallback=False),
            ArchitectureAgent(enable_fallback=False),
            DatabaseAgent(enable_fallback=False),
            ApiAgent(enable_fallback=False),
            FrontendAgent(enable_fallback=False),
            LogicAgent(enable_fallback=False),
            DevOpsAgent(enable_fallback=False),
        ]

    def _build_runtime_components(
        self,
        *,
        provider_override: str | None,
        model_override: str | None,
        disable_fallback: bool,
    ) -> tuple[FileReader, Synthesizer, list[BaseAgent]]:
        """Construye reader/LLMs específicos por job si hay override interno."""
        if not provider_override and not model_override and not disable_fallback:
            return self._reader, self._synthesizer, self._agents

        reader = FileReader(
            max_files=settings.max_files,
            file_size_limit_kb=settings.file_size_limit_kb,
            max_context_chars=settings.max_context_chars,
        )
        synthesizer = Synthesizer(
            provider_override=provider_override,
            model_override=model_override,
            enable_fallback=not disable_fallback,
        )
        agent_kwargs = {
            "provider_override": provider_override,
            "model_override": model_override,
            "enable_fallback": False,
        }
        agents: list[BaseAgent] = [
            StackAgent(**agent_kwargs),
            ArchitectureAgent(**agent_kwargs),
            DatabaseAgent(**agent_kwargs),
            ApiAgent(**agent_kwargs),
            FrontendAgent(**agent_kwargs),
            LogicAgent(**agent_kwargs),
            DevOpsAgent(**agent_kwargs),
        ]
        return reader, synthesizer, agents

    async def run(self, job_id: str) -> None:
        """
        Ejecuta el pipeline completo para el job indicado.

        Los errores se capturan y se comunican al frontend vía SSE
        sin dejar el job en estado inconsistente. La limpieza del
        directorio temporal se garantiza en el bloque finally.
        El job se elimina del store tras _JOB_RETENTION_SECONDS para
        liberar memoria sin privar al cliente del documento recién generado.

        Args:
            job_id: Identificador del job a procesar.
        """
        job = self._store.get(job_id)
        if job is None:
            _logger.error(
                "run() invocado con job_id '%s' que no existe en el store. "
                "Posible condición de carrera o reinicio del proceso.",
                job_id,
            )
            return

        try:
            reader, synthesizer, agents = self._build_runtime_components(
                provider_override=job.provider_override,
                model_override=job.model_override,
                disable_fallback=job.disable_fallback,
            )
            if job.profile_label:
                _logger.info(
                    "Job '%s' ejecutando perfil interno '%s' (provider=%s model=%s fallback=%s)",
                    job_id,
                    job.profile_label,
                    job.provider_override or settings.provider,
                    _model_name_for_provider(
                        job.provider_override or settings.provider,
                        job.model_override,
                    ),
                    "off" if job.disable_fallback else "on",
                )

            await self._abort_if_cancel_requested(job_id)
            # Fase 1: Clonar el repositorio
            self._store.update_status(job_id, JobStatus.CLONING)
            await self._emit(job_id, "status", {"status": "cloning"})

            clone_path, git_sha = await self._cloner.clone(job.repo_url, job_id)
            await self._abort_if_cancel_requested(job_id)

            # Obtener topics del repo desde GitHub API (best-effort: fallo silencioso)
            repo_full_name_for_topics = "/".join(job.repo_url.rstrip("/").split("/")[-2:])
            from app.services.github_api import get_repo_topics
            topics = await get_repo_topics(repo_full_name_for_topics)

            # Fase 2: Leer y filtrar los archivos del repo
            context = reader.read(clone_path)
            await self._abort_if_cancel_requested(job_id)

            # Fase 3: 7 especialistas en lotes con concurrencia acotada
            self._store.update_status(job_id, JobStatus.ANALYZING)
            await self._emit(job_id, "status", {"status": "analyzing"})
            await self._abort_if_cancel_requested(job_id)

            try:
                sections = await self._run_agents(
                    job_id,
                    context,
                    agents=agents,
                    allow_backup_recovery=not job.disable_fallback,
                    primary_provider=job.provider_override or settings.provider,
                )
            except AllAgentsFailedError as agents_exc:
                _logger.error(
                    "Todos los agentes fallaron para el job '%s' (repo: %s). "
                    "No se guardará un análisis degradado en la biblioteca.",
                    job_id,
                    job.repo_url,
                )
                raise RuntimeError(
                    "Los proveedores de análisis no están disponibles. "
                    "Por favor, inténtalo de nuevo en unos minutos."
                ) from agents_exc

            # Fase 4: Sintetizar el documento final
            self._store.update_status(job_id, JobStatus.SYNTHESIZING)
            await self._emit(job_id, "status", {"status": "synthesizing"})
            await self._abort_if_cancel_requested(job_id)

            if not synthesizer.has_complete_section_set(sections):
                usable_count = synthesizer.usable_section_count(sections)
                _logger.warning(
                    "Job '%s' recibió un set incompleto de secciones (%d/%d). "
                    "Se cerrará con documento determinista para evitar pedir datos al usuario.",
                    job_id,
                    usable_count,
                    len(agents),
                )
                document = synthesizer.synthesize_deterministic(
                    repo_url=job.repo_url,
                    sections=sections,
                )
                await self._finalize_success(
                    job_id=job_id,
                    repo_url=job.repo_url,
                    document=document,
                    git_sha=git_sha,
                    topics=topics,
                )
                return

            try:
                document = await synthesizer.synthesize(job.repo_url, sections)
            except Exception as synth_exc:
                _logger.warning(
                    "La síntesis final falló para el job '%s' (repo: %s). "
                    "Se conservarán las secciones en un documento determinista. "
                    "Error: %s",
                    job_id,
                    job.repo_url,
                    synth_exc,
                    exc_info=True,
                )
                document = synthesizer.synthesize_deterministic(
                    repo_url=job.repo_url,
                    sections=sections,
                )
            await self._finalize_success(
                job_id=job_id,
                repo_url=job.repo_url,
                document=document,
                git_sha=git_sha,
                topics=topics,
            )

        except asyncio.CancelledError:
            # El cliente cerró la conexión antes de que terminara el análisis.
            # CancelledError hereda de BaseException, no de Exception, por lo que
            # debe capturarse ANTES del bloque except Exception.
            _logger.info(
                "Pipeline cancelado para job '%s' (repo: %s).",
                job_id,
                job.repo_url,
            )
            raise  # re-propagar para que asyncio gestione la tarea correctamente

        except Exception as exc:
            # Distinguir errores de negocio (mensaje legible) de bugs internos
            is_business_error = isinstance(exc, (RuntimeError, ValueError))
            user_message = (
                str(exc)
                if is_business_error
                else "Error interno del servidor. Por favor, inténtalo de nuevo."
            )
            _logger.error(
                "Pipeline fallido para job '%s' (repo: %s): %s",
                job_id,
                job.repo_url,
                exc,
                exc_info=True,
            )
            self._store.set_error(job_id, str(exc))
            await self._emit(job_id, "analysis_error", {"message": user_message})

        finally:
            # La limpieza del directorio temporal se ejecuta siempre
            self._cloner.cleanup(job_id)
            # Guardar la referencia de la tarea para evitar que el GC la elimine
            # antes de que termine. asyncio.create_task() sin guardar referencia
            # es un bug silencioso: el GC puede destruir la tarea prematuramente.
            self._cleanup_task = asyncio.create_task(self._schedule_job_cleanup(job_id))

    async def _abort_if_cancel_requested(self, job_id: str) -> None:
        """Detiene el pipeline si el cliente pidió cancelarlo."""
        if not self._store.is_cancel_requested(job_id):
            return

        message = "El análisis se canceló porque cerraste la pestaña antes de terminar."
        self._store.set_error(job_id, message)
        await self._emit(job_id, "analysis_error", {"message": message})
        raise AnalysisCancelledError(message)

    async def _run_agents(
        self,
        job_id: str,
        context: RepoContext,
        *,
        agents: list[BaseAgent] | None = None,
        allow_backup_recovery: bool = True,
        primary_provider: str | None = None,
    ) -> dict[str, str]:
        """
        Lanza los 7 agentes en lotes de hasta tres y emite un evento SSE por cada uno.

        Cuando un agente falla, el fallo se registra y se notifica al cliente
        vía ``agent_error``, pero el pipeline continúa con los agentes restantes.
        Si todos los agentes fallan, se eleva un RuntimeError.

        Args:
            job_id: ID del job para emitir eventos SSE.
            context: Contexto completo del repo para todos los agentes.

        Returns:
            Diccionario {agent_name: section_markdown} con los resultados.

        Raises:
            RuntimeError: Si ningún agente produce una sección válida.
        """

        active_agents = agents or self._agents
        sections, failures = await self._run_agents_attempt(
            job_id,
            context,
            agents=active_agents,
            sequential=False,
        )

        if failures:
            recovered_sections, failures = await self._recover_failed_agents_with_backup(
                job_id,
                context,
                agents=active_agents,
                failures=failures,
                enabled=allow_backup_recovery,
                primary_provider=primary_provider or settings.provider,
            )
            if recovered_sections:
                sections.update(recovered_sections)

        if failures:
            degraded_sections, failures = (
                await self._recover_failed_agents_with_degraded_context(
                    job_id,
                    context,
                    agents=active_agents,
                    failures=failures,
                    enabled=allow_backup_recovery,
                )
            )
            if degraded_sections:
                sections.update(degraded_sections)

        valid = [section for section in sections.values() if section.strip()]
        if valid:
            return sections

        if failures and all(_is_transient_agent_failure(exc) for exc in failures.values()):
            _logger.warning(
                "Todos los agentes fallaron por errores transitorios en job '%s'. "
                "Se reintentará con contexto degradado y ejecución secuencial.",
                job_id,
            )
            degraded_context = self._build_degraded_context(context)
            sections, failures = await self._run_agents_attempt(
                job_id,
                degraded_context,
                agents=active_agents,
                sequential=True,
            )
            valid = [section for section in sections.values() if section.strip()]
            if valid:
                return sections

        raise AllAgentsFailedError(
            "Todos los agentes fallaron. No es posible generar el documento."
        )

    async def _recover_failed_agents_with_backup(
        self,
        job_id: str,
        context: RepoContext,
        *,
        agents: list[BaseAgent],
        failures: dict[str, BaseException],
        enabled: bool,
        primary_provider: str,
    ) -> tuple[dict[str, str], dict[str, BaseException]]:
        """
        Reintenta agentes fallidos con el proveedor backup cuando el fallo parece transitorio.

        El objetivo es que un timeout del proveedor primario o un wall-clock
        agotado por cola no deje huecos evitables en el documento final.
        """
        if not enabled:
            return {}, failures
        backup_providers = resolve_backup_providers(primary_provider)
        if not backup_providers:
            return {}, failures

        transient_agents = [
            agent
            for agent in agents
            if agent.agent_name in failures and _is_transient_agent_failure(failures[agent.agent_name])
        ]
        if not transient_agents:
            return {}, failures

        recovered_sections: dict[str, str] = {}
        merged_failures = dict(failures)
        pending_agents = list(transient_agents)

        for backup_provider, backup_model in backup_providers:
            backup_agents: list[BaseAgent] = []
            for agent in pending_agents:
                try:
                    backup_agents.append(
                        type(agent)(
                            provider_override=backup_provider,
                            model_override=backup_model,
                            enable_fallback=False,
                        )
                    )
                except TypeError:
                    _logger.warning(
                        "No se pudo construir el backup agent '%s' para job '%s'.",
                        agent.agent_name,
                        job_id,
                        exc_info=True,
                    )

            if not backup_agents:
                continue

            _logger.warning(
                "Job '%s': reintento secuencial con %s para %d agentes transitorios: %s",
                job_id,
                provider_model_label(backup_provider, backup_model),
                len(backup_agents),
                ", ".join(agent.agent_name for agent in backup_agents),
            )
            attempt_sections, attempt_failures = await self._run_agents_attempt(
                job_id,
                context,
                agents=backup_agents,
                sequential=True,
            )
            recovered_sections.update(attempt_sections)
            for agent_name in attempt_sections:
                merged_failures.pop(agent_name, None)
            merged_failures.update(attempt_failures)
            pending_names = {
                agent.agent_name for agent in pending_agents
            } - set(attempt_sections)
            pending_agents = [
                agent for agent in pending_agents if agent.agent_name in pending_names
            ]
            if not pending_agents:
                break

        return recovered_sections, merged_failures

    async def _recover_failed_agents_with_degraded_context(
        self,
        job_id: str,
        context: RepoContext,
        *,
        agents: list[BaseAgent],
        failures: dict[str, BaseException],
        enabled: bool,
    ) -> tuple[dict[str, str], dict[str, BaseException]]:
        """
        Último rescate para agentes individuales que agotan proveedor y backups.

        Si el repo entra justo en el límite de contexto, algunos agentes pueden
        no responder aunque otros sí. Antes de cerrar el documento parcial,
        reintentamos solo esos agentes con un contexto compacto.
        """
        if not enabled:
            return {}, failures

        transient_agents = [
            agent
            for agent in agents
            if agent.agent_name in failures and _is_transient_agent_failure(failures[agent.agent_name])
        ]
        if not transient_agents:
            return {}, failures

        degraded_context = self._build_degraded_context(context)
        _logger.warning(
            "Job '%s': reintento con contexto compacto para %d agentes transitorios: %s",
            job_id,
            len(transient_agents),
            ", ".join(agent.agent_name for agent in transient_agents),
        )
        recovered_sections, recovered_failures = await self._run_agents_attempt(
            job_id,
            degraded_context,
            agents=transient_agents,
            sequential=True,
        )
        merged_failures = dict(failures)
        for agent_name in recovered_sections:
            merged_failures.pop(agent_name, None)
        merged_failures.update(recovered_failures)
        return recovered_sections, merged_failures

    async def _run_agents_attempt(
        self,
        job_id: str,
        context: RepoContext,
        *,
        agents: list[BaseAgent] | None = None,
        sequential: bool,
    ) -> tuple[dict[str, str], dict[str, BaseException]]:
        """Ejecuta una pasada de agentes y devuelve secciones más fallos."""
        active_agents = agents or self._agents

        async def run_single(agent: BaseAgent) -> tuple[str, str]:
            started_at = time.monotonic()
            _logger.info(
                "Agente '%s' iniciado en job '%s'.",
                agent.agent_name,
                job_id,
            )
            try:
                section = await asyncio.wait_for(
                    agent.analyze(context),
                    timeout=settings.llm_agent_wall_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                elapsed = time.monotonic() - started_at
                raise RuntimeError(
                    "agent wall-clock timed out after "
                    f"{elapsed:.1f}s (límite {settings.llm_agent_wall_timeout_seconds:.0f}s)"
                ) from exc
            elapsed = time.monotonic() - started_at
            _logger.info(
                "Agente '%s' completado en job '%s' en %.1fs.",
                agent.agent_name,
                job_id,
                elapsed,
            )
            await self._emit(job_id, "agent", {
                "agent": agent.agent_name,
                "section": section,
            })
            return agent.agent_name, section

        sections: dict[str, str] = {}
        failures: dict[str, BaseException] = {}

        async def record_result(
            agent: BaseAgent,
            result: tuple[str, str] | BaseException,
        ) -> None:
            if isinstance(result, BaseException):
                failures[agent.agent_name] = result
                _logger.error(
                    "Agente '%s' falló en job '%s': %s",
                    agent.agent_name,
                    job_id,
                    result,
                    exc_info=result,
                )
                await self._emit(job_id, "agent_error", {
                    "agent": agent.agent_name,
                    "message": f"El agente {agent.agent_name} no pudo completar su análisis.",
                })
                return

            name, section = result
            sections[name] = section

        if sequential:
            for agent in active_agents:
                try:
                    result: tuple[str, str] | BaseException = await run_single(agent)
                except BaseException as exc:
                    result = exc
                await record_result(agent, result)
        else:
            batches = _chunk_agents(active_agents, settings.llm_agent_batch_size)
            total_batches = len(batches)
            for batch_index, batch in enumerate(batches, start=1):
                _logger.info(
                    "Job '%s': ejecutando tanda %d/%d de agentes (%d agentes): %s",
                    job_id,
                    batch_index,
                    total_batches,
                    len(batch),
                    ", ".join(agent.agent_name for agent in batch),
                )
                batch_results = await asyncio.gather(
                    *[run_single(agent) for agent in batch],
                    return_exceptions=True,
                )
                for agent, result in zip(batch, batch_results):
                    await record_result(agent, result)

        return sections, failures

    def _build_degraded_context(self, context: RepoContext) -> RepoContext:
        """Reduce el contexto para un segundo intento más ligero."""
        files: dict[str, str] = {}
        chars_used = 0

        for path, content in context.files.items():
            if len(files) >= _DEGRADED_CONTEXT_MAX_FILES or chars_used >= _DEGRADED_CONTEXT_MAX_CHARS:
                break
            remaining = _DEGRADED_CONTEXT_MAX_CHARS - chars_used
            if len(content) > remaining:
                content = content[:remaining] + "\n\n[... contexto degradado truncado ...]"
                chars_used = _DEGRADED_CONTEXT_MAX_CHARS
            else:
                chars_used += len(content)
            files[path] = content

        return RepoContext(tree=context.tree, files=files)

    async def _finalize_success(
        self,
        *,
        job_id: str,
        repo_url: str,
        document: str,
        git_sha: str,
        topics: list[str],
    ) -> None:
        """Persiste, notifica y emite el documento final de un job exitoso."""
        repo_full_name = "/".join(repo_url.rstrip("/").split("/")[-2:])
        tags = merge_tags(derive_analysis_tags(document), topics)
        self._store.set_document(job_id, document)

        try:
            AnalysesRepo().save(
                repo_url=repo_url,
                repo_full_name=repo_full_name,
                document=document,
                git_sha=git_sha,
                tags=tags,
            )
        except Exception as storage_exc:
            _logger.error(
                "No se pudo persistir el análisis del job '%s' en la biblioteca: %s",
                job_id,
                storage_exc,
            )

        direct_notified_emails = self._send_email_notifications(
            job_id=job_id,
            repo_url=repo_url,
            repo_full_name=repo_full_name,
        )
        self._seed_repo_subscriptions(repo_url=repo_url, git_sha=git_sha)
        self._send_repo_update_notifications(
            repo_url=repo_url,
            repo_full_name=repo_full_name,
            git_sha=git_sha,
            skip_emails=direct_notified_emails,
        )
        await self._emit(job_id, "complete", {"document": document})

    async def _schedule_job_cleanup(self, job_id: str) -> None:
        """
        Elimina el job del store tras el período de retención configurado.

        Se ejecuta como tarea asyncio en segundo plano para no bloquear
        el pipeline. El retardo permite que el cliente descargue el documento
        antes de que el job desaparezca del store.

        Args:
            job_id: Identificador del job a eliminar.
        """
        await asyncio.sleep(_JOB_RETENTION_SECONDS)
        self._store.remove(job_id)
        _logger.debug(
            "Job '%s' eliminado del store tras %ds de retención.",
            job_id,
            _JOB_RETENTION_SECONDS,
        )

    def _send_email_notifications(
        self,
        *,
        job_id: str,
        repo_url: str,
        repo_full_name: str,
    ) -> set[str]:
        """
        Envía el email de «análisis listo» a todos los usuarios pendientes del repo.

        Consulta la tabla ``repo_notifications`` por ``repo_url`` para cubrir
        el caso en que el análisis exitoso llegue desde un job distinto al que
        registró originalmente el email. Se deduplican emails para no enviar
        múltiples avisos al mismo destinatario en una sola finalización.

        Args:
            job_id: Identificador del job completado.
            repo_url: URL del repositorio cuyo análisis se ha guardado.
            repo_full_name: Nombre «owner/repo» para construir la URL de la biblioteca.
        """
        try:
            from app.database.notifications_repo import NotificationsRepo
            from app.services.email_service import send_analysis_ready

            notifications_repo = NotificationsRepo()
            notifications = notifications_repo.find_pending_for_repo(repo_url)
            if not notifications:
                return set()

            biblioteca_url = _build_biblioteca_url(repo_full_name)
            notifications_by_email: dict[str, list[dict]] = {}
            for notification in notifications:
                email = str(notification.get("email") or "").strip().lower()
                if not email:
                    continue
                notifications_by_email.setdefault(email, []).append(notification)

            sent_emails: set[str] = set()
            for email, grouped_notifications in notifications_by_email.items():
                success = send_analysis_ready(
                    to_email=email,
                    repo_full_name=repo_full_name,
                    biblioteca_url=biblioteca_url,
                    repo_url=repo_url,
                )
                if success:
                    sent_emails.add(email)
                    for notification in grouped_notifications:
                        notifications_repo.mark_sent(notification["id"])
            return sent_emails

        except Exception as exc:
            _logger.error(
                "Error en el fanout de emails para job '%s': %s",
                job_id,
                exc,
            )
            return set()

    def _seed_repo_subscriptions(self, *, repo_url: str, git_sha: str) -> None:
        """Inicializa nuevas suscripciones del repo con el SHA recién analizado."""
        try:
            from app.database.subscriptions_store import SubscriptionsStore

            SubscriptionsStore().seed_repo_subscriptions(repo_url=repo_url, git_sha=git_sha)
        except Exception as exc:
            _logger.error(
                "Error al preparar suscripciones del repo '%s' tras completar el análisis: %s",
                repo_url,
                exc,
            )

    def _send_repo_update_notifications(
        self,
        *,
        repo_url: str,
        repo_full_name: str,
        git_sha: str,
        skip_emails: set[str] | None = None,
    ) -> None:
        """Envía avisos de análisis nuevo a suscriptores cuando cambia el SHA."""
        skip_emails = {email.strip().lower() for email in (skip_emails or set())}
        try:
            from app.database.subscriptions_store import SubscriptionsStore
            from app.services.email_service import send_repo_update_ready

            store = SubscriptionsStore()
            notifications = store.list_pending_repo_updates(
                repo_url=repo_url,
                git_sha=git_sha,
            )
            if not notifications:
                return

            biblioteca_url = _build_biblioteca_url(repo_full_name)
            for notification in notifications:
                email = str(notification.get("email") or "").strip().lower()
                if not email:
                    continue
                if email in skip_emails:
                    store.mark_repo_notified(
                        repo_url=repo_url,
                        email=email,
                        git_sha=git_sha,
                    )
                    continue

                success = send_repo_update_ready(
                    to_email=email,
                    repo_full_name=repo_full_name,
                    biblioteca_url=biblioteca_url,
                    repo_url=repo_url,
                    git_sha=git_sha,
                )
                if success:
                    store.mark_repo_notified(
                        repo_url=repo_url,
                        email=email,
                        git_sha=git_sha,
                    )
        except Exception as exc:
            _logger.error(
                "Error al enviar avisos evolutivos para repo '%s': %s",
                repo_url,
                exc,
            )

    async def _emit(self, job_id: str, event_type: str, data: dict) -> None:
        """
        Encola un evento SSE para el job indicado.

        Args:
            job_id: ID del job cuya cola recibe el evento.
            event_type: Tipo de evento (status, agent, agent_error, complete, analysis_error).
            data: Payload del evento (se enviará como JSON al cliente).
        """
        try:
            await self._store.emit_event(job_id, event_type, data)
        except Exception:
            if event_type not in ("complete", "analysis_error"):
                return
            _logger.warning(
                "Evento '%s' del job '%s' descartado: la cola SSE no está disponible.",
                event_type,
                job_id,
            )
