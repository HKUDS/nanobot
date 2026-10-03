"""Shared isolation for WebSocket tests that persist runtime state."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_websocket_runtime_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep transcripts and other runtime files out of the active user data directory."""
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
