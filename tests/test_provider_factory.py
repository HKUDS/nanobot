from nanobot.config.schema import Config
from nanobot.providers.factory import create_provider


def test_create_provider_supports_minimax_via_anthropic_compatible_endpoint() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "minimax",
                    "model": "minimax/MiniMax-M2.5",
                }
            },
            "providers": {
                "anthropic": {
                    "apiKey": "mini-key",
                    "apiBase": "https://api.minimaxi.com/anthropic",
                }
            },
        }
    )

    provider = create_provider(config)

    assert provider.default_model == "anthropic/MiniMax-M2.5"
    assert provider.api_key == "mini-key"
    assert provider.api_base == "https://api.minimaxi.com/anthropic"
