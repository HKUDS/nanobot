"""Schema tests for AuxiliaryConfig (M1 Task D1)."""


def test_auxiliary_config_accepts_camelcase_alias():
    from nanobot.config.schema import AuxiliaryConfig

    aux = AuxiliaryConfig.model_validate({"modelPreset": "curator-aux"})
    assert aux.model_preset == "curator-aux"


def test_auxiliary_config_accepts_snake_case_field_name():
    from nanobot.config.schema import AuxiliaryConfig

    aux = AuxiliaryConfig.model_validate({"model_preset": "curator-aux"})
    assert aux.model_preset == "curator-aux"


def test_auxiliary_config_defaults_to_none():
    from nanobot.config.schema import AuxiliaryConfig

    aux = AuxiliaryConfig()
    assert aux.model_preset is None


def test_auxiliary_config_serialises_back_to_camelcase():
    from nanobot.config.schema import AuxiliaryConfig

    aux = AuxiliaryConfig(model_preset="curator-aux")
    dumped = aux.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"modelPreset": "curator-aux"}
