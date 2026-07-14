"""Worker dedicado que consume jobs desde Redis y ejecuta el pipeline."""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.database.schema import ensure_schema
from app.services.orchestrator import Orchestrator
from app.store.job_store import JobStore
from app.store.redis_job_store import RedisJobStore

_logger = logging.getLogger(__name__)


def _build_store() -> JobStore | RedisJobStore:
    if settings.job_store_backend == "redis":
        return RedisJobStore()
    return JobStore()


async def _run_worker() -> None:
    ensure_schema()
    store = _build_store()
    if getattr(store, "backend_kind", "memory") != "redis":
        raise RuntimeError("El worker dedicado requiere JOB_STORE_BACKEND=redis")

    orchestrator = Orchestrator(store=store)
    _logger.info("Worker IWTBI escuchando cola Redis")

    while True:
        job_id = await asyncio.to_thread(store.pop_next_job, 5)
        if not job_id:
            continue

        job = store.get(job_id)
        if job is None:
            continue

        _logger.info("Procesando job '%s' para repo %s", job_id, job.repo_url)
        try:
            await orchestrator.run(job_id)
        except asyncio.CancelledError:
            _logger.info("Job '%s' cancelado antes de terminar.", job_id)
        except Exception as exc:
            _logger.exception(
                "El worker encontró un error inesperado en '%s': %s",
                job_id,
                exc,
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
