"""Best-effort macOS Dock presence for local WebUI clients and gateways.

The icon owns no gateway lease or user data. Open local sockets keep one helper
alive; the OS closes them even when a launcher is killed. Everything executable
comes from the current installation, never a download or generated shell script.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import plistlib
import shutil
import socket
import stat
import subprocess
import sys
import threading
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from filelock import FileLock
from loguru import logger

_WORKER = Path(__file__).with_name("_macos_dock.py")
_ICON = Path(__file__).with_name("assets") / "dock-icon.png"
_STARTUP_TIMEOUT = 10


def _desktop_available() -> bool:
    if sys.platform != "darwin" or any(os.environ.get(key) for key in (
        "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY",
    )):
        return False
    try:
        return os.getuid() != 0 and Path("/dev/console").stat().st_uid == os.getuid()
    except OSError:
        return False


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("Dock directory must be private to this user")


def _directory(instance: Path, url: str) -> Path:
    # Keep AF_UNIX paths short and isolate installations, instances and dev URLs.
    # macOS AF_UNIX addresses are limited to 104 bytes. TMPDIR can be an arbitrary
    # long path (including during isolated update acceptance); this directory is
    # private, owner-checked and contains neither the URL nor user data.
    root = Path("/tmp") / f"nanobot-dock-{os.getuid()}"
    _private_directory(root)
    origin = urlsplit(url)._replace(query="", fragment="").geturl()
    identity = "\0".join((str(instance), sys.executable, str(_WORKER), origin)).encode()
    digest = hashlib.sha256(identity + _WORKER.read_bytes() + _ICON.read_bytes()).hexdigest()
    directory = root / digest[:12]
    _private_directory(directory)
    return directory


def _bundle(directory: Path) -> Path:
    contents = directory / "nanobot.app" / "Contents"
    executable = contents / "MacOS" / "nanobot"
    executable.parent.mkdir(parents=True, exist_ok=True)
    resources = contents / "Resources"
    resources.mkdir(exist_ok=True)
    if not executable.is_symlink():
        executable.symlink_to(sys.executable)
    elif os.readlink(executable) != sys.executable:
        raise ValueError("Dock interpreter does not match this installation")
    shutil.copyfile(_ICON, resources / "dock-icon.png")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "nanobot",
        "CFBundleIdentifier": f"dev.nanobot.webui.{directory.name}",
        "CFBundleName": "nanobot",
        "CFBundleDisplayName": "nanobot",
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "dock-icon.png",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    }))
    return executable


def _connect(address: Path) -> socket.socket | None:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(2)
    try:
        connection.connect(str(address))
        return connection
    except (FileNotFoundError, ConnectionRefusedError):
        connection.close()
        return None
    except OSError:
        connection.close()
        raise


def _attach(directory: Path, url: str) -> socket.socket:
    address = directory / "s"
    process: subprocess.Popen[bytes] | None = None
    connection: socket.socket | None = None
    with FileLock(str(directory / "start.lock"), timeout=_STARTUP_TIMEOUT):
        try:
            connection = _connect(address)
            if connection is None:
                if address.exists():
                    if not stat.S_ISSOCK(address.lstat().st_mode):
                        raise ValueError("Unexpected Dock socket path")
                    address.unlink()
                executable = _bundle(directory)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    listener.bind(str(address))
                    listener.listen()
                    process = subprocess.Popen(
                        [str(executable), "-I", "-S", str(_WORKER), str(listener.fileno()),
                         str(address), str(_ICON)],
                        pass_fds=(listener.fileno(),), stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    # Reap our child without making its lifetime depend on this thread.
                    threading.Thread(target=process.wait, daemon=True).start()
                    connection = _connect(address)
            if connection is None:
                raise OSError("Dock helper did not start")
            # Connecting to the inherited listener is immediate, but the helper
            # loads AppKit before acknowledging readiness. A cold post-update
            # launch can exceed the short socket-connect deadline. Keep this
            # bounded off the gateway event loop, including concurrent joiners.
            connection.settimeout(_STARTUP_TIMEOUT)
            # Credentials stay in the private local socket, never argv or a file.
            connection.sendall(url.encode("utf-8") + b"\n")
            if connection.recv(1) != b"1":
                raise OSError("Dock helper did not become ready")
            return connection
        except BaseException:
            # Ctrl-C can arrive during startup, before the context owns this socket.
            # Clean up the new helper too, then propagate the original interruption.
            if connection is not None:
                connection.close()
            if process is not None and process.poll() is None:
                process.terminate()
            raise


@contextmanager
def dock_icon(url: str, *, instance: Path, enabled: bool = True) -> Generator[None]:
    """Show a shared icon while this WebUI launcher is attached; never own its service."""
    connection: socket.socket | None = None
    if enabled and _desktop_available():
        from nanobot.cli._macos_dock import is_local_browser_url

        try:
            if is_local_browser_url(url):
                connection = _attach(_directory(instance, url), url)
        except (OSError, ValueError, TimeoutError) as exc:
            # Do not include exception text: URL/installation details are private.
            logger.debug("Dock startup failure category: {}", type(exc).__name__)
            logger.warning("Dock icon unavailable; WebUI can still be used in your browser.")
    try:
        yield
    finally:
        if connection is not None:
            connection.close()


def request_gateway_icon(instance: Path, *, enabled: bool) -> None:
    """Remember desktop intent, not a service lease, credential, or restart command."""
    if not _desktop_available():
        return
    from nanobot.utils.atomic_file import atomic_write_text

    try:
        instance.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(instance.with_suffix(".dock"), f"{'show' if enabled else 'hide'}:{uuid4().hex}")
    except OSError:
        logger.warning("Dock preference unavailable; WebUI can still be used in your browser.")


def _watch_gateway_icon(url: str, instance: Path, stopped: threading.Event) -> None:
    selected = ""
    presence = ExitStack()
    try:
        while not stopped.is_set():
            try:
                with instance.with_suffix(".dock").open(encoding="ascii") as stream:
                    request = stream.read(64)
            except (OSError, UnicodeError):
                request = ""
            if request != selected:
                replacement = ExitStack()
                if request.startswith("show:"):
                    # Join before releasing our old connection, so reopening the
                    # launcher cannot race the last-client cleanup of a live icon.
                    replacement.enter_context(dock_icon(url, instance=instance))
                presence.close()
                presence = replacement
                selected = request
            stopped.wait(0.5)
    finally:
        presence.close()


async def watch_gateway_icon(url: str, *, instance: Path, activated: asyncio.Event) -> None:
    """Own optional Dock presence only after ordinary/protected startup is activated.

    The persisted request lets an existing gateway observe a detached launcher and
    lets the next gateway generation restore it. No updater or data format changes.
    Quitting the icon is respected until another explicit request or service start.
    """
    if not _desktop_available():
        return
    await activated.wait()
    stopped = threading.Event()
    watcher = asyncio.create_task(asyncio.to_thread(_watch_gateway_icon, url, instance, stopped))
    try:
        await asyncio.shield(watcher)
    finally:
        stopped.set()
        # Never leave a still-starting helper behind when the gateway is cancelled.
        await watcher
