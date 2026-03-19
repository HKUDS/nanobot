from nanobot.providers.litellm_provider import LiteLLMProvider


def test_kimi_coding_model_ref_is_rewritten_to_anthropic_messages() -> None:
    provider = LiteLLMProvider(default_model="kimi-coding/k2p5")

    assert provider._resolve_model("kimi-coding/k2p5") == "anthropic/k2p5"
    assert provider._resolve_model("kimi-coding/kimi-for-coding") == "anthropic/k2p5"


def test_kimi_coding_api_base_uses_kimi_coding_endpoint_when_moonshot_base_configured() -> None:
    provider = LiteLLMProvider(
        default_model="kimi-coding/k2p5",
        api_base="https://api.moonshot.cn/v1",
    )

    assert provider._resolve_api_base_for_model("kimi-coding/k2p5") == "https://api.kimi.com/coding"


def test_kimi_coding_api_base_strips_trailing_v1() -> None:
    provider = LiteLLMProvider(
        default_model="kimi-coding/k2p5",
        api_base="https://api.kimi.com/coding/v1/",
    )

    assert provider._resolve_api_base_for_model("kimi-coding/k2p5") == "https://api.kimi.com/coding"
