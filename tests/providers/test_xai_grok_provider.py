from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.registry import find_by_name
from nanobot.providers.xai_grok_provider import (
    DEFAULT_XAI_GROK_MODEL,
    DEFAULT_XAI_GROK_MODELS_URL,
    XAIGrokProvider,
    _bounded_error_body,
    _build_headers,
    _build_model_headers,
    _build_reasoning_options,
    _fetch_xai_model_capabilities,
    _parse_xai_model_capabilities,
    _request_xai,
    _xai_error_response,
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
        "nanobot.providers.xai_grok_provider.get_xai_oauth_token",
        lambda **_kwargs: _token(),
    )


def _mock_model_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    *,
    supports_backend_search: bool,
) -> None:
    async def fake_fetch(*_args, **_kwargs):
        return {"grok-4.5": supports_backend_search}

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider._fetch_xai_model_capabilities",
        fake_fetch,
    )


def test_xai_grok_registry_exposes_curated_x_search_model() -> None:
    spec = find_by_name("xai_grok")

    assert spec is not None
    assert spec.is_oauth is True
    assert spec.backend == "xai_grok"
    assert spec.builtin_models[0].id == DEFAULT_XAI_GROK_MODEL
    assert spec.builtin_models[0].context_window == 500000
    assert "when supported" in spec.builtin_models[0].description


def test_reasoning_options_omit_disabled_effort() -> None:
    assert _build_reasoning_options("none") == {"summary": "concise"}


@pytest.mark.asyncio
async def test_provider_injects_hosted_x_search_and_required_proxy_headers(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=True)
    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def fake_request(url, headers, body, **_kwargs):
        calls.append((url, headers, body))
        return "answer [[1]](https://x.com/example/status/1)", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()
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
async def test_provider_keeps_local_x_search_when_model_does_not_support_hosted_search(
    monkeypatch,
) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "x_search",
                "description": "A local search fallback",
                "parameters": {"type": "object"},
            },
        }
    ]

    response = await provider.chat([{"role": "user", "content": "search"}], tools=tools)

    assert response.content == "ok"
    assert bodies[0]["tools"] == [
        {
            "type": "function",
            "name": "x_search",
            "description": "A local search fallback",
            "parameters": {"type": "object"},
        }
    ]


@pytest.mark.asyncio
async def test_provider_fails_closed_and_caches_model_catalog_failure(monkeypatch) -> None:
    _mock_token(monkeypatch)
    fetch_calls = 0
    bodies: list[dict[str, Any]] = []

    async def failing_fetch(*_args, **_kwargs):
        nonlocal fetch_calls
        fetch_calls += 1
        raise httpx.ConnectError("catalog unavailable")

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider._fetch_xai_model_capabilities",
        failing_fetch,
    )
    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()

    await provider.chat([{"role": "user", "content": "first"}])
    await provider.chat([{"role": "user", "content": "second"}])

    assert fetch_calls == 1
    assert all({"type": "x_search"} not in body["tools"] for body in bodies)


@pytest.mark.asyncio
async def test_provider_refreshes_and_retries_exactly_once_after_401(monkeypatch) -> None:
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    token_calls: list[tuple[str | None, bool]] = []

    def fake_token(*, proxy=None, force_refresh=False):
        token_calls.append((proxy, force_refresh))
        return _token("fresh-token" if force_refresh else "stale-token")

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_oauth_token",
        fake_token,
    )
    request_tokens: list[str] = []

    async def fake_request(_url, headers, _body, **_kwargs):
        request_tokens.append(headers["Authorization"])
        if len(request_tokens) == 1:
            raise _XAIHTTPError("unauthorized", status_code=401, should_retry=False)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider(proxy="http://127.0.0.1:7890")

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
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)

    async def always_unauthorized(*_args, **_kwargs):
        raise _XAIHTTPError(
            "xAI rejected the login. Sign in again with `nanobot provider login xai-grok`.",
            status_code=401,
            should_retry=False,
        )

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider._request_xai",
        always_unauthorized,
    )
    provider = XAIGrokProvider()

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert response.error_status_code == 401
    assert response.error_kind == "http"
    assert response.error_should_retry is False
    assert "nanobot provider login xai-grok" in (response.content or "")


@pytest.mark.asyncio
async def test_factory_builds_xai_provider_and_applies_explicit_body_overrides(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=True)
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return "ok", [], "stop", {}, None

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "xai-grok/grok-4.5",
                    "provider": "xai_grok",
                }
            },
            "providers": {
                "xaiGrok": {
                    "proxy": "http://127.0.0.1:7890",
                    "extraBody": {"parallel_tool_calls": False},
                }
            },
        }
    )

    provider = make_provider(config)
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert isinstance(provider, XAIGrokProvider)
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

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)
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


def test_model_capabilities_follow_upstream_aliases_and_default_to_disabled() -> None:
    capabilities = _parse_xai_model_capabilities(
        {
            "data": [
                {"id": "grok-4.5", "supportsBackendSearch": False},
                {
                    "model": "grok-search",
                    "supports_backend_search": True,
                },
                {
                    "modelId": "grok-meta",
                    "_meta": {"supportsBackendSearch": True},
                },
                {"id": "grok-unknown"},
            ]
        }
    )

    assert capabilities == {
        "grok-4.5": False,
        "grok-search": True,
        "grok-meta": True,
        "grok-unknown": False,
    }


@pytest.mark.asyncio
async def test_model_capability_request_uses_subscription_headers(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={"data": [{"id": "grok-search", "supportsBackendSearch": True}]},
            request=request,
        )

    def fake_client(**kwargs) -> httpx.AsyncClient:
        captured["kwargs"] = kwargs
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
            follow_redirects=kwargs["follow_redirects"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "user-42", "email": "user@example.com"}).encode()
    ).decode().rstrip("=")
    access_token = f"header.{payload}.signature"
    headers = _build_model_headers(_token(access_token))

    capabilities = await _fetch_xai_model_capabilities(
        DEFAULT_XAI_GROK_MODELS_URL,
        headers,
    )

    request = captured["request"]
    assert isinstance(request, httpx.Request)
    assert request.method == "GET"
    assert str(request.url) == DEFAULT_XAI_GROK_MODELS_URL
    assert request.headers["Authorization"] == f"Bearer {access_token}"
    assert request.headers["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert request.headers["x-userid"] == "user-42"
    assert request.headers["x-email"] == "user@example.com"
    assert captured["kwargs"] == {"timeout": 10.0, "follow_redirects": False}
    assert capabilities == {"grok-search": True}


@pytest.mark.asyncio
async def test_raw_response_error_preserves_bounded_redacted_body(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    raw = json.dumps(
        {
            "code": "invalid-argument",
            "message": "Hosted x_search is not supported by grok-4.5",
            "access_token": "must-not-leak",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=raw, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)

    with pytest.raises(_XAIHTTPError) as caught:
        await _request_xai(
            "https://cli-chat-proxy.grok.com/v1/responses",
            _build_headers("secret", "grok-4.5"),
            {"model": "grok-4.5"},
        )

    error = caught.value
    assert error.status_code == 400
    assert error.error_code == "invalid-argument"
    assert error.should_retry is False
    assert error.response_body == (
        '{"code":"invalid-argument","message":"Hosted x_search is not supported by '
        'grok-4.5","access_token":"[REDACTED]"}'
    )
    assert f"Response body: {error.response_body}" in str(error)
    assert "must-not-leak" not in str(error)

    provider_response = _xai_error_response(error)
    assert provider_response.error_status_code == 400
    assert provider_response.error_code == "invalid-argument"
    assert error.response_body in (provider_response.content or "")


def test_plain_error_body_is_single_line_and_bounded() -> None:
    detail = _bounded_error_body("Bearer secret-token\n" + "x" * 1100)

    assert detail is not None
    assert detail.startswith("Bearer [REDACTED] ")
    assert detail.endswith("…")
    assert len(detail) == 1001


def test_large_json_error_body_redacts_camel_case_credentials_before_bounding() -> None:
    detail = _bounded_error_body(
        json.dumps(
            {
                "accessToken": "access-must-not-leak",
                "refresh-token": "refresh-must-not-leak",
                "padding": "x" * 33_000,
            }
        )
    )

    assert detail is not None
    assert '"accessToken":"[REDACTED]"' in detail
    assert '"refresh-token":"[REDACTED]"' in detail
    assert "access-must-not-leak" not in detail
    assert "refresh-must-not-leak" not in detail
    assert detail.endswith("…")
    assert len(detail) == 1001


async def _append(target: list[str], value: str) -> None:
    target.append(value)
