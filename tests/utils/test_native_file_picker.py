from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nanobot.webui import native_file_picker as picker


def _picker_command(tmp_path: Path, body: str) -> picker._PickerCommand:
    script = tmp_path / "picker.py"
    script.write_text(f"{body}\n", encoding="utf-8")
    return picker._PickerCommand((sys.executable, str(script)), frozenset({1}))


@pytest.mark.asyncio
async def test_pick_native_file_uses_secret_free_environment(tmp_path, monkeypatch) -> None:
    selected = tmp_path / "project"
    selected.write_text("ssh-key")
    command = _picker_command(tmp_path, f"print({str(selected)!r}, end='')")
    monkeypatch.setattr(picker, "_picker_command", lambda: command)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-picker")
    original_spawn = picker.asyncio.create_subprocess_exec
    captured_env: dict[str, str] = {}

    async def capture_spawn(*args, **kwargs):
        captured_env.update(kwargs["env"])
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(picker.asyncio, "create_subprocess_exec", capture_spawn)

    assert await picker.pick_native_file() == str(selected)
    assert captured_env["HOME"] == str(tmp_path)
    assert "OPENAI_API_KEY" not in captured_env


def test_picker_environment_preserves_linux_display_context(monkeypatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":42")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/test/bus")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-picker")

    environment = picker._picker_environment()

    assert environment["DISPLAY"] == ":42"
    assert environment["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/test/bus"
    assert "ANTHROPIC_API_KEY" not in environment


@pytest.mark.asyncio
async def test_pick_native_file_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(picker, "_picker_command", lambda: None)

    with pytest.raises(picker.NativeFilePickerError, match="unavailable"):
        await picker.pick_native_file()


@pytest.mark.asyncio
async def test_pick_native_file_wraps_process_start_failure(tmp_path, monkeypatch) -> None:
    command = _picker_command(tmp_path, "raise AssertionError('not started')")
    monkeypatch.setattr(picker, "_picker_command", lambda: command)

    async def fail_spawn(*args, **kwargs):
        raise OSError("executable disappeared")

    monkeypatch.setattr(picker.asyncio, "create_subprocess_exec", fail_spawn)

    with pytest.raises(picker.NativeFilePickerError, match="failed to start"):
        await picker.pick_native_file()


@pytest.mark.parametrize("result", ["file", "directory", "cancel"])
async def test_pick_native_file_returns_only_existing_file_path(tmp_path, monkeypatch, result):
    selected = tmp_path / "ssh-config"
    selected.write_text("must-not-be-read-or-returned")
    output = str(selected if result == "file" else tmp_path)
    command = _picker_command(tmp_path, "raise SystemExit(1)" if result == "cancel" else f"print({output!r})")
    monkeypatch.setattr(picker, "_picker_command", lambda: command)
    if result == "directory":
        with pytest.raises(picker.NativeFilePickerError, match="invalid file"):
            await picker.pick_native_file()
    else:
        assert await picker.pick_native_file() == (str(selected) if result == "file" else None)


@pytest.mark.parametrize("platform,marker", [
    ("darwin", "choose file"), ("win32", "OpenFileDialog"), ("linux", "--file-selection"),
])
def test_file_picker_uses_platform_file_dialog(monkeypatch, platform, marker):
    monkeypatch.setattr(picker.sys, "platform", platform)
    monkeypatch.setattr(picker.shutil, "which", lambda executable: executable)
    monkeypatch.setenv("DISPLAY", ":test")
    command = picker._picker_command()
    assert command is not None
    assert marker in " ".join(command.argv)
    assert "--directory" not in command.argv


def test_file_picker_is_unavailable_on_headless_linux(monkeypatch):
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert picker._picker_command() is None


async def test_file_picker_cancellation_reaps_process(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    process = MagicMock(returncode=None)
    process.communicate = AsyncMock(side_effect=asyncio.CancelledError)
    process.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(picker, "_picker_command", lambda: picker._PickerCommand(("picker",), frozenset()))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await picker.pick_native_file()
    process.terminate.assert_called_once()
