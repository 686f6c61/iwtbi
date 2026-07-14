"""Tests del servicio de GitHub API para obtener el SHA del HEAD."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.github_api import get_head_sha


@pytest.mark.asyncio
async def test_get_head_sha_returns_sha_on_success():
    """get_head_sha devuelve el SHA cuando la API responde correctamente."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = "abc1234567890abcdef1234567890abcdef123456"  # pragma: allowlist secret

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.services.github_api.httpx.AsyncClient", return_value=mock_client):
        result = await get_head_sha("user/repo")

    assert result == "abc1234567890abcdef1234567890abcdef123456"  # pragma: allowlist secret


@pytest.mark.asyncio
async def test_get_head_sha_returns_none_on_network_error():
    """get_head_sha devuelve None si la petición falla."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.services.github_api.httpx.AsyncClient", return_value=mock_client):
        result = await get_head_sha("user/repo")

    assert result is None


@pytest.mark.asyncio
async def test_get_head_sha_returns_none_on_http_error():
    """get_head_sha devuelve None en repos privados o rate limit."""
    from httpx import HTTPStatusError, Request, Response

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = HTTPStatusError(
        "403", request=MagicMock(spec=Request), response=MagicMock(spec=Response)
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.services.github_api.httpx.AsyncClient", return_value=mock_client):
        result = await get_head_sha("user/private-repo")

    assert result is None
