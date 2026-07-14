"""
Endpoint POST /api/analyze — inicia el análisis de un repositorio.

Antes de lanzar el pipeline, comprueba si existe un análisis cacheado en la
biblioteca persistida para esa URL. Si existe y force_new=False, devuelve el caché
directamente. Si el SHA ha cambiado, incluye has_changes=True para que
el frontend muestre el aviso de «posibles cambios».

Si force_new=True o no hay caché, crea el job y lanza el orquestador
con asyncio.create_task() para poder almacenar la referencia de la tarea
y cancelarla si el cliente desconecta sin haber dejado email.

Rate limiting: 10 peticiones por hora por IP. Cada análisis lanza hasta
8 llamadas a LLM en paralelo — proteger este endpoint es crítico para
evitar abuso de costes y denegación de servicio.
"""

import asyncio
import ipaddress
import logging
import secrets
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
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
_INTERNAL_TOKEN_HEADER = "x-internal-token"


def _is_internal_client_ip(client_ip: str) -> bool:
    """Acepta loopback y redes privadas vistas desde el bridge Docker del VPS."""
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip == "localhost"
    return ip.is_loopback or ip.is_private


def _validate_internal_request(request: Request, client_ip: str) -> None:
    """Protege la ruta interna con token dedicado y comprobación de red."""
    expected_token = settings.internal_analyze_token.strip()
    provided_token = request.headers.get(_INTERNAL_TOKEN_HEADER, "").strip()
    if (
        not expected_token
        or not provided_token
        or not secrets.compare_digest(provided_token, expected_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="Token interno inválido o no configurado.",
        )
    if not _is_internal_client_ip(client_ip):
        raise HTTPException(
            status_code=403,
            detail="Esta ruta interna solo está disponible desde la red interna.",
        )


class AnalyzeRequest(BaseModel):
    """Cuerpo de la petición de análisis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=2048)
    force_new: bool = False
    subscribe_updates: bool = False
    # EmailStr valida el formato RFC 5322 en tiempo de deserialización.
    # Requiere pydantic[email] (email-validator) instalado.
    email: Optional[EmailStr] = None


class InternalAnalyzeRequest(AnalyzeRequest):
    """Cuerpo ampliado para benchmarks internos y backfills controlados."""

    provider_override: Optional[
        Literal["openai_compatible", "nan", "zai", "ollama_cloud"]
    ] = None
    model_override: Optional[str] = Field(default=None, max_length=200)
    disable_fallback: bool = False
    profile_label: Optional[str] = Field(default=None, max_length=100)


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
    Busca un análisis cacheado en la biblioteca y compara el SHA actual.

    Args:
        url: URL del repositorio a consultar.
        repo_full_name: Nombre «owner/repo» para consultar el SHA en la API de GitHub.

    Returns:
        AnalyzeResponse cacheada si existe, None si no hay caché.
    """
    repo = AnalysesRepo()
    cached_entry = repo.find_by_url(url)
    if repo.last_error:
        raise HTTPException(
            status_code=503,
            detail="La biblioteca no está disponible temporalmente. Inténtalo de nuevo en unos minutos.",
        )
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


def _register_repo_subscription(
    repo_url: str,
    email: str,
    *,
    last_notified_git_sha: str | None = None,
) -> None:
    """
    Registra o reactiva la suscripción a futuros análisis de un repo.

    Si se conoce ya el SHA actual (por ejemplo, en un cache hit), se siembra
    como `last_notified_git_sha` para evitar que el usuario reciba un correo
    evolutivo inmediato por el mismo análisis ya disponible.
    """
    try:
        from app.database.subscriptions_store import SubscriptionsStore

        SubscriptionsStore().upsert_repo_subscription(
            repo_url=repo_url,
            email=email,
            last_notified_git_sha=last_notified_git_sha,
        )
    except Exception as exc:
        _logger.warning(
            "No se pudo guardar la suscripción futura para repo '%s' y email '%s': %s",
            repo_url,
            email,
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

    async def _start_analysis(
        *,
        request: Request,
        body: AnalyzeRequest,
        require_ticket: bool,
    ) -> AnalyzeResponse:
        if require_ticket:
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
        else:
            client_ip = get_client_ip(request)
            _validate_internal_request(request, client_ip)

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
                if body.email and body.subscribe_updates:
                    cached_entry = AnalysesRepo().find_by_url(url)
                    _register_repo_subscription(
                        url,
                        body.email,
                        last_notified_git_sha=str(cached_entry.get("git_sha") or "")
                        if cached_entry
                        else None,
                    )
                return cached_response

        # Lanzar análisis nuevo
        provider_override = getattr(body, "provider_override", None)
        model_override = getattr(body, "model_override", None)
        disable_fallback = bool(getattr(body, "disable_fallback", False))
        profile_label = getattr(body, "profile_label", None)

        job = store.create(
            url,
            provider_override=provider_override,
            model_override=model_override,
            disable_fallback=disable_fallback,
            profile_label=profile_label,
        )
        await store.emit_event(job.job_id, "status", {"status": "queued"})

        if body.email:
            _register_email_notification(job.job_id, url, body.email)
            if body.subscribe_updates:
                _register_repo_subscription(url, body.email)

        if settings.job_store_backend == "redis":
            store.enqueue(job.job_id)
        else:
            orchestrator = Orchestrator(store=store)
            task = asyncio.create_task(orchestrator.run(job.job_id))
            store.set_task(job.job_id, task)

        return AnalyzeResponse(
            cached=False,
            job_id=job.job_id,
            stream_url=f"/api/stream/{job.job_id}",
        )

    @router.post(
        "/analyze",
        responses={
            403: {"description": "Ticket inválido o ausente"},
            422: {"description": "URL de GitHub no válida"},
        },
    )
    @limiter.limit(settings.analyze_rate_limit)
    async def analyze(request: Request, body: AnalyzeRequest) -> AnalyzeResponse:
        """Ruta pública: requiere ticket y aplica límite de tasa."""
        return await _start_analysis(request=request, body=body, require_ticket=True)

    @router.post("/analyze/internal")
    async def analyze_internal(
        request: Request,
        body: InternalAnalyzeRequest,
    ) -> AnalyzeResponse:
        """Ruta interna para backfills desde loopback sin rate limit público."""
        return await _start_analysis(request=request, body=body, require_ticket=False)

    return router
