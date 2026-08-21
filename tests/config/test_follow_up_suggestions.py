from nanobot.config.schema import Config


def test_follow_up_suggestions_default_disabled_and_uses_camel_case_alias() -> None:
    config = Config()

    assert config.follow_up_suggestions.enabled is False
    assert config.model_dump(mode="json", by_alias=True)["followUpSuggestions"] == {
        "enabled": False,
    }


def test_follow_up_suggestions_accepts_serialized_alias() -> None:
    config = Config.model_validate({"followUpSuggestions": {"enabled": True}})

    assert config.follow_up_suggestions.enabled is True
