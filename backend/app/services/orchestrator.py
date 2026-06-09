"""
Orquestador del pipeline de análisis de repositorios.

Coordina el ciclo completo: clonar → leer → 7 agentes en paralelo →
sintetizar → emitir eventos SSE. Gestiona errores y limpieza de temporales.

El orquestador se ejecuta como background task de FastAPI: no bloquea
la respuesta HTTP y emite eventos SSE conforme avanza el análisis.
"""

import asyncio
import logging
from urllib.parse import quote

from app.agents.api_agent import ApiAgent
from app.agents.architecture import ArchitectureAgent
from app.agents.base import BaseAgent
from app.agents.database import DatabaseAgent
from app.agents.devops import DevOpsAgent
from app.agents.frontend_agent import FrontendAgent
from app.agents.logic import LogicAgent
from app.agents.stack import StackAgent
from app.agents.synthesizer import Synthesizer
from app.database.analyses_repo import AnalysesRepo
from app.models.job import JobStatus
from app.models.job import LlmConfig
from app.models.repo_context import RepoContext
from app.config import settings
from app.services.file_reader import FileReader
from app.services.git_cloner import GitCloner
from app.store.job_store import JobStore

_logger = logging.getLogger(__name__)

# Segundos que un job completado permanece en memoria antes de ser eliminado.
# El retardo permite que el cliente descargue el documento sin carreras.
_JOB_RETENTION_SECONDS = 1800  # 30 minutos


def _build_biblioteca_url(repo_full_name: str) -> str:
    """Construye la URL pública correcta al análisis guardado en la biblioteca."""
    encoded_repo = quote(repo_full_name, safe="")
    return f"https://app.example.com/biblioteca/view?repo={encoded_repo}&open=1"


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

    def _build_agents(self, llm_config: LlmConfig | None) -> list[BaseAgent]:
        return [
            StackAgent(llm_config),
            ArchitectureAgent(llm_config),
            DatabaseAgent(llm_config),
            ApiAgent(llm_config),
            FrontendAgent(llm_config),
            LogicAgent(llm_config),
            DevOpsAgent(llm_config),
        ]

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
            # Fase 1: Clonar el repositorio
            self._store.update_status(job_id, JobStatus.CLONING)
            await self._emit(job_id, "status", {"status": "cloning"})

            clone_path, git_sha = await self._cloner.clone(job.repo_url, job_id)

            # Obtener topics del repo desde GitHub API (best-effort: fallo silencioso)
            repo_full_name_for_topics = "/".join(job.repo_url.rstrip("/").split("/")[-2:])
            from app.services.github_api import get_repo_topics
            topics = await get_repo_topics(repo_full_name_for_topics)

            # Fase 2: Leer y filtrar los archivos del repo
            context = self._reader.read(clone_path)

            # Fase 3: 7 agentes en paralelo
            self._store.update_status(job_id, JobStatus.ANALYZING)
            await self._emit(job_id, "status", {"status": "analyzing"})

            self._agents = self._build_agents(job.llm_config)
            sections = await self._run_agents(job_id, context)

            # Fase 4: Sintetizar el documento final
            self._store.update_status(job_id, JobStatus.SYNTHESIZING)
            await self._emit(job_id, "status", {"status": "synthesizing"})

            repo_full_name = "/".join(job.repo_url.rstrip("/").split("/")[-2:])
            synthesizer = (
                Synthesizer(job.llm_config)
                if job.llm_config
                else self._synthesizer
            )
            try:
                document = await synthesizer.synthesize(sections)
            except Exception as synth_exc:
                _logger.warning(
                    "La síntesis final falló para el job '%s' (repo: %s). "
                    "Se intentará una síntesis de rescate antes de abortar. "
                    "Error: %s",
                    job_id,
                    job.repo_url,
                    synth_exc,
                    exc_info=True,
                )
                try:
                    document = await synthesizer.synthesize_rescue(
                        repo_url=job.repo_url,
                        sections=sections,
                    )
                except Exception as rescue_exc:
                    _logger.error(
                        "La síntesis de rescate también falló para job '%s' "
                        "(repo: %s): %s. Se montará un documento determinista.",
                        job_id,
                        job.repo_url,
                        rescue_exc,
                        exc_info=True,
                    )
                    document = synthesizer.synthesize_deterministic(
                        repo_url=job.repo_url,
                        sections=sections,
                    )
            self._store.set_document(job_id, document)

            # Persistir en Supabase. El fallo es silencioso: no interrumpe la entrega.
            try:
                AnalysesRepo().save(
                    repo_url=job.repo_url,
                    repo_full_name=repo_full_name,
                    document=document,
                    git_sha=git_sha,
                    tags=topics,
                )
            except Exception as supabase_exc:
                _logger.error(
                    "No se pudo persistir el análisis del job '%s' en Supabase: %s",
                    job_id,
                    supabase_exc,
                )

            # Fanout de emails: notificar a todos los suscritos al análisis.
            self._send_email_notifications(job_id, repo_full_name)

            await self._emit(job_id, "complete", {"document": document})

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

    async def _run_agents(
        self, job_id: str, context: RepoContext
    ) -> dict[str, str]:
        """
        Lanza los 7 agentes en paralelo y emite un evento SSE por cada uno.

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

        async def run_single(agent: BaseAgent) -> tuple[str, str]:
            section = await agent.analyze(context)
            await self._emit(job_id, "agent", {
                "agent": agent.agent_name,
                "section": section,
            })
            return agent.agent_name, section

        results = await asyncio.gather(
            *[run_single(a) for a in self._agents],
            return_exceptions=True,
        )

        sections: dict[str, str] = {}
        for agent, result in zip(self._agents, results):
            if isinstance(result, BaseException):
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
                # Incluir marcador para que el sintetizador sepa que falta la sección
                sections[agent.agent_name] = (
                    "_Esta sección no pudo generarse debido a un error interno._"
                )
            else:
                name, section = result
                sections[name] = section

        # Si todas las secciones son placeholders de error, no tiene sentido sintetizar
        valid = [v for v in sections.values() if not v.startswith("_Esta sección")]
        if not valid:
            raise RuntimeError(
                "Todos los agentes fallaron. No es posible generar el documento."
            )

        return sections

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
        self, job_id: str, repo_full_name: str
    ) -> None:
        """
        Envía el email de «análisis listo» a todos los usuarios suscritos al job.

        Consulta la tabla ``repo_notifications`` por ``job_id`` y llama a
        ``send_analysis_ready`` por cada entrada no enviada. Los fallos de
        envío se registran pero no interrumpen el flujo. Tras cada envío
        exitoso marca la fila como ``sent_at = now()``.

        Args:
            job_id: Identificador del job completado.
            repo_full_name: Nombre «owner/repo» para construir la URL de la biblioteca.
        """
        try:
            from app.database.notifications_repo import NotificationsRepo
            from app.services.email_service import send_analysis_ready

            notifications = NotificationsRepo().find_by_job(job_id)
            if not notifications:
                return

            biblioteca_url = _build_biblioteca_url(repo_full_name)
            notifications_repo = NotificationsRepo()

            for notification in notifications:
                success = send_analysis_ready(
                    to_email=notification["email"],
                    repo_full_name=repo_full_name,
                    biblioteca_url=biblioteca_url,
                )
                if success:
                    notifications_repo.mark_sent(notification["id"])

        except Exception as exc:
            _logger.error(
                "Error en el fanout de emails para job '%s': %s",
                job_id,
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
        job = self._store.get(job_id)
        if job and job.queue:
            await job.queue.put({"type": event_type, "data": data})
        elif event_type in ("complete", "analysis_error"):
            _logger.warning(
                "Evento '%s' del job '%s' descartado: la cola SSE no está disponible.",
                event_type,
                job_id,
            )
