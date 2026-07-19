"""Tests for atomic config.json writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_save_config_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    loaded = load_config(path)
    assert loaded.agents.defaults.model


def test_save_config_preserves_existing_file_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    before = path.read_text(encoding="utf-8")

    def boom(self: Path, target: Path) -> Path:  # noqa: ARG001
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        save_config(Config(), path)

    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before)  # still valid JSON
