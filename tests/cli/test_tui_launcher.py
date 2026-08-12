import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.cli.agent import agent
from nanobot.cli.tui_launcher import (
    TuiUnavailableError,
    _authenticated_ws_url,
    _download_release_tui,
    _resolve_tui_command,
    _websocket_chat_id,
)
from nanobot.config.schema import Config


def test_authenticated_ws_url_preserves_existing_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.cli.tui_launcher.os.getpid", lambda: 42)
    url = _authenticated_ws_url(
        {"ws_url": "ws://127.0.0.1:8765/ws?mode=local", "token": "a b"}
    )
    assert url == "ws://127.0.0.1:8765/ws?mode=local&token=a+b&client_id=tui-42"


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("cli:direct", "tui-direct"),
        ("websocket:abc", "abc"),
        ("abc", "abc"),
    ],
)
def test_websocket_chat_id(session_id: str, expected: str | None) -> None:
    assert _websocket_chat_id(session_id) == expected


def test_explicit_tui_binary_must_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("NANOBOT_TUI_BIN", str(missing))
    with pytest.raises(TuiUnavailableError, match="does not exist"):
        _resolve_tui_command()


def test_interactive_agent_uses_native_tui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    config_path = tmp_path / "config.json"
    launched: dict[str, object] = {}

    def launch(*args: object, **kwargs: object) -> int:
        launched["args"] = args
        launched["kwargs"] = kwargs
        return 0

    monkeypatch.setattr("nanobot.cli.agent._load_runtime_config", lambda *_args: config)
    monkeypatch.setattr("nanobot.cli.tui_launcher.launch_tui", launch)
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("nanobot.cli.agent.sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("nanobot.cli.agent.sys.stdout", SimpleNamespace(isatty=lambda: True))

    agent(
        message=None,
        session_id="websocket:terminal-chat",
        workspace=None,
        config=None,
        markdown=True,
        logs=False,
        classic=False,
    )

    assert launched["args"] == (config,)
    assert launched["kwargs"] == {
        "config_path": config_path,
        "workspace_override": None,
        "session_id": "websocket:terminal-chat",
    }


def test_release_tui_is_verified_and_cached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = b"native-tui"
    digest = hashlib.sha256(binary).hexdigest().encode()
    downloads: list[str] = []

    def read_asset(url: str, *, max_bytes: int) -> bytes:
        downloads.append(url)
        return digest if url.endswith(".sha256") else binary

    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.tui_launcher._read_release_asset", read_asset)

    target = _download_release_tui("nanobot-tui-linux-x64")

    assert target == tmp_path / "bin" / "tui" / "9.9.9" / "nanobot-tui-linux-x64"
    assert target.read_bytes() == binary
    assert len(downloads) == 2

    assert _download_release_tui("nanobot-tui-linux-x64") == target
    assert len(downloads) == 2


def test_release_tui_rejects_bad_checksum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._read_release_asset",
        lambda url, *, max_bytes: b"0" * 64 if url.endswith(".sha256") else b"tampered",
    )

    with pytest.raises(TuiUnavailableError, match="checksum"):
        _download_release_tui("nanobot-tui-linux-x64")
