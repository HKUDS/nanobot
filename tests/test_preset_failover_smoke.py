"""End-to-end smoke tests for model presets + failover.

Uses a local aiohttp fake OpenAI server so requests are real HTTP,
not mocked at the provider level.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.nanobot import Nanobot
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.failover import ModelRouter
from nanobot.providers.openai_compat_provider import OpenAICompatProvider

try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


@pytest.fixture(autouse=True)
def _disable_proxy_for_localhost_tests(monkeypatch):
    """Prevent httpx from routing localhost requests through a system proxy."""
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


# ---------------------------------------------------------------------------
# Helpers (mock-level preset tests)
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, **overrides) -> Path:
    data = {
        "providers": {
            "openrouter": {"apiKey": "sk-test-key"},
            "openai": {"apiKey": "sk-openai-test"},
        },
        "agents": {"defaults": {"model": "openai/gpt-4.1"}},
        "tools": {"my": {"allowSet": True}},
    }
    data.update(overrides)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data))
    return config_path



# ---------------------------------------------------------------------------
# 1. Model Preset Mock Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preset_loaded_at_startup(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        model_presets={
            "fast": {
                "model": "gpt-4.1-mini",
                "provider": "openai",
                "max_tokens": 4096,
                "context_window_tokens": 128000,
                "temperature": 0.3,
            }
        },
        agents={"defaults": {"model_preset": "fast", "model": "ignored-model"}},
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        bot = Nanobot.from_config(config_path, workspace=tmp_path)

    loop = bot._loop
    assert loop.model == "gpt-4.1-mini"
    assert loop.context_window_tokens == 128000
    assert loop.provider.generation.temperature == 0.3
    assert loop.provider.generation.max_tokens == 4096
    assert loop.model_preset == "fast"


@pytest.mark.asyncio
async def test_preset_runtime_switch_updates_all_fields(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        model_presets={
            "cheap": {
                "model": "gpt-4.1-mini",
                "provider": "openai",
                "max_tokens": 2048,
                "context_window_tokens": 64000,
                "temperature": 0.5,
            },
            "power": {
                "model": "gpt-4.1",
                "provider": "openai",
                "max_tokens": 8192,
                "context_window_tokens": 256000,
                "temperature": 0.1,
            },
        },
        agents={"defaults": {"model_preset": "cheap"}},
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        bot = Nanobot.from_config(config_path, workspace=tmp_path)

    loop = bot._loop
    assert loop.model == "gpt-4.1-mini"

    my_tool = loop.tools.get("my")
    result = await my_tool.execute(action="set", key="model_preset", value="power")
    assert "Error" not in result

    assert loop.model == "gpt-4.1"
    assert loop.context_window_tokens == 256000
    assert loop.provider.generation.temperature == 0.1
    assert loop.provider.generation.max_tokens == 8192
    assert loop.model_preset == "power"


@pytest.mark.asyncio
async def test_preset_switch_unknown_returns_error(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        model_presets={"a": {"model": "model-a"}},
        agents={"defaults": {"model_preset": "a"}},
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        bot = Nanobot.from_config(config_path, workspace=tmp_path)

    loop = bot._loop
    original_model = loop.model

    my_tool = loop.tools.get("my")
    result = await my_tool.execute(action="set", key="model_preset", value="nonexistent")
    assert "not found" in result.lower()

    assert loop.model == original_model
    assert loop.model_preset == "a"


@pytest.mark.asyncio
async def test_preset_model_with_fallback_presets_in_config(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        model_presets={
            "prod": {
                "model": "gpt-4.1",
                "provider": "openai",
                "max_tokens": 8192,
                "temperature": 0.1,
            },
            "fallback": {
                "model": "gpt-4.1-mini",
                "provider": "openai",
                "max_tokens": 4096,
                "temperature": 0.2,
            },
        },
        agents={
            "defaults": {
                "model_preset": "prod",
                "fallback_presets": ["fallback"],
            }
        },
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        bot = Nanobot.from_config(config_path, workspace=tmp_path)

    loop = bot._loop
    assert loop.model == "gpt-4.1"
    assert isinstance(loop.provider, ModelRouter)
    assert loop.provider.fallback_presets == ["fallback"]


@pytest.mark.asyncio
async def test_fallback_presets_wired_to_all_subsystems(tmp_path: Path) -> None:
    """When fallback_presets is configured, every subsystem that calls the LLM
    must use the same ModelRouter instance, not the raw primary provider."""
    config_path = _write_config(
        tmp_path,
        model_presets={
            "prod": {
                "model": "gpt-4.1",
                "provider": "openai",
                "max_tokens": 8192,
                "temperature": 0.1,
            },
            "fallback": {
                "model": "gpt-4.1-mini",
                "provider": "openai",
                "max_tokens": 4096,
                "temperature": 0.2,
            },
        },
        agents={
            "defaults": {
                "model_preset": "prod",
                "fallback_presets": ["fallback"],
            }
        },
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        bot = Nanobot.from_config(config_path, workspace=tmp_path)

    loop = bot._loop
    router = loop.provider
    assert isinstance(router, ModelRouter)

    # Every LLM-consuming subsystem must share the same router
    assert loop.runner.provider is router, "AgentRunner must use ModelRouter"
    assert loop.subagents.provider is router, "SubagentManager must use ModelRouter"
    assert loop.consolidator.provider is router, "Consolidator must use ModelRouter"
    assert loop.dream.provider is router, "Dream must use ModelRouter"


# ---------------------------------------------------------------------------
# 2. Real HTTP Smoke Tests (aiohttp fake OpenAI server)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_preset_generation_params_reach_http_request() -> None:
    """Provider.generation settings must appear in the actual HTTP request body."""
    requests_log: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        requests_log.append(body)
        return web.json_response({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": body.get("model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "pong"},
                "finish_reason": "stop",
            }],
        })

    app = web.Application()
    app.router.add_post("/chat/completions", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        base_url = str(server.make_url("/"))
        provider = OpenAICompatProvider(
            api_key="test",
            api_base=base_url,
            default_model="test-model",
        )
        provider.generation = GenerationSettings(temperature=0.42, max_tokens=1024)

        with patch.object(LLMProvider, "_CHAT_RETRY_DELAYS", (0,)):
            response = await provider.chat_with_retry(
                messages=[{"role": "user", "content": "ping"}],
            )

        assert response.finish_reason != "error"
        assert len(requests_log) >= 1
        req = requests_log[0]
        assert req["model"] == "test-model"
        assert req["temperature"] == 0.42
        assert req["max_tokens"] == 1024
    finally:
        await server.close()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_failover_sends_second_request_to_fallback_model() -> None:
    """Primary returns 503; after retry exhaustion ModelRouter hits fallback."""
    requests_log: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        requests_log.append(body)
        model = body.get("model")

        if model == "primary-model":
            return web.Response(
                status=503,
                body=json.dumps({"error": {"message": "overloaded", "type": "server_error"}}),
                content_type="application/json",
            )

        return web.json_response({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "fallback-ok"},
                "finish_reason": "stop",
            }],
        })

    app = web.Application()
    app.router.add_post("/chat/completions", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        base_url = str(server.make_url("/"))
        primary = OpenAICompatProvider(
            api_key="test", api_base=base_url, default_model="primary-model"
        )
        fallback = OpenAICompatProvider(
            api_key="test", api_base=base_url, default_model="fallback-model"
        )

        factory = MagicMock(return_value=fallback)

        router = ModelRouter(
            primary_provider=primary,
            primary_model="primary-model",
            fallback_presets=["fallback-model"],
            provider_factory=factory,
        )

        with patch.object(LLMProvider, "_CHAT_RETRY_DELAYS", (0,)):
            response = await router.chat_with_retry(
                messages=[{"role": "user", "content": "hi"}],
            )

        assert response.finish_reason != "error"
        assert response.content == "fallback-ok"

        models_requested = [r["model"] for r in requests_log]
        assert "primary-model" in models_requested
        assert "fallback-model" in models_requested
        factory.assert_called_once_with("fallback-model")
    finally:
        await server.close()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_failover_on_quota_429() -> None:
    """Quota 429 on one provider may still work on a different provider."""
    requests_log: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        requests_log.append(body)
        return web.Response(
            status=429,
            body=json.dumps({
                "error": {
                    "message": "insufficient quota",
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                }
            }),
            content_type="application/json",
        )

    app = web.Application()
    app.router.add_post("/chat/completions", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        base_url = str(server.make_url("/"))
        primary = OpenAICompatProvider(
            api_key="test", api_base=base_url, default_model="primary-model"
        )
        fallback = OpenAICompatProvider(
            api_key="test", api_base=base_url, default_model="fallback-model"
        )

        factory = MagicMock(return_value=fallback)

        router = ModelRouter(
            primary_provider=primary,
            primary_model="primary-model",
            fallback_presets=["fallback-model"],
            provider_factory=factory,
        )

        with patch.object(LLMProvider, "_CHAT_RETRY_DELAYS", (0,)):
            response = await router.chat_with_retry(
                messages=[{"role": "user", "content": "hi"}],
            )

        # Quota 429 SHOULD trigger failover — another provider may still work.
        factory.assert_called_once_with("fallback-model")
        assert response.finish_reason == "error"
        # Both primary and fallback should have been requested.
        assert len(requests_log) == 2
    finally:
        await server.close()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_model_router_failover_integration() -> None:
    """ModelRouter -> real HTTP failover chain (primary 503, fallback 200)."""
    requests_log: list[dict] = []

    async def handler(request: web.Request) -> web.Response:
        body = await request.json()
        requests_log.append(body)
        model = body.get("model")

        if model == "primary-model":
            return web.Response(
                status=503,
                body=json.dumps({"error": {"message": "overloaded", "type": "server_error"}}),
                content_type="application/json",
            )

        return web.json_response({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "fallback-ok"},
                "finish_reason": "stop",
            }],
        })

    app = web.Application()
    app.router.add_post("/chat/completions", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        base_url = str(server.make_url("/"))
        primary = OpenAICompatProvider(
            api_key="test", api_base=base_url, default_model="primary-model"
        )
        fallback = OpenAICompatProvider(
            api_key="test", api_base=base_url, default_model="fallback-model"
        )

        factory = MagicMock(return_value=fallback)

        router = ModelRouter(
            primary_provider=primary,
            primary_model="primary-model",
            fallback_presets=["fallback-model"],
            provider_factory=factory,
        )

        with patch.object(LLMProvider, "_CHAT_RETRY_DELAYS", (0,)):
            response = await router.chat_with_retry(
                messages=[{"role": "user", "content": "hello"}],
            )

        assert response.finish_reason != "error"
        assert response.content == "fallback-ok"
        models_requested = [r["model"] for r in requests_log]
        assert "primary-model" in models_requested
        assert "fallback-model" in models_requested
        factory.assert_called_once_with("fallback-model")
    finally:
        await server.close()
