"""Punto de entrada y configuración de seguridad de la API de IWTBI."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database.schema import ensure_schema
from app.routes.analyze import get_analyze_router
from app.routes.biblioteca import get_biblioteca_router
from app.routes.health import health_router
from app.routes.preflight import get_preflight_router
from app.routes.stream import get_stream_router
from app.routes.subscriptions import get_subscriptions_router
from app.routes.ticket import get_ticket_router
from app.services.request_meta import get_client_ip
from app.services.llm_profiles import get_llm_profiles
from app.store.job_store import JobStore
from app.store.redis_job_store import RedisJobStore


def _build_store() -> JobStore | RedisJobStore:
    """Elige el backend de jobs según configuración."""
    if settings.job_store_backend == "redis":
        return RedisJobStore()
    return JobStore()


_store = _build_store()

# Limiter global: usa la IP original del cliente pasada por nginx.
# En local, cae al host observado por FastAPI.
limiter = Limiter(
    key_func=get_client_ip,
    storage_uri=settings.rate_limit_storage_uri,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Valida la configuración y el esquema antes de aceptar tráfico."""
    get_llm_profiles()
    ensure_schema()
    yield

app = FastAPI(
    title="IWTBI API",
    description="Analiza repositorios GitHub y genera documentación de reconstrucción accionable para IAs.",
    version="2.1.1",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    lifespan=_lifespan,
)

# Exponer el limiter en el estado de la app para que slowapi lo encuentre
app.state.limiter = limiter

# Middleware de slowapi: intercepta las excepciones de límite de tasa
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Los orígenes permitidos se leen de la variable de entorno CORS_ORIGINS.
# En local: http://localhost:3410,http://localhost:4321
# En producción: http://localhost:3410
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Ticket"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Aplica una base común también a errores y respuestas JSON."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    return response


# Se añade al final para que sea el middleware más externo.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
)

app.include_router(get_preflight_router(limiter), prefix="/api")
app.include_router(get_ticket_router(_store, limiter), prefix="/api")
app.include_router(get_analyze_router(_store, limiter), prefix="/api")
app.include_router(get_stream_router(_store, limiter), prefix="/api")
app.include_router(get_subscriptions_router(limiter), prefix="/api")
app.include_router(get_biblioteca_router(limiter), prefix="/api")
app.include_router(health_router)
