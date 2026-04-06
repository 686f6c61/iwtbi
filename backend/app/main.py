"""
Punto de entrada de la aplicación FastAPI de IWTBI.

Crea la instancia de FastAPI, configura CORS, registra las rutas y
expone el job store como estado compartido del proceso. El store es
una única instancia en memoria que comparten todos los requests.

Rate limiting implementado con slowapi (basado en limits):
- POST /api/preflight: 12 req/min por IP — clonado temporal + medición sin LLM
- GET /api/ticket: 30 req/min por IP — emisión barata de tickets efímeros
- POST /api/analyze: 5 req/h por IP — lanza un pipeline costoso (LLM x8)
- GET /api/stream/{job_id}: 20 req/min por IP — SSE de larga duración
- GET /api/biblioteca*: 60 req/min por IP — lectura simple de BD
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.routes.analyze import get_analyze_router
from app.routes.biblioteca import biblioteca_router
from app.routes.preflight import get_preflight_router
from app.routes.stream import get_stream_router
from app.routes.ticket import get_ticket_router
from app.services.request_meta import get_client_ip
from app.store.job_store import JobStore

# Instancia singleton del store: persiste durante toda la vida del proceso.
# En v1 no hay base de datos; los jobs son efímeros por diseño.
_store = JobStore()

# Limiter global: usa la IP original del cliente pasada por nginx.
# En local, cae al host observado por FastAPI.
limiter = Limiter(key_func=get_client_ip)

app = FastAPI(
    title="IWTBI API",
    description="Analiza repositorios GitHub y genera documentación de reconstrucción accionable para IAs.",
    version="1.0.0",
)

# Exponer el limiter en el estado de la app para que slowapi lo encuentre
app.state.limiter = limiter

# Middleware de slowapi: intercepta las excepciones de límite de tasa
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Los orígenes permitidos se leen de la variable de entorno CORS_ORIGINS.
# En local: http://localhost:3410,http://localhost:4321
# En producción: https://app.example.com
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Ticket"],
)

app.include_router(get_preflight_router(limiter), prefix="/api")
app.include_router(get_ticket_router(_store, limiter), prefix="/api")
app.include_router(get_analyze_router(_store, limiter), prefix="/api")
app.include_router(get_stream_router(_store, limiter), prefix="/api")
app.include_router(biblioteca_router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, bool | str]:
    """Endpoint de salud para Docker healthcheck y el proxy inverso."""
    return {
        "status": "ok",
        "email_notifications_enabled": bool(settings.resend_api_key.strip()),
    }
