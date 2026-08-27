from nanobot.config.schema import AgentDefaults


def test_legacy_memory_prompt_injection_defaults_off() -> None:
    assert AgentDefaults().legacy_memory_prompt_injection is False


def test_legacy_memory_prompt_injection_uses_camel_case_config_key() -> None:
    defaults = AgentDefaults.model_validate({"legacyMemoryPromptInjection": True})

    assert defaults.legacy_memory_prompt_injection is True
    assert defaults.model_dump(by_alias=True)["legacyMemoryPromptInjection"] is True
