"""Select local SSH files for the WebUI without reading their contents."""

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


class NativeFilePickerError(RuntimeError):
    """Raised when a native file picker cannot complete."""


@dataclass(frozen=True)
class _PickerCommand:
    argv: tuple[str, ...]
    cancel_codes: frozenset[int]
    cancel_markers: tuple[str, ...] = ()


def _picker_command() -> _PickerCommand | None:
    title = "Select SSH key or configuration file"
    if sys.platform == "darwin":
        executable = shutil.which("osascript")
        if executable is None:
            return None
        return _PickerCommand(
            argv=(
                executable,
                "-e",
                f'set selectedPath to choose file with prompt "{title}"',
                "-e",
                "POSIX path of selectedPath",
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
            "$dialog=New-Object System.Windows.Forms.OpenFileDialog;"
            f"$dialog.Title='{title}';"
            "$dialog.CheckFileExists=$true;$dialog.Multiselect=$false;"
            "if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();"
            "[Console]::Out.Write($dialog.FileName)}"
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
                    f"--title={title}",
                ),
                cancel_codes=frozenset({1}),
            )
        kdialog = shutil.which("kdialog")
        if kdialog is not None:
            return _PickerCommand(
                argv=(kdialog, "--getopenfilename", str(Path.home())),
                cancel_codes=frozenset({1}),
            )
    return None


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


async def pick_native_file() -> str | None:
    """Choose an existing local file without opening, uploading or copying it."""
    command = _picker_command()
    if command is None:
        raise NativeFilePickerError("native file picker is unavailable on this host")

    try:
        process = await asyncio.create_subprocess_exec(
            *command.argv,
            env=_picker_environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise NativeFilePickerError("native file picker failed to start") from exc
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
        raise NativeFilePickerError("native file picker timed out") from exc

    error_text = stderr.decode("utf-8", errors="replace").strip()
    normalized_error = error_text.lower()
    if process.returncode != 0:
        if process.returncode in command.cancel_codes and (
            not command.cancel_markers
            or any(marker in normalized_error for marker in command.cancel_markers)
        ):
            return None
        raise NativeFilePickerError("native file picker failed")

    selected = stdout.decode("utf-8", errors="replace").strip()
    if not selected:
        return None
    path = Path(selected).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise NativeFilePickerError("native file picker returned an invalid file")
    return str(path)
