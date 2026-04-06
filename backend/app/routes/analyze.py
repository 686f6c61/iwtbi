"""
Endpoint POST /api/analyze — inicia el análisis de un repositorio.

Antes de lanzar el pipeline, comprueba si existe un análisis cacheado en
Supabase para esa URL. Si existe y force_new=False, devuelve el caché
directamente. Si el SHA ha cambiado, incluye has_changes=True para que
el frontend muestre el aviso de «posibles cambios».

Si force_new=True o no hay caché, crea el job y lanza el orquestador
con asyncio.create_task() para poder almacenar la referencia de la tarea
y cancelarla si el cliente desconecta sin haber dejado email.

Rate limiting: 5 peticiones por hora por IP. Cada análisis lanza hasta
8 llamadas a LLM en paralelo — proteger este endpoint es crítico para
evitar abuso de costes y denegación de servicio.
"""

import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from slowapi import Limiter

from app.config import settings
from app.database.analyses_repo import AnalysesRepo
from app.services.request_meta import get_client_ip, get_user_agent
from app.services.git_cloner import validate_github_url
from app.services.github_api import get_head_sha
from app.services.orchestrator import Orchestrator
from app.store.job_store import JobStore

_logger = logging.getLogger(__name__)
_INVALID_TICKET_DETAIL = (
    "No se pudo validar la solicitud. Recarga la página y vuelve a intentarlo."
)


class AnalyzeRequest(BaseModel):
    """Cuerpo de la petición de análisis."""

    url: str
    force_new: bool = False
    # EmailStr valida el formato RFC 5322 en tiempo de deserialización.
    # Requiere pydantic[email] (email-validator) instalado.
    email: Optional[EmailStr] = None


class AnalyzeResponse(BaseModel):
    """
    Respuesta del endpoint de análisis.

    Dos formas posibles:
    - Cache hit: cached=True, has_changes, document, repo_full_name, updated_at
    - Nuevo análisis: cached=False, job_id, stream_url
    """

    cached: bool
    # --- Campos de cache hit ---
    has_changes: Optional[bool] = None
    document: Optional[str] = None
    repo_full_name: Optional[str] = None
    updated_at: Optional[str] = None
    # --- Campos de nuevo análisis ---
    job_id: Optional[str] = None
    stream_url: Optional[str] = None


def _extract_full_name(repo_url: str) -> str:
    """
    Extrae el nombre «owner/repo» de la URL del repositorio.

    Args:
        repo_url: URL en formato https://github.com/owner/repo

    Returns:
        Nombre en formato «owner/repo».
    """
    path = urlparse(repo_url).path.strip("/")
    return path


async def _check_cache(
    url: str, repo_full_name: str
) -> Optional[AnalyzeResponse]:
    """
    Busca un análisis cacheado en Supabase y compara el SHA actual.

    Args:
        url: URL del repositorio a consultar.
        repo_full_name: Nombre «owner/repo» para consultar el SHA en la API de GitHub.

    Returns:
        AnalyzeResponse cacheada si existe, None si no hay caché.
    """
    cached_entry = AnalysesRepo().find_by_url(url)
    if not cached_entry:
        return None

    current_sha = await get_head_sha(repo_full_name)
    has_changes = current_sha != cached_entry["git_sha"] if current_sha else False
    return AnalyzeResponse(
        cached=True,
        has_changes=has_changes,
        document=cached_entry["document"],
        repo_full_name=cached_entry["repo_full_name"],
        updated_at=str(cached_entry["updated_at"]),
    )


def _register_email_notification(job_id: str, repo_url: str, email: str) -> None:
    """
    Registra el email del usuario en repo_notifications para notificarle al terminar.

    El fallo es no crítico: si la inserción falla, el análisis continúa sin notificación.

    Args:
        job_id: Identificador del job en curso.
        repo_url: URL del repositorio analizado.
        email: Dirección de correo electrónico validada por Pydantic EmailStr.
    """
    try:
        from app.database.notifications_repo import NotificationsRepo
        NotificationsRepo().save(job_id=job_id, repo_url=repo_url, email=email)
    except Exception as exc:
        _logger.warning(
            "No se pudo guardar el email para el job '%s': %s",
            job_id,
            exc,
        )


def get_analyze_router(store: JobStore, limiter: Limiter) -> APIRouter:
    """
    Construye el router de análisis con el store y el limiter inyectados.

    El patrón de inyección del store (en lugar de importarlo como singleton)
    facilita los tests: cada test puede pasar su propio store aislado.

    Args:
        store: Instancia compartida del job store.
        limiter: Instancia de slowapi.Limiter configurada en main.py.

    Returns:
        Router FastAPI con el endpoint POST /analyze registrado.
    """
    router = APIRouter()

    @router.post(
        "/analyze",
        responses={
            403: {"description": "Ticket inválido o ausente"},
            422: {"description": "URL de GitHub no válida"},
        },
    )
    @limiter.limit(settings.analyze_rate_limit)
    async def analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
        """
        Valida el ticket, la URL, comprueba caché y lanza el análisis si es necesario.

        Flujo:
        1. Validar y consumir el ticket X-Ticket.
        2. Validar la URL de GitHub.
        3. Si force_new=False, buscar en Supabase.
        4. Si hay caché, consultar el SHA actual en GitHub API y devolver la
           respuesta cacheada (con has_changes si el SHA difiere).
        5. Si no hay caché o force_new=True, crear el job, almacenar el email
           en repo_notifications si se proporcionó, lanzar el pipeline con
           asyncio.create_task() y devolver job_id + stream_url.

        Args:
            request: Request de FastAPI (necesario para slowapi).
            body: Petición con url, force_new opcional y email opcional.

        Returns:
            AnalyzeResponse con los campos apropiados para cache hit o nuevo análisis.

        Raises:
            HTTPException 403: Si falta el ticket, ya fue usado o no pertenece al cliente.
            HTTPException 422: Si la URL no es un repositorio GitHub válido.
            HTTPException 429: Si se supera el límite configurado por IP.
        """
        ticket = request.headers.get("x-ticket", "").strip()
        client_ip = get_client_ip(request)
        user_agent = get_user_agent(request)

        if not ticket or not store.consume_ticket(
            ticket,
            client_ip=client_ip,
            user_agent=user_agent,
        ):
            _logger.warning(
                "Ticket inválido para POST /api/analyze desde ip=%s ua=%r",
                client_ip,
                user_agent[:120],
            )
            raise HTTPException(status_code=403, detail=_INVALID_TICKET_DETAIL)

        url = body.url.rstrip("/")
        if not validate_github_url(url):
            raise HTTPException(
                status_code=422,
                detail=(
                    "La URL debe ser un repositorio GitHub público válido: "
                    "https://github.com/usuario/repositorio"
                ),
            )

        repo_full_name = _extract_full_name(url)

        # Comprobar caché si no se fuerza un análisis nuevo
        if not body.force_new:
            cached_response = await _check_cache(url, repo_full_name)
            if cached_response:
                return cached_response

        # Lanzar análisis nuevo
        job = store.create(url)
        orchestrator = Orchestrator(store=store)

        # asyncio.create_task() en lugar de BackgroundTasks para obtener
        # la referencia de la tarea y poder cancelarla si el cliente desconecta
        task = asyncio.create_task(orchestrator.run(job.job_id))
        store.set_task(job.job_id, task)

        if body.email:
            _register_email_notification(job.job_id, url, body.email)

        return AnalyzeResponse(
            cached=False,
            job_id=job.job_id,
            stream_url=f"/api/stream/{job.job_id}",
        )

    return router
