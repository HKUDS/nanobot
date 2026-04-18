from nanobot.config.schema import GatewayConfig


def test_gateway_config_lifecycle_hooks_default_to_none() -> None:
    cfg = GatewayConfig()

    assert cfg.on_start is None
    assert cfg.on_stop is None


def test_gateway_config_accepts_lifecycle_hook_strings() -> None:
    cfg = GatewayConfig.model_validate({
        "onStart": "Gateway 已启动 🟢",
        "onStop": "Gateway 已停止 🔴",
    })

    assert cfg.on_start == "Gateway 已启动 🟢"
    assert cfg.on_stop == "Gateway 已停止 🔴"


def test_gateway_config_dumps_lifecycle_hooks_with_camel_case_aliases() -> None:
    cfg = GatewayConfig(on_start="ready", on_stop="bye")

    dumped = cfg.model_dump(by_alias=True)

    assert dumped["onStart"] == "ready"
    assert dumped["onStop"] == "bye"
