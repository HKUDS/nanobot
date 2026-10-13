"""Keep Linear installation and permission state out of the user's real profile."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_linear_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.channels.linear.state.get_runtime_subdir", lambda _name: tmp_path / "linear",
    )
