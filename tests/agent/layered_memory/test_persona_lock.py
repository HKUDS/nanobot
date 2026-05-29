"""Tests for persona file lock (LM3-B)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.layered_memory.persona.lock import PersonaLock


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_persona_lock_serializes(workspace: Path) -> None:
    lock = PersonaLock(workspace, timeout_seconds=5.0)
    order: list[str] = []

    with lock.hold():
        order.append("a")
    with lock.hold():
        order.append("b")

    assert order == ["a", "b"]
    assert lock.lock_path.parent.name == ".nanobot"
