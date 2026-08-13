import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.cli.agent import agent
from nanobot.cli.tui_launcher import (
    TuiUnavailableError,
    _authenticated_ws_url,
    _download_release_tui,
    _ensure_gateway,
    _initial_tui_chat_id,
    _read_tui_chat_id,
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


def test_tui_chat_state_is_optional_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "tui" / "state.json"
    assert _read_tui_chat_id(path) is None

    path.parent.mkdir()
    path.write_text('{"schema_version": 1, "chat_id": "saved-chat"}', encoding="utf-8")
    assert _read_tui_chat_id(path) == "saved-chat"

    path.write_text('{"chat_id": "bad\\nchat"}', encoding="utf-8")
    assert _read_tui_chat_id(path) is None


def test_default_tui_resumes_but_explicit_session_wins(tmp_path: Path) -> None:
    path = tmp_path / "tui" / "state.json"
    path.parent.mkdir()
    path.write_text('{"chat_id": "saved-chat"}', encoding="utf-8")

    assert _initial_tui_chat_id(None, path) == "saved-chat"
    assert _initial_tui_chat_id("cli:direct", path) == "tui-direct"
    assert _initial_tui_chat_id("websocket:chosen", path) == "chosen"


def test_explicit_tui_binary_must_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("NANOBOT_TUI_BIN", str(missing))
    with pytest.raises(TuiUnavailableError, match="does not exist"):
        _resolve_tui_command()


def test_windows_arm64_uses_the_classic_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NANOBOT_TUI_BIN", raising=False)
    monkeypatch.setattr("nanobot.cli.tui_launcher.platform.system", lambda: "Windows")
    monkeypatch.setattr("nanobot.cli.tui_launcher.platform.machine", lambda: "ARM64")

    with pytest.raises(TuiUnavailableError, match="Windows ARM64"):
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
        theme="light",
    )

    assert launched["args"] == (config,)
    assert launched["kwargs"] == {
        "config_path": config_path,
        "workspace_override": None,
        "session_id": "websocket:terminal-chat",
        "theme": "light",
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
    assert target.with_name(f"{target.name}.sha256").read_text().startswith(digest.decode())
    assert len(downloads) == 2

    assert _download_release_tui("nanobot-tui-linux-x64") == target
    assert len(downloads) == 2


def test_release_tui_replaces_a_corrupted_cached_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = b"native-tui"
    digest = hashlib.sha256(binary).hexdigest().encode()
    asset = "nanobot-tui-linux-x64"
    target = tmp_path / "bin" / "tui" / "9.9.9" / asset
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupted")
    target.with_name(f"{target.name}.sha256").write_text(
        f"{hashlib.sha256(binary).hexdigest()}  {asset}\n"
    )
    downloads: list[str] = []

    def read_asset(url: str, *, max_bytes: int) -> bytes:
        downloads.append(url)
        return digest if url.endswith(".sha256") else binary

    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.tui_launcher._read_release_asset", read_asset)

    assert _download_release_tui(asset) == target
    assert target.read_bytes() == binary
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


def test_gateway_reuse_requires_the_matching_managed_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config.agents.defaults.workspace = str(workspace)

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(running=False, port=None)

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr("nanobot.cli.tui_launcher._webui_endpoint_reachable", lambda _url: True)

    with pytest.raises(TuiUnavailableError, match="different nanobot instance"):
        _ensure_gateway(
            config,
            config_path=tmp_path / "config.json",
            workspace_override=str(workspace),
        )


def test_gateway_reuses_the_matching_managed_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config.agents.defaults.workspace = str(workspace)
    runtime: object | None = None

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            nonlocal runtime
            self.paths = paths
            runtime = self

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(running=True, port=config.gateway.port)

        def stop(self, *, timeout_s: int) -> None:
            raise AssertionError(f"unowned gateway stopped with timeout {timeout_s}")

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr("nanobot.cli.tui_launcher._webui_endpoint_reachable", lambda _url: True)

    lease = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=str(workspace),
    )

    assert lease.runtime is runtime
    assert lease.owned is False
    lease.close()
