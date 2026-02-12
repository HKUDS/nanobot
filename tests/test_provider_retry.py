from nanobot.providers.litellm_provider import LiteLLMProvider


def test_is_transient_network_error_detects_connection_reset() -> None:
    provider = LiteLLMProvider(default_model="ollama/gpt-oss", provider_name="ollama_cloud")

    err = Exception("litellm.APIConnectionError: Connection reset by peer")
    assert provider._is_transient_network_error(err) is True


def test_is_transient_network_error_ignores_non_network_errors() -> None:
    provider = LiteLLMProvider(default_model="ollama/gpt-oss", provider_name="ollama_cloud")

    err = Exception("NotFoundError: model not found")
    assert provider._is_transient_network_error(err) is False
