"""Tests for the OpenCode Zen and OpenCode Go provider registrations."""

from blackcat.config.schema import Config, ProvidersConfig
from blackcat.providers.openai_compat_provider import OpenAICompatProvider
from blackcat.providers.registry import PROVIDERS, find_by_name


def test_opencode_config_fields_exist() -> None:
    config = ProvidersConfig()

    assert hasattr(config, "opencode_zen")
    assert hasattr(config, "opencode_go")


def test_opencode_specs_use_openai_compatible_gateways() -> None:
    specs = {spec.name: spec for spec in PROVIDERS}

    zen = specs["opencode_zen"]
    assert zen.backend == "openai_compat"
    assert zen.env_key == "OPENCODE_API_KEY"
    assert zen.display_name == "OpenCode Zen"
    assert zen.is_gateway is True
    assert zen.detect_by_base_keyword == "opencode.ai/zen"
    assert zen.default_api_base == "https://opencode.ai/zen/v1"
    assert "opencode" in zen.strip_model_prefixes

    go = specs["opencode_go"]
    assert go.backend == "openai_compat"
    assert go.env_key == "OPENCODE_API_KEY"
    assert go.display_name == "OpenCode Go"
    assert go.is_gateway is True
    assert go.detect_by_base_keyword == "opencode.ai/zen/go"
    assert go.default_api_base == "https://opencode.ai/zen/go/v1"
    assert "opencode-go" in go.strip_model_prefixes


def test_find_by_name_opencode_providers() -> None:
    zen = find_by_name("opencode_zen")
    assert zen is not None
    assert zen.name == "opencode_zen"

    go = find_by_name("opencode-go")
    assert go is not None
    assert go.name == "opencode_go"


def test_opencode_forced_providers_use_default_api_base() -> None:
    zen_config = Config.model_validate(
        {
            "providers": {"opencodeZen": {"apiKey": "opencode-key"}},
            "agents": {"defaults": {"provider": "opencode_zen", "model": "opencode/o3"}},
        }
    )

    assert zen_config.get_provider_name() == "opencode_zen"
    assert zen_config.get_api_key() == "opencode-key"
    assert zen_config.get_api_base() == "https://opencode.ai/zen/v1"

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
        spec=find_by_name("opencode_zen"),
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
