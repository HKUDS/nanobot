"""Tests for the OpenCode Zen and OpenCode Go provider registrations."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


def _fake_chat_response() -> SimpleNamespace:
    message = SimpleNamespace(content="ok", tool_calls=None, reasoning_content=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


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
    expected = {"x-opencode-session": "s-1"}
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


def test_opencode_chat_injects_session_header():
    provider = _affinity_provider("opencode")
    client = AsyncMock()
    client.chat.completions.create.return_value = _fake_chat_response()
    provider._client = client
    result = asyncio.run(provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="opencode/o3",
        provider_context=ProviderCallContext(session_id="convo-xyz"),
    ))
    assert client.chat.completions.create.call_args.kwargs["extra_headers"] == {"x-opencode-session": "convo-xyz"}
    assert result.content == "ok"


def test_opencode_chat_stream_injects_session_header():
    provider = _affinity_provider("opencode")
    client = AsyncMock()

    async def _chunks():
        for text, finish in (("hel", None), ("lo", "stop")):
            delta = SimpleNamespace(content=text)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=None)

    client.chat.completions.create.return_value = _chunks()
    provider._client = client
    result = asyncio.run(provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        model="opencode/o3",
        provider_context=ProviderCallContext(session_id="convo-stream"),
    ))
    assert client.chat.completions.create.call_args.kwargs["extra_headers"] == {"x-opencode-session": "convo-stream"}
    assert result.content == "hello"


def test_opencode_responses_api_injects_session_header():
    # Config-reachable combo: providers.openai + apiType=responses + base
    # aimed at opencode.ai => affinity on, header must reach /responses too.
    provider = OpenAICompatProvider(
        api_key=None,
        default_model="gpt-5",
        api_base="https://opencode.ai/zen/v1",
        spec=find_by_name("openai"),
        api_type="responses",
    )
    client = AsyncMock()
    client.responses.create.return_value = _fake_responses_output()
    provider._client = client
    result = asyncio.run(provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5",
        provider_context=ProviderCallContext(session_id="convo-rsp"),
    ))
    assert client.responses.create.call_args.kwargs["extra_headers"] == {"x-opencode-session": "convo-rsp"}
    assert result.content == "ok"
