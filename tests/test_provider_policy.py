from nanobot.providers.litellm_provider import LiteLLMProvider


def test_llm_policy_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_LLM_MAX_RETRIES", "9")
    monkeypatch.setenv("NANOBOT_LLM_RETRY_BASE_DELAY_SEC", "9")
    monkeypatch.setenv("NANOBOT_LLM_RETRY_MAX_DELAY_SEC", "9")
    monkeypatch.setenv("NANOBOT_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("NANOBOT_LLM_FALLBACK_RETRYABLE_ONLY", "true")

    provider = LiteLLMProvider(
        default_model="openai/gpt-4o-mini",
        llm_policy={
            "retry": {
                "max_retries": 1,
                "base_delay_sec": 0.2,
                "max_delay_sec": 0.4,
            },
            "fallback": {
                "enabled": False,
                "retryable_errors_only": False,
            },
        },
    )

    assert provider._retry_settings() == (1, 0.2, 0.4)
    assert provider._fallback_settings() == (False, False)


def test_retryable_status_codes_can_be_configured(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_LLM_RETRYABLE_STATUS_CODES", raising=False)

    provider = LiteLLMProvider(
        default_model="openai/gpt-4o-mini",
        llm_policy={"retry": {"retryable_status_codes": [418]}},
    )

    class TeapotError(Exception):
        status_code = 418

    class InternalError(Exception):
        status_code = 500

    assert provider._is_retryable_error(TeapotError("teapot"))
    assert not provider._is_retryable_error(InternalError("internal"))
