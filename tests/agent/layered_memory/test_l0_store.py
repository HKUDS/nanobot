"""Tests for L0 SQLite store (LM2-A)."""

from pathlib import Path

import pytest

from nanobot.agent.layered_memory.l0_store import L0Store
from nanobot.agent.layered_memory.sanitize import L0CaptureRow


@pytest.fixture
def store(tmp_path: Path) -> L0Store:
    return L0Store(tmp_path)


def test_append_creates_sqlite_and_rows(store: L0Store) -> None:
    rows = [
        L0CaptureRow(role="user", content="hello", timestamp_ms=1_000),
        L0CaptureRow(role="assistant", content="hi there", timestamp_ms=1_001),
    ]
    n = store.append_messages("cli:direct", "cli:direct:1", rows)
    assert n == 2
    assert store.db_path.exists()
    assert store.count_messages("cli:direct") == 2


def test_two_turns_increment_count(store: L0Store) -> None:
    store.append_messages(
        "cli:direct",
        "turn-1",
        [L0CaptureRow(role="user", content="first", timestamp_ms=1)],
    )
    store.append_messages(
        "cli:direct",
        "turn-2",
        [L0CaptureRow(role="user", content="second", timestamp_ms=2)],
    )
    assert store.count_messages("cli:direct") == 2
    checkpoint = store.get_checkpoint("cli:direct")
    assert checkpoint is not None
    assert checkpoint.message_count == 2


def test_checkpoint_created_on_first_capture(store: L0Store) -> None:
    store.append_messages(
        "webui:main",
        "t1",
        [L0CaptureRow(role="user", content="q", timestamp_ms=1)],
    )
    cp = store.get_checkpoint("webui:main")
    assert cp is not None
    assert cp.session_key == "webui:main"
    assert cp.enabled_at > 0


def test_prune_older_than_days(store: L0Store) -> None:
    import sqlite3
    import time

    store.append_messages(
        "cli:direct",
        "old",
        [L0CaptureRow(role="user", content="old msg", timestamp_ms=1)],
    )
    conn = store._connect()
    conn.execute(
        "UPDATE l0_messages SET recorded_at = ? WHERE session_key = ?",
        (time.time() - 40 * 86400, "cli:direct"),
    )
    conn.commit()
    store.append_messages(
        "cli:direct",
        "new",
        [L0CaptureRow(role="user", content="new msg", timestamp_ms=2)],
    )
    deleted = store.prune_older_than_days(30)
    assert deleted >= 1
    assert store.count_messages("cli:direct") == 1
