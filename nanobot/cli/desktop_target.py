"""Discover and attach to an already-running Nanobot Desktop instance."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import stat
import struct
import sys
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

_DESCRIPTOR_NAME = "instance-v1.json"
_MAX_MESSAGE_BYTES = 8192
_PROTOCOL_TIMEOUT_S = 6.0
_SCHEMA_VERSION = 1


class DesktopTargetError(RuntimeError):
    """Raised when a discovered Desktop target cannot be used safely."""


@dataclass(frozen=True)
class DesktopReply:
    """Validated reply from the Desktop rendezvous protocol."""

    state: str
    capabilities: frozenset[str]
    webui_url: str | None = None
    tui: dict[str, object] | None = None


@dataclass(frozen=True)
class DesktopTarget:
    """Authenticated-on-use handle for one advertised Desktop instance."""

    instance_id: str
    transport: Literal["unix", "namedPipe"]
    address: str

    def request(self, operation: Literal["status", "webui", "tui"]) -> DesktopReply:
        """Perform one bounded, side-effect-free Desktop rendezvous request."""
        payload = json.dumps(
            {
                "schemaVersion": _SCHEMA_VERSION,
                "instanceId": self.instance_id,
                "operation": operation,
            },
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        try:
            if self.transport == "unix":
                raw = _unix_exchange(self.address, payload)
            else:
                raw = _named_pipe_exchange(self.address, payload)
            return _parse_reply(raw, expected_instance_id=self.instance_id)
        except DesktopTargetError:
            raise
        except OSError as exc:
            raise DesktopTargetError("Desktop connection unavailable") from exc


def discover_desktop_target() -> DesktopTarget | None:
    """Return the current user's advertised Desktop target, if one exists."""
    directory = _desktop_terminal_directory()
    if directory is None:
        return None
    descriptor = directory / _DESCRIPTOR_NAME
    try:
        descriptor.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DesktopTargetError("Desktop discovery is unavailable") from exc

    raw = _read_private_descriptor(directory, descriptor)
    return _parse_descriptor(raw, directory=directory)


def dispatch_bare_desktop_target(args: list[str]) -> int | None:
    """Handle Desktop selection for a bare interactive command.

    ``None`` means the caller should continue through the current Python
    environment. An integer means the invocation was handled here and should
    exit with that status.
    """
    if (
        args not in ([], ["webui"])
        or os.environ.get("_NANOBOT_COMPLETE")
        or not _interactive_shell()
    ):
        return None

    try:
        target = discover_desktop_target()
    except DesktopTargetError:
        print("Nanobot Desktop discovery could not be authenticated.", file=sys.stderr)
        _print_python_target()
        return None

    if target is None:
        _print_python_target()
        return None

    try:
        status = target.request("status")
    except DesktopTargetError:
        print("Nanobot Desktop is unavailable.", file=sys.stderr)
        _print_python_target()
        return None

    if status.state != "ready":
        print(f"Nanobot Desktop is not ready ({status.state}).", file=sys.stderr)
        _print_python_target()
        return None

    if _choose_target(status) == "python":
        _print_python_target()
        return None

    # Revalidate after selection. A status probe is never treated as authority
    # to reuse stale bootstrap data or silently choose another backend.
    if not args:
        from nanobot.cli.desktop_tui import launch_desktop_tui

        try:
            return launch_desktop_tui(target)
        except DesktopTargetError:
            _print_desktop_error("Desktop terminal attachment is unavailable or incompatible. Update Desktop and nanobot, then try again.")
            return 3

    try:
        reply = target.request("webui")
        url = _desktop_webui_url(reply)
    except DesktopTargetError:
        _print_desktop_error("Nanobot Desktop disconnected or returned an incompatible WebUI.")
        return 3
    from nanobot.cli.webui_support import _launch_browser

    try:
        opened = _launch_browser(url)
    except (OSError, ValueError, webbrowser.Error):
        # Browser exceptions can embed the credential-bearing URL. Report only
        # the failure, never the exception, and never fall back to Python.
        opened = False
    if not opened:
        _print_desktop_error("The default browser could not open Nanobot Desktop.")
        return 3
    print("Connected to Nanobot Desktop. Closing the browser leaves Desktop running.")
    return 0


def _interactive_shell() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _python_target_label() -> str:
    # Resolving a venv's symlink points at the base interpreter, losing identity.
    return os.path.abspath(sys.executable)


def _print_python_target() -> None:
    print(f"Using current Python environment: {_python_target_label()}")


def _print_desktop_error(message: str) -> None:
    print(f"{message} No backend was started.", file=sys.stderr)


def _choose_target(status: DesktopReply) -> Literal["desktop", "python"]:
    import questionary

    detail = "" if status.state == "ready" else f" ({status.state})"
    try:
        answer = questionary.select(
            "Nanobot Desktop is running. Choose a target for this invocation:",
            choices=[
                questionary.Choice(f"Nanobot Desktop{detail}", value="desktop"),
                questionary.Choice(
                    f"Current Python environment ({_python_target_label()})", value="python"
                ),
            ],
            default="desktop",
            instruction="(↑/↓ to move, Enter to confirm, Ctrl+C to cancel)",
        ).unsafe_ask()
    except (EOFError, KeyboardInterrupt):
        answer = None
    if answer == "desktop":
        return "desktop"
    if answer == "python":
        return "python"
    _print_desktop_error("Target selection cancelled.")
    raise SystemExit(130)


def _desktop_terminal_directory() -> Path | None:
    if sys.platform == "darwin":
        root = os.environ.get("NANOBOT_DESKTOP_ROOT", "").strip()
        base = Path(root).expanduser() if root else Path.home() / "Library/Application Support/Nanobot"
        return base.absolute() / "terminal"
    if sys.platform == "win32":
        override = os.environ.get("NANOBOT_DESKTOP_DATA_DIR", "").strip()
        local_app_data = override or os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            return None
        base = Path(os.path.expandvars(local_app_data)).expanduser()
        if not override:
            base /= "Nanobot"
        return base.absolute() / "terminal"
    return None


def _read_private_descriptor(directory: Path, descriptor: Path) -> bytes:
    if os.name == "nt":
        _validate_windows_path(directory, directory=True)
        _validate_windows_path(descriptor, directory=False)
        try:
            with descriptor.open("rb") as handle:
                raw = handle.read(_MAX_MESSAGE_BYTES + 1)
        except OSError as exc:
            raise DesktopTargetError("Desktop descriptor could not be read") from exc
    else:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_flags = (
            os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            directory_fd = os.open(directory, directory_flags)
        except OSError as exc:
            raise DesktopTargetError("Desktop terminal directory is not private") from exc
        try:
            _validate_posix_stat(os.fstat(directory_fd), directory=True)
            descriptor_fd = os.open(_DESCRIPTOR_NAME, file_flags, dir_fd=directory_fd)
            try:
                _validate_posix_stat(os.fstat(descriptor_fd), directory=False)
                raw = os.read(descriptor_fd, _MAX_MESSAGE_BYTES + 1)
            finally:
                os.close(descriptor_fd)
        except OSError as exc:
            raise DesktopTargetError("Desktop descriptor could not be read safely") from exc
        finally:
            os.close(directory_fd)
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise DesktopTargetError("Desktop descriptor is too large")
    return raw


def _validate_posix_stat(value: os.stat_result, *, directory: bool) -> None:
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected_type(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        raise DesktopTargetError("Desktop discovery is not private to the current user")


def _validate_windows_path(path: Path, *, directory: bool) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise DesktopTargetError("Desktop discovery path is unavailable") from exc
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    attributes = int(getattr(value, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if not expected_type(value.st_mode) or attributes & reparse:
        raise DesktopTargetError("Desktop discovery path is not a private regular path")


def _parse_descriptor(raw: bytes, *, directory: Path) -> DesktopTarget:
    try:
        value: object = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopTargetError("Desktop descriptor is invalid") from exc
    if not isinstance(value, dict):
        raise DesktopTargetError("Desktop descriptor is invalid")
    fields = cast(dict[str, object], value)
    schema_version = fields.get("schemaVersion")
    instance_id = fields.get("instanceId")
    transport = fields.get("transport")
    address = fields.get("address")
    if (
        type(schema_version) is not int
        or schema_version != _SCHEMA_VERSION
        or not isinstance(instance_id, str)
        or not isinstance(transport, str)
        or not isinstance(address, str)
    ):
        raise DesktopTargetError("Unsupported Desktop descriptor")
    try:
        uuid.UUID(instance_id)
    except ValueError as exc:
        raise DesktopTargetError("Desktop instance identity is invalid") from exc

    if sys.platform == "darwin":
        expected = str(directory / "connect-v1.sock")
        if transport != "unix" or address != expected:
            raise DesktopTargetError("Unsupported Desktop transport")
        selected_transport: Literal["unix", "namedPipe"] = "unix"
    elif sys.platform == "win32":
        expected = f"nanobot-desktop-v1-{instance_id}"
        if transport != "namedPipe" or address != expected:
            raise DesktopTargetError("Unsupported Desktop transport")
        selected_transport = "namedPipe"
    else:
        raise DesktopTargetError("Nanobot Desktop is not supported on this platform")
    return DesktopTarget(instance_id, selected_transport, address)


def _parse_reply(raw: bytes, *, expected_instance_id: str) -> DesktopReply:
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise DesktopTargetError("Desktop reply is too large")
    try:
        value: object = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopTargetError("Desktop reply is invalid") from exc
    if not isinstance(value, dict):
        raise DesktopTargetError("Desktop reply is invalid")
    fields = cast(dict[str, object], value)
    schema_version = fields.get("schemaVersion")
    instance_id = fields.get("instanceId")
    state_value = fields.get("state")
    raw_capabilities = fields.get("capabilities")
    webui_url = fields.get("webuiUrl")
    if (
        type(schema_version) is not int
        or schema_version != _SCHEMA_VERSION
        or instance_id != expected_instance_id
        or not isinstance(state_value, str)
        or state_value not in {"ready", "busy", "unavailable"}
        or not isinstance(raw_capabilities, list)
        or webui_url is not None
        and not isinstance(webui_url, str)
    ):
        raise DesktopTargetError("Desktop reply is incompatible")
    capability_values = cast(list[object], raw_capabilities)
    if any(not isinstance(item, str) for item in capability_values):
        raise DesktopTargetError("Desktop reply is incompatible")
    capabilities = frozenset(cast(list[str], capability_values))
    tui = fields.get("tui")
    if tui is not None and not isinstance(tui, dict):
        raise DesktopTargetError("Desktop terminal connection is incompatible")
    return DesktopReply(
        state=state_value, capabilities=capabilities, webui_url=webui_url,
        tui=cast(dict[str, object] | None, tui),
    )


def _desktop_webui_url(reply: DesktopReply) -> str:
    if reply.state != "ready":
        raise DesktopTargetError(f"Desktop is not ready ({reply.state})")
    if "webui" not in reply.capabilities or not reply.webui_url:
        raise DesktopTargetError("Desktop does not advertise WebUI attachment")
    if "\\" in reply.webui_url or reply.webui_url != reply.webui_url.strip() or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in reply.webui_url
    ):
        raise DesktopTargetError("Desktop returned an invalid WebUI URL")
    try:
        parsed = urlsplit(reply.webui_url)
        port = parsed.port  # Validate invalid/out-of-range ports before browser handoff.
    except ValueError as exc:
        raise DesktopTargetError("Desktop returned an invalid WebUI URL") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        raise DesktopTargetError("Desktop returned a non-loopback WebUI URL")
    return reply.webui_url


def _unix_exchange(address: str, payload: bytes) -> bytes:
    try:
        value = os.lstat(address)
    except OSError as exc:
        raise DesktopTargetError("Desktop socket is unavailable") from exc
    if (
        not stat.S_ISSOCK(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        raise DesktopTargetError("Desktop socket is not private to the current user")

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    deadline = time.monotonic() + _PROTOCOL_TIMEOUT_S
    try:
        client.settimeout(_remaining_seconds(deadline))
        client.connect(address)
        if not _peer_is_current_user(client):
            raise DesktopTargetError("Desktop socket peer identity did not match")
        client.settimeout(_remaining_seconds(deadline))
        client.sendall(payload)
        return _read_socket_line(client, deadline=deadline)
    finally:
        client.close()


def _peer_is_current_user(client: socket.socket) -> bool:
    if sys.platform == "darwin":
        uid = ctypes.c_uint()
        gid = ctypes.c_uint()
        library = ctypes.CDLL(None, use_errno=True)
        getpeereid = library.getpeereid
        getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        getpeereid.restype = ctypes.c_int
        return getpeereid(client.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0 and uid.value == os.geteuid()
    peer_credential = getattr(socket, "SO_PEERCRED", None)
    if peer_credential is None:
        return False
    raw = client.getsockopt(socket.SOL_SOCKET, peer_credential, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid == os.geteuid()


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DesktopTargetError("Desktop response timed out")
    return remaining


def _read_socket_line(client: socket.socket, *, deadline: float) -> bytes:
    data = bytearray()
    while len(data) <= _MAX_MESSAGE_BYTES:
        client.settimeout(_remaining_seconds(deadline))
        chunk = client.recv(min(1024, _MAX_MESSAGE_BYTES + 1 - len(data)))
        if not chunk:
            break
        newline = chunk.find(b"\n")
        if newline >= 0:
            data.extend(chunk[:newline])
            return bytes(data)
        data.extend(chunk)
    raise DesktopTargetError("Desktop disconnected or returned an oversized reply")


def _named_pipe_exchange(address: str, payload: bytes) -> bytes:
    if sys.platform != "win32":
        raise DesktopTargetError("Desktop named pipes are available only on Windows")
    return _windows_pipe_request(address, payload)


def _windows_pipe_request(address: str, payload: bytes) -> bytes:
    """Exchange one line over a bounded overlapped Windows named pipe."""
    from ctypes import wintypes

    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:  # pragma: no cover - defensive for non-Windows runtimes
        raise DesktopTargetError("Windows named pipe support is unavailable")
    kernel32: Any = loader("kernel32", use_last_error=True)

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    io_arguments = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(Overlapped),
    ]
    kernel32.WriteFile.argtypes = io_arguments
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = io_arguments
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Overlapped),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    kernel32.GetOverlappedResult.restype = wintypes.BOOL
    kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped)]
    kernel32.CancelIoEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    generic_read = 0x80000000
    generic_write = 0x40000000
    open_existing = 3
    file_flag_overlapped = 0x40000000
    # Permit identity checks, but never let the pipe server impersonate us.
    security_identification = 0x00010000
    security_sqos_present = 0x00100000
    error_io_pending = 997
    wait_object_0 = 0
    invalid_handle = ctypes.c_void_p(-1).value
    pipe_name = rf"\\.\pipe\{address}"
    deadline = time.monotonic() + _PROTOCOL_TIMEOUT_S

    remaining_ms = max(1, int(_remaining_seconds(deadline) * 1000))
    if not kernel32.WaitNamedPipeW(pipe_name, remaining_ms):
        raise DesktopTargetError("Desktop named pipe is unavailable")
    handle = kernel32.CreateFileW(
        pipe_name,
        generic_read | generic_write,
        0,
        None,
        open_existing,
        file_flag_overlapped | security_sqos_present | security_identification,
        None,
    )
    if handle == invalid_handle:
        raise DesktopTargetError("Desktop named pipe could not be opened")

    def transfer(function: Any, buffer: Any, size: int) -> int:
        _remaining_seconds(deadline)
        event = kernel32.CreateEventW(None, True, False, None)
        if not event:
            raise DesktopTargetError("Desktop named pipe event could not be created")
        overlapped = Overlapped()
        overlapped.hEvent = event
        transferred = wintypes.DWORD()
        pending = False
        try:
            complete = function(
                handle,
                buffer,
                size,
                ctypes.byref(transferred),
                ctypes.byref(overlapped),
            )
            if not complete and ctypes.get_last_error() != error_io_pending:
                raise DesktopTargetError("Desktop named pipe I/O failed")
            if not complete:
                pending = True
                wait_ms = max(1, int(_remaining_seconds(deadline) * 1000))
                if kernel32.WaitForSingleObject(event, wait_ms) != wait_object_0:
                    raise DesktopTargetError("Desktop named pipe response timed out")
                if not kernel32.GetOverlappedResult(
                    handle, ctypes.byref(overlapped), ctypes.byref(transferred), False
                ):
                    raise DesktopTargetError("Desktop named pipe I/O failed")
                pending = False
            return int(transferred.value)
        finally:
            if pending:
                # CancelIoEx only requests cancellation. The OS still owns these
                # buffers and OVERLAPPED until completion (also on Ctrl+C).
                kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
                kernel32.GetOverlappedResult(
                    handle, ctypes.byref(overlapped), ctypes.byref(transferred), True
                )
            kernel32.CloseHandle(event)

    try:
        _verify_windows_pipe_owner(handle, kernel32=kernel32)
        outgoing = ctypes.create_string_buffer(payload)
        if transfer(kernel32.WriteFile, outgoing, len(payload)) != len(payload):
            raise DesktopTargetError("Desktop named pipe write was incomplete")
        data = bytearray()
        while len(data) <= _MAX_MESSAGE_BYTES:
            incoming = ctypes.create_string_buffer(
                min(1024, _MAX_MESSAGE_BYTES + 1 - len(data))
            )
            count = transfer(kernel32.ReadFile, incoming, len(incoming))
            if count <= 0:
                break
            chunk = incoming.raw[:count]
            newline = chunk.find(b"\n")
            if newline >= 0:
                data.extend(chunk[:newline])
                return bytes(data)
            data.extend(chunk)
    finally:
        kernel32.CloseHandle(handle)
    raise DesktopTargetError("Desktop disconnected or returned an oversized reply")


def _verify_windows_pipe_owner(handle: Any, *, kernel32: Any) -> None:
    """Authenticate the opened pipe, not its spoofable discovery filename.

    Match the process token's owner SID, as .NET CurrentUserOnly does (including
    elevation). No request or bootstrap URL is exchanged before verification.
    """
    from ctypes import wintypes

    loader = getattr(ctypes, "WinDLL")
    advapi32: Any = loader("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(wintypes.LPVOID)
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
        pointer, pointer, pointer, pointer, pointer,
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID

    owner = wintypes.LPVOID()
    security_descriptor = wintypes.LPVOID()
    token = wintypes.HANDLE()
    se_kernel_object = 6
    owner_security_information = 1
    token_query = 0x0008
    token_owner = 4
    try:
        if advapi32.GetSecurityInfo(
            handle, se_kernel_object, owner_security_information,
            ctypes.byref(owner), None, None, None, ctypes.byref(security_descriptor),
        ) != 0 or not owner.value:
            raise DesktopTargetError("Desktop named pipe owner could not be verified")
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
        ):
            raise DesktopTargetError("Current Windows user could not be verified")
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, token_owner, None, 0, ctypes.byref(required))
        if not 0 < required.value <= 65536:
            raise DesktopTargetError("Current Windows user could not be verified")
        owner_info = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, token_owner, owner_info, len(owner_info), ctypes.byref(required)
        ):
            raise DesktopTargetError("Current Windows user could not be verified")
        # TOKEN_OWNER contains one PSID backed by this token-information buffer.
        current_owner = ctypes.cast(owner_info, pointer).contents
        if not current_owner.value or not advapi32.EqualSid(owner, current_owner):
            raise DesktopTargetError("Desktop named pipe owner is not the current user")
    finally:
        if token.value:
            kernel32.CloseHandle(token)
        if security_descriptor.value:
            kernel32.LocalFree(security_descriptor)
