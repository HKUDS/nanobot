"""Tests for the OpenCode Zen and OpenCode Go provider registrations."""

import asyncio
import hashlib
import json

import httpx
import pytest

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.base import ProviderCallContext
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


def test_opencode_config_fields_exist() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "opencode")
    assert hasattr(config, "opencode_zen")
    assert hasattr(config, "opencode_go")


def test_opencode_specs_use_openai_compatible_gateways() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    zen = specs["opencode"]
    assert zen.backend == "openai_compat"
    assert zen.env_key == "OPENCODE_API_KEY"
    assert zen.display_name == "OpenCode Zen"
    assert zen.is_gateway is True
    assert zen.detect_by_base_keyword == "opencode.ai/zen"
    assert zen.default_api_base == "https://opencode.ai/zen/v1"
    assert "opencode" in zen.strip_model_prefixes

    zen_compat = specs["opencode_zen"]
    assert zen_compat.env_key == "OPENCODE_API_KEY"
    assert zen_compat.default_api_base == zen.default_api_base

    go = specs["opencode_go"]
    assert go.backend == "openai_compat"
    assert go.env_key == "OPENCODE_API_KEY"
    assert go.display_name == "OpenCode Go"
    assert go.is_gateway is True
    assert go.detect_by_base_keyword == "opencode.ai/zen/go"
    assert go.default_api_base == "https://opencode.ai/zen/go/v1"
    assert "opencode-go" in go.strip_model_prefixes


def test_find_by_name_opencode_providers() -> None:
    canonical = find_by_name("opencode")
    assert canonical is not None
    assert canonical.name == "opencode"

    zen = find_by_name("opencode_zen")
    assert zen is not None
    assert zen.name == "opencode_zen"

    go = find_by_name("opencode-go")
    assert go is not None
    assert go.name == "opencode_go"


def test_opencode_forced_providers_use_default_api_base() -> None:
    zen_config = Config.model_validate(
        {
            "providers": {"opencode": {"apiKey": "opencode-key"}},
            "agents": {"defaults": {"provider": "opencode", "model": "opencode/o3"}},
        }
    )

    assert zen_config.get_provider_name() == "opencode"
    assert zen_config.get_api_key() == "opencode-key"
    assert zen_config.get_api_base() == "https://opencode.ai/zen/v1"

    legacy_zen_config = Config.model_validate(
        {
            "providers": {"opencodeZen": {"apiKey": "opencode-key"}},
            "agents": {"defaults": {"provider": "opencode_zen", "model": "opencode/o3"}},
        }
    )

    assert legacy_zen_config.get_provider_name() == "opencode_zen"
    assert legacy_zen_config.get_api_key() == "opencode-key"
    assert legacy_zen_config.get_api_base() == "https://opencode.ai/zen/v1"

    go_config = Config.model_validate(
        {
            "providers": {"opencodeGo": {"apiKey": "opencode-key"}},
            "agents": {"defaults": {"provider": "opencode_go", "model": "opencode-go/o3"}},
        }
    )

    assert go_config.get_provider_name() == "opencode_go"
    assert go_config.get_api_key() == "opencode-key"
    assert go_config.get_api_base() == "https://opencode.ai/zen/go/v1"


def test_opencode_prefixes_are_stripped_before_request() -> None:
    zen_provider = OpenAICompatProvider(
        api_key=None,
        default_model="opencode/o3",
        spec=find_by_name("opencode"),
    )
    zen_kwargs = zen_provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="opencode/o3",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )
    assert zen_kwargs["model"] == "o3"

    go_provider = OpenAICompatProvider(
        api_key=None,
        default_model="opencode-go/o3",
        spec=find_by_name("opencode_go"),
    )
    go_kwargs = go_provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="opencode-go/o3",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )
    assert go_kwargs["model"] == "o3"


def _fake_responses_output() -> dict[str, object]:
    return {
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "ok"}],
        }],
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def _affinity_provider(name: str) -> OpenAICompatProvider:
    return OpenAICompatProvider(api_key=None, default_model="opencode/o3", spec=find_by_name(name))


def test_opencode_affinity_headers_enabled():
    ctx = ProviderCallContext(session_id="s-1")
    expected = {"x-opencode-session": hashlib.sha256(b"s-1").hexdigest()}
    for name in ("opencode", "opencode_go", "opencode_zen"):
        assert _affinity_provider(name)._opencode_affinity_headers(ctx) == expected
    relayed = OpenAICompatProvider(api_key=None, default_model="o3", api_base="https://opencode.ai/zen/v1")
    assert relayed._opencode_affinity_headers(ctx) == expected


def test_opencode_affinity_headers_disabled():
    assert _affinity_provider("opencode")._opencode_affinity_headers(ProviderCallContext()) is None
    plain = OpenAICompatProvider(api_key=None, default_model="gpt-4o", spec=find_by_name("openai"))
    assert plain._opencode_affinity_headers(ProviderCallContext(session_id="s-1")) is None
    openai_base = OpenAICompatProvider(api_key=None, default_model="gpt-4o", api_base="https://api.openai.com/v1")
    assert openai_base._opencode_affinity_headers(ProviderCallContext(session_id="s-1")) is None


@pytest.mark.parametrize(("base", "enabled"), [
    ("https://OPENCODE.AI/zen/v1", True),
    ("https://relay.opencode.ai/v1", True),
    ("https://opencode.ai./zen/v1", True),
    ("https://opencode.ai.example.com/v1", False),
    ("https://notopencode.ai/v1", False),
    ("https://example.com/opencode.ai", False),
    ("https://example.com/v1?target=opencode.ai", False),
    ("https://opencode.ai@example.com/v1", False),
])
def test_opencode_affinity_matches_hostname(base, enabled):
    provider = OpenAICompatProvider(api_base=base)
    assert ("x-opencode-session" in provider._default_headers) is enabled


@pytest.mark.parametrize("api_type", ["chat_completions", "responses", "responses_compaction"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("configured_header", [None, "x-opencode-session", "X-OpenCode-Session"])
async def test_opencode_wire_affinity(monkeypatch, api_type, stream, configured_header):
    """Exercise SDK header encoding/merging through the public provider entrypoints."""
    from openai import AsyncOpenAI

    from nanobot.providers import openai_compat_provider

    requests: list[httpx.Request] = []
    rejected: list[httpx.Request] = []
    compaction = api_type == "responses_compaction"
    if compaction:
        api_type = "responses"

    async def handle(request: httpx.Request) -> httpx.Response:
        if "context_management" in json.loads(request.content):
            rejected.append(request)
            return httpx.Response(400, json={"error": {
                "message": "Unsupported parameter: context_management",
                "type": "invalid_request_error",
            }})
        requests.append(request)
        await asyncio.sleep(0)
        if api_type == "responses":
            output = _fake_responses_output()
            output.update(id="resp_test", object="response", created_at=0, model="gpt-5")
            events = [
                {"type": "response.output_text.delta", "delta": "ok"},
                {"type": "response.completed", "response": output},
            ]
        else:
            output = {
                "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
                "model": "gpt-5", "choices": [{
                    "index": 0, "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }],
            }
            events = [{
                "id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0,
                "model": "gpt-5", "choices": [{
                    "index": 0, "delta": {"content": "ok"}, "finish_reason": "stop",
                }],
            }]
        if stream:
            payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=output)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        def make_client(**kwargs):
            return AsyncOpenAI(**{**kwargs, "http_client": transport})

        monkeypatch.setattr(openai_compat_provider, "AsyncOpenAI", make_client)
        headers = {"x-custom": "preserved", "x-session-affinity": "existing"}
        if configured_header:
            headers[configured_header] = "configured"
        provider = OpenAICompatProvider(
            api_key="test", api_base="https://opencode.ai/zen/v1",
            spec=find_by_name("openai"), api_type=api_type, extra_headers=headers,
            default_model="gpt-5",
            extra_body={"context_management": [{"type": "compaction"}]} if compaction else None,
        )
        call = provider.chat_stream_with_retry if stream else provider.chat_with_retry

        async def send(session_id):
            context = ProviderCallContext(session_id=session_id) if session_id is not None else None
            result = await call(
                messages=[{"role": "user", "content": session_id or "no-context"}],
                provider_context=context,
            )
            assert result.content == "ok"

        await send(None)
        fallback = requests[-1].headers["x-opencode-session"]
        assert fallback.isascii() and fallback
        await asyncio.gather(send("sdk:中文"), send("sdk:other"))
        for request in requests[1:]:
            body = json.loads(request.content)
            messages = body["input"] if api_type == "responses" else body["messages"]
            content = messages[0]["content"]
            session_id = content if isinstance(content, str) else content[0]["text"]
            expected = "configured" if configured_header else hashlib.sha256(
                session_id.encode("utf-8"),
            ).hexdigest()
            assert request.headers["x-opencode-session"] == expected
        await send("sdk:中文")
        await send("")
        await send(None)
        assert len(requests) == 6
        assert requests[3].headers["x-opencode-session"] == (
            "configured" if configured_header else hashlib.sha256("sdk:中文".encode()).hexdigest()
        )
        assert requests[4].headers["x-opencode-session"] == fallback
        assert requests[5].headers["x-opencode-session"] == fallback
        if compaction:
            assert len(rejected) == 6
            assert [r.headers["x-opencode-session"] for r in rejected] == [
                r.headers["x-opencode-session"] for r in requests
            ]
        for request in [*requests, *rejected]:
            assert request.headers["x-custom"] == "preserved"
            assert request.headers["x-session-affinity"] == "existing"
            assert len(request.headers.get_list("x-opencode-session")) == 1
