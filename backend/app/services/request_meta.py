"""Helpers para derivar metadatos del cliente desde cabeceras de proxy."""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    Obtiene la IP original del cliente.

    En producción el backend vive detrás de un único nginx que fija X-Real-IP.
    Se prioriza esa cabecera para no confiar en un X-Forwarded-For inyectado
    por el cliente. En desarrollo, si no hay proxy, cae al host observado
    por FastAPI.
    """
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


def get_user_agent(request: Request) -> str:
    """Devuelve el User-Agent del cliente o cadena vacía si falta."""
    return request.headers.get("user-agent", "").strip()
