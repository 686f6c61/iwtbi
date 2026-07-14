"""Tests del helper de invocación LLM compartido."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agents.base import (
    BaseAgent,
    build_llm,
    invoke_llm,
    provider_label,
    resolve_backup_provider,
    resolve_backup_providers,
)
from app.models.repo_context import RepoContext


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


class _TestAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return "test"

    @property
    def agent_name(self) -> str:
        return "test-agent"


def test_build_llm_supports_generic_openai_compatible(monkeypatch):
    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.agents.base.ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(  # pragma: allowlist secret
        "app.agents.base.settings.openai_compatible_api_key", "local-key"
    )
    monkeypatch.setattr(
        "app.agents.base.settings.openai_compatible_base_url",
        "http://llm.internal/v1",
    )
    monkeypatch.setattr("app.agents.base.settings.openai_compatible_model", "my-model")

    llm = build_llm(provider="openai_compatible", max_tokens=2048)

    assert isinstance(llm, _FakeChatOpenAI)
    assert captured["api_key"] == "local-key"  # pragma: allowlist secret
    assert captured["base_url"] == "http://llm.internal/v1"
    assert captured["model"] == "my-model"
    assert captured["max_tokens"] == 2048
    assert provider_label("openai_compatible") == "OpenAI-compatible"


def test_build_llm_uses_server_resolved_profile_overrides(monkeypatch):
    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.agents.base.ChatOpenAI", _FakeChatOpenAI)

    build_llm(
        provider="openai_compatible",
        model_override="profile-model",
        api_key_override="profile-key",  # pragma: allowlist secret
        base_url_override="https://profile.example.test/v1",
    )

    assert captured["model"] == "profile-model"
    assert captured["api_key"] == "profile-key"  # pragma: allowlist secret
    assert captured["base_url"] == "https://profile.example.test/v1"


def test_build_llm_supports_nan_openai_compatible(monkeypatch):
    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.agents.base.ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(  # pragma: allowlist secret
        "app.agents.base.settings.nan_api_key", "nan-key"
    )
    monkeypatch.setattr(
        "app.agents.base.settings.nan_base_url",
        "https://api.nan.builders/v1",
    )
    monkeypatch.setattr("app.agents.base.settings.nan_model", "qwen3.6")

    llm = build_llm(
        provider="nan",
        temperature=0.2,
        max_tokens=1234,
        request_timeout_seconds=9,
    )

    assert isinstance(llm, _FakeChatOpenAI)
    assert captured["api_key"] == "nan-key"  # pragma: allowlist secret
    assert captured["base_url"] == "https://api.nan.builders/v1"
    assert captured["model"] == "qwen3.6"
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 1234
    assert captured["timeout"] == 9
    assert captured["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_resolve_backup_provider_prefers_ollama_when_nan_primary(monkeypatch):
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_api_key", "ollama-key")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_model", "deepseek-v4-pro:cloud")
    monkeypatch.setattr(
        "app.agents.base.settings.ollama_cloud_fallback_models",
        "kimi-k2.7-code:cloud",
    )
    monkeypatch.setattr("app.agents.base.settings.zai_api_key", "zai-key")
    monkeypatch.setattr("app.agents.base.settings.zai_model", "glm-5.2")

    assert resolve_backup_providers("nan") == [
        ("ollama_cloud", "deepseek-v4-pro:cloud"),
        ("ollama_cloud", "kimi-k2.7-code:cloud"),
        ("zai", "glm-5.2"),
    ]
    assert resolve_backup_provider("nan") == ("ollama_cloud", "deepseek-v4-pro:cloud")
    assert provider_label("nan") == "NaN"


@pytest.mark.asyncio
async def test_invoke_llm_retries_when_provider_returns_empty_content(monkeypatch):
    monkeypatch.setattr("app.agents.base._llm_semaphore", None)
    llm = _FakeLLM([_FakeResponse(""), _FakeResponse("ok")])

    response = await invoke_llm(llm, ["hola"])

    assert response.content == "ok"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_invoke_llm_retries_when_provider_times_out(monkeypatch):
    monkeypatch.setattr("app.agents.base._llm_semaphore", None)
    monkeypatch.setattr("app.agents.base.settings.llm_request_timeout_seconds", 0.01)
    monkeypatch.setattr("app.agents.base.settings.llm_retry_attempts", 1)
    llm = _SlowThenFastLLM()

    response = await invoke_llm(llm, ["hola"])

    assert response.content == "ok"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_invoke_llm_retries_when_provider_returns_429(monkeypatch):
    monkeypatch.setattr("app.agents.base._llm_semaphore", None)
    monkeypatch.setattr("app.agents.base.settings.llm_retry_attempts", 1)
    monkeypatch.setattr("app.agents.base.settings.llm_retry_base_delay_seconds", 0)
    llm = _FakeLLM(
        [
            RuntimeError("Error code: 429 - Too Many Requests"),
            _FakeResponse("ok"),
        ]
    )

    response = await invoke_llm(llm, ["hola"])

    assert response.content == "ok"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_base_agent_uses_zai_fallback_when_primary_fails(monkeypatch):
    primary_llm = object()
    fallback_llm = object()
    build_calls = []

    def fake_build_llm(**kwargs):
        build_calls.append(kwargs)
        return primary_llm if len(build_calls) == 1 else fallback_llm

    monkeypatch.setattr("app.agents.base.settings.provider", "ollama_cloud")
    monkeypatch.setattr("app.agents.base.settings.nan_api_key", "")
    monkeypatch.setattr("app.agents.base.settings.zai_api_key", "test-key")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_fallback_models", "")
    monkeypatch.setattr("app.agents.base.build_llm", fake_build_llm)
    invoke = AsyncMock(side_effect=[RuntimeError("llm request timed out"), _FakeResponse("fallback ok")])
    monkeypatch.setattr("app.agents.base.invoke_llm", invoke)

    agent = _TestAgent()
    context = RepoContext(tree="└── README.md", files={"README.md": "# test"})

    result = await agent.analyze(context)

    assert result == "fallback ok"
    assert invoke.await_count == 2
    assert invoke.await_args_list[0].args[0] is primary_llm
    assert invoke.await_args_list[1].args[0] is fallback_llm


@pytest.mark.asyncio
async def test_base_agent_uses_ollama_fallback_when_zai_primary_fails(monkeypatch):
    primary_llm = object()
    fallback_llm = object()
    build_calls = []

    def fake_build_llm(**kwargs):
        build_calls.append(kwargs)
        return primary_llm if len(build_calls) == 1 else fallback_llm

    monkeypatch.setattr("app.agents.base.settings.provider", "zai")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_api_key", "ollama-key")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_model", "deepseek-v4-pro:cloud")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_fallback_models", "")
    monkeypatch.setattr("app.agents.base.settings.nan_api_key", "")
    monkeypatch.setattr("app.agents.base.build_llm", fake_build_llm)
    invoke = AsyncMock(
        side_effect=[RuntimeError("llm request timed out"), _FakeResponse("fallback ok")]
    )
    monkeypatch.setattr("app.agents.base.invoke_llm", invoke)

    agent = _TestAgent()
    context = RepoContext(tree="└── README.md", files={"README.md": "# test"})

    result = await agent.analyze(context)

    assert result == "fallback ok"
    assert invoke.await_count == 2
    assert invoke.await_args_list[0].args[0] is primary_llm
    assert invoke.await_args_list[1].args[0] is fallback_llm
    assert build_calls[1]["provider"] == "ollama_cloud"
    assert build_calls[1]["model_override"] == "deepseek-v4-pro:cloud"


@pytest.mark.asyncio
async def test_base_agent_tries_second_fallback_when_first_backup_fails(monkeypatch):
    primary_llm = object()
    first_fallback_llm = object()
    second_fallback_llm = object()
    third_fallback_llm = object()
    llms = [primary_llm, first_fallback_llm, second_fallback_llm, third_fallback_llm]
    build_calls = []

    def fake_build_llm(**kwargs):
        build_calls.append(kwargs)
        return llms[len(build_calls) - 1]

    monkeypatch.setattr("app.agents.base.settings.provider", "nan")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_api_key", "ollama-key")
    monkeypatch.setattr("app.agents.base.settings.ollama_cloud_model", "deepseek-v4-pro:cloud")
    monkeypatch.setattr(
        "app.agents.base.settings.ollama_cloud_fallback_models",
        "kimi-k2.7-code:cloud",
    )
    monkeypatch.setattr("app.agents.base.settings.zai_api_key", "zai-key")
    monkeypatch.setattr("app.agents.base.settings.zai_model", "glm-5.2")
    monkeypatch.setattr("app.agents.base.build_llm", fake_build_llm)
    invoke = AsyncMock(
        side_effect=[
            RuntimeError("llm request timed out"),
            RuntimeError("ollama subscription required"),
            RuntimeError("ollama second model failed"),
            _FakeResponse("third fallback ok"),
        ]
    )
    monkeypatch.setattr("app.agents.base.invoke_llm", invoke)

    agent = _TestAgent()
    context = RepoContext(tree="└── README.md", files={"README.md": "# test"})

    result = await agent.analyze(context)

    assert result == "third fallback ok"
    assert invoke.await_count == 4
    assert invoke.await_args_list[0].args[0] is primary_llm
    assert invoke.await_args_list[1].args[0] is first_fallback_llm
    assert invoke.await_args_list[2].args[0] is second_fallback_llm
    assert invoke.await_args_list[3].args[0] is third_fallback_llm
    assert [call["provider"] for call in build_calls] == [
        "nan",
        "ollama_cloud",
        "ollama_cloud",
        "zai",
    ]
    assert build_calls[1]["model_override"] == "deepseek-v4-pro:cloud"
    assert build_calls[2]["model_override"] == "kimi-k2.7-code:cloud"
