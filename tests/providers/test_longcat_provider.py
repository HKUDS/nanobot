from nanobot.config.schema import ProvidersConfig
from nanobot.providers.registry import find_by_name


def test_longcat_config_field_exists():
    config = ProvidersConfig()
    assert hasattr(config, "longcat")


def test_longcat_provider_in_registry():
    longcat = find_by_name("longcat")
    assert longcat is not None
    assert longcat.name == "longcat"
    assert longcat.backend == "openai_compat"
    assert longcat.env_key == "LONGCAT_API_KEY"
    assert longcat.default_api_base == "https://api.longcat.chat/openai/v1"
