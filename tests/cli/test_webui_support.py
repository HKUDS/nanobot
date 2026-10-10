from types import SimpleNamespace

import pytest

from nanobot.cli.webui_support import _prepare_webui_bundle_for_gateway
from nanobot.config.schema import Config


@pytest.mark.parametrize("authentication", [
    {"token": "existing-token"},
    {"tokenIssueSecret": "old-random-password"},
    {"trustedProxyAuth": {"trustedPeerCidrs": ["127.0.0.1/32"], "assertionHeader": "X-Identity"}},
])
def test_webui_setup_preserves_existing_auth_and_custom_bind(authentication) -> None:
    from nanobot.cli.webui_support import _ensure_local_webui_channel

    config = Config(channels={"websocket": {
        "enabled": False, "host": "192.168.1.42", **authentication,
    }})
    assert _ensure_local_webui_channel(config, port=9888, yes=True)
    saved = config.channels.websocket
    assert saved["enabled"] is True
    assert saved["host"] == "192.168.1.42"
    assert saved["port"] == 9888
    for field, value in authentication.items():
        assert saved[field] == value


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param("warn", id="source_checkout_preserves_warn_only_gateway_startup"),
        pytest.param("skip", id="skip_mode_does_not_build_the_source_webui_bundle"),
    ],
)
def test_source_checkout_respects_webui_build_mode(monkeypatch, mode) -> None:
    modes: list[str] = []
    monkeypatch.setattr(
        "nanobot.cli.webui_support.inspect_webui_bundle",
        lambda: SimpleNamespace(source_available=True),
    )
    monkeypatch.setattr("nanobot.cli.webui_support._webui_channel_enabled", lambda _config: True)
    monkeypatch.setattr(
        "nanobot.cli.webui_support.ensure_webui_bundle",
        lambda **kwargs: modes.append(kwargs["mode"]),
    )

    _prepare_webui_bundle_for_gateway(Config(), mode=mode)

    assert modes == [mode]
