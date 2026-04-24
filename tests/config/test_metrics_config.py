from nanobot.config.schema import GatewayConfig


def test_gateway_metrics_enabled_defaults_to_false() -> None:
    cfg = GatewayConfig()

    assert cfg.metrics_enabled is False


def test_gateway_metrics_enabled_accepts_camel_case_alias() -> None:
    cfg = GatewayConfig.model_validate({"metricsEnabled": True})

    assert cfg.metrics_enabled is True


def test_gateway_metrics_enabled_dumps_with_camel_case_alias() -> None:
    cfg = GatewayConfig(metrics_enabled=True)

    dumped = cfg.model_dump(by_alias=True)

    assert dumped["metricsEnabled"] is True
