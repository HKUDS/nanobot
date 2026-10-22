"""The Dock shortcut never owns gateway execution, data, or credentials on disk."""

import asyncio
import socket
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from nanobot.cli import dock
from nanobot.cli._macos_dock import _Clients, _serve, is_local_browser_url


@pytest.mark.parametrize("url,root", [
    ("http://LOCALHOST:8765/#/chat", "http://localhost:8765"),
    ("http://[0:0:0:0:0:0:0:1]:8765/#/chat", "http://[::1]:8765"),
    ("http://127.0.0.1:80/#/chat", "http://127.0.0.1"),
    ("http://localhost:8765/WebUI/?token=private#/chat", "http://localhost:8765/WebUI"),
])
def test_window_lookup_matches_browser_origin_normalization(url, root):
    from nanobot.cli._macos_dock import _browser_root

    assert is_local_browser_url(url)
    assert _browser_root(url) == root


def test_activation_and_reopen_share_one_deferred_focus_request(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from nanobot.cli import _macos_dock as native

    def function(value):
        return lambda *_: value

    objc = SimpleNamespace(**{name: function(value) for name, value in (
        ("objc_getClass", 1), ("sel_registerName", 2), ("objc_allocateClassPair", 3),
        ("class_addMethod", True), ("objc_registerClassPair", None),
    )})
    monkeypatch.setattr(native.c, "CDLL", lambda *_: objc)
    queued = []

    def send(app, _target, selector, *_args, **_kwargs):
        if selector == "activationPolicy":
            return 0
        if selector == "finishLaunching":
            app.callbacks[2](1, 1, 1)
        if selector == "performSelector:withObject:afterDelay:":
            queued.append(app.callbacks[1])
        return 1

    monkeypatch.setattr(native._AppKit, "send", send)
    clients = native._Clients()
    first, other = socket.socketpair()
    with first, other:
        clients.add(first, "http://localhost:5173/#/existing")
        app = native._AppKit(tmp_path / "icon.png", clients)
        assert not queued  # Startup must not open a page or request permission.
        focused = []

        def focus(_self, url):
            focused.append(url)
            app.callbacks[2](1, 1, 1)  # Permission/modal reactivation is not a new request.

        monkeypatch.setattr(native._AppKit, "focus_browser", focus)
        app.callbacks[2](1, 1, 1)  # Command-Tab activation.
        assert app.callbacks[3](1, 1, 1, False) is False  # Dock reopen in the same turn.
        assert len(queued) == 1
        queued.pop()(1, 1, 1)
        assert focused == ["http://localhost:5173/#/existing"]
        assert not queued and not app.opening
        app.callbacks[0](1, 1, 1)  # Menu action uses the same path.
        clients.remove(first)  # Gateway stopped before the queued action ran.
        queued.pop()(1, 1, 1)
        assert len(focused) == 1
        assert not app.opening


@pytest.mark.parametrize("bundle,error,expected", [
    (b"com.google.Chrome", -1743, "Allow nanobot"),
    (b"com.apple.Safari", -1712, "Could not restore"),
    (b"org.mozilla.firefox", 0, "Window reuse needs"),
])
def test_browser_failure_never_falls_back_to_opening_a_duplicate(monkeypatch, bundle, error, expected):
    from nanobot.cli import _macos_dock as native

    app = object.__new__(native._AppKit)
    calls, alerts = [], []
    monkeypatch.setattr(app, "cls", lambda _: 1)
    monkeypatch.setattr(app, "string", lambda _: 1)

    def send(_target, selector, *_args, **_kwargs):
        calls.append(selector)
        if selector == "UTF8String":
            return bundle
        if selector == "executeAndReturnError:":
            return None
        if selector == "integerValue":
            return error
        return 1

    monkeypatch.setattr(app, "send", send)
    monkeypatch.setattr(app, "alert", lambda title, detail: alerts.append((title, detail)))
    app.focus_browser("http://localhost:5173/#/?bootstrapSecret=private")
    assert len(alerts) == 1 and alerts[0][0].startswith(expected)
    assert not any("openURL" in call for call in calls)
    assert "private" not in str(alerts)


@pytest.mark.skipif(sys.platform != "darwin", reason="native AppleScript parser")
def test_browser_script_quotes_urls_without_evaluating_them():
    import subprocess

    from nanobot.cli._macos_dock import _applescript_string

    url = 'http://localhost:5173/#/quote" & error "injected\\路径'
    result = subprocess.run(["/usr/bin/osascript", "-"], input="return " + _applescript_string(url),
                            capture_output=True, text=True, check=True, timeout=10)
    assert result.stdout.rstrip("\n") == url


@pytest.mark.skipif(sys.platform != "darwin", reason="native AppleScript parser")
@pytest.mark.parametrize("browser", ["com.google.Chrome", "com.apple.Safari"])
def test_browser_script_compiles(browser):
    import subprocess

    from nanobot.cli._macos_dock import _browser_script

    # Compiling Chrome's terminology requires its optional app dictionary.
    if browser == "com.google.Chrome" and not any((root / "Google Chrome.app").is_dir()
                                                   for root in (Path("/Applications"), Path.home() / "Applications")):
        pytest.skip("Chrome is not installed in a standard Applications directory")
    subprocess.run(["/usr/bin/osacompile", "-o", "/dev/null"],
                   input=_browser_script(browser, 'http://localhost:5173/#/quote" & error "injected\\路径'),
                   text=True, capture_output=True, check=True, timeout=10)


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_other_platforms_do_not_prepare_or_launch_an_icon(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(dock.sys, "platform", platform)
    monkeypatch.setattr(dock, "_attach", lambda *_: pytest.fail("must not launch"))
    with dock.dock_icon("http://127.0.0.1:8765/", instance=tmp_path / "gateway.json"):
        pass
    assert list(tmp_path.iterdir()) == []


def test_explicit_opt_out_and_ssh_do_not_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(dock.sys, "platform", "darwin")
    monkeypatch.setattr(dock, "_attach", lambda *_: pytest.fail("must not launch"))
    with dock.dock_icon("http://127.0.0.1:8765/", instance=tmp_path, enabled=False):
        pass
    monkeypatch.setenv("SSH_CONNECTION", "test")
    with dock.dock_icon("http://127.0.0.1:8765/", instance=tmp_path):
        pass


def test_optional_failure_does_not_swallow_webui_failure_or_log_credentials(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(dock, "_desktop_available", lambda: True)
    monkeypatch.setattr(dock, "_directory", lambda *_: tmp_path)
    monkeypatch.setattr(dock.logger, "warning", warnings.append)

    def unavailable(*_):
        raise OSError("sensitive-url-fragment")

    monkeypatch.setattr(dock, "_attach", unavailable)
    with pytest.raises(RuntimeError, match="gateway failure"):
        with dock.dock_icon("http://127.0.0.1:8765/", instance=tmp_path):
            raise RuntimeError("gateway failure")
    assert len(warnings) == 1
    assert "sensitive" not in warnings[0]


def test_context_releases_its_connection_even_when_the_launcher_is_interrupted(monkeypatch, tmp_path):
    first, other = socket.socketpair()
    monkeypatch.setattr(dock, "_desktop_available", lambda: True)
    monkeypatch.setattr(dock, "_directory", lambda *_: tmp_path)
    monkeypatch.setattr(dock, "_attach", lambda *_: first)
    with other, pytest.raises(KeyboardInterrupt):
        try:
            with dock.dock_icon("http://127.0.0.1:8765/", instance=tmp_path):
                raise KeyboardInterrupt
        finally:
            other.settimeout(1)
            assert other.recv(1) == b""


@pytest.mark.skipif(sys.platform == "win32", reason="Darwin/Unix helper startup contract")
def test_interrupt_during_handshake_closes_connection_and_stops_new_helper(monkeypatch):
    from unittest.mock import MagicMock

    connection = MagicMock()
    connection.recv.side_effect = KeyboardInterrupt
    process = MagicMock()
    process.poll.return_value = None
    attempts = iter((None, connection))
    monkeypatch.setattr(dock, "_connect", lambda *_: next(attempts))
    monkeypatch.setattr(dock, "_bundle", lambda *_: Path("unused-test-interpreter"))
    monkeypatch.setattr(dock.subprocess, "Popen", lambda *_args, **_kwargs: process)
    with tempfile.TemporaryDirectory(prefix="nb-dock-") as name, pytest.raises(KeyboardInterrupt):
        dock._attach(Path(name), "http://127.0.0.1:8765/")
    connection.close.assert_called_once()
    process.terminate.assert_called_once()


@pytest.mark.skipif(sys.platform == "win32", reason="Darwin/Unix helper startup contract")
def test_cold_helper_startup_keeps_the_connection_until_ready(monkeypatch, tmp_path):
    # Native AppKit startup was measured at 1.928s after an update, already at
    # the old 2s socket deadline. Exercise a cold start without requiring a GUI.
    helper = tmp_path / "slow-helper.py"
    helper.write_text("""import socket, sys, time
listener = socket.socket(fileno=int(sys.argv[1]))
time.sleep(2.5)
connection, _ = listener.accept()
with connection:
    assert connection.recv(8192).endswith(b'\\n')
    connection.sendall(b'1')
    assert connection.recv(1) == b''
listener.close()
""")
    spawned = []
    popen = dock.subprocess.Popen

    def launch(*args, **kwargs):
        process = popen(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(dock, "_WORKER", helper)
    monkeypatch.setattr(dock, "_bundle", lambda _: Path(sys.executable))
    monkeypatch.setattr(dock.subprocess, "Popen", launch)
    with tempfile.TemporaryDirectory(prefix="nb-dock-") as name:
        try:
            connection = dock._attach(Path(name), "http://127.0.0.1:8765/")
            connection.close()
            assert spawned[0].wait(timeout=3) == 0
        finally:
            for process in spawned:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)


@pytest.mark.skipif(sys.platform == "win32", reason="macOS private-directory contract")
def test_private_cache_rejects_symlink_and_shared_directory(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(PermissionError):
        dock._private_directory(shared)
    private = tmp_path / "private"
    dock._private_directory(private)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(PermissionError):
        dock._private_directory(link)


@pytest.mark.parametrize("url, valid", [
    ("http://127.0.0.1:8765/#/?bootstrapSecret=test", True),
    ("http://localhost:8765/", True),
    ("http://[::1]:5173/", True),
    ("http://example.com:8765/", False),
    ("http://127.0.0.1.example.com:8765/", False),
    ("http://user:pass@127.0.0.1:8765/", False),
    ("file:///tmp/index.html", False),
    ("http://127.0.0.1:8765/\n", False),
    ("http://127.0.0.1:99999/", False),
])
def test_private_socket_only_accepts_local_browser_urls(url, valid):
    assert is_local_browser_url(url) is valid


@contextmanager
def _server():
    # macOS has a short AF_UNIX address limit; pytest's nested tmp_path can exceed it.
    with tempfile.TemporaryDirectory(prefix="nb-dock-") as name:
        address = Path(name) / "s"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(address))
        listener.listen()
        clients = _Clients()
        stopped = threading.Event()
        # Keep startup serialized just like the launcher: first connect before release.
        from filelock import FileLock
        with FileLock(str(address.parent / "start.lock")):
            thread = threading.Thread(target=_serve, args=(listener, address, clients, stopped.set))
            thread.start()
            first = _join(address, "http://127.0.0.1:8765/#/first")
        try:
            yield address, first, clients, stopped
        finally:
            first.close()
            assert stopped.wait(3)
            thread.join(timeout=1)


def _join(address, url):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(2)
    connection.connect(str(address))
    connection.sendall(url.encode() + b"\n")
    assert connection.recv(1) == b"1"
    return connection


@pytest.mark.skipif(sys.platform == "win32", reason="Darwin/Unix socket lifetime contract")
def test_shared_icon_survives_first_launcher_and_stops_after_last():
    with _server() as (address, first, clients, stopped):
        second = _join(address, "http://127.0.0.1:8765/#/second")
        try:
            assert clients.current_url().endswith("/second")
            first.close()
            assert not stopped.wait(0.15)
            assert address.exists()
        finally:
            second.close()
        assert stopped.wait(3)
        assert not address.exists()
        assert clients.current_url() is None


@pytest.mark.skipif(sys.platform == "win32", reason="Darwin/Unix socket lifetime contract")
def test_rejected_peer_does_not_replace_live_url_or_stop_the_icon():
    with _server() as (address, first, clients, stopped):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as invalid:
            invalid.settimeout(2)
            invalid.connect(str(address))
            invalid.sendall(b"https://example.com/\n")
            assert invalid.recv(1) == b""
        assert clients.current_url().endswith("/first")
        assert not stopped.is_set()
        first.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Darwin/Unix socket lifetime contract")
def test_new_launcher_can_join_while_the_previous_launcher_exits():
    from filelock import FileLock

    with _server() as (address, first, _clients, stopped):
        with FileLock(str(address.parent / "start.lock")):
            first.close()
            assert not stopped.wait(0.15)
            second = _join(address, "http://127.0.0.1:8765/#/next")
        try:
            assert not stopped.wait(0.15)
        finally:
            second.close()


@pytest.mark.skipif(sys.platform == "win32", reason="macOS interpreter wrapper")
def test_bundle_uses_current_python_and_never_contains_the_login_url(tmp_path):
    import plistlib

    executable = dock._bundle(tmp_path)
    assert executable.is_symlink()
    assert executable.resolve().is_file()
    info = plistlib.loads((executable.parent.parent / "Info.plist").read_bytes())
    assert info["CFBundleDisplayName"] == "nanobot"
    assert "browser tab" in info["NSAppleEventsUsageDescription"]
    assert (executable.parent.parent / "Resources" / "dock-icon.png").read_bytes() == dock._ICON.read_bytes()
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 3


@pytest.mark.skipif(sys.platform != "darwin", reason="real macOS bundle identity")
def test_framework_python_keeps_the_helpers_bundle_identity(tmp_path):
    import subprocess

    executable = dock._bundle(tmp_path)
    # Run the actual helper interpreter. Framework Python launchers used to exec
    # Python.app and lose this bundle's name and Automation usage description.
    result = subprocess.run([str(executable), "-I", "-S", "-c", """
import ctypes as c
objc = c.CDLL('/usr/lib/libobjc.A.dylib')
c.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
objc.objc_getClass.argtypes = [c.c_char_p]
objc.objc_getClass.restype = c.c_void_p
objc.sel_registerName.argtypes = [c.c_char_p]
objc.sel_registerName.restype = c.c_void_p
send = c.CFUNCTYPE(c.c_void_p, c.c_void_p, c.c_void_p)(('objc_msgSend', objc))
bundle = send(objc.objc_getClass(b'NSBundle'), objc.sel_registerName(b'mainBundle'))
identifier = send(bundle, objc.sel_registerName(b'bundleIdentifier'))
text = c.CFUNCTYPE(c.c_char_p, c.c_void_p, c.c_void_p)(('objc_msgSend', objc))
print(text(identifier, objc.sel_registerName(b'UTF8String')).decode())
"""], capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == f"dev.nanobot.webui.{tmp_path.name}"


@pytest.mark.skipif(sys.platform == "win32", reason="macOS interpreter wrapper")
def test_cached_bundle_refreshes_an_obsolete_interpreter_link(tmp_path):
    executable = dock._bundle(tmp_path)
    current = executable.resolve()
    obsolete = tmp_path / "previous-python"
    obsolete.write_text("old installation")
    executable.unlink()
    executable.symlink_to(obsolete)
    assert dock._bundle(tmp_path).resolve() == current
    assert obsolete.read_text() == "old installation"
    assert not list(executable.parent.glob(".nanobot-*"))


@pytest.mark.skipif(sys.platform == "win32", reason="macOS private-directory contract")
def test_code_updates_keep_the_same_dock_identity(monkeypatch, tmp_path):
    worker = tmp_path / "_macos_dock.py"
    icon = tmp_path / "icon.png"
    worker.write_text("old code")
    icon.write_bytes(b"old icon")
    monkeypatch.setattr(dock, "_WORKER", worker)
    monkeypatch.setattr(dock, "_ICON", icon)
    monkeypatch.setattr(dock, "_private_directory", lambda *_: None)
    before = dock._directory(tmp_path / "gateway.json", "http://localhost:5173/#/old")
    worker.write_text("updated code")
    icon.write_bytes(b"updated icon")
    assert dock._directory(tmp_path / "gateway.json", "http://localhost:5173/#/new") == before
    assert dock._directory(tmp_path / "other.json", "http://localhost:5173/") != before
    assert dock._directory(tmp_path / "gateway.json", "http://localhost:5174/") != before


async def test_background_presence_waits_for_activation_and_remembers_explicit_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(dock, "_desktop_available", lambda: True)
    instance = tmp_path / "run" / "gateway.json"
    entered, closed = threading.Event(), threading.Event()

    @contextmanager
    def icon(url, **_kwargs):
        assert url == "http://127.0.0.1:8765/"
        entered.set()
        try:
            yield
        finally:
            closed.set()

    monkeypatch.setattr(dock, "dock_icon", icon)
    dock.request_gateway_icon(instance, enabled=True)
    intent = instance.with_suffix(".dock").read_text()
    assert intent.startswith("show:") and "http" not in intent
    activated = asyncio.Event()
    watcher = asyncio.create_task(dock.watch_gateway_icon(
        "http://127.0.0.1:8765/", instance=instance, activated=activated,
    ))
    try:
        await asyncio.sleep(0)
        assert not entered.is_set()
        activated.set()
        assert await asyncio.to_thread(entered.wait, 2)
        dock.request_gateway_icon(instance, enabled=False)
        assert await asyncio.to_thread(closed.wait, 2)
        entered.clear()
        closed.clear()
        dock.request_gateway_icon(instance, enabled=True)
        assert await asyncio.to_thread(entered.wait, 2)
    finally:
        watcher.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watcher
    assert closed.is_set()
    # A new gateway generation, including a protected update restart, reads the
    # same intent without rewriting configuration or learning an updater protocol.
    entered.clear()
    watcher = asyncio.create_task(dock.watch_gateway_icon(
        "http://127.0.0.1:8765/", instance=instance, activated=activated,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
    finally:
        watcher.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watcher


async def test_cancelled_gateway_joins_pending_dock_startup_before_releasing_it(monkeypatch, tmp_path):
    monkeypatch.setattr(dock, "_desktop_available", lambda: True)
    started, release, closed = threading.Event(), threading.Event(), threading.Event()

    @contextmanager
    def slow_icon(*_args, **_kwargs):
        started.set()
        assert release.wait(3)
        try:
            yield
        finally:
            closed.set()

    monkeypatch.setattr(dock, "dock_icon", slow_icon)
    instance = tmp_path / "gateway.json"
    dock.request_gateway_icon(instance, enabled=True)
    activated = asyncio.Event()
    activated.set()
    watcher = asyncio.create_task(dock.watch_gateway_icon(
        "http://127.0.0.1:8765/", instance=instance, activated=activated,
    ))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        watcher.cancel()
        await asyncio.sleep(0)
        assert not watcher.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await watcher
    assert closed.is_set()


def test_background_preference_failure_never_blocks_the_launcher(monkeypatch, tmp_path):
    monkeypatch.setattr(dock, "_desktop_available", lambda: True)
    not_directory = tmp_path / "file"
    not_directory.write_text("test")
    dock.request_gateway_icon(not_directory / "gateway.json", enabled=True)
