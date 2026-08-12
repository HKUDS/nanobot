"""Windows Job Object ownership for subprocess trees."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_CREATE_SUSPENDED = 0x00000004
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_kernel32.CreateJobObjectW.restype = wintypes.HANDLE
_kernel32.SetInformationJobObject.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_kernel32.SetInformationJobObject.restype = wintypes.BOOL
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateProcess.restype = wintypes.BOOL
_kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateJobObject.restype = wintypes.BOOL
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
_kernel32.Thread32First.restype = wintypes.BOOL
_kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
_kernel32.Thread32Next.restype = wintypes.BOOL
_kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenThread.restype = wintypes.HANDLE
_kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
_kernel32.ResumeThread.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def _win_error(operation: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{operation} failed (Windows error {code})")


def _close_handle(handle: int | None) -> None:
    if handle:
        _kernel32.CloseHandle(handle)


def _set_kill_on_close(handle: int, enabled: bool) -> None:
    info = _ExtendedLimitInformation()
    if enabled:
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _win_error("SetInformationJobObject")


def _resume_primary_thread(pid: int) -> None:
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        raise _win_error("CreateToolhelp32Snapshot")
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        found = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME,
                    False,
                    entry.th32ThreadID,
                )
                if not thread:
                    raise _win_error("OpenThread")
                try:
                    if _kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                        raise _win_error("ResumeThread")
                    return
                finally:
                    _close_handle(thread)
            found = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        raise RuntimeError(f"suspended process {pid} has no resumable thread")
    finally:
        _close_handle(snapshot)


class WindowsJob:
    """Own a process tree even after its root process exits."""

    creation_flags = _CREATE_SUSPENDED

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle

    @classmethod
    def create(cls) -> WindowsJob:
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise _win_error("CreateJobObjectW")
        try:
            _set_kill_on_close(handle, True)
        except Exception:
            _close_handle(handle)
            raise
        return cls(handle)

    def assign_and_resume(self, pid: int) -> None:
        """Atomically establish tree ownership before the root can spawn."""
        if self._handle is None:
            raise RuntimeError("Windows job is already closed")
        process = _kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE,
            False,
            pid,
        )
        if not process:
            error = _win_error("OpenProcess")
            self.close()
            raise error

        if not _kernel32.AssignProcessToJobObject(self._handle, process):
            error = _win_error("AssignProcessToJobObject")
            _kernel32.TerminateProcess(process, 1)
            _close_handle(process)
            self.close()
            raise error

        try:
            _resume_primary_thread(pid)
        except Exception:
            self.terminate()
            raise
        finally:
            _close_handle(process)

    def release(self) -> None:
        """Release ownership after successful output collection."""
        if self._handle is None:
            return
        _set_kill_on_close(self._handle, False)
        self.close()

    def terminate(self) -> None:
        """Terminate every process in the job and close its handle."""
        if self._handle is None:
            return
        try:
            _kernel32.TerminateJobObject(self._handle, 1)
        finally:
            self.close()

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        _close_handle(handle)
