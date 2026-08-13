from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.webui import native_folder_picker as picker


def _picker_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "picker.sh"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return script


@pytest.mark.asyncio
async def test_pick_native_folder_returns_selected_directory(tmp_path, monkeypatch) -> None:
    selected = tmp_path / "project"
    selected.mkdir()
    script = _picker_script(tmp_path, f"printf '%s' '{selected}'")
    monkeypatch.setattr(
        picker,
        "_picker_command",
        lambda: picker._PickerCommand((str(script),), frozenset({1})),
    )

    assert await picker.pick_native_folder() == str(selected)


@pytest.mark.asyncio
async def test_pick_native_folder_maps_dialog_cancel_to_none(tmp_path, monkeypatch) -> None:
    script = _picker_script(tmp_path, "exit 1")
    monkeypatch.setattr(
        picker,
        "_picker_command",
        lambda: picker._PickerCommand((str(script),), frozenset({1})),
    )

    assert await picker.pick_native_folder() is None


@pytest.mark.asyncio
async def test_pick_native_folder_rejects_non_directory_result(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing"
    script = _picker_script(tmp_path, f"printf '%s' '{missing}'")
    monkeypatch.setattr(
        picker,
        "_picker_command",
        lambda: picker._PickerCommand((str(script),), frozenset({1})),
    )

    with pytest.raises(picker.NativeFolderPickerError, match="invalid directory"):
        await picker.pick_native_folder()


@pytest.mark.asyncio
async def test_pick_native_folder_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(picker, "_picker_command", lambda: None)

    assert picker.native_folder_picker_available() is False
    with pytest.raises(picker.NativeFolderPickerError, match="unavailable"):
        await picker.pick_native_folder()
