"""
Almacén de jobs y tickets efímeros en memoria.

En v1 no hay persistencia: los jobs y tickets viven mientras el proceso
esté activo. Si se añade persistencia en el futuro, esta interfaz
permanece estable y solo cambia la implementación interna.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from app.models.job import Job, JobStatus, LlmConfig


@dataclass(slots=True)
class _TicketRecord:
    """Asocia un ticket temporal con su huella mínima de cliente."""

    created_at: float
    client_ip: str
    user_agent: str


class JobStore:
    """
    Repositorio en memoria para los jobs de análisis activos.

    Thread-safety: asyncio es single-threaded por naturaleza;
    no se necesitan locks adicionales en este contexto.
    """

    _TICKET_TTL_SECONDS = 300

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tickets: dict[str, _TicketRecord] = {}

    def create(self, repo_url: str, llm_config: LlmConfig | None = None) -> Job:
        """
        Crea un nuevo job y lo registra en el store.

        Args:
            repo_url: URL del repositorio a analizar.

        Returns:
            El job creado con su cola SSE inicializada.
        """
        job = Job(repo_url=repo_url, llm_config=llm_config)
        job.new_queue()
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        """Devuelve el job por su ID o None si no existe."""
        return self._jobs.get(job_id)

    def update_status(self, job_id: str, status: JobStatus) -> None:
        """Actualiza el estado de un job existente."""
        if job := self._jobs.get(job_id):
            job.status = status

    def set_document(self, job_id: str, document: str) -> None:
        """Persiste el documento final y marca el job como COMPLETE."""
        if job := self._jobs.get(job_id):
            job.document = document
            job.status = JobStatus.COMPLETE

    def set_error(self, job_id: str, error: str) -> None:
        """Registra el error y marca el job como ERROR."""
        if job := self._jobs.get(job_id):
            job.error = error
            job.status = JobStatus.ERROR

    def set_task(self, job_id: str, task: asyncio.Task) -> None:
        """
        Almacena la referencia de la tarea asyncio del orquestador.

        La referencia permite cancelar el pipeline desde el endpoint SSE
        si el cliente desconecta sin haber dejado un email de notificación.

        Args:
            job_id: Identificador del job.
            task: Tarea asyncio retornada por asyncio.create_task().
        """
        if job := self._jobs.get(job_id):
            job.orchestrator_task = task

    def remove(self, job_id: str) -> None:
        """
        Elimina un job del store para liberar memoria.

        Seguro de llamar aunque el job no exista. El orquestador lo
        invoca tras un retardo de retención para evitar fuga de memoria.

        Args:
            job_id: Identificador del job a eliminar.
        """
        self._jobs.pop(job_id, None)

    def issue_ticket(self, *, client_ip: str, user_agent: str) -> str:
        """
        Emite un ticket UUID v4 de un solo uso vinculado al cliente.

        Args:
            client_ip: IP observada por el backend.
            user_agent: User-Agent del cliente emisor.

        Returns:
            Ticket temporal que el frontend enviará en X-Ticket.
        """
        self._cleanup_expired_tickets()
        ticket = str(uuid.uuid4())
        self._tickets[ticket] = _TicketRecord(
            created_at=time.time(),
            client_ip=client_ip,
            user_agent=user_agent.strip(),
        )
        return ticket

    def consume_ticket(
        self, ticket: str, *, client_ip: str, user_agent: str
    ) -> bool:
        """
        Valida y consume un ticket de un solo uso.

        Un ticket solo es válido si existe, no ha expirado y lo usa el mismo
        cliente que lo solicitó originalmente.
        """
        self._cleanup_expired_tickets()
        record = self._tickets.get(ticket)
        if record is None:
            return False
        if record.client_ip != client_ip:
            return False
        if record.user_agent != user_agent.strip():
            return False

        del self._tickets[ticket]
        return True

    def _cleanup_expired_tickets(self) -> None:
        """Elimina tickets vencidos para evitar acumulación en memoria."""
        now = time.time()
        expired = [
            ticket
            for ticket, record in self._tickets.items()
            if now - record.created_at > self._TICKET_TTL_SECONDS
        ]
        for ticket in expired:
            del self._tickets[ticket]
