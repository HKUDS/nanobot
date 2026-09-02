import hashlib
import io
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

import nanobot.cli.tui_launcher as tui_launcher
from nanobot.cli.agent import agent
from nanobot.cli.tui_launcher import (
    TuiSessionError,
    TuiUnavailableError,
    _download_release_tui,
    _ensure_gateway,
    _initial_tui_chat_id,
    _initial_tui_workspace,
    _resolve_source_tui_command,
    _resolve_tui_command,
    _websocket_chat_id,
    launch_tui,
)
from nanobot.config.schema import Config, ModelPresetConfig


def _release_archive(
    asset: str,
    *,
    binary: bytes = b"native-tui",
    omit: str | None = None,
) -> tuple[bytes, bytes]:
    files = {
        asset: binary,
        **{name: f"contents of {name}\n".encode() for name in tui_launcher._TUI_RELEASE_FILES},
    }
    if omit:
        files.pop(omit)
    manifest = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n" for name, content in files.items()
    ).encode()
    files["MANIFEST.sha256"] = manifest
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    payload = output.getvalue()
    archive_name = f"{asset}.zip"
    checksum = f"{hashlib.sha256(payload).hexdigest()}  {archive_name}\n".encode()
    return payload, checksum


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
    with pytest.raises(TuiSessionError, match="only WebSocket sessions"):
        _websocket_chat_id("telegram:123")


def test_default_tui_starts_fresh_but_explicit_session_wins() -> None:
    assert _initial_tui_chat_id(None) is None
    assert _initial_tui_chat_id("websocket:chosen") == "chosen"


def test_default_tui_workspace_is_the_launch_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch_directory = tmp_path / "project"
    override = tmp_path / "override"
    launch_directory.mkdir()
    monkeypatch.chdir(launch_directory)

    assert _initial_tui_workspace(None) == launch_directory.resolve()
    assert _initial_tui_workspace(str(override)) == override.resolve()


def test_launcher_passes_the_canonical_model_preset_to_the_tui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config(
        channels={"websocket": {"tokenIssueSecret": "bootstrap-secret"}},
    )
    config.model_presets["Deep Research"] = ModelPresetConfig(model="openai/gpt-5.6")
    config.agents.defaults.model_preset = "Deep Research"
    captured: dict[str, str] = {}
    events: list[str] = []
    released: list[bool] = []

    class FakeLease:
        def release(self, *, wait_for_stop: bool = True) -> None:
            assert wait_for_stop is False
            released.append(True)

    monkeypatch.setattr("nanobot.cli.tui_launcher._resolve_tui_command", lambda: ["nanobot-tui"])
    def ensure_gateway(*args: object, **kwargs: object) -> SimpleNamespace:
        assert events == ["spawned"]
        assert kwargs["wait_until_ready"] is False
        return SimpleNamespace(
            base_url="http://127.0.0.1:8765",
            lease=FakeLease(),
        )

    monkeypatch.setattr("nanobot.cli.tui_launcher._ensure_gateway", ensure_gateway)

    class FakeProcess:
        def wait(self) -> int:
            events.append("waited")
            return 0

    def popen(command: list[str], *, env: dict[str, str]) -> FakeProcess:
        assert command == ["nanobot-tui"]
        captured.update(env)
        events.append("spawned")
        return FakeProcess()

    monkeypatch.setattr("nanobot.cli.tui_launcher.subprocess.Popen", popen)

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
    assert captured["NANOBOT_TUI_WORKSPACE"] == str(Path.cwd().resolve())
    assert captured["NANOBOT_TUI_BOOTSTRAP_URL"] == (
        "http://127.0.0.1:8765/webui/bootstrap"
    )
    assert captured["NANOBOT_TUI_HEALTH_URL"] == "http://127.0.0.1:18790/health"
    assert captured["NANOBOT_TUI_BOOTSTRAP_SECRET"] == "bootstrap-secret"
    assert "NANOBOT_TUI_WS_URL" not in captured
    assert "NANOBOT_TUI_API_TOKEN" not in captured
    assert "NANOBOT_TUI_CHAT_ID" not in captured
    assert "NANOBOT_TUI_STATE_PATH" not in captured
    assert events == ["spawned", "waited"]
    assert released == [True]


def test_launcher_terminates_the_tui_when_gateway_start_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    terminated: list[bool] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            terminated.append(True)

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 5
            return 1

    def fail_gateway(*args: object, **kwargs: object) -> None:
        raise RuntimeError("gateway failed")

    monkeypatch.setattr("nanobot.cli.tui_launcher._resolve_tui_command", lambda: ["nanobot-tui"])
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr("nanobot.cli.tui_launcher._ensure_gateway", fail_gateway)

    with pytest.raises(RuntimeError, match="gateway failed"):
        launch_tui(
            config,
            config_path=tmp_path / "config.json",
            workspace_override=None,
            session_id=None,
            theme="dark",
        )

    assert terminated == [True]


def test_launcher_keeps_the_tui_alive_while_an_existing_gateway_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    events: list[str] = []
    status_calls = 0

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            nonlocal status_calls
            status_calls += 1
            return SimpleNamespace(
                running=True,
                port=config.gateway.port,
                ready=False,
                log_path=tmp_path / "gateway.log",
            )

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminated")

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is None
            events.append("waited")
            return 0

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr("nanobot.cli.tui_launcher._resolve_tui_command", lambda: ["nanobot-tui"])
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._webui_endpoint_reachable",
        lambda _url: pytest.fail(
            "launcher must not probe readiness for a live recovering gateway"
        ),
    )
    monkeypatch.setattr(
        tui_launcher,
        "time",
        SimpleNamespace(
            monotonic=lambda: pytest.fail(
                "launcher must not wait for a live gateway to recover"
            ),
            sleep=lambda _seconds: pytest.fail(
                "launcher must not sleep for gateway recovery"
            ),
        ),
    )

    result = launch_tui(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=None,
        session_id=None,
        theme="auto",
    )

    assert result == 0
    assert status_calls == 1
    assert events == ["waited"]


def test_launcher_promotes_the_gateway_when_the_tui_detaches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    events: list[str] = []
    captured: dict[str, str] = {}

    class FakeLease:
        def mark_persistent(self) -> bool:
            events.append("promoted")
            return True

        def release(self, *, wait_for_stop: bool = True) -> None:
            assert wait_for_stop is False
            events.append("released")

    class FakeProcess:
        def wait(self) -> int:
            events.append("waited")
            return tui_launcher._TUI_DETACH_EXIT_CODE

    monkeypatch.setattr("nanobot.cli.tui_launcher._resolve_tui_command", lambda: ["nanobot-tui"])
    def popen(command: list[str], *, env: dict[str, str]) -> FakeProcess:
        assert command == ["nanobot-tui"]
        captured.update(env)
        return FakeProcess()

    monkeypatch.setattr("nanobot.cli.tui_launcher.subprocess.Popen", popen)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._ensure_gateway",
        lambda *args, **kwargs: SimpleNamespace(
            base_url="http://127.0.0.1:8765",
            lease=FakeLease(),
        ),
    )

    config_path = tmp_path / "custom config" / "config.json"
    workspace = tmp_path / "custom workspace"
    result = launch_tui(
        config,
        config_path=config_path,
        workspace_override=str(workspace),
        session_id=None,
        theme="auto",
    )

    assert result == 0
    assert events == ["waited", "promoted", "released"]
    assert captured["NANOBOT_TUI_GATEWAY_STOP_COMMAND"] == (
        f"nanobot gateway stop --config '{config_path}' --workspace '{workspace.resolve()}'"
    )


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


def test_source_checkout_does_not_fall_back_to_a_release_tui_without_bun(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "tui"
    source_dir.mkdir()
    monkeypatch.delenv("NANOBOT_TUI_BIN", raising=False)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._source_checkout_tui_dir",
        lambda: source_dir,
    )
    monkeypatch.setattr("nanobot.cli.tui_launcher.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._download_release_tui",
        lambda _asset: pytest.fail("a source checkout must not download a release TUI"),
    )

    with pytest.raises(TuiUnavailableError, match="source checkout requires Bun"):
        _resolve_tui_command()


def test_source_checkout_requires_project_and_tui_markers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    module_path = project_root / "nanobot" / "cli" / "tui_launcher.py"
    source_dir = project_root / "tui"
    module_path.parent.mkdir(parents=True)
    source_dir.mkdir()
    monkeypatch.setattr(tui_launcher, "__file__", str(module_path))

    assert tui_launcher._source_checkout_tui_dir() is None
    (source_dir / "package.json").write_text("{}", encoding="utf-8")
    assert tui_launcher._source_checkout_tui_dir() is None
    (project_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert tui_launcher._source_checkout_tui_dir() == source_dir


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


def test_native_tui_rejects_a_classic_session_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("nanobot.cli.agent._load_runtime_config", lambda *_args: Config())
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("nanobot.cli.agent.sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("nanobot.cli.agent.sys.stdout", SimpleNamespace(isatty=lambda: True))

    with pytest.raises(typer.BadParameter, match="only WebSocket sessions"):
        agent(
            message=None,
            session_id="cli:direct",
            workspace=None,
            config=None,
            markdown=True,
            logs=False,
            classic=False,
            theme="auto",
        )


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
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher.named_executable",
        lambda executable, **_kwargs: f"{executable}-named",
    )

    assert _resolve_source_tui_command(source_dir, bun) == [
        f"{bun}-named",
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
    asset = "nanobot-tui-linux-x64"
    binary = b"native-tui"
    archive, checksum = _release_archive(asset, binary=binary)
    downloads: list[str] = []

    def read_asset(url: str, *, max_bytes: int) -> bytes:
        downloads.append(url)
        return checksum if url.endswith(".sha256") else archive

    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.tui_launcher._read_release_asset", read_asset)

    target = _download_release_tui(asset)

    assert target == tmp_path / "bin" / "tui" / "9.9.9" / asset
    assert target.read_bytes() == binary
    for name in (*tui_launcher._TUI_RELEASE_FILES, "MANIFEST.sha256"):
        assert (target.parent / name).is_file()
    assert len(downloads) == 2

    assert _download_release_tui(asset) == target
    assert len(downloads) == 2


def test_release_tui_replaces_a_corrupted_cached_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = b"native-tui"
    asset = "nanobot-tui-linux-x64"
    archive, checksum = _release_archive(asset, binary=binary)
    downloads: list[str] = []

    def read_asset(url: str, *, max_bytes: int) -> bytes:
        downloads.append(url)
        return checksum if url.endswith(".sha256") else archive

    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.tui_launcher._read_release_asset", read_asset)

    target = _download_release_tui(asset)
    assert target is not None
    target.write_bytes(b"corrupted")

    assert _download_release_tui(asset) == target
    assert target.read_bytes() == binary
    assert len(downloads) == 4


def test_release_tui_replaces_corrupted_cached_notices(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = "nanobot-tui-linux-x64"
    archive, checksum = _release_archive(asset)
    downloads: list[str] = []

    def read_asset(url: str, *, max_bytes: int) -> bytes:
        downloads.append(url)
        return checksum if url.endswith(".sha256") else archive

    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.tui_launcher._read_release_asset", read_asset)

    target = _download_release_tui(asset)
    assert target is not None
    notices = target.parent / "THIRD_PARTY_NOTICES.txt"
    notices.write_text("corrupted", encoding="utf-8")

    assert _download_release_tui(asset) == target
    assert notices.read_bytes() == b"contents of THIRD_PARTY_NOTICES.txt\n"
    assert len(downloads) == 4


def test_release_tui_rejects_bad_checksum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = "nanobot-tui-linux-x64"
    archive, _checksum = _release_archive(asset)
    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._read_release_asset",
        lambda url, *, max_bytes: (
            f"{'0' * 64}  {asset}.zip\n".encode() if url.endswith(".sha256") else archive
        ),
    )

    with pytest.raises(TuiUnavailableError, match="checksum"):
        _download_release_tui(asset)


def test_release_tui_rejects_an_archive_without_required_notices(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = "nanobot-tui-linux-x64"
    archive, checksum = _release_archive(asset, omit="THIRD_PARTY_NOTICES.txt")
    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._read_release_asset",
        lambda url, *, max_bytes: checksum if url.endswith(".sha256") else archive,
    )

    with pytest.raises(TuiUnavailableError, match="archive is incomplete"):
        _download_release_tui(asset)


def test_release_tui_rejects_an_empty_required_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset = "nanobot-tui-linux-x64"
    archive, _checksum = _release_archive(asset)
    source = io.BytesIO(archive)
    output = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w") as rebuilt:
        for entry in original.infolist():
            content = b"" if entry.filename == "SOURCE_OFFER.md" else original.read(entry)
            rebuilt.writestr(entry.filename, content)
    payload = output.getvalue()
    checksum = f"{hashlib.sha256(payload).hexdigest()}  {asset}.zip\n".encode()

    monkeypatch.setattr("nanobot.cli.tui_launcher.__version__", "9.9.9")
    monkeypatch.setattr("nanobot.cli.tui_launcher.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._read_release_asset",
        lambda url, *, max_bytes: checksum if url.endswith(".sha256") else payload,
    )

    with pytest.raises(TuiUnavailableError, match="invalid size"):
        _download_release_tui(asset)


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
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._gateway_health_ready",
        lambda *_args, **_kwargs: True,
    )

    gateway = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=str(workspace),
    )

    assert gateway.base_url == "http://127.0.0.1:8765"


def test_gateway_reuse_returns_a_degraded_live_gateway_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    status_calls = 0

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            nonlocal status_calls
            status_calls += 1
            return SimpleNamespace(
                running=True,
                port=config.gateway.port,
                ready=False,
                log_path=tmp_path / "gateway.log",
            )

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._webui_endpoint_reachable",
        lambda _url: pytest.fail("non-blocking reuse must not probe readiness"),
    )
    monkeypatch.setattr(
        tui_launcher,
        "time",
        SimpleNamespace(
            monotonic=lambda: pytest.fail(
                "non-blocking reuse must not enter the readiness wait"
            ),
            sleep=lambda _seconds: pytest.fail("non-blocking reuse must not sleep"),
        ),
    )

    gateway = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=None,
        wait_until_ready=False,
    )

    assert gateway.base_url == "http://127.0.0.1:8765"
    assert gateway.lease is not None
    assert status_calls == 1
    gateway.lease.release(wait_for_stop=False)


def test_gateway_reuse_waits_for_a_live_gateway_to_recover_its_webui_listener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    endpoint_results = iter((False, False, True))

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(
                running=True,
                port=config.gateway.port,
                log_path=tmp_path / "gateway.log",
            )

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._webui_endpoint_reachable",
        lambda _url: next(endpoint_results),
    )
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._gateway_health_ready",
        lambda *_args, **_kwargs: True,
    )
    clock = iter((0.0, 0.0, 0.1))
    sleeps: list[float] = []
    monkeypatch.setattr(
        tui_launcher,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock), sleep=sleeps.append),
    )

    gateway = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=None,
    )

    assert gateway.base_url == "http://127.0.0.1:8765"
    assert gateway.lease is not None
    assert sleeps == [tui_launcher._GATEWAY_READY_POLL_S]
    gateway.lease.release(wait_for_stop=False)


def test_gateway_reuse_with_explicit_wait_rejects_a_live_but_unready_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()

    class FakeRuntime:
        def __init__(self, *, paths: object) -> None:
            self.paths = paths

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(
                running=True,
                port=config.gateway.port,
                log_path=tmp_path / "gateway.log",
            )

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._webui_endpoint_reachable",
        lambda _url: False,
    )
    clock = iter((0.0, tui_launcher._GATEWAY_READY_TIMEOUT_S))
    monkeypatch.setattr(
        tui_launcher,
        "time",
        SimpleNamespace(
            monotonic=lambda: next(clock),
            sleep=lambda _seconds: pytest.fail("expired readiness wait must not sleep"),
        ),
    )

    with pytest.raises(TuiUnavailableError, match="process is running.*listener is unavailable"):
        _ensure_gateway(
            config,
            config_path=tmp_path / "config.json",
            workspace_override=None,
        )


def test_gateway_started_for_tui_stops_when_its_last_lease_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Config()
    started = False
    stopped = False

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

        def start_on_demand(self, options: object) -> SimpleNamespace:
            from nanobot.gateway import GatewayClientLease

            GatewayClientLease(self, kind="test-tui").mark_ephemeral()
            return self.start_background(options)

        def stop(self, *, timeout_s: int) -> SimpleNamespace:
            nonlocal stopped
            assert timeout_s == 20
            stopped = True
            return SimpleNamespace(ok=True, message="gateway_stopped")

        _stop = stop

    monkeypatch.setattr("nanobot.gateway.GatewayRuntime", FakeRuntime)
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._webui_endpoint_reachable",
        lambda _url: started,
    )
    monkeypatch.setattr(
        "nanobot.cli.tui_launcher._gateway_health_ready",
        lambda *_args, **_kwargs: started,
    )

    gateway = _ensure_gateway(
        config,
        config_path=tmp_path / "config.json",
        workspace_override=None,
    )

    assert gateway.base_url == "http://127.0.0.1:8765"
    assert started is True
    assert gateway.lease is not None
    assert gateway.lease.release() is True
    assert stopped is True
