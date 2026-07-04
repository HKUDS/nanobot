from blackcat.config.schema import Config, ProviderConfig
from blackcat.providers.factory import _provider_extra_headers, provider_signature
from blackcat.providers.registry import find_by_name


def test_kimi_coding_uses_default_user_agent_header() -> None:
    spec = find_by_name("kimi_coding")

    assert spec is not None
    assert _provider_extra_headers(spec, ProviderConfig()) == {
        "User-Agent": "claude-code/0.1.0",
    }


def test_provider_config_extra_headers_override_defaults() -> None:
    spec = find_by_name("kimi_coding")
    provider = ProviderConfig.model_validate({
        "extraHeaders": {
            "User-Agent": "custom-client/1.0",
            "X-Test": "1",
        },
    })

    assert _provider_extra_headers(spec, provider) == {
        "User-Agent": "custom-client/1.0",
        "X-Test": "1",
    }


def test_provider_signature_tracks_default_extra_headers() -> None:
    config = Config.model_validate({
        "providers": {
            "kimiCoding": {
                "apiKey": "sk-kimi-test",
            },
        },
        "modelPresets": {
            "primary": {
                "provider": "kimi_coding",
                "model": "kimi-for-coding",
            },
        },
        "agents": {
            "defaults": {
                "modelPreset": "primary",
            },
        },
    })

    assert {"User-Agent": "claude-code/0.1.0"} in provider_signature(config)
