import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.cli import desktop_target, desktop_tui, tui_launcher
from nanobot.cli.desktop_target import DesktopReply, DesktopTargetError

DESKTOP_ID = "d4f6cc96-a3a2-4a68-9a45-cec04b79ab53"
GATEWAY_ID = "d4f6cc96-a3a2-4a68-9a45-cec04b79ab54"


def connection(**overrides):
    return {
        "protocolVersion": 1, "gatewayId": GATEWAY_ID,
        "apiUrl": "http://127.0.0.1:8765", "wsUrl": "ws://127.0.0.1:8765/ws",
        "wsToken": "synthetic-ws-token", "apiToken": "synthetic-api-token", **overrides,
    }


def target(**overrides):
    value = MagicMock(instance_id=DESKTOP_ID)
    value.request.return_value = DesktopReply("ready", frozenset({"tui"}), tui=connection(**overrides))
    return value


@pytest.mark.parametrize("overrides", [
    {"protocolVersion": True}, {"protocolVersion": 2}, {"gatewayId": "not-a-uuid"},
    {"wsUrl": "ws://evil.example/ws"}, {"apiUrl": "https://127.0.0.1:8765"},
    {"apiUrl": "http://localhost:8765"}, {"apiUrl": "http://127.0.0.1:0"},
    {"wsUrl": "ws://127.0.0.1:8766/ws"}, {"wsUrl": "ws://127.0.0.1:8765/ws?token=hidden"},
    {"wsUrl": "ws://user@127.0.0.1:8765/ws"}, {"wsUrl": "ws://127.0.0.1:8765/ws#fragment"},
    {"apiUrl": "http://127.0.0.1:8765/api"}, {"apiToken": ""}, {"wsToken": "secret\n"},
])
def test_resolver_rejects_unusable_or_unsafe_connection(monkeypatch, overrides):
    monkeypatch.setattr(desktop_tui, "discover_desktop_target", lambda: target(**overrides))
    with pytest.raises(DesktopTargetError):
        desktop_tui.resolve_request(json.dumps({"instanceId": DESKTOP_ID, "gatewayId": GATEWAY_ID}).encode())


def test_resolver_revalidates_both_instances_for_each_refresh(monkeypatch):
    chosen = target()
    monkeypatch.setattr(desktop_tui, "discover_desktop_target", lambda: chosen)
    request = json.dumps({"instanceId": DESKTOP_ID, "gatewayId": GATEWAY_ID}).encode()
    assert desktop_tui.resolve_request(request) == connection()
    assert desktop_tui.resolve_request(request) == connection()
    assert chosen.request.call_count == 2
    chosen.instance_id = "replacement"
    with pytest.raises(DesktopTargetError, match="disconnected"):
        desktop_tui.resolve_request(request)
    chosen.instance_id = DESKTOP_ID
    chosen.request.return_value = DesktopReply("ready", frozenset({"tui"}), tui=connection(gatewayId=DESKTOP_ID))
    with pytest.raises(DesktopTargetError, match="identity changed"):
        desktop_tui.resolve_request(request)


def test_launcher_has_no_gateway_ownership_and_no_credentials_in_child_env(monkeypatch):
    chosen = target()
    monkeypatch.setattr(tui_launcher, "resolve_tui_command", lambda: ["terminal-client"])
    monkeypatch.setattr(tui_launcher, "_ensure_gateway", lambda *a, **k: pytest.fail("must not own gateway"))
    monkeypatch.setenv("NANOBOT_TUI_GATEWAY_STOP_COMMAND", "forbidden stop")
    monkeypatch.setenv("NANOBOT_TUI_BOOTSTRAP_SECRET", "unrelated-bootstrap")
    monkeypatch.setenv("NANOBOT_TUI_WS_URL", "ws://unrelated")
    monkeypatch.delenv("NANOBOT_DESKTOP_CLIENT_CACHE", raising=False)
    calls = []
    process = MagicMock()
    process.wait.return_value = 90
    process.poll.return_value = 90
    def probe(args, **kw):
        assert args == ["terminal-client", "--desktop-protocol"]
        assert kw["stdin"] == subprocess.DEVNULL
        assert not any(key.startswith("NANOBOT_TUI_") for key in kw["env"])
        assert "unrelated-bootstrap" not in json.dumps((args, kw))
        return subprocess.CompletedProcess(args, 0, b"1\n", b"")
    monkeypatch.setattr(desktop_tui.subprocess, "run", probe)
    def start(args, **kw):
        calls.append((args, kw))
        return process
    monkeypatch.setattr(desktop_tui.subprocess, "Popen", start)
    assert desktop_tui.launch_desktop_tui(chosen) == 0
    args, options = calls[0]
    assert args == ["terminal-client"]
    env = options["env"]
    assert set(key for key in env if key.startswith("NANOBOT_TUI_")) == {
        "NANOBOT_TUI_DESKTOP_TARGET", "NANOBOT_TUI_DESKTOP_RESOLVER",
    }
    assert "synthetic" not in json.dumps((args, options))
    assert "unrelated-bootstrap" not in json.dumps((args, options))
    assert json.loads(env["NANOBOT_TUI_DESKTOP_TARGET"])["gatewayId"] == GATEWAY_ID
    resolver = json.loads(env["NANOBOT_TUI_DESKTOP_RESOLVER"])
    assert resolver[:3] == [sys.executable, "-I", "-S"]
    assert resolver[-1] == "--resolve"
    process.terminate.assert_not_called()


def test_protocol_probe_is_isolated_in_a_real_child(monkeypatch):
    # Older clients ignore --desktop-protocol and consume normal connection env.
    # Probe them without credentials or terminal input, before allowing launch.
    command = [sys.executable, "-I", "-S", "-c", """
import os, sys
keys = {key for key in os.environ if key.startswith('NANOBOT_TUI_')}
if sys.argv[-1] == '--desktop-protocol':
    if keys:
        sys.exit(7)
    if sys.stdin.buffer.read(1):
        sys.exit(8)
    print(1)
else:
    assert keys == {'NANOBOT_TUI_DESKTOP_TARGET', 'NANOBOT_TUI_DESKTOP_RESOLVER'}
    sys.exit(90)
"""]
    monkeypatch.setattr(tui_launcher, "resolve_tui_command", lambda: command)
    monkeypatch.delenv("NANOBOT_DESKTOP_CLIENT_CACHE", raising=False)
    monkeypatch.setenv("NANOBOT_TUI_BOOTSTRAP_URL", "http://127.0.0.1:1/webui/bootstrap")
    monkeypatch.setenv("NANOBOT_TUI_BOOTSTRAP_SECRET", "unrelated-bootstrap")
    monkeypatch.setenv("NANOBOT_TUI_DESKTOP_RESOLVER", "unrelated-resolver")
    assert desktop_tui.launch_desktop_tui(target()) == 0


def test_unsupported_desktop_does_not_install_or_launch_a_client(monkeypatch):
    chosen = target()
    chosen.request.return_value = DesktopReply("ready", frozenset({"webui"}))
    monkeypatch.setattr(tui_launcher, "resolve_tui_command", lambda: pytest.fail("unsupported target"))
    with pytest.raises(DesktopTargetError):
        desktop_tui.launch_desktop_tui(chosen)


def test_incompatible_tui_fails_without_fallback(monkeypatch):
    monkeypatch.setattr(tui_launcher, "resolve_tui_command", lambda: ["old-client"])
    monkeypatch.setattr(desktop_tui.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1, b"", b""))
    monkeypatch.setattr(desktop_tui.subprocess, "Popen", lambda *a, **kw: pytest.fail("cannot start client"))
    with pytest.raises(DesktopTargetError, match="does not support"):
        desktop_tui.launch_desktop_tui(target())


def test_bare_command_uses_attachment_and_preserves_return_code(monkeypatch):
    chosen = target()
    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", lambda: chosen)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda status: "desktop")
    monkeypatch.setattr(desktop_tui, "launch_desktop_tui", lambda selected: 17 if selected is chosen else 99)
    assert desktop_target.dispatch_bare_desktop_target([]) == 17


def test_standalone_resolver_is_silent_on_invalid_input(tmp_path):
    script = str(Path(desktop_tui.__file__).resolve())
    result = subprocess.run([sys.executable, "-I", "-S", script, "--resolve"],
                            input=b'{"apiToken":"synthetic"}\n', capture_output=True, timeout=5)
    assert result.returncode == 3
    assert result.stdout == result.stderr == b""
    with (tmp_path / "not-a-pipe").open("wb") as output:
        result = subprocess.run([sys.executable, "-I", "-S", script, "--resolve"],
                                input=b"{}\n", stdout=output, stderr=subprocess.PIPE, timeout=5)
    assert result.returncode == 3
    assert (tmp_path / "not-a-pipe").read_bytes() == b""


@pytest.mark.skipif(os.name != "posix", reason="Bun Unix socket-pair stdout")
def test_resolver_output_accepts_only_anonymous_ipc(tmp_path):
    first, second = socket.socketpair()
    with first, second:
        assert desktop_tui._anonymous_output(first.fileno())
    read_fd, write_fd = os.pipe()
    try:
        assert desktop_tui._anonymous_output(write_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)
    with (tmp_path / "file").open("wb") as file:
        assert not desktop_tui._anonymous_output(file.fileno())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with socket.create_connection(listener.getsockname()) as client:
            peer, _ = listener.accept()
            with peer:
                assert not desktop_tui._anonymous_output(client.fileno())


@pytest.mark.parametrize("args", [["--config", "elsewhere"], ["gateway", "stop"], ["--help"], ["webui"]])
def test_desktop_only_entry_never_forwards_unknown_commands(args, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nanobot-desktop-tui", *args])
    monkeypatch.setattr(desktop_tui, "discover_desktop_target", lambda: pytest.fail("explicit command"))
    with pytest.raises(SystemExit) as error:
        desktop_tui.main()
    assert error.value.code == 2


def test_desktop_cache_avoids_default_python_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOBOT_DESKTOP_CLIENT_CACHE", str(tmp_path))
    observed = []
    def resolve(**kwargs):
        observed.append(kwargs)
        raise tui_launcher.TuiUnavailableError("not installed")
    monkeypatch.setattr(tui_launcher, "resolve_tui_command", resolve)
    with pytest.raises(DesktopTargetError):
        desktop_tui.launch_desktop_tui(target())
    assert observed == [{"data_dir": tmp_path}]
