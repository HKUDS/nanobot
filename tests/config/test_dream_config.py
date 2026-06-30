from nanobot.config.schema import DreamConfig


def test_dream_config_defaults_to_interval_hours() -> None:
    cfg = DreamConfig()

    assert cfg.interval_h == 2
    assert cfg.cron is None
    assert cfg.eager_consolidation is False
    assert cfg.eager_min_messages == 3
    assert cfg.eager_min_interval_s == 120
    assert cfg.eager_max_batch == 20


def test_dream_config_builds_every_schedule_from_interval() -> None:
    cfg = DreamConfig(interval_h=3)

    schedule = cfg.build_schedule("UTC")

    assert schedule.kind == "every"
    assert schedule.every_ms == 3 * 3_600_000
    assert schedule.expr is None


def test_dream_config_honors_legacy_cron_override() -> None:
    cfg = DreamConfig.model_validate({"cron": "0 */4 * * *"})

    schedule = cfg.build_schedule("UTC")

    assert schedule.kind == "cron"
    assert schedule.expr == "0 */4 * * *"
    assert schedule.tz == "UTC"
    assert cfg.describe_schedule() == "cron 0 */4 * * * (legacy)"


def test_dream_config_dump_preserves_legacy_cron_override() -> None:
    cfg = DreamConfig.model_validate({"intervalH": 5, "cron": "0 */4 * * *"})

    dumped = cfg.model_dump(by_alias=True)

    assert dumped["intervalH"] == 5
    assert dumped["cron"] == "0 */4 * * *"


def test_dream_config_dump_omits_empty_legacy_cron() -> None:
    dumped = DreamConfig().model_dump(by_alias=True)

    assert "cron" not in dumped


def test_dream_config_uses_model_override_name_and_accepts_legacy_model() -> None:
    cfg = DreamConfig.model_validate({"model": "openrouter/sonnet"})

    dumped = cfg.model_dump(by_alias=True)

    assert cfg.model_override == "openrouter/sonnet"
    assert dumped["modelOverride"] == "openrouter/sonnet"
    assert "model" not in dumped


def test_dream_config_accepts_eager_consolidation_camel_case() -> None:
    cfg = DreamConfig.model_validate(
        {
            "eagerConsolidation": True,
            "eagerMinMessages": 4,
            "eagerMinIntervalS": 30,
            "eagerMaxBatch": 12,
        }
    )

    dumped = cfg.model_dump(by_alias=True)

    assert cfg.eager_consolidation is True
    assert cfg.eager_min_messages == 4
    assert cfg.eager_min_interval_s == 30
    assert cfg.eager_max_batch == 12
    assert dumped["eagerConsolidation"] is True
    assert dumped["eagerMinMessages"] == 4
    assert dumped["eagerMinIntervalS"] == 30
    assert dumped["eagerMaxBatch"] == 12
