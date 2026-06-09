"""Tests del helper de invocación LLM compartido."""

import asyncio

import pytest

from app.agents.base import invoke_llm, validate_llm_settings


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _SlowThenFastLLM:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(0.02)
        return _FakeResponse("ok")


@pytest.mark.asyncio
async def test_invoke_llm_retries_when_provider_returns_empty_content(monkeypatch):
    monkeypatch.setattr("app.agents.base._llm_semaphore", None)
    llm = _FakeLLM([_FakeResponse(""), _FakeResponse("ok")])

    response = await invoke_llm(llm, ["hola"])

    assert response.content == "ok"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_invoke_llm_fails_fast_when_provider_times_out(monkeypatch):
    monkeypatch.setattr("app.agents.base._llm_semaphore", None)
    monkeypatch.setattr("app.agents.base.settings.llm_request_timeout_seconds", 0.01)
    llm = _SlowThenFastLLM()

    with pytest.raises(RuntimeError, match="llm request timed out"):
        await invoke_llm(llm, ["hola"])

    assert llm.calls == 1


def test_validate_llm_settings_rejects_missing_zai_key(monkeypatch):
    monkeypatch.setattr("app.agents.base.settings.provider", "zai")
    monkeypatch.setattr("app.agents.base.settings.zai_api_key", "your_z_ai_key_here")
    monkeypatch.setattr(
        "app.agents.base.settings.zai_base_url",
        "https://api.z.ai/api/paas/v4/",
    )

    with pytest.raises(ValueError, match="API key real"):
        validate_llm_settings()


def test_validate_llm_settings_rejects_legacy_zai_base_url(monkeypatch):
    monkeypatch.setattr("app.agents.base.settings.provider", "zai")
    monkeypatch.setattr("app.agents.base.settings.zai_api_key", "test-key")
    monkeypatch.setattr("app.agents.base.settings.zai_base_url", "https://api.z.ai/v1")

    with pytest.raises(ValueError, match="endpoint antiguo"):
        validate_llm_settings()
