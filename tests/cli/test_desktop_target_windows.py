"""Win32 boundary tests; native pipe integration additionally runs on Windows."""

import ctypes
import os
import threading
import uuid
from ctypes import wintypes
from unittest.mock import MagicMock

import pytest

from nanobot.cli import desktop_target
from nanobot.cli.desktop_target import DesktopTargetError


def _set_pointer(pointer, value, value_type=wintypes.LPVOID):
    ctypes.cast(pointer, ctypes.POINTER(value_type)).contents.value = value


@pytest.fixture
def kernel(monkeypatch):
    api = MagicMock()
    api.WaitNamedPipeW.return_value = True
    api.CreateFileW.return_value = 11
    api.CreateEventW.return_value = 12
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_kw: api, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 997, raising=False)
    monkeypatch.setattr(desktop_target, "_verify_windows_pipe_owner", lambda *_a, **_kw: None)
    return api


def test_windows_pipe_authenticates_before_io(monkeypatch, kernel):
    def deny(*_args, **_kwargs):
        raise DesktopTargetError("wrong owner")

    monkeypatch.setattr(desktop_target, "_verify_windows_pipe_owner", deny)
    with pytest.raises(DesktopTargetError, match="wrong owner"):
        desktop_target._windows_pipe_request("local-test", b"request\n")
    kernel.WriteFile.assert_not_called()
    kernel.ReadFile.assert_not_called()
    kernel.CloseHandle.assert_called_once_with(11)
    # No impersonation/delegation; only allow identifying the connecting user.
    assert kernel.CreateFileW.call_args.args[5] == 0x40110000
    assert kernel.CreateFileW.call_args.args[0] == r"\\.\pipe\local-test"


@pytest.mark.parametrize("failure", ["timeout", "interrupt", "deadline"])
def test_windows_pending_io_is_drained_before_buffers_are_freed(monkeypatch, kernel, failure):
    lifecycle = []
    kernel.WriteFile.return_value = False
    kernel.WaitForSingleObject.return_value = 258  # WAIT_TIMEOUT
    if failure == "interrupt":
        kernel.WaitForSingleObject.side_effect = KeyboardInterrupt
    elif failure == "deadline":
        # Whole request budget: wait-pipe, pre-transfer, then pending wait.
        monkeypatch.setattr(
            desktop_target, "_remaining_seconds",
            MagicMock(side_effect=[1.0, 0.5, DesktopTargetError("timed out")]),
        )
    kernel.CancelIoEx.side_effect = lambda *_: lifecycle.append("cancel") or True
    kernel.GetOverlappedResult.side_effect = (
        lambda _h, _o, _n, wait: lifecycle.append(("drain", wait)) or False
    )
    kernel.CloseHandle.side_effect = lambda handle: lifecycle.append(("close", handle))
    expected = KeyboardInterrupt if failure == "interrupt" else DesktopTargetError
    with pytest.raises(expected):
        desktop_target._windows_pipe_request("local-test", b"request\n")
    assert lifecycle == ["cancel", ("drain", True), ("close", 12), ("close", 11)]


def test_windows_synchronous_io_cannot_restart_expired_budget(monkeypatch, kernel):
    def write(_handle, _buffer, size, count, _overlapped):
        _set_pointer(count, size, wintypes.DWORD)
        return True

    kernel.WriteFile.side_effect = write
    monkeypatch.setattr(
        desktop_target, "_remaining_seconds",
        MagicMock(side_effect=[1.0, 0.5, DesktopTargetError("timed out")]),
    )
    with pytest.raises(DesktopTargetError, match="timed out"):
        desktop_target._windows_pipe_request("local-test", b"request\n")
    kernel.ReadFile.assert_not_called()
    kernel.CancelIoEx.assert_not_called()


@pytest.mark.parametrize("same_user", [False, True])
def test_windows_owner_sid_is_checked_and_handles_released(monkeypatch, same_user):
    kernel = MagicMock()
    security = MagicMock()
    kernel.GetCurrentProcess.return_value = -1

    def security_info(_handle, object_type, fields, owner, _g, _d, _s, descriptor):
        assert object_type == 6 and fields == 1
        _set_pointer(owner, 101)
        _set_pointer(descriptor, 102)
        return 0

    def open_token(_process, access, token):
        assert access == 8
        _set_pointer(token, 13)
        return True

    def token_info(_token, kind, buffer, _length, required):
        assert kind == 4  # TOKEN_OWNER matches .NET CurrentUserOnly, including elevation.
        _set_pointer(required, 64, wintypes.DWORD)
        if buffer is None:
            return False
        _set_pointer(buffer, 101 if same_user else 201)
        return True

    security.GetSecurityInfo.side_effect = security_info
    security.OpenProcessToken.side_effect = open_token
    security.GetTokenInformation.side_effect = token_info
    security.EqualSid.side_effect = lambda owner, user: owner.value == user.value
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_kw: security, raising=False)
    if same_user:
        desktop_target._verify_windows_pipe_owner(11, kernel32=kernel)
    else:
        with pytest.raises(DesktopTargetError, match="not the current user"):
            desktop_target._verify_windows_pipe_owner(11, kernel32=kernel)
    security.EqualSid.assert_called_once()
    assert kernel.CloseHandle.call_args.args[0].value == 13
    assert kernel.LocalFree.call_args.args[0].value == 102


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows named pipes")
def test_native_windows_pipe_roundtrip():
    # _winapi is bundled with CPython on Windows; no test/runtime dependency.
    winapi = pytest.importorskip("_winapi")
    address = f"nanobot-desktop-v1-{uuid.uuid4()}"
    handle = winapi.CreateNamedPipe(
        rf"\\.\pipe\{address}",
        winapi.PIPE_ACCESS_DUPLEX | winapi.FILE_FLAG_OVERLAPPED,
        0,  # PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT
        1, 8192, 8192, 1000, 0,
    )
    connected = winapi.ConnectNamedPipe(handle, overlapped=True)
    received = []
    failures = []

    def serve():
        try:
            connected.GetOverlappedResult(True)
            pending, _ = winapi.ReadFile(handle, 8192, True)
            pending.GetOverlappedResult(True)
            received.append(pending.getbuffer())
            pending, _ = winapi.WriteFile(handle, b'{"state":"ready"}\n', True)
            pending.GetOverlappedResult(True)
        except OSError as exc:
            failures.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert desktop_target._windows_pipe_request(address, b"status\n") == b'{"state":"ready"}'
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert received == [b"status\n"]
        assert not failures
    finally:
        connected.cancel()
        winapi.CloseHandle(handle)
        thread.join(timeout=2)
