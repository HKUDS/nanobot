"""Tests for OpenCode Go provider registration, matching, and prefix stripping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.registry import PROVIDERS, find_by_name


# ── registry 注册验证 ──────────────────────────────────────────────────


def test_opencode_go_spec_exists_in_registry():
    """OpenCode Go (OpenAI compat) 应在 PROVIDERS 中注册。"""
    spec = find_by_name("opencode_go")
    assert spec is not None
    assert spec.backend == "openai_compat"
    assert spec.is_gateway is True
    assert spec.strip_model_prefix is True
    assert spec.env_key == "OPENCODE_GO_API_KEY"
    assert spec.default_api_base == "https://opencode.ai/zen/go/v1"
    assert "opencode-go" in spec.keywords
    assert "kimi-k2" in spec.keywords
    assert "deepseek-v4" in spec.keywords
    assert spec.display_name == "OpenCode Go"


def test_opencode_go_anthropic_spec_exists_in_registry():
    """OpenCode Go (Anthropic compat) 应在 PROVIDERS 中注册。"""
    spec = find_by_name("opencode_go_anthropic")
    assert spec is not None
    assert spec.backend == "anthropic"
    assert spec.is_gateway is True
    assert spec.strip_model_prefix is True
    assert spec.env_key == "OPENCODE_GO_API_KEY"
    assert spec.default_api_base == "https://opencode.ai/zen/go/v1"
    assert spec.display_name == "OpenCode Go Anthropic"


# ── schema 配置字段验证 ────────────────────────────────────────────────


def test_opencode_go_config_field_exists():
    """ProvidersConfig 应包含 opencode_go 和 opencode_go_anthropic 字段。"""
    cfg = ProvidersConfig()
    assert hasattr(cfg, "opencode_go")
    assert hasattr(cfg, "opencode_go_anthropic")


def test_opencode_go_field_is_not_excluded():
    """OpenCode Go 不是 OAuth provider，不应被 exclude。"""
    cfg = ProvidersConfig()
    dumped = cfg.model_dump(by_alias=True)
    assert "opencodeGo" in dumped
    assert "opencodeGoAnthropic" in dumped


# ── 模型匹配验证 ─────────────────────────────────────────────────────


def test_config_matches_opencode_go_by_prefix():
    """通过 opencode-go/ 前缀匹配到 opencode_go provider。"""
    config = Config()
    config.agents.defaults.model = "opencode-go/kimi-k2.6"
    config.providers.opencode_go.api_key = "sk-test"

    assert config.get_provider_name() == "opencode_go"
    assert config.get_api_base() == "https://opencode.ai/zen/go/v1"


def test_config_matches_opencode_go_anthropic_by_prefix():
    """通过 opencode-go-anthropic/ 前缀匹配到 opencode_go_anthropic provider。"""
    config = Config()
    config.agents.defaults.model = "opencode-go-anthropic/minimax-m2.7"
    config.providers.opencode_go_anthropic.api_key = "sk-test"

    assert config.get_provider_name() == "opencode_go_anthropic"
    assert config.get_api_base() == "https://opencode.ai/zen/go/v1"


def test_config_matches_opencode_go_by_keyword():
    """通过关键词 kimi-k2 匹配到 opencode_go provider（无前缀时）。"""
    config = Config()
    config.agents.defaults.model = "kimi-k2.6"
    config.providers.opencode_go.api_key = "sk-test"

    assert config.get_provider_name() == "opencode_go"


def test_config_matches_opencode_go_by_deepseek_keyword():
    """通过关键词 deepseek-v4 匹配到 opencode_go provider。"""
    config = Config()
    config.agents.defaults.model = "deepseek-v4-pro"
    config.providers.opencode_go.api_key = "sk-test"

    assert config.get_provider_name() == "opencode_go"


def test_config_opencode_go_falls_back_to_default_api_base():
    """未配置 api_base 时，回退到 ProviderSpec.default_api_base。"""
    config = Config()
    config.agents.defaults.model = "opencode-go/kimi-k2.6"
    config.providers.opencode_go.api_key = "sk-test"
    # 不设置 api_base

    assert config.get_api_base() == "https://opencode.ai/zen/go/v1"


# ── 前缀剥离验证（OpenAI compat） ─────────────────────────────────────


@pytest.mark.asyncio
async def test_opencode_go_openai_strips_model_prefix():
    """OpenAI compat 路径下，strip_model_prefix=True 应剥离 opencode-go/ 前缀。"""
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    mock_create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )
    )
    spec = find_by_name("opencode_go")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        provider = OpenAICompatProvider(
            api_key="sk-test",
            api_base="https://opencode.ai/zen/go/v1",
            default_model="opencode-go/kimi-k2.6",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="opencode-go/kimi-k2.6",
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "kimi-k2.6"


# ── 前缀剥离验证（Anthropic compat） ──────────────────────────────────


@pytest.mark.asyncio
async def test_opencode_go_anthropic_strips_model_prefix():
    """Anthropic 路径下，strip_model_prefix=True 应剥离 opencode-go-anthropic/ 前缀。"""
    from nanobot.providers.anthropic_provider import AnthropicProvider

    mock_create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(text="ok", type="text")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
            model="minimax-m2.7",
        )
    )
    spec = find_by_name("opencode_go_anthropic")

    with patch("nanobot.providers.anthropic_provider.AsyncAnthropic") as MockClient:
        client_instance = MockClient.return_value
        client_instance.messages.create = mock_create

        provider = AnthropicProvider(
            api_key="sk-test",
            api_base="https://opencode.ai/zen/go/v1",
            default_model="opencode-go-anthropic/minimax-m2.7",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="opencode-go-anthropic/minimax-m2.7",
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "minimax-m2.7"


# ── api_base 传递验证 ─────────────────────────────────────────────────


def test_opencode_go_custom_api_base_overrides_default():
    """用户自定义 api_base 应覆盖 ProviderSpec.default_api_base。"""
    config = Config()
    config.agents.defaults.model = "opencode-go/kimi-k2.6"
    config.providers.opencode_go.api_key = "sk-test"
    config.providers.opencode_go.api_base = "https://custom-proxy.example.com/v1"

    assert config.get_api_base() == "https://custom-proxy.example.com/v1"
