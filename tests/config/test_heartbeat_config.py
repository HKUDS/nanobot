from nanobot.config.schema import HeartbeatConfig


def test_heartbeat_config_defaults() -> None:
    cfg = HeartbeatConfig()

    assert cfg.enabled is True
    assert cfg.interval_s == 30 * 60
    assert cfg.keep_recent_messages == 8
    assert cfg.eval_model_override is None
    assert cfg.exec_model_override is None


def test_heartbeat_config_accepts_eval_model_override_camel_case() -> None:
    cfg = HeartbeatConfig.model_validate({"evalModelOverride": "openai/gpt-4.1-mini"})

    assert cfg.eval_model_override == "openai/gpt-4.1-mini"


def test_heartbeat_config_accepts_eval_model_override_snake_case() -> None:
    cfg = HeartbeatConfig.model_validate({"eval_model_override": "openai/gpt-4.1-mini"})

    assert cfg.eval_model_override == "openai/gpt-4.1-mini"


def test_heartbeat_config_accepts_exec_model_override_camel_case() -> None:
    cfg = HeartbeatConfig.model_validate({"execModelOverride": "openai/gpt-4.1"})

    assert cfg.exec_model_override == "openai/gpt-4.1"


def test_heartbeat_config_accepts_exec_model_override_snake_case() -> None:
    cfg = HeartbeatConfig.model_validate({"exec_model_override": "openai/gpt-4.1"})

    assert cfg.exec_model_override == "openai/gpt-4.1"


def test_heartbeat_config_both_overrides_set_independently() -> None:
    cfg = HeartbeatConfig.model_validate({
        "evalModelOverride": "openai/gpt-4.1-mini",
        "execModelOverride": "openai/gpt-4.1",
    })

    assert cfg.eval_model_override == "openai/gpt-4.1-mini"
    assert cfg.exec_model_override == "openai/gpt-4.1"


def test_heartbeat_config_dumps_camel_case_aliases() -> None:
    cfg = HeartbeatConfig.model_validate({
        "evalModelOverride": "free-model",
        "execModelOverride": "paid-model",
    })

    dumped = cfg.model_dump(by_alias=True)

    assert dumped["evalModelOverride"] == "free-model"
    assert dumped["execModelOverride"] == "paid-model"
