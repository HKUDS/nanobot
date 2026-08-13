"""Native directory picker used by a locally hosted WebUI."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_PICKER_TIMEOUT_SECONDS = 300
_COMMON_ENV_KEYS = (
    "HOME",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TMPDIR",
    "USER",
)
_LINUX_GUI_ENV_KEYS = (
    "DBUS_SESSION_BUS_ADDRESS",
    "DESKTOP_SESSION",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_CURRENT_DESKTOP",
    "XDG_RUNTIME_DIR",
)
_MACOS_GUI_ENV_KEYS = ("SECURITYSESSIONID", "__CF_USER_TEXT_ENCODING")
_WINDOWS_GUI_ENV_KEYS = (
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATHEXT",
    "ProgramData",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "SESSIONNAME",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
)


class NativeFolderPickerError(RuntimeError):
    """Raised when an available native folder picker cannot complete."""


@dataclass(frozen=True)
class _PickerCommand:
    argv: tuple[str, ...]
    cancel_codes: frozenset[int]
    cancel_markers: tuple[str, ...] = ()


def _picker_command() -> _PickerCommand | None:
    if sys.platform == "darwin":
        executable = shutil.which("osascript")
        if executable is None:
            return None
        return _PickerCommand(
            argv=(
                executable,
                "-e",
                'set selectedFolder to choose folder with prompt "Select Workspace Directory"',
                "-e",
                "POSIX path of selectedFolder",
            ),
            cancel_codes=frozenset({1}),
            cancel_markers=("user canceled", "(-128)"),
        )

    if sys.platform == "win32":
        executable = shutil.which("powershell.exe") or shutil.which("powershell")
        if executable is None:
            return None
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$dialog=New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$dialog.Description='Select Workspace Directory';"
            "$dialog.ShowNewFolderButton=$true;"
            "if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();"
            "[Console]::Out.Write($dialog.SelectedPath)}"
        )
        return _PickerCommand(
            argv=(
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-STA",
                "-Command",
                script,
            ),
            cancel_codes=frozenset(),
        )

    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return None
        zenity = shutil.which("zenity")
        if zenity is not None:
            return _PickerCommand(
                argv=(
                    zenity,
                    "--file-selection",
                    "--directory",
                    "--title=Select Workspace Directory",
                ),
                cancel_codes=frozenset({1}),
            )
        kdialog = shutil.which("kdialog")
        if kdialog is not None:
            return _PickerCommand(
                argv=(kdialog, "--getexistingdirectory", str(Path.home())),
                cancel_codes=frozenset({1}),
            )
    return None


def native_folder_picker_available() -> bool:
    """Return whether this host can display a native directory picker."""
    return _picker_command() is not None


def _picker_environment() -> dict[str, str]:
    """Pass only host UI/runtime variables, never provider or gateway secrets."""
    keys: list[str] = list(_COMMON_ENV_KEYS)
    if sys.platform == "darwin":
        keys.extend(_MACOS_GUI_ENV_KEYS)
    elif sys.platform == "win32":
        keys.extend(_WINDOWS_GUI_ENV_KEYS)
    elif sys.platform.startswith("linux"):
        keys.extend(_LINUX_GUI_ENV_KEYS)
    return {
        key: value
        for key in keys
        if (value := os.environ.get(key)) is not None
    }


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()


async def pick_native_folder() -> str | None:
    """Open the platform directory picker and return an existing absolute path."""
    command = _picker_command()
    if command is None:
        raise NativeFolderPickerError("native folder picker is unavailable on this host")

    try:
        process = await asyncio.create_subprocess_exec(
            *command.argv,
            env=_picker_environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise NativeFolderPickerError("native folder picker failed to start") from exc
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_PICKER_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        await _stop_process(process)
        raise
    except TimeoutError as exc:
        await _stop_process(process)
        raise NativeFolderPickerError("native folder picker timed out") from exc

    error_text = stderr.decode("utf-8", errors="replace").strip()
    normalized_error = error_text.lower()
    if process.returncode != 0:
        if process.returncode in command.cancel_codes and (
            not command.cancel_markers
            or any(marker in normalized_error for marker in command.cancel_markers)
        ):
            return None
        raise NativeFolderPickerError("native folder picker failed")

    selected = stdout.decode("utf-8", errors="replace").strip()
    if not selected:
        return None
    path = Path(selected).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise NativeFolderPickerError("native folder picker returned an invalid directory")
    return str(path)
