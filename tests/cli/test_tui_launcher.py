import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from nanobot.cli.agent import agent
from nanobot.cli.tui_launcher import (
    TuiUnavailableError,
    _authenticated_ws_url,
    _download_release_tui,
    _ensure_gateway,
    _initial_tui_chat_id,
    _read_tui_chat_id,
    _resolve_source_tui_command,
    _resolve_tui_command,
    _websocket_chat_id,
    launch_tui,
)
from nanobot.config.schema import Config, ModelPresetConfig


def test_authenticated_ws_url_preserves_existing_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.cli.tui_launcher.os.getpid", lambda: 42)
    url = _authenticated_ws_url(
        {"ws_url": "ws://127.0.0.1:8765/ws?mode=local", "token": "a b"}
    )
    assert url == "ws://127.0.0.1:8765/ws?mode=local&token=a+b&client_id=tui-42"


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("websocket:abc", "abc"),
        ("abc", "abc"),
    ],
)
def test_websocket_chat_id(session_id: str, expected: str | None) -> None:
    assert _websocket_chat_id(session_id) == expected


def test_native_tui_rejects_a_session_owned_by_another_channel() -> None:
    with pytest.raises(TuiUnavailableError, match="only WebSocket sessions"):
        _websocket_chat_id("telegram:123")


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
    assert _initial_tui_chat_id("websocket:chosen", path) == "chosen"

    path.unlink()
    assert _initial_tui_chat_id(None, path) == "tui-direct"


def test_launcher_passes_the_canonical_model_preset_to_the_tui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    config.model_presets["Deep Research"] = ModelPresetConfig(model="openai/gpt-5.6")
    config.agents.defaults.model_preset = "Deep Research"
    captured: dict[str, str] = {}

    monkeypatch.setattr("nanobot.cli.tui_launcher._resolve_tui_command", lambda: ["nanobot-tui"])
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._ensure_gateway",
        lambda *args, **kwargs: SimpleNamespace(
            base_url="http://127.0.0.1:8765",
        ),
    )
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._fetch_bootstrap",
        lambda *args, **kwargs: {
            "ws_url": "ws://127.0.0.1:8765/ws",
            "token": "socket-token",
            "api_token": "api-token",
        },
    )

    def run(command: list[str], *, env: dict[str, str], check: bool) -> subprocess.CompletedProcess:
        assert command == ["nanobot-tui"]
        assert check is False
        captured.update(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("nanobot.cli.tui_launcher.subprocess.run", run)

    result = launch_tui(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=None,
        session_id=None,
        theme="auto",
    )

    assert result == 0
    assert captured["NANOBOT_TUI_MODEL"] == "openai/gpt-5.6"
    assert captured["NANOBOT_TUI_MODEL_PRESET"] == "Deep Research"


def test_explicit_tui_binary_must_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("NANOBOT_TUI_BIN", str(missing))
    with pytest.raises(TuiUnavailableError, match="does not exist"):
        _resolve_tui_command()


def test_windows_arm64_fails_instead_of_using_the_classic_prompt(
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


def test_interactive_agent_does_not_silently_fall_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    output: list[str] = []

    def unavailable(*_args: object, **_kwargs: object) -> int:
        raise TuiUnavailableError("missing sidecar")

    monkeypatch.setattr("nanobot.cli.agent._load_runtime_config", lambda *_args: config)
    monkeypatch.setattr("nanobot.cli.agent.console.print", lambda value: output.append(value))
    monkeypatch.setattr("nanobot.cli.tui_launcher.launch_tui", unavailable)
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("nanobot.cli.agent.sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("nanobot.cli.agent.sys.stdout", SimpleNamespace(isatty=lambda: True))

    with pytest.raises(typer.Exit) as exc_info:
        agent(
            message=None,
            session_id=None,
            workspace=None,
            config=None,
            markdown=True,
            logs=False,
            classic=False,
            theme="auto",
        )

    assert exc_info.value.exit_code == 1
    assert output == [
        "[red]Native TUI unavailable: missing sidecar[/red]",
        "[dim]Use `nanobot agent --classic` only if you want the old prompt.[/dim]",
    ]


def test_default_agent_does_not_fall_back_outside_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.cli.agent._load_runtime_config", lambda *_args: Config())
    monkeypatch.setattr("nanobot.cli.agent.sys.stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr("nanobot.cli.agent.sys.stdout", SimpleNamespace(isatty=lambda: True))

    with pytest.raises(typer.BadParameter, match="requires an interactive terminal"):
        agent(
            message=None,
            session_id=None,
            workspace=None,
            config=None,
            markdown=True,
            logs=False,
            classic=False,
            theme="auto",
        )


@pytest.mark.parametrize(
    ("markdown", "logs", "option"),
    [
        (False, False, "--no-markdown"),
        (True, True, "--logs"),
    ],
)
def test_classic_options_require_an_explicit_classic_prompt(
    monkeypatch: pytest.MonkeyPatch,
    markdown: bool,
    logs: bool,
    option: str,
) -> None:
    monkeypatch.setattr("nanobot.cli.agent._load_runtime_config", lambda *_args: Config())
    monkeypatch.setattr("nanobot.cli.agent.sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("nanobot.cli.agent.sys.stdout", SimpleNamespace(isatty=lambda: True))

    with pytest.raises(typer.BadParameter, match=f"{option} requires --classic"):
        agent(
            message=None,
            session_id=None,
            workspace=None,
            config=None,
            markdown=markdown,
            logs=logs,
            classic=False,
            theme="auto",
        )


def test_source_checkout_refreshes_locked_tui_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "tui"
    source_dir.mkdir()
    (source_dir / "node_modules" / "@opentui" / "core").mkdir(parents=True)
    bun = str(tmp_path / "bun")

    def install(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == [bun, "install", "--frozen-lockfile"]
        assert kwargs["cwd"] == source_dir
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("nanobot.cli.tui_launcher.subprocess.run", install)

    assert _resolve_source_tui_command(source_dir, bun) == [
        bun,
        str(source_dir / "src" / "index.ts"),
    ]


def test_source_checkout_fails_when_locked_dependencies_cannot_be_refreshed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "tui"
    source_dir.mkdir()
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "lockfile mismatch"),
    )

    with pytest.raises(TuiUnavailableError, match="lockfile mismatch"):
        _resolve_source_tui_command(source_dir, "bun")


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

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(running=True, port=config.gateway.port)

        def stop(self, *, timeout_s: int) -> None:
            raise AssertionError(f"unowned gateway stopped with timeout {timeout_s}")

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr("nanobot.cli.tui_launcher._webui_endpoint_reachable", lambda _url: True)

    gateway = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=str(workspace),
    )

    assert gateway.base_url == "http://127.0.0.1:8765"


def test_gateway_started_for_tui_remains_shared_after_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    started = False

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(
                running=started,
                port=config.gateway.port if started else None,
            )

        def start_background(self, _options: object) -> SimpleNamespace:
            nonlocal started
            started = True
            return SimpleNamespace(
                ok=True,
                message="gateway_started",
                status=SimpleNamespace(log_path=tmp_path / "gateway.log"),
            )

        def stop(self, *, timeout_s: int) -> None:
            raise AssertionError(f"shared gateway stopped with timeout {timeout_s}")

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._webui_endpoint_reachable",
        lambda _url: started,
    )

    gateway = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=None,
    )

    assert gateway.base_url == "http://127.0.0.1:8765"
    assert started is True
