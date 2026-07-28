from nanobot.config.schema import Config


def test_extensions_can_be_disabled_globally() -> None:
    config = Config.model_validate({"extensions": {"enabled": False}})

    assert config.extensions.enabled is False
