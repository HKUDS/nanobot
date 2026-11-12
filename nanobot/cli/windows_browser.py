"""Windows browser handoff without putting bootstrap URLs in process arguments.

This stdlib-only module also runs in an isolated, short-lived child interpreter.
The child owns the redirect file so its lifetime does not depend on the CLI staying
open. URLs travel only through an anonymous pipe and the ACL-protected file.
"""

from __future__ import annotations

import ctypes
import html
import re
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

_MAX_URL_BYTES = 65536
_START_TIMEOUT_S = 10.0
_FILE_LIFETIME_S = 120.0
_STALE_AFTER_S = 600.0
_DIRECTORY_NAME = "NanobotBrowserHandoff-v1"
_FILE_NAME = re.compile(r"[0-9a-f]{32}\.html")


def _url_bytes(url: str) -> bytes:
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("Invalid browser URL")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid browser URL")
    data = url.encode("utf-8")
    if len(data) > _MAX_URL_BYTES:
        raise ValueError("Browser URL is too long")
    return data


def launch_browser(url: str) -> bool:
    """Wait for a credential-free native launch acknowledgement, not file expiry."""
    process: subprocess.Popen[bytes] | None = None
    worker: threading.Thread | None = None
    opened = False
    try:
        payload = _url_bytes(url) + b"\n"
        # -I -S keeps user-site, cwd, PYTHONPATH and .pth startup code out of this
        # stdlib-only helper. In particular, do not use BROWSER or URL arguments.
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        incoming, outgoing = process.stdin, process.stdout
        if incoming is None or outgoing is None:
            return False
        reply: list[bytes] = []

        def exchange() -> None:
            try:
                incoming.write(payload)
                incoming.close()
                reply.append(outgoing.read(1))
            except OSError:
                pass

        worker = threading.Thread(target=exchange, daemon=True)
        worker.start()
        worker.join(_START_TIMEOUT_S)
        opened = not worker.is_alive() and reply == [b"1"]
        return opened
    except (OSError, ValueError, RuntimeError):
        # Existing callers display exception text. Never return a URL-bearing
        # exception or retry using raw ShellExecute/webbrowser URL dispatch.
        return False
    finally:
        if process is not None:
            if not opened:
                try:
                    process.kill()
                except OSError:
                    pass
            # Reap even in a long-running gateway, without retaining its caller.
            threading.Thread(target=process.wait, daemon=True).start()
            if worker is not None:
                worker.join(1.0)
            if worker is None or not worker.is_alive():
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except OSError:
                            pass


def _redirect_html(url: str) -> bytes:
    _url_bytes(url)
    return (
        '<!doctype html><meta charset="utf-8">'
        '<meta name="referrer" content="no-referrer">'
        '<meta http-equiv="refresh" content="0; url='
        + html.escape(url, quote=True)
        + '"><title>Opening Nanobot</title>'
    ).encode("utf-8")


def _serve(incoming: BinaryIO, outgoing: BinaryIO, *, lifetime: float = _FILE_LIFETIME_S) -> int:
    data = incoming.readline(_MAX_URL_BYTES + 2)
    if not data.endswith(b"\n") or len(data) > _MAX_URL_BYTES + 1:
        return 1
    content = _redirect_html(data[:-1].decode("utf-8"))
    with _private_redirect(content) as path:
        if not _open_redirect(path):
            return 1
        outgoing.write(b"1")
        outgoing.flush()
        time.sleep(lifetime)
    return 0


def _bind(library: Any, name: str, result: Any, *arguments: Any) -> Any:
    function = getattr(library, name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _WindowsFiles:
    """Native file boundary; no chmod or inherited-ACL assumptions."""

    def __init__(self) -> None:
        loader = getattr(ctypes, "WinDLL")
        kernel = loader("kernel32", use_last_error=True)
        security = loader("advapi32", use_last_error=True)
        shell = loader("shell32", use_last_error=True)
        ole = loader("ole32", use_last_error=True)
        ptr = wintypes.LPVOID
        pptr = ctypes.POINTER(ptr)
        word = wintypes.DWORD
        pword = ctypes.POINTER(word)
        handle = wintypes.HANDLE
        text = wintypes.LPCWSTR
        boolean = wintypes.BOOL
        self.close = _bind(kernel, "CloseHandle", boolean, handle)
        self.free = _bind(kernel, "LocalFree", ptr, ptr)
        self.create_file = _bind(
            kernel, "CreateFileW", handle, text, word, word, ptr, word, word, handle,
        )
        self.create_directory = _bind(kernel, "CreateDirectoryW", boolean, text, ptr)
        self.attributes = _bind(
            kernel, "GetFileInformationByHandleEx", boolean, handle, ctypes.c_int, ptr, word,
        )
        self.volume = _bind(
            kernel, "GetVolumeInformationByHandleW", boolean,
            handle, ptr, word, pword, pword, pword, ptr, word,
        )
        self.write = _bind(kernel, "WriteFile", boolean, handle, ptr, word, pword, ptr)
        self.get_security = _bind(
            security, "GetSecurityInfo", word,
            handle, ctypes.c_int, word, pptr, pptr, pptr, pptr, pptr,
        )
        self.control = _bind(
            security, "GetSecurityDescriptorControl", boolean,
            ptr, ctypes.POINTER(wintypes.WORD), pword,
        )
        self.get_ace = _bind(security, "GetAce", boolean, ptr, word, pptr)
        self.sid_string = _bind(
            security, "ConvertSidToStringSidW", boolean, ptr, ctypes.POINTER(wintypes.LPWSTR),
        )
        self.convert_sd = _bind(
            security, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            boolean, text, word, pptr, pword,
        )
        current = _bind(kernel, "GetCurrentProcess", handle)
        open_token = _bind(security, "OpenProcessToken", boolean, handle, word, ctypes.POINTER(handle))
        token_info = _bind(security, "GetTokenInformation", boolean, handle, ctypes.c_int, ptr, word, pword)
        token = handle()
        if not open_token(current(), 0x0008, ctypes.byref(token)):
            raise OSError("Cannot identify Windows user")
        try:
            size = word()
            token_info(token, 1, None, 0, ctypes.byref(size))  # TokenUser, not TokenOwner
            if not 0 < size.value <= 65536:
                raise OSError("Invalid Windows user information")
            buffer = ctypes.create_string_buffer(size.value)
            if not token_info(token, 1, buffer, len(buffer), ctypes.byref(size)):
                raise OSError("Cannot identify Windows user")
            self.user = self._sid_text(ctypes.cast(buffer, pptr).contents)
        finally:
            self.close(token)
        folder = _bind(shell, "SHGetKnownFolderPath", ctypes.c_int32, ptr, word, handle,
                       ctypes.POINTER(wintypes.LPWSTR))
        free_folder = _bind(ole, "CoTaskMemFree", None, ptr)
        guid = ctypes.create_string_buffer(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
        location = wintypes.LPWSTR()
        try:
            if folder(guid, 0, None, ctypes.byref(location)) != 0 or not location.value:
                raise OSError("Cannot locate local application data")
            self.base = Path(location.value)
            if not self.base.is_absolute() or len(self.base.drive) != 2:
                raise OSError("Browser handoff requires a local volume")
        finally:
            if location:
                free_folder(location)

    def _sid_text(self, sid: Any) -> str:
        value = wintypes.LPWSTR()
        try:
            if not sid or not self.sid_string(sid, ctypes.byref(value)) or not value.value:
                raise OSError("Cannot verify Windows identity")
            return value.value
        finally:
            if value:
                self.free(value)

    @contextmanager
    def descriptor(self) -> Generator[_SecurityAttributes, None, None]:
        descriptor = wintypes.LPVOID()
        try:
            # Protected DACL, one non-inherited ACE, no group/admin grants.
            if not self.convert_sd(
                f"O:{self.user}D:P(A;;FA;;;{self.user})", 1, ctypes.byref(descriptor), None,
            ):
                raise OSError("Cannot create private file security")
            yield _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        finally:
            if descriptor:
                self.free(descriptor)

    @contextmanager
    def opened(
        self, path: Path, *, access: int = 0x20080, create: Any = None,
    ) -> Generator[Any, None, None]:
        handle = self.create_file(
            str(path), access, 3, create, 1 if create is not None else 3,
            0x02200000, None,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT, no delete sharing
        )
        if handle is None or handle == wintypes.HANDLE(-1).value:
            raise OSError("Cannot open browser handoff storage")
        try:
            yield handle
        finally:
            self.close(handle)

    def check_type(self, handle: Any, *, directory: bool) -> None:
        attributes = (wintypes.DWORD * 2)()  # FILE_ATTRIBUTE_TAG_INFO
        if not self.attributes(handle, 9, attributes, ctypes.sizeof(attributes)):
            raise OSError("Cannot verify browser handoff storage")
        if attributes[0] & 0x400 or bool(attributes[0] & 0x10) != directory:
            raise OSError("Browser handoff storage cannot use reparse points")

    def check_private(self, handle: Any, *, directory: bool) -> None:
        self.check_type(handle, directory=directory)
        owner, acl, descriptor = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPVOID()
        try:
            if self.get_security(
                handle, 1, 5, ctypes.byref(owner), None, ctypes.byref(acl), None,
                ctypes.byref(descriptor),
            ) != 0 or not acl.value or self._sid_text(owner) != self.user:
                raise OSError("Browser handoff storage is not private")
            control, revision = wintypes.WORD(), wintypes.DWORD()
            if not self.control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
                raise OSError("Cannot verify private file security")
            # ACL header's AceCount is the third WORD; require one allow ACE.
            count = ctypes.cast(acl, ctypes.POINTER(wintypes.WORD))[2]
            ace = wintypes.LPVOID()
            if not control.value & 0x1000 or count != 1 or not self.get_ace(acl, 0, ctypes.byref(ace)):
                raise OSError("Browser handoff storage permits inherited or extra access")
            if not ace.value:
                raise OSError("Invalid private file access entry")
            header = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte))
            mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD)).contents.value
            if header[0] != 0 or header[1] != 0 or mask != 0x1F01FF:
                raise OSError("Browser handoff storage has unexpected access rules")
            if self._sid_text(ace.value + 8) != self.user:
                raise OSError("Browser handoff storage permits another user")
        finally:
            if descriptor:
                self.free(descriptor)


def _remove_stale(root: Path, api: _WindowsFiles) -> None:
    cutoff = time.time() - _STALE_AFTER_S
    for path in root.iterdir():
        if not _FILE_NAME.fullmatch(path.name):
            continue
        try:
            if path.lstat().st_mtime >= cutoff:
                continue
            with api.opened(path) as handle:
                api.check_private(handle, directory=False)
            # Active helpers deny delete sharing; never recurse or follow links.
            path.unlink()
        except OSError:
            continue


@contextmanager
def _private_redirect(content: bytes) -> Generator[Path, None, None]:
    api = _WindowsFiles()
    with api.descriptor() as security, ExitStack() as guards:
        # Pin the complete path, rejecting junctions before descending. A later
        # absolute open must not resolve through a swapped ancestor.
        for ancestor in reversed(api.base.parents):
            handle = guards.enter_context(api.opened(ancestor))
            api.check_type(handle, directory=True)
        handle = guards.enter_context(api.opened(api.base))
        api.check_type(handle, directory=True)
        flags = wintypes.DWORD()
        if not api.volume(handle, None, 0, None, None, ctypes.byref(flags), None, 0) or not flags.value & 8:
            raise OSError("Browser handoff requires filesystem ACL enforcement")
        root = api.base / _DIRECTORY_NAME
        created = api.create_directory(str(root), ctypes.byref(security))
        if not created and getattr(ctypes, "get_last_error")() != 183:
            raise OSError("Cannot create browser handoff directory")
        root_handle = guards.enter_context(api.opened(root))
        # Desired SECURITY_ATTRIBUTES do not secure an already-existing object.
        api.check_private(root_handle, directory=True)
        _remove_stale(root, api)
        path = root / f"{uuid.uuid4().hex}.html"
        owned = False
        try:
            with api.opened(path, access=0x40020080, create=ctypes.byref(security)) as file:
                owned = True
                api.check_private(file, directory=False)
                written = wintypes.DWORD()
                buffer = ctypes.create_string_buffer(content)
                if not api.write(file, buffer, len(content), ctypes.byref(written), None) or written.value != len(content):
                    raise OSError("Cannot write browser handoff file")
            # Do not keep a write/delete-access handle across browser startup:
            # browsers need not share those access modes with existing handles.
            with api.opened(path, access=0x80020080) as file:
                api.check_private(file, directory=False)
                yield path
        finally:
            if owned:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass  # A later invocation retries cleanup of private stale files.


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def _open_redirect(path: Path) -> bool:
    loader = getattr(ctypes, "WinDLL")
    ole, shell = loader("ole32"), loader("shell32")
    initialize = _bind(ole, "CoInitializeEx", ctypes.c_int32, wintypes.LPVOID, wintypes.DWORD)
    uninitialize = _bind(ole, "CoUninitialize", None)
    execute = _bind(shell, "ShellExecuteExW", wintypes.BOOL, ctypes.POINTER(_ShellExecuteInfo))
    if initialize(None, 6) not in {0, 1}:  # APARTMENTTHREADED | DISABLE_OLE1DDE
        return False
    try:
        info = _ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x501  # CLASSNAME | NOASYNC | FLAG_NO_UI
        info.lpVerb, info.lpClass = "open", "http"
        info.lpFile = str(path)
        info.nShow = 1
        return bool(execute(ctypes.byref(info)))
    finally:
        uninitialize()


if __name__ == "__main__":
    result = 1
    if sys.platform == "win32" and sys.argv[1:] == ["--serve"]:
        try:
            result = _serve(sys.stdin.buffer, sys.stdout.buffer)
        except Exception:
            pass  # No URL, HTML, or exception content may reach console/log output.
    raise SystemExit(result)
