from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.registry import find_by_name
from nanobot.providers.xai_oauth_provider import (
    DEFAULT_XAI_OAUTH_MODEL,
    XAIOAuthProvider,
    _build_headers,
    _request_xai,
    _XAIHTTPError,
)


def _token(access: str = "subscription-token") -> SimpleNamespace:
    return SimpleNamespace(
        access=access,
        refresh="refresh-token",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id="account",
    )


def _mock_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.providers.xai_oauth_provider.get_xai_oauth_token",
        lambda **_kwargs: _token(),
    )


def test_xai_oauth_registry_exposes_curated_x_search_model() -> None:
    spec = find_by_name("xai_oauth")

    assert spec is not None
    assert spec.is_oauth is True
    assert spec.backend == "xai_oauth"
    assert spec.builtin_models[0].id == DEFAULT_XAI_OAUTH_MODEL
    assert spec.builtin_models[0].context_window == 500000
    assert "X Search" in spec.builtin_models[0].description


@pytest.mark.asyncio
async def test_provider_injects_hosted_x_search_and_required_proxy_headers(monkeypatch) -> None:
    _mock_token(monkeypatch)
    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def fake_request(url, headers, body, **_kwargs):
        calls.append((url, headers, body))
        return "answer [[1]](https://x.com/example/status/1)", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_oauth_provider._request_xai", fake_request)
    provider = XAIOAuthProvider()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object"},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "x_search",
                "description": "A colliding local tool",
                "parameters": {"type": "object"},
            },
        },
    ]

    response = await provider.chat(
        [{"role": "user", "content": "What is happening on X?"}],
        tools=tools,
        max_tokens=1234,
        temperature=0.2,
        reasoning_effort="high",
    )

    assert response.content == "answer [[1]](https://x.com/example/status/1)"
    url, headers, body = calls[0]
    assert url == "https://cli-chat-proxy.grok.com/v1/responses"
    assert body["model"] == "grok-4.5"
    assert body["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object"},
        },
        {"type": "x_search"},
    ]
    assert body["max_output_tokens"] == 1234
    assert body["temperature"] == 0.2
    assert body["stream_tool_calls"] is True
    assert body["reasoning"] == {"summary": "concise", "effort": "high"}
    assert body["store"] is False
    assert headers["Authorization"] == "Bearer subscription-token"
    assert headers["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert headers["x-authenticateresponse"] == "authenticate-response"
    assert headers["x-grok-client-identifier"] == "nanobot"
    assert headers["x-grok-client-mode"] == "headless"
    assert headers["x-grok-model-override"] == "grok-4.5"


@pytest.mark.asyncio
async def test_provider_refreshes_and_retries_exactly_once_after_401(monkeypatch) -> None:
    token_calls: list[tuple[str | None, bool]] = []

    def fake_token(*, proxy=None, force_refresh=False):
        token_calls.append((proxy, force_refresh))
        return _token("fresh-token" if force_refresh else "stale-token")

    monkeypatch.setattr(
        "nanobot.providers.xai_oauth_provider.get_xai_oauth_token",
        fake_token,
    )
    request_tokens: list[str] = []

    async def fake_request(_url, headers, _body, **_kwargs):
        request_tokens.append(headers["Authorization"])
        if len(request_tokens) == 1:
            raise _XAIHTTPError("unauthorized", status_code=401, should_retry=False)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_oauth_provider._request_xai", fake_request)
    provider = XAIOAuthProvider(proxy="http://127.0.0.1:7890")

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert token_calls == [
        ("http://127.0.0.1:7890", False),
        ("http://127.0.0.1:7890", True),
    ]
    assert request_tokens == ["Bearer stale-token", "Bearer fresh-token"]


@pytest.mark.asyncio
async def test_second_401_is_non_retryable_and_prompts_reauthentication(monkeypatch) -> None:
    _mock_token(monkeypatch)

    async def always_unauthorized(*_args, **_kwargs):
        raise _XAIHTTPError(
            "xAI rejected the login. Sign in again with `nanobot provider login xai-oauth`.",
            status_code=401,
            should_retry=False,
        )

    monkeypatch.setattr(
        "nanobot.providers.xai_oauth_provider._request_xai",
        always_unauthorized,
    )
    provider = XAIOAuthProvider()

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert response.error_status_code == 401
    assert response.error_kind == "http"
    assert response.error_should_retry is False
    assert "nanobot provider login xai-oauth" in (response.content or "")


@pytest.mark.asyncio
async def test_factory_builds_xai_provider_and_applies_explicit_body_overrides(monkeypatch) -> None:
    _mock_token(monkeypatch)
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_oauth_provider._request_xai", fake_request)
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "xai-oauth/grok-4.5",
                    "provider": "xai_oauth",
                }
            },
            "providers": {
                "xaiOauth": {
                    "proxy": "http://127.0.0.1:7890",
                    "extraBody": {"parallel_tool_calls": False},
                }
            },
        }
    )

    provider = make_provider(config)
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert isinstance(provider, XAIOAuthProvider)
    assert provider.proxy == "http://127.0.0.1:7890"
    assert response.content == "ok"
    assert bodies[0]["parallel_tool_calls"] is False
    assert {"type": "x_search"} in bodies[0]["tools"]


@pytest.mark.asyncio
async def test_raw_response_request_streams_text_usage_and_inline_citations(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    captured: dict[str, Any] = {}
    events = [
        {"type": "response.output_text.delta", "delta": "Live result "},
        {
            "type": "response.output_text.delta",
            "delta": "[[1]](https://x.com/example/status/1)",
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            },
        },
    ]
    content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, content=content, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        captured["kwargs"] = kwargs
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_oauth_provider.httpx.AsyncClient", fake_client)
    deltas: list[str] = []

    result = await _request_xai(
        "https://cli-chat-proxy.grok.com/v1/responses",
        _build_headers("secret", "grok-4.5"),
        {"model": "grok-4.5", "tools": [{"type": "x_search"}]},
        on_content_delta=lambda delta: _append(deltas, delta),
    )

    assert result[0] == "Live result [[1]](https://x.com/example/status/1)"
    assert result[2] == "stop"
    assert result[3] == {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
    assert deltas == ["Live result ", "[[1]](https://x.com/example/status/1)"]
    assert captured["json"]["tools"] == [{"type": "x_search"}]


async def _append(target: list[str], value: str) -> None:
    target.append(value)
