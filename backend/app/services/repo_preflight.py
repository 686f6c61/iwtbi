"""
Preflight de repositorios antes de lanzar el análisis LLM.

La preflight clona el repo de forma temporal, mide el contexto útil con las
mismas reglas que usa el pipeline real y devuelve una decisión explícita:

- ``normal``: el repo cabe dentro del presupuesto previsto
- ``optimized``: conviene priorizar archivos clave
- ``too_large``: el repo supera el rango seguro para una sola pasada
"""

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from app.config import settings
from app.services.file_reader import ContextEstimate, FileReader
from app.services.git_cloner import GitCloner, RepoSizeLimitExceeded

PreflightMode = Literal["normal", "optimized", "too_large"]
PreflightReason = Literal[
    "fits_context",
    "prioritized_context",
    "context_budget_exceeded",
    "file_count_limit",
    "repo_size_limit",
]


@dataclass(frozen=True, slots=True)
class RepoPreflightResult:
    """Resultado estructurado de la premedición del repositorio."""

    mode: PreflightMode
    reason: PreflightReason
    candidate_files: int
    selected_files: int
    total_candidate_chars: int
    selected_chars: int
    oversized_files: int
    budget_truncated_files: int


class RepoPreflightService:
    """
    Calcula si un repo entra en el modo normal, optimizado o demasiado grande.
    """

    _TOO_LARGE_CONTEXT_MULTIPLIER = 24
    _SPARSE_CONTEXT_FILE_FLOOR = 8
    _SPARSE_HUGE_FILE_FLOOR = 12
    _SPARSE_HUGE_CONTEXT_MULTIPLIER = 18

    def __init__(self) -> None:
        self._cloner = GitCloner()
        self._reader = FileReader(
            max_files=settings.max_files,
            file_size_limit_kb=settings.file_size_limit_kb,
            max_context_chars=settings.max_context_chars,
        )

    async def inspect(self, repo_url: str) -> RepoPreflightResult:
        """
        Clona temporalmente el repo, mide el contexto y lo clasifica.
        """
        job_id = f"preflight-{uuid4()}"

        try:
            clone_path, _ = await self._cloner.clone(repo_url, job_id)
            estimate = self._reader.estimate(clone_path)
            mode, reason = self._decide_mode(estimate)
            return RepoPreflightResult(
                mode=mode,
                reason=reason,
                candidate_files=estimate.candidate_files,
                selected_files=estimate.selected_files,
                total_candidate_chars=estimate.total_candidate_chars,
                selected_chars=estimate.selected_chars,
                oversized_files=estimate.oversized_files,
                budget_truncated_files=estimate.budget_truncated_files,
            )
        except RepoSizeLimitExceeded:
            return RepoPreflightResult(
                mode="too_large",
                reason="repo_size_limit",
                candidate_files=0,
                selected_files=0,
                total_candidate_chars=0,
                selected_chars=0,
                oversized_files=0,
                budget_truncated_files=0,
            )
        finally:
            self._cloner.cleanup(job_id)

    def _decide_mode(
        self, estimate: ContextEstimate
    ) -> tuple[PreflightMode, PreflightReason]:
        """
        Decide el modo de análisis a partir del contexto útil medido.
        """
        if estimate.candidate_files == 0 or estimate.total_candidate_chars == 0:
            return "normal", "fits_context"

        if estimate.candidate_files > settings.preflight_max_candidate_files:
            return "too_large", "file_count_limit"

        if estimate.total_candidate_chars <= settings.max_context_chars:
            return "normal", "fits_context"

        if (
            estimate.selected_files < self._SPARSE_CONTEXT_FILE_FLOOR
            or estimate.total_candidate_chars
            > settings.max_context_chars * self._TOO_LARGE_CONTEXT_MULTIPLIER
            or (
                estimate.selected_files < self._SPARSE_HUGE_FILE_FLOOR
                and estimate.total_candidate_chars
                > settings.max_context_chars * self._SPARSE_HUGE_CONTEXT_MULTIPLIER
            )
        ):
            return "too_large", "context_budget_exceeded"

        return "optimized", "prioritized_context"
