"""Helpers para derivar metadatos del cliente desde cabeceras de proxy."""

import ipaddress
from typing import TypeAlias

from fastapi import Request

from app.config import settings

IpNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_ip(value: str) -> str | None:
    """Devuelve una IP normalizada si el valor es válido."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _trusted_proxy_networks() -> list[IpNetwork]:
    networks: list[IpNetwork] = []
    for raw in settings.trusted_proxy_cidrs.split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted_proxy(peer_ip: str) -> bool:
    parsed = _parse_ip(peer_ip)
    if parsed is None:
        return peer_ip == "localhost"
    ip = ipaddress.ip_address(parsed)
    return any(ip in network for network in _trusted_proxy_networks())


def _first_forwarded_ip(header_value: str) -> str | None:
    for candidate in header_value.split(","):
        parsed = _parse_ip(candidate)
        if parsed:
            return parsed
    return None


def get_client_ip(request: Request) -> str:
    """
    Obtiene la IP original del cliente.

    Las cabeceras de proxy solo se aceptan si el peer inmediato pertenece a
    ``TRUSTED_PROXY_CIDRS``. Si el backend recibe tráfico directo, se usa la
    IP del socket y se ignoran cabeceras spoofeables.

    ``CF-Connecting-IP`` y ``True-Client-IP`` solo se aceptan cuando
    ``TRUST_CLOUDFLARE_CLIENT_HEADERS`` está activo. Con DNS directo al VPS,
    esas cabeceras son triviales de falsear aunque el peer observado sea el
    proxy interno.

    Prioridad cuando el peer es confiable:
    1. ``CF-Connecting-IP`` / ``True-Client-IP`` cuando el modo Cloudflare está activo.
    2. ``X-Real-IP`` si el proxy interno ya resolvió la IP real.
    3. ``X-Forwarded-For`` como fallback best-effort.
    4. ``request.client.host`` en desarrollo o sin proxy.
    """
    peer_ip = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer_ip):
        return peer_ip

    if settings.trust_cloudflare_client_headers:
        cloudflare_ip = _parse_ip(request.headers.get("cf-connecting-ip", ""))
        if cloudflare_ip:
            return cloudflare_ip

        true_client_ip = _parse_ip(request.headers.get("true-client-ip", ""))
        if true_client_ip:
            return true_client_ip

    real_ip = _parse_ip(request.headers.get("x-real-ip", ""))
    if real_ip:
        return real_ip

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        parsed = _first_forwarded_ip(forwarded_for)
        if parsed:
            return parsed

    return peer_ip


def get_user_agent(request: Request) -> str:
    """Devuelve el User-Agent del cliente o cadena vacía si falta."""
    return request.headers.get("user-agent", "").strip()
