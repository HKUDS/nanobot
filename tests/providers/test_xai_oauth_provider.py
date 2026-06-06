from __future__ import annotations

import asyncio

from nanobot.config.schema import XaiOAuthXSearchConfig
import nanobot.providers.xai_oauth_provider as xai_oauth_provider
from nanobot.providers.xai_oauth_provider import (
    XaiOAuthCredential,
    XaiOAuthProvider,
    _build_xai_responses_body,
    _strip_model_prefix,
)


def test_xai_oauth_strip_prefix_supports_aliases() -> None:
    assert _strip_model_prefix("xai-oauth/grok-4.3") == "grok-4.3"
    assert _strip_model_prefix("xai_oauth/grok-4.3") == "grok-4.3"
    assert _strip_model_prefix("grok-oauth/grok-4.3") == "grok-4.3"
    assert _strip_model_prefix("grok-4.3") == "grok-4.3"


def test_build_xai_responses_body_keeps_system_prompt_in_input() -> None:
    body = _build_xai_responses_body(
        messages=[
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "hi"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "Ping",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        model="xai-oauth/grok-4.3",
        max_tokens=32,
        temperature=0.2,
        reasoning_effort="high",
        tool_choice=None,
    )

    assert body["model"] == "grok-4.3"
    assert "instructions" not in body
    assert body["input"][0] == {
        "role": "system",
        "content": [{"type": "input_text", "text": "You are nanobot."}],
    }
    assert body["input"][1]["role"] == "user"
    assert body["max_output_tokens"] == 32
    assert body["temperature"] == 0.2
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"][0]["name"] == "ping"


def test_build_xai_responses_body_attaches_hosted_x_search_by_default() -> None:
    body = _build_xai_responses_body(
        messages=[{"role": "user", "content": "what is happening on X?"}],
        tools=None,
        model="xai-oauth/grok-4.3",
        max_tokens=32,
        temperature=0.2,
        reasoning_effort=None,
        tool_choice=None,
        hosted_x_search=XaiOAuthXSearchConfig(),
    )

    assert body["tools"] == [{"type": "x_search"}]


def test_build_xai_responses_body_can_customize_hosted_x_search() -> None:
    body = _build_xai_responses_body(
        messages=[{"role": "user", "content": "what is happening on X?"}],
        tools=None,
        model="xai-oauth/grok-4.3",
        max_tokens=32,
        temperature=0.2,
        reasoning_effort=None,
        tool_choice=None,
        hosted_x_search=XaiOAuthXSearchConfig(
            allowed_x_handles=["@xai", " nanobot "],
            enable_image_understanding=True,
        ),
    )

    assert body["tools"] == [
        {
            "type": "x_search",
            "allowed_x_handles": ["xai", "nanobot"],
            "enable_image_understanding": True,
        }
    ]


def test_build_xai_responses_body_omits_disabled_hosted_x_search() -> None:
    body = _build_xai_responses_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="xai-oauth/grok-4.3",
        max_tokens=32,
        temperature=0.2,
        reasoning_effort=None,
        tool_choice=None,
        hosted_x_search=XaiOAuthXSearchConfig(enable=False),
    )

    assert "tools" not in body


def test_xai_oauth_provider_refreshes_once_on_401(monkeypatch) -> None:
    async def run() -> None:
        response = await provider.chat([{"role": "user", "content": "hi"}])

        assert response.content == "ok"
        assert response.finish_reason == "stop"
        assert calls == [("resolve", False), ("resolve", True)]

    provider = XaiOAuthProvider(default_model="xai-oauth/grok-4.3")
    credentials = [
        XaiOAuthCredential(access_token="expired"),
        XaiOAuthCredential(access_token="fresh"),
    ]
    calls: list[tuple[str, bool]] = []

    def fake_resolve(*, force_refresh: bool = False) -> XaiOAuthCredential:
        calls.append(("resolve", force_refresh))
        return credentials.pop(0)

    async def fake_request(credential, body, on_content_delta=None, on_tool_call_delta=None):
        from nanobot.providers.xai_oauth_provider import _XaiHTTPError

        if credential.access_token == "expired":
            raise _XaiHTTPError("expired", status_code=401)
        return "ok", [], "stop"

    monkeypatch.setattr(xai_oauth_provider, "resolve_xai_oauth_credential", fake_resolve)
    monkeypatch.setattr(xai_oauth_provider, "_request_xai", fake_request)

    asyncio.run(run())
