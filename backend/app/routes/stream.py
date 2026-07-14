"""
Endpoint GET /api/stream/<job_id> — streaming SSE de progreso del análisis.

Mantiene la conexión HTTP abierta y envía eventos conforme el orquestador
los encola. Cierra la conexión al recibir el evento 'complete' o
'analysis_error'. Si el cliente se desconecta, el pipeline continúa:
el análisis debe terminar y persistirse igualmente en biblioteca.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter

from app.store.job_store import JobStore

_logger = logging.getLogger(__name__)

# Segundos entre pings para mantener la conexión HTTP activa.
# Sin esto, los proxies y CDNs pueden cerrar la conexión por inactividad.
_SSE_PING_INTERVAL = 15

# Tipos de evento que indican el fin del análisis
_TERMINAL_EVENTS = frozenset({"complete", "analysis_error"})


async def _read_next_sse_frame(store: JobStore, job_id: str) -> tuple[str, bool]:
    """
    Espera el siguiente evento de la cola y lo formatea como frame SSE.

    Devuelve el frame SSE y un flag que indica si ese evento es terminal.
    Si la cola no produce eventos en el intervalo, devuelve un ping SSE estándar.

    Args:
        queue: Cola asyncio del job.

    Returns:
        Tupla (frame, is_terminal).
    """
    try:
        event = await store.read_next_event(job_id, _SSE_PING_INTERVAL)
        if event is None:
            return ": ping\n\n", False
        payload = json.dumps(event["data"], ensure_ascii=False)
        frame = f"event: {event['type']}\ndata: {payload}\n\n"
        return frame, event["type"] in _TERMINAL_EVENTS
    except TimeoutError:
        # Ping SSE estándar: mantiene la conexión viva sin datos reales
        return ": ping\n\n", False


async def _sse_generator(store: JobStore, job_id: str):
    """
    Generador asíncrono que emite frames SSE hasta que el análisis termina.

    Gestiona la desconexión del cliente vía CancelledError: drena la cola
    pendiente del stream, pero no cancela el pipeline.

    Args:
        queue: Cola asyncio del job.
        store: Store de jobs (para cancelar el pipeline si el cliente desconecta).
        job_id: Identificador del job en curso.

    Yields:
        Frames SSE en formato texto.
    """
    try:
        while True:
            frame, is_terminal = await _read_next_sse_frame(store, job_id)
            yield frame
            if is_terminal:
                break
    except GeneratorExit:
        _logger.info(
            "Cliente desconectado del stream del job '%s'. Limpiando eventos.",
            job_id,
        )
        store.drain_events(job_id)
        raise
    except asyncio.CancelledError:
        _logger.info(
            "Cliente desconectado del stream del job '%s'. Drenando cola.",
            job_id,
        )
        store.drain_events(job_id)
        raise  # propagar para que FastAPI gestione la limpieza HTTP


def get_stream_router(store: JobStore, limiter: Limiter) -> APIRouter:
    """
    Construye el router de streaming con el store y el limiter inyectados.

    Args:
        store: Instancia compartida del job store.
        limiter: Instancia de slowapi.Limiter configurada en main.py.

    Returns:
        Router FastAPI con el endpoint GET /stream/<job_id> registrado.
    """
    router = APIRouter()

    @router.get(
        "/stream/{job_id}",
        responses={404: {"description": "Job no encontrado en el store"}},
    )
    @limiter.limit("20/minute")
    async def stream(request: Request, job_id: str) -> StreamingResponse:
        """
        Abre una conexión SSE y transmite los eventos del job en tiempo real.

        Los eventos siguen el formato estándar SSE:
            event: <tipo>\\n
            data: <json>\\n\\n

        Cuando el cliente desconecta antes del final, FastAPI cancela
        la corutina del generador vía asyncio.CancelledError. En ese
        caso se drena la cola para que el orquestador no quede bloqueado
        esperando que alguien consuma los eventos.

        Args:
            job_id: Identificador del job a observar.

        Returns:
            StreamingResponse con Content-Type text/event-stream.

        Raises:
            HTTPException 404: Si el job_id no existe en el store.
        """
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job no encontrado")

        return StreamingResponse(
            _sse_generator(store, job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # Desactiva el buffer de nginx para que los eventos
                # lleguen al cliente inmediatamente (sin acumularse)
                "X-Accel-Buffering": "no",
            },
        )

    return router
