from starlette.requests import Request

from app.config import settings
from app.services.request_meta import get_client_ip


def _request_with_headers(
    headers: list[tuple[bytes, bytes]],
    *,
    client_host: str = "127.0.0.1",
) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_get_client_ip_ignores_cf_connecting_ip_by_default() -> None:
    request = _request_with_headers(
        [
            (b"cf-connecting-ip", b"203.0.113.10"),
            (b"x-real-ip", b"198.51.100.7"),
            (b"x-forwarded-for", b"198.51.100.8"),
        ]
    )

    assert get_client_ip(request) == "198.51.100.7"


def test_get_client_ip_prefers_cf_connecting_ip_when_cloudflare_trust_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "trust_cloudflare_client_headers", True)
    request = _request_with_headers(
        [
            (b"cf-connecting-ip", b"203.0.113.10"),
            (b"x-real-ip", b"198.51.100.7"),
            (b"x-forwarded-for", b"198.51.100.8"),
        ]
    )

    assert get_client_ip(request) == "203.0.113.10"


def test_get_client_ip_ignores_spoofed_proxy_headers_from_untrusted_peer() -> None:
    request = _request_with_headers(
        [
            (b"cf-connecting-ip", b"10.0.0.5"),
            (b"x-real-ip", b"127.0.0.1"),
            (b"x-forwarded-for", b"172.19.0.1"),
        ],
        client_host="203.0.113.20",
    )

    assert get_client_ip(request) == "203.0.113.20"


def test_get_client_ip_uses_true_client_ip_before_proxy_headers_when_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "trust_cloudflare_client_headers", True)
    request = _request_with_headers(
        [
            (b"true-client-ip", b"203.0.113.11"),
            (b"x-real-ip", b"198.51.100.9"),
        ]
    )

    assert get_client_ip(request) == "203.0.113.11"


def test_get_client_ip_falls_back_to_client_host_without_proxy_headers() -> None:
    request = _request_with_headers([], client_host="192.0.2.25")

    assert get_client_ip(request) == "192.0.2.25"
