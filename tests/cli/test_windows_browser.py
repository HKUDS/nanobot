"""Windows redirect, secret transport and cleanup regressions."""

import ctypes
import io
import os
import subprocess
import threading
from contextlib import contextmanager
from ctypes import wintypes
from html.parser import HTMLParser
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.cli import desktop_target, webui_support
from nanobot.cli import windows_browser as browser


class RecordingInput(io.BytesIO):
    payload = b""

    def close(self):
        if not self.closed:
            self.payload = self.getvalue()
        super().close()


@pytest.fixture
def launcher(monkeypatch):
    process = SimpleNamespace(
        stdin=RecordingInput(), stdout=io.BytesIO(b"1"), kill=MagicMock(), wait=MagicMock(),
    )
    spawn = MagicMock(return_value=process)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(browser.sys, "platform", "win32")
    monkeypatch.setenv("BROWSER", "unsafe-browser %s")
    monkeypatch.setattr(
        webui_support.webbrowser, "open", lambda *_a, **_kw: pytest.fail("raw URL fallback"),
    )
    return process, spawn


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/",
    "http://127.0.0.1:8765/#/?bootstrapSecret=synthetic-only",
    "http://localhost:5173/#/?bootstrapSecret=quote%22%27%24%28%29%26",
    "http://[::1]:8765/#/中文?bootstrapSecret=synthetic-only",
    "https://localhost/?token=synthetic-only#%62ootstrapSecret=alternate",
])
def test_windows_uses_pipe_not_argv_or_browser_override(launcher, capsys, url):
    process, spawn = launcher
    assert webui_support._launch_browser(url) is True
    args, options = spawn.call_args
    assert args[0] == [
        browser.sys.executable, "-I", "-S", str(Path(browser.__file__).resolve()), "--serve",
    ]
    assert url not in repr(spawn.call_args) and "synthetic-only" not in repr(spawn.call_args)
    assert options["creationflags"] == 0x08000000
    assert options["close_fds"] is True
    assert options["stderr"] == subprocess.DEVNULL
    assert process.stdin.payload == url.encode() + b"\n"
    process.kill.assert_not_called()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "file:///tmp/secret", "http:///", "http://[invalid/",
    "http://localhost/\nsecret", "http://localhost/\rsecret", "http://localhost/\x00",
    "http://localhost/\ud800", "http://localhost/" + "x" * browser._MAX_URL_BYTES,
])
def test_invalid_input_does_not_spawn_a_helper(launcher, url, capsys):
    _, spawn = launcher
    assert browser.launch_browser(url) is False
    spawn.assert_not_called()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure", ["spawn", "eof", "bad_ack", "pipe"])
def test_launcher_failure_never_logs_url_or_retries(launcher, failure, capsys):
    process, spawn = launcher
    url = "http://localhost/#/?bootstrapSecret=synthetic-only"
    if failure == "spawn":
        spawn.side_effect = OSError(url)
    elif failure == "pipe":
        process.stdin.write = MagicMock(side_effect=OSError(url))
    else:
        process.stdout = io.BytesIO(b"" if failure == "eof" else b"0")
    assert browser.launch_browser(url) is False
    assert spawn.call_count == 1
    if failure != "spawn":
        process.kill.assert_called_once()
    assert capsys.readouterr() == ("", "")


def test_startup_timeout_kills_helper_and_drains_pipe_reader(launcher, monkeypatch):
    process, _ = launcher
    exited = threading.Event()

    class BlockedOutput(io.BytesIO):
        def read(self, _count):
            assert exited.wait(2)
            return b""

    process.stdout = BlockedOutput()
    process.kill.side_effect = exited.set
    monkeypatch.setattr(browser, "_START_TIMEOUT_S", 0.02)
    assert browser.launch_browser("http://localhost/#/?token=synthetic-only") is False
    process.kill.assert_called_once()
    assert process.stdout.closed


@pytest.mark.parametrize("ack, status", [(b"1", 0), (b"", 3)])
def test_windows_desktop_handoff_retains_revalidation_and_no_fallback(launcher, monkeypatch, capsys, ack, status):
    process, _ = launcher
    process.stdout = io.BytesIO(ack)
    calls = []

    class Target:
        def request(self, operation):
            calls.append(operation)
            return desktop_target.DesktopReply(
                "ready", frozenset({"webui"}),
                "http://localhost:8765/#/?bootstrapSecret=synthetic-only",
            )

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _: "desktop")
    assert desktop_target.dispatch_bare_desktop_target(["webui"]) == status
    assert calls == ["status", "webui"]
    output = capsys.readouterr()
    assert "synthetic-only" not in output.out + output.err
    assert "Using current Python" not in output.out


def test_redirect_escapes_html_without_changing_url():
    url = 'http://localhost/#/?bootstrapSecret="/><script>alert(1)</script>&other=中文'
    content = browser._redirect_html(url)
    tags = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append((tag, dict(attrs)))

    Parser().feed(content.decode())
    assert all(tag != "script" for tag, _ in tags)
    refresh = [attrs for tag, attrs in tags if attrs.get("http-equiv") == "refresh"]
    assert refresh == [{"http-equiv": "refresh", "content": "0; url=" + url}]
    assert ("meta", {"name": "referrer", "content": "no-referrer"}) in tags


@pytest.fixture
def helper_file(tmp_path, monkeypatch):
    paths = []

    @contextmanager
    def private(content):
        path = tmp_path / f"{len(paths)}.html"
        path.write_bytes(content)
        paths.append(path)
        try:
            yield path
        finally:
            path.unlink()

    monkeypatch.setattr(browser, "_private_redirect", private)
    return paths


@pytest.mark.parametrize("failure", [None, "launch", "exception", "ack", "interrupted"])
def test_helper_owns_file_until_expiry_and_cleans_every_exit(helper_file, monkeypatch, failure):
    incoming = io.BytesIO(b"http://localhost/#/?bootstrapSecret=synthetic-only\n")
    outgoing = io.BytesIO()
    events = []

    def open_file(path):
        assert path.exists() and b"synthetic-only" in path.read_bytes()
        assert "synthetic-only" not in str(path)
        events.append("launch")
        if failure == "exception":
            raise OSError("launch failed")
        return failure != "launch"

    def sleep(seconds):
        assert seconds == 120
        assert helper_file[0].exists()
        assert outgoing.getvalue() == b"1"
        events.append("retained")
        if failure == "interrupted":
            raise KeyboardInterrupt

    monkeypatch.setattr(browser, "_open_redirect", open_file)
    monkeypatch.setattr(browser.time, "sleep", sleep)
    if failure == "ack":
        outgoing.write = MagicMock(side_effect=BrokenPipeError)
    error = KeyboardInterrupt if failure == "interrupted" else OSError
    if failure in {"exception", "ack", "interrupted"}:
        with pytest.raises(error):
            browser._serve(incoming, outgoing)
    else:
        assert browser._serve(incoming, outgoing) == (1 if failure == "launch" else 0)
    assert not helper_file[0].exists()
    assert ("retained" in events) == (failure in {None, "interrupted"})


@pytest.mark.parametrize("data", [b"", b"http://localhost/", b"x" * 65537 + b"\n"])
def test_helper_rejects_incomplete_or_oversized_pipe_message(helper_file, data):
    assert browser._serve(io.BytesIO(data), io.BytesIO()) == 1
    assert helper_file == []


@pytest.mark.parametrize("initialized, launched", [(0, True), (1, False), (-1, False)])
def test_native_launch_receives_only_path_and_uses_http_association(monkeypatch, initialized, launched):
    ole, shell = MagicMock(), MagicMock()
    ole.CoInitializeEx.return_value = initialized
    captured = []

    def execute(pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(browser._ShellExecuteInfo)).contents
        captured.append((info.lpFile, info.lpClass, info.lpParameters, info.fMask))
        return launched

    shell.ShellExecuteExW.side_effect = execute
    monkeypatch.setattr(ctypes, "WinDLL", lambda name: ole if name == "ole32" else shell, raising=False)
    path = Path("C:/Users/Example/中文/test.html")
    assert browser._open_redirect(path) is launched
    if initialized >= 0:
        assert captured == [(str(path), "http", None, 0x501)]
        ole.CoUninitialize.assert_called_once()
    else:
        assert captured == []
        ole.CoUninitialize.assert_not_called()


def _set(pointer, value, kind=wintypes.LPVOID):
    ctypes.cast(pointer, ctypes.POINTER(kind)).contents.value = value


@pytest.mark.parametrize("problem", [
    None, "owner", "null_acl", "unprotected", "extra_ace", "inherited", "mask", "other_user",
])
def test_private_acl_is_verified_not_merely_requested(problem):
    api = browser._WindowsFiles.__new__(browser._WindowsFiles)
    api.user = "current-user"
    api.check_type = MagicMock()
    api.free = MagicMock()
    acl = (wintypes.WORD * 4)(2, 32, 2 if problem == "extra_ace" else 1, 0)
    ace = ctypes.create_string_buffer(32)
    ctypes.cast(ctypes.addressof(ace) + 4, ctypes.POINTER(wintypes.DWORD)).contents.value = (
        0x1F01FF if problem != "mask" else 0x120089
    )
    if problem == "inherited":
        ace[1] = b"\x10"

    def security(_h, kind, fields, owner, _g, dacl, _s, descriptor):
        assert kind == 1 and fields == 5
        _set(owner, 10)
        _set(dacl, 0 if problem == "null_acl" else ctypes.addressof(acl))
        _set(descriptor, 20)
        return 0

    api.get_security = security
    api.control = lambda _sd, flags, _r: _set(flags, 0 if problem == "unprotected" else 0x1000, wintypes.WORD) or True
    api.get_ace = lambda _acl, _i, pointer: _set(pointer, ctypes.addressof(ace)) or True
    api._sid_text = MagicMock(side_effect=[
        "wrong-owner" if problem == "owner" else api.user,
        "another-user" if problem == "other_user" else api.user,
    ])
    if problem is None:
        api.check_private(100, directory=True)
    else:
        with pytest.raises(OSError):
            api.check_private(100, directory=True)
    api.free.assert_called_once()


def test_windows_security_uses_token_user_and_explicit_protected_descriptor(monkeypatch):
    kernel, security, shell, ole = (MagicMock() for _ in range(4))
    token_kinds = []
    sid = ctypes.create_unicode_buffer("S-1-5-21-123-456-789-1001")
    location = ctypes.create_unicode_buffer(r"C:\Users\Example\AppData\Local")
    descriptor = ctypes.create_string_buffer(64)

    def token_info(_token, kind, result, _length, size):
        token_kinds.append(kind)
        _set(size, 64, wintypes.DWORD)
        if result is not None:
            _set(result, 100)
            return True
        return False

    security.OpenProcessToken.side_effect = lambda _p, access, out: _set(out, 10) or access == 8
    security.GetTokenInformation.side_effect = token_info
    security.ConvertSidToStringSidW.side_effect = lambda _sid, out: _set(out, ctypes.addressof(sid)) or True
    shell.SHGetKnownFolderPath.side_effect = lambda _guid, _flags, _token, out: _set(out, ctypes.addressof(location)) or 0

    def convert(value, revision, out, size):
        assert value == "O:S-1-5-21-123-456-789-1001D:P(A;;FA;;;S-1-5-21-123-456-789-1001)"
        assert revision == 1 and size is None
        _set(out, ctypes.addressof(descriptor))
        return True

    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.side_effect = convert
    libraries = {"kernel32": kernel, "advapi32": security, "shell32": shell, "ole32": ole}
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_: libraries[name], raising=False)
    monkeypatch.setattr(browser, "Path", PureWindowsPath)
    api = browser._WindowsFiles()
    assert token_kinds == [1, 1]  # Never TokenOwner (4), even for elevated callers.
    assert str(api.base) == location.value
    with api.descriptor() as attrs:
        assert attrs.lpSecurityDescriptor == ctypes.addressof(descriptor)
        assert not attrs.bInheritHandle
    assert kernel.CloseHandle.call_args.args[0].value == 10
    assert security.ConvertStringSecurityDescriptorToSecurityDescriptorW.call_count == 1
    ole.CoTaskMemFree.assert_called_once()


@pytest.mark.parametrize("flags, directory, denied", [(0x10, True, False), (0x410, True, True), (0x400, False, True), (0x10, False, True)])
def test_reparse_and_wrong_object_types_are_rejected(flags, directory, denied):
    api = browser._WindowsFiles.__new__(browser._WindowsFiles)
    api.attributes = lambda _h, kind, result, _size: _set(result, flags, wintypes.DWORD) or kind == 9
    if denied:
        with pytest.raises(OSError):
            api.check_type(100, directory=directory)
    else:
        api.check_type(100, directory=directory)


def test_native_open_uses_create_new_nofollow_and_no_delete_sharing():
    api = browser._WindowsFiles.__new__(browser._WindowsFiles)
    api.create_file = MagicMock(return_value=100)
    api.close = MagicMock()
    security = browser._SecurityAttributes()
    with api.opened(Path("file.html"), access=0x40020080, create=ctypes.byref(security)):
        pass
    args = api.create_file.call_args.args
    assert args[1] == 0x40020080 and args[2] == 3 and args[4] == 1
    assert args[5] == 0x02200000
    api.close.assert_called_once_with(100)


@pytest.mark.parametrize("failure", [None, "reparse", "filesystem", "root_acl", "file_acl", "write", "partial"])
def test_private_file_checks_precede_secret_write_and_failures_clean_up(tmp_path, monkeypatch, failure):
    events = []

    class Files:
        base = tmp_path

        @contextmanager
        def descriptor(self):
            yield browser._SecurityAttributes()

        @contextmanager
        def opened(self, path, *, access=0x20080, create=None):
            events.append(("open", path, access))
            if create is not None:
                with path.open("xb"):
                    pass
            try:
                yield path
            finally:
                events.append(("close", path, access))

        def check_type(self, path, *, directory):
            if failure == "reparse":
                raise OSError("reparse ancestor")

        def check_private(self, path, *, directory):
            events.append(("private", path, directory))
            if failure == ("root_acl" if directory else "file_acl"):
                raise OSError("unsafe ACL")

        def volume(self, _h, _name, _n, _serial, _max, flags, _fs, _fs_size):
            _set(flags, 0 if failure == "filesystem" else 8, wintypes.DWORD)
            return True

        def create_directory(self, path, _security):
            Path(path).mkdir(exist_ok=True)
            return True

        def write(self, path, content, size, count, _overlapped):
            events.append(("write", path))
            if failure == "write":
                return False
            path.write_bytes(ctypes.string_at(content, size))
            _set(count, size - 1 if failure == "partial" else size, wintypes.DWORD)
            return True

    monkeypatch.setattr(browser, "_WindowsFiles", Files)
    if failure:
        with pytest.raises(OSError):
            with browser._private_redirect(b"synthetic-only"):
                pytest.fail("unsafe handoff became available")
    else:
        with browser._private_redirect(b"synthetic-only") as path:
            assert path.read_bytes() == b"synthetic-only"
            assert events.index(("private", path, False)) < events.index(("write", path))
            assert ("close", path, 0x40020080) in events  # No live write handle for browser.
            assert ("close", path.parent, 0x20080) not in events  # Directory is pinned.
        assert not path.exists()
    assert not list(tmp_path.glob("*/*.html"))
    if failure in {"reparse", "filesystem", "root_acl", "file_acl"}:
        assert not any(event[0] == "write" for event in events)


def test_helper_lifetime_is_independent_of_client_pipes(tmp_path):
    # Exercise the actual _serve lifecycle in a real child, without launching a
    # browser or claiming to emulate Windows ACLs on non-Windows test hosts.
    path = tmp_path / "synthetic.html"
    script = "\n".join([
        "import importlib.util, pathlib, sys",
        "from contextlib import contextmanager",
        f"spec = importlib.util.spec_from_file_location('handoff', {browser.__file__!r})",
        "module = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(module)",
        f"path = pathlib.Path({str(path)!r})",
        "@contextmanager",
        "def private(content):",
        "    path.write_bytes(content)",
        "    try: yield path",
        "    finally: path.unlink()",
        "module._private_redirect = private",
        "module._open_redirect = lambda path: True",
        "sys.exit(module._serve(sys.stdin.buffer, sys.stdout.buffer, lifetime=0.2))",
    ])
    with subprocess.Popen(
        [browser.sys.executable, "-I", "-S", "-c", script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as child:
        child.stdin.write(b"http://localhost/#/?bootstrapSecret=synthetic-only\n")
        child.stdin.close()
        assert child.stdout.read(1) == b"1"
        assert path.exists()
        child.stdout.close()
        assert child.wait(timeout=3) == 0
        assert child.stderr.read() == b""
    assert not path.exists()


def test_stale_cleanup_preserves_active_unsafe_and_unrelated_entries(tmp_path):
    names = ["a" * 32 + ".html", "b" * 32 + ".html", "c" * 32 + ".html", "notes.txt"]
    paths = [tmp_path / name for name in names]
    for path in paths:
        path.write_text("synthetic")
        os.utime(path, (0, 0))
    paths[1].touch()  # fresh / active
    (tmp_path / ("d" * 32 + ".html")).mkdir()

    @contextmanager
    def opened(path):
        yield path

    def check(path, *, directory):
        assert directory is False
        if path == paths[2] or path.is_dir():
            raise OSError("unsafe")

    browser._remove_stale(tmp_path, SimpleNamespace(opened=opened, check_private=check))
    assert not paths[0].exists()
    assert all(path.exists() for path in paths[1:])
    assert (tmp_path / ("d" * 32 + ".html")).is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows file ACLs and sharing")
def test_native_private_file_permissions_sharing_and_cleanup(tmp_path, monkeypatch):
    api = browser._WindowsFiles()
    api.base = tmp_path
    monkeypatch.setattr(browser, "_WindowsFiles", lambda: api)
    with browser._private_redirect(b"synthetic-only") as path:
        assert path.read_bytes() == b"synthetic-only"
        with api.opened(path) as handle:
            api.check_private(handle, directory=False)
        with pytest.raises(PermissionError):
            path.unlink()  # A live handoff cannot be removed by stale cleanup.
    assert not path.exists()


def test_linux_browser_behavior_is_unchanged(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    opened = MagicMock(return_value=True)
    monkeypatch.setattr(webui_support.webbrowser, "open", opened)
    assert webui_support._launch_browser("http://localhost/")
    opened.assert_called_once_with("http://localhost/", new=2, autoraise=True)
