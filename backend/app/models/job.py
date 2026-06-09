"""
Modelos del ciclo de vida de un job de análisis.

Un Job representa una solicitud de análisis de repositorio desde su
creación hasta la entrega del documento final. AgentEvent transporta
los resultados parciales de cada agente vía SSE.
"""

import asyncio
import uuid
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


LlmProvider = Literal[
    "zai",
    "openai",
    "openrouter",
    "anthropic",
    "ollama_local",
    "ollama_cloud",
]


class LlmConfig(BaseModel):
    """Configuración LLM efímera para un análisis concreto."""

    provider: LlmProvider
    model: str
    api_key: Optional[str] = Field(default=None, exclude=True)
    base_url: Optional[str] = None


class JobStatus(str, Enum):
    """Estado del job de análisis."""

    PENDING = "pending"
    CLONING = "cloning"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    ERROR = "error"


class AgentEvent(BaseModel):
    """Evento SSE emitido cuando un agente completa su sección."""

    agent: str
    section: str


class Job(BaseModel):
    """
    Representa un job de análisis en curso o completado.

    El campo ``queue`` no es serializable por Pydantic; se accede
    directamente para enviar eventos SSE al frontend.
    """

    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    repo_url: str
    llm_config: Optional[LlmConfig] = Field(default=None, exclude=True)
    status: JobStatus = JobStatus.PENDING
    document: Optional[str] = None
    error: Optional[str] = None

    # Cola de eventos SSE: excluida de serialización JSON
    queue: Optional[asyncio.Queue] = Field(default=None, exclude=True)

    # Tarea asyncio del orquestador: permite cancelarla si el cliente desconecta
    # sin haber dejado email. Se excluye de serialización.
    orchestrator_task: Optional[asyncio.Task] = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def new_queue(self) -> asyncio.Queue:
        """Crea e instala la cola de eventos SSE para este job."""
        self.queue = asyncio.Queue()
        return self.queue
