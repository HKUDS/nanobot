import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from nanobot.cli import desktop_target
from nanobot.cli.desktop_target import (
    DesktopReply,
    DesktopTarget,
    DesktopTargetError,
    _desktop_webui_url,
    _parse_descriptor,
    _parse_reply,
    discover_desktop_target,
    dispatch_bare_desktop_target,
)


def _write_descriptor(directory: Path, *, instance_id: str, transport: str, address: str) -> None:
    directory.mkdir(mode=0o700)
    descriptor = directory / "instance-v1.json"
    descriptor.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "instanceId": instance_id,
                "transport": transport,
                "address": address,
            }
        ),
        encoding="utf-8",
    )
    descriptor.chmod(0o600)


def test_macos_discovery_uses_private_versioned_descriptor(monkeypatch, tmp_path: Path) -> None:
    instance_id = "0b47107a-cd31-4711-b1ca-3b53dcedf90a"
    terminal = tmp_path / "terminal"
    address = str(terminal / "connect-v1.sock")
    _write_descriptor(
        terminal,
        instance_id=instance_id,
        transport="unix",
        address=address,
    )
    monkeypatch.setattr(desktop_target.sys, "platform", "darwin")
    monkeypatch.setenv("NANOBOT_DESKTOP_ROOT", str(tmp_path))

    assert discover_desktop_target() == DesktopTarget(instance_id, "unix", address)


def test_relative_desktop_root_matches_absolute_advertised_address(monkeypatch, tmp_path):
    instance_id = "0b47107a-cd31-4711-b1ca-3b53dcedf90a"
    terminal = tmp_path / "terminal"
    address = str(terminal / "connect-v1.sock")
    _write_descriptor(terminal, instance_id=instance_id, transport="unix", address=address)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(desktop_target.sys, "platform", "darwin")
    monkeypatch.setenv("NANOBOT_DESKTOP_ROOT", ".")
    assert discover_desktop_target() == DesktopTarget(instance_id, "unix", address)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_discovery_rejects_non_private_directory(monkeypatch, tmp_path: Path) -> None:
    instance_id = "0b47107a-cd31-4711-b1ca-3b53dcedf90a"
    terminal = tmp_path / "terminal"
    _write_descriptor(
        terminal,
        instance_id=instance_id,
        transport="unix",
        address=str(terminal / "connect-v1.sock"),
    )
    terminal.chmod(0o755)
    monkeypatch.setattr(desktop_target.sys, "platform", "darwin")
    monkeypatch.setenv("NANOBOT_DESKTOP_ROOT", str(tmp_path))

    with pytest.raises(DesktopTargetError, match="private"):
        discover_desktop_target()


def test_descriptor_transport_is_bound_to_platform(monkeypatch, tmp_path: Path) -> None:
    instance_id = "0b47107a-cd31-4711-b1ca-3b53dcedf90a"
    raw = json.dumps(
        {
            "schemaVersion": 1,
            "instanceId": instance_id,
            "transport": "namedPipe",
            "address": f"nanobot-desktop-v1-{instance_id}",
        }
    ).encode()
    monkeypatch.setattr(desktop_target.sys, "platform", "win32")

    assert _parse_descriptor(raw, directory=tmp_path) == DesktopTarget(
        instance_id,
        "namedPipe",
        f"nanobot-desktop-v1-{instance_id}",
    )


@pytest.mark.skipif(os.name == "nt", reason="Unix-domain socket protocol")
def test_unix_request_revalidates_instance_identity() -> None:
    instance_id = "0b47107a-cd31-4711-b1ca-3b53dcedf90a"
    with tempfile.TemporaryDirectory(prefix="nb-desktop-", dir="/tmp") as temporary:
        address = Path(temporary) / "connect-v1.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(address))
        address.chmod(0o600)
        server.listen(1)
        server.settimeout(2)
        received: list[dict[str, object]] = []

        def serve() -> None:
            client, _ = server.accept()
            with client:
                client.settimeout(2)
                request = client.makefile("rb").readline()
                received.append(json.loads(request))
                client.sendall(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "instanceId": instance_id,
                            "state": "ready",
                            "capabilities": ["webui"],
                        }
                    ).encode()
                    + b"\n"
                )

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            reply = DesktopTarget(instance_id, "unix", str(address)).request("status")
        finally:
            thread.join(timeout=2)
            server.close()

    assert reply == DesktopReply("ready", frozenset({"webui"}))
    assert received == [
        {
            "schemaVersion": 1,
            "instanceId": instance_id,
            "operation": "status",
        }
    ]


def test_webui_url_requires_ready_capability_and_loopback() -> None:
    assert (
        _desktop_webui_url(
            DesktopReply(
                "ready",
                frozenset({"webui"}),
                "http://127.0.0.1:8765/#/?bootstrapSecret=private",
            )
        )
        == "http://127.0.0.1:8765/#/?bootstrapSecret=private"
    )
    with pytest.raises(DesktopTargetError, match="non-loopback"):
        _desktop_webui_url(
            DesktopReply("ready", frozenset({"webui"}), "https://example.com/")
        )


def test_reply_must_match_selected_instance() -> None:
    raw = json.dumps(
        {
            "schemaVersion": 1,
            "instanceId": "7ebaf7ba-194e-4df5-a9a0-b9a760086a89",
            "state": "ready",
            "capabilities": ["webui"],
        }
    ).encode()

    with pytest.raises(DesktopTargetError, match="incompatible"):
        _parse_reply(
            raw,
            expected_instance_id="0b47107a-cd31-4711-b1ca-3b53dcedf90a",
        )


def test_non_bare_or_noninteractive_invocations_do_not_discover(monkeypatch) -> None:
    monkeypatch.setattr(
        desktop_target,
        "discover_desktop_target",
        lambda: pytest.fail("explicit invocation must not discover Desktop"),
    )
    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)

    assert dispatch_bare_desktop_target(["webui", "--no-open"]) is None
    assert dispatch_bare_desktop_target(["agent"]) is None

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: False)
    assert dispatch_bare_desktop_target([]) is None
    assert dispatch_bare_desktop_target(["webui"]) is None


def test_absent_desktop_selects_current_python(monkeypatch, capsys) -> None:
    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", lambda: None)

    assert dispatch_bare_desktop_target([]) is None
    assert "Using current Python environment:" in capsys.readouterr().out


def test_python_choice_does_not_request_desktop_operation(monkeypatch, capsys) -> None:
    calls: list[str] = []

    class Target:
        def request(self, operation: str) -> DesktopReply:
            calls.append(operation)
            return DesktopReply("ready", frozenset({"webui"}))

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _status: "python")

    assert dispatch_bare_desktop_target(["webui"]) is None
    assert calls == ["status"]
    assert "Using current Python environment:" in capsys.readouterr().out


def test_desktop_webui_selection_revalidates_and_opens_browser(monkeypatch, capsys) -> None:
    calls: list[str] = []
    browser_urls: list[str] = []
    url = "http://localhost:8765/#/?bootstrapSecret=private"

    class Target:
        def request(self, operation: str) -> DesktopReply:
            calls.append(operation)
            return DesktopReply("ready", frozenset({"webui"}), url if operation == "webui" else None)

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _status: "desktop")
    monkeypatch.setattr(
        "nanobot.cli.webui_support._launch_browser",
        lambda value: browser_urls.append(value) or True,
    )

    assert dispatch_bare_desktop_target(["webui"]) == 0
    assert calls == ["status", "webui"]
    assert browser_urls == [url]
    output = capsys.readouterr().out
    assert "Closing the browser leaves Desktop running" in output
    assert "bootstrapSecret" not in output


def test_desktop_tui_selection_fails_without_fallback(monkeypatch, capsys) -> None:
    calls: list[str] = []

    class Target:
        def request(self, operation: str) -> DesktopReply:
            calls.append(operation)
            return DesktopReply("ready", frozenset({"webui"}))

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _status: "desktop")

    assert dispatch_bare_desktop_target([]) == 3
    assert calls == ["status", "tui"]
    error = capsys.readouterr().err
    assert "unavailable or incompatible" in error
    assert "No backend was started" in error


def test_disconnect_after_desktop_selection_never_falls_back(monkeypatch, capsys) -> None:
    calls = 0

    class Target:
        def request(self, _operation: str) -> DesktopReply:
            nonlocal calls
            calls += 1
            if calls == 1:
                return DesktopReply("ready", frozenset({"webui"}))
            raise DesktopTargetError("disconnected")

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _status: "desktop")

    assert dispatch_bare_desktop_target(["webui"]) == 3
    assert calls == 2
    assert "No backend was started" in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], ["webui"]])
@pytest.mark.parametrize("state", ["busy", "unavailable", "offline", "untrusted"])
def test_unready_desktop_preserves_python_before_selection(monkeypatch, capsys, args, state):
    class Target:
        def request(self, _operation):
            if state == "offline":
                raise DesktopTargetError("stale socket")
            return DesktopReply(state, frozenset({"webui"}))

    def discover():
        if state == "untrusted":
            raise DesktopTargetError("unsafe descriptor")
        return Target()

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", discover)
    monkeypatch.setattr(
        desktop_target, "_choose_target", lambda _: pytest.fail("not a usable Desktop target")
    )
    assert dispatch_bare_desktop_target(args) is None
    output = capsys.readouterr()
    assert "Using current Python environment:" in output.out
    assert "No backend was started" not in output.err


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv executable symlinks")
def test_python_label_preserves_venv_executable(monkeypatch, tmp_path):
    interpreter = tmp_path / "python"
    interpreter.symlink_to(desktop_target.sys.executable)
    monkeypatch.setattr(desktop_target.sys, "executable", str(interpreter))
    assert desktop_target._python_target_label() == str(interpreter)


@pytest.mark.parametrize("url", [
    "http://[::1/#/?bootstrapSecret=private",
    "http://localhost:invalid/#/?bootstrapSecret=private",
    "http://localhost:99999/",
    "http://localhost:0/",
    "http://evil.example\\@localhost/",
    "http://localhost\\evil.example/",
    "http://localhost/\n",
])
def test_invalid_browser_urls_are_protocol_errors(url):
    with pytest.raises(DesktopTargetError):
        _desktop_webui_url(DesktopReply("ready", frozenset({"webui"}), url))


def test_browser_failure_does_not_leak_bootstrap_or_fall_back(monkeypatch, capsys):
    url = "http://localhost:8765/#/?bootstrapSecret=private"

    class Target:
        def request(self, _operation):
            return DesktopReply("ready", frozenset({"webui"}), url)

    def fail_browser(_url):
        raise OSError(f"Could not open {url}")

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _: "desktop")
    monkeypatch.setattr("nanobot.cli.webui_support._launch_browser", fail_browser)
    assert dispatch_bare_desktop_target(["webui"]) == 3
    output = capsys.readouterr()
    assert "bootstrapSecret" not in output.out + output.err
    assert "Using current Python" not in output.out


@pytest.mark.skipif(os.name == "nt", reason="POSIX discovery file types")
@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_discovery_rejects_special_files_without_blocking(monkeypatch, tmp_path, kind):
    terminal = tmp_path / "terminal"
    terminal.mkdir(mode=0o700)
    descriptor = terminal / "instance-v1.json"
    if kind == "fifo":
        os.mkfifo(descriptor, mode=0o600)
    else:
        other = tmp_path / "other"
        other.write_text("{}")
        descriptor.symlink_to(other)
    monkeypatch.setattr(desktop_target.sys, "platform", "darwin")
    monkeypatch.setenv("NANOBOT_DESKTOP_ROOT", str(tmp_path))
    with pytest.raises(DesktopTargetError):
        discover_desktop_target()


@pytest.mark.skipif(os.name == "nt", reason="Unix socketpair")
def test_socket_response_timeout_is_bounded():
    client, server = socket.socketpair()
    with client, server, pytest.raises(TimeoutError):
        desktop_target._read_socket_line(client, deadline=time.monotonic() + 0.02)


@pytest.mark.skipif(os.name == "nt", reason="Unix socketpair")
@pytest.mark.parametrize("reply", [b"{}", b"x" * 17])
def test_socket_rejects_truncated_or_oversized_reply(monkeypatch, reply):
    monkeypatch.setattr(desktop_target, "_MAX_MESSAGE_BYTES", 16)
    client, server = socket.socketpair()
    with client, server:
        server.sendall(reply)
        server.shutdown(socket.SHUT_WR)
        with pytest.raises(DesktopTargetError):
            desktop_target._read_socket_line(client, deadline=time.monotonic() + 1)


@pytest.mark.parametrize("args", [[], ["webui"]])
def test_completion_never_discovers_desktop(monkeypatch, args):
    monkeypatch.setenv("_NANOBOT_COMPLETE", "complete_bash")
    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(
        desktop_target, "discover_desktop_target", lambda: pytest.fail("completion must bypass")
    )
    assert dispatch_bare_desktop_target(args) is None
