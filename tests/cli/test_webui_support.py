import os
import shlex
import sys
import webbrowser
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from rich.console import Console

from nanobot.cli import webui_support
from nanobot.cli.webui_support import _prepare_webui_bundle_for_gateway
from nanobot.config.schema import Config


@pytest.mark.parametrize("authentication", [
    {"token": "existing-token"},
    {"tokenIssueSecret": "old-random-password"},
    {"tokenIssueSecret": "${WEBUI_PASSWORD}"},
    {"trustedProxyAuth": {"trustedPeerCidrs": ["127.0.0.1/32"], "assertionHeader": "X-Identity"}},
])
def test_webui_setup_preserves_existing_auth_and_custom_bind(monkeypatch, authentication) -> None:
    from nanobot.cli.webui_support import _ensure_local_webui_channel

    monkeypatch.setenv("WEBUI_PASSWORD", "env-password")
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
    assert not saved.get("tokenIssueSecretGenerated", False)
    if "trustedProxyAuth" in authentication:
        assert not saved.get("tokenIssueSecret")


def test_webui_setup_generates_a_credential_once_for_an_enabled_local_channel() -> None:
    config = Config(channels={"websocket": {"enabled": True, "host": "127.0.0.1"}})

    assert webui_support._ensure_local_webui_channel(config, port=None, yes=True)
    saved = dict(config.channels.websocket)
    assert len(saved["tokenIssueSecret"]) >= 32
    assert saved["tokenIssueSecretGenerated"] is True
    assert not webui_support._ensure_local_webui_channel(config, port=None, yes=False)
    assert config.channels.websocket == saved


@pytest.mark.parametrize("width", [32, 100])
def test_webui_ready_keeps_the_complete_login_url_copyable(monkeypatch, width: int) -> None:
    output = StringIO()
    monkeypatch.setattr(webui_support, "console", Console(file=output, width=width))
    password = "local/中文+#?" * 5
    config = Config(channels={"websocket": {"tokenIssueSecret": password}})
    url = webui_support._webui_browser_url(config)
    config_path = Path("/srv/nanobot/config.json")

    webui_support._print_webui_ready(
        config, config_path, url, workspace=None, dev=False, managed=True,
    )

    lines = output.getvalue().splitlines()
    assert f"http://127.0.0.1:8765/#/?bootstrapSecret={quote(password, safe='')}" in lines
    assert "Page: http://127.0.0.1:8765" in lines
    assert lines.index(url) < lines.index("Page: http://127.0.0.1:8765")
    assert lines[lines.index(url) - 1] == "Open in your browser:"
    assert output.getvalue().count("bootstrapSecret=") == 1
    assert "Open in your browser:" in output.getvalue()
    assert f"Config: {config_path}" in lines
    log_command = next(line.removeprefix("Logs: ") for line in lines if line.startswith("Logs: "))
    assert shlex.split(log_command) == ["nanobot", "gateway", "logs", "--config", str(config_path)]


def test_unix_browser_reports_delayed_launcher_failure_without_raw_output(monkeypatch, tmp_path, capfd) -> None:
    launcher = tmp_path / "failing_browser.py"
    launcher.write_text(
        "import sys, time\n"
        "time.sleep(0.1)\n"
        "print('launcher stdout: ' + sys.argv[-1])\n"
        "print('gio: ' + sys.argv[-1] + ': Operation not supported', file=sys.stderr)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    browser = webbrowser.BackgroundBrowser([sys.executable, str(launcher), "%s"])
    monkeypatch.setattr(webui_support.sys, "platform", "linux")
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setattr(webui_support.webbrowser, "get", lambda _choice=None: browser)

    assert not webui_support._open_webui_browser(
        "http://127.0.0.1:8765/#/?bootstrapSecret=private-test-credential", wait=False,
    )

    captured = capfd.readouterr()
    assert "Could not open a browser automatically." in captured.out
    assert "Open the link above." in " ".join(captured.out.split())
    assert "private-test-credential" not in captured.out + captured.err
    assert "Operation not supported" not in captured.out + captured.err
    assert "launcher stdout" not in captured.out + captured.err


def test_unix_browser_preserves_custom_commands_and_candidate_order(monkeypatch, tmp_path) -> None:
    launcher = tmp_path / "custom browser.py"
    result = tmp_path / "received.txt"
    launcher.write_text(
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = shlex.join([sys.executable, str(launcher), str(result), "%s"])
    monkeypatch.setenv("BROWSER", f"unavailable-nanobot-test-browser{os.pathsep}{command}")
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    monkeypatch.setattr(webbrowser, "_tryorder", None)
    monkeypatch.setattr(webbrowser, "_browsers", {})
    monkeypatch.setattr(webui_support.sys, "platform", "linux")
    url = "http://127.0.0.1:8765/#/?bootstrapSecret=custom%20password"

    assert webui_support._launch_browser(url)
    assert result.read_text(encoding="utf-8") == url


def test_unix_browser_keeps_native_controller_new_tab_behavior(monkeypatch) -> None:
    opened = []
    controller = SimpleNamespace(open=lambda url, **options: opened.append((url, options)) or True)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setattr(webui_support.webbrowser, "get", lambda _choice=None: controller)

    assert webui_support._launch_unix_browser("http://127.0.0.1:8765/")
    assert opened == [("http://127.0.0.1:8765/", {"new": 2, "autoraise": True})]


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
