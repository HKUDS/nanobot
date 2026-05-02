from unittest.mock import patch

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider


def test_explicit_null_reasoning_effort_becomes_provider_disable_signal() -> None:
    config = Config.model_validate({
        "providers": {"xiaomiMimo": {"apiKey": "sk-test"}},
        "agents": {
            "defaults": {
                "provider": "xiaomi_mimo",
                "model": "mimo-pro",
                "reasoningEffort": None,
            }
        },
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert provider.generation.reasoning_effort == "none"


def test_omitted_reasoning_effort_preserves_provider_default() -> None:
    config = Config.model_validate({
        "providers": {"xiaomiMimo": {"apiKey": "sk-test"}},
        "agents": {
            "defaults": {
                "provider": "xiaomi_mimo",
                "model": "mimo-pro",
            }
        },
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = make_provider(config)

    assert provider.generation.reasoning_effort is None
