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
