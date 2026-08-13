from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nanobot.webui import native_folder_picker as picker


def _picker_command(tmp_path: Path, body: str) -> picker._PickerCommand:
    script = tmp_path / "picker.py"
    script.write_text(f"{body}\n", encoding="utf-8")
    return picker._PickerCommand((sys.executable, str(script)), frozenset({1}))


@pytest.mark.asyncio
async def test_pick_native_folder_returns_selected_directory(tmp_path, monkeypatch) -> None:
    selected = tmp_path / "project"
    selected.mkdir()
    command = _picker_command(tmp_path, f"print({str(selected)!r}, end='')")
    monkeypatch.setattr(
        picker,
        "_picker_command",
        lambda: command,
    )

    assert await picker.pick_native_folder() == str(selected)


@pytest.mark.asyncio
async def test_pick_native_folder_uses_secret_free_environment(tmp_path, monkeypatch) -> None:
    selected = tmp_path / "project"
    selected.mkdir()
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

    assert await picker.pick_native_folder() == str(selected)
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
async def test_pick_native_folder_maps_dialog_cancel_to_none(tmp_path, monkeypatch) -> None:
    command = _picker_command(tmp_path, "raise SystemExit(1)")
    monkeypatch.setattr(
        picker,
        "_picker_command",
        lambda: command,
    )

    assert await picker.pick_native_folder() is None


@pytest.mark.asyncio
async def test_pick_native_folder_rejects_non_directory_result(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing"
    command = _picker_command(tmp_path, f"print({str(missing)!r}, end='')")
    monkeypatch.setattr(
        picker,
        "_picker_command",
        lambda: command,
    )

    with pytest.raises(picker.NativeFolderPickerError, match="invalid directory"):
        await picker.pick_native_folder()


@pytest.mark.asyncio
async def test_pick_native_folder_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(picker, "_picker_command", lambda: None)

    assert picker.native_folder_picker_available() is False
    with pytest.raises(picker.NativeFolderPickerError, match="unavailable"):
        await picker.pick_native_folder()


@pytest.mark.asyncio
async def test_pick_native_folder_wraps_process_start_failure(tmp_path, monkeypatch) -> None:
    command = _picker_command(tmp_path, "raise AssertionError('not started')")
    monkeypatch.setattr(picker, "_picker_command", lambda: command)

    async def fail_spawn(*args, **kwargs):
        raise OSError("executable disappeared")

    monkeypatch.setattr(picker.asyncio, "create_subprocess_exec", fail_spawn)

    with pytest.raises(picker.NativeFolderPickerError, match="failed to start"):
        await picker.pick_native_folder()
