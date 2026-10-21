"""User-private, process-bound Windows gateway shutdown signals."""

from __future__ import annotations

import ctypes
import re
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from ctypes import wintypes
from functools import lru_cache
from typing import Any


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("descriptor", wintypes.LPVOID),
        ("inherit", wintypes.BOOL),
    ]


@lru_cache(maxsize=1)
def _kernel32() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CreateEventW.argtypes = [
        ctypes.POINTER(_SecurityAttributes), wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
    ]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    return kernel


@contextmanager
def _private_security() -> Generator[_SecurityAttributes]:
    kernel = _kernel32()
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    security.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR),
    ]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), wintypes.LPVOID,
    ]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError()
    sid_text = wintypes.LPWSTR()
    descriptor = wintypes.LPVOID()
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if not size.value:
            raise ctypes.WinError()
        user = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, user, len(user), ctypes.byref(size)):
            raise ctypes.WinError()
        sid = ctypes.cast(user, ctypes.POINTER(wintypes.LPVOID))[0]
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise ctypes.WinError()
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"O:{sid_text.value}D:P(A;;GA;;;{sid_text.value})", 1,
            ctypes.byref(descriptor), None,
        ):
            raise ctypes.WinError()
        yield _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(sid_text)
        kernel.CloseHandle(token)


def _event_name(pid: int, identity: str, token: str) -> str:
    return rf"Local\nanobot-gateway-stop-{pid}-{identity}-{token}"


class WindowsShutdownEvent:
    """Own one latched signal; close only after the native waiter has drained."""

    def __init__(self, pid: int, identity: str) -> None:
        self.token = uuid.uuid4().hex
        kernel = _kernel32()
        with _private_security() as security:
            ctypes.set_last_error(0)
            handle = kernel.CreateEventW(
                ctypes.byref(security), True, False, _event_name(pid, identity, self.token),
            )
            error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS: the requested DACL was not applied.
            kernel.CloseHandle(handle)
            raise OSError("Gateway shutdown event already exists")
        self._handle: int | None = int(handle)

    def wait(self) -> None:
        """Block a worker, never the event loop; signal() also wakes cancellation."""
        if _kernel32().WaitForSingleObject(self._handle, 0xFFFFFFFF) != 0:
            raise ctypes.WinError()

    def signal(self) -> None:
        if not _kernel32().SetEvent(self._handle):
            raise ctypes.WinError()

    def close(self) -> None:
        if self._handle is not None:
            _kernel32().CloseHandle(self._handle)
            self._handle = None


def request_windows_shutdown(pid: int, identity: str, token: object) -> bool:
    """Signal only a validated token in this exact process-birth namespace."""
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{32}", token) is None:
        return False
    kernel = _kernel32()
    handle = kernel.OpenEventW(0x0002, False, _event_name(pid, identity, token))
    if not handle:
        error = ctypes.get_last_error()
        if error == 2:  # The process exited, or never published this event.
            return False
        raise ctypes.WinError(error)
    try:
        if not kernel.SetEvent(handle):
            raise ctypes.WinError()
        return True
    finally:
        kernel.CloseHandle(handle)
