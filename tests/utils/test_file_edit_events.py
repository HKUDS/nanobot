from __future__ import annotations

from pathlib import Path

from nanobot.utils.file_edit_events import (
    build_file_edit_end_event,
    build_file_edit_start_event,
    line_diff_stats,
    prepare_file_edit_tracker,
    read_file_snapshot,
)


def test_line_diff_stats_counts_replacements_insertions_and_deletions() -> None:
    added, deleted = line_diff_stats("a\nb\nc\n", "a\nB\nc\nd\n")
    assert (added, deleted) == (2, 1)


def test_line_diff_stats_normalizes_crlf() -> None:
    assert line_diff_stats("a\r\nb\r\n", "a\nb\nc\n") == (1, 0)


def test_write_file_start_predicts_and_end_calibrates_exact_diff(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("old\nkeep\n", encoding="utf-8")
    params = {"path": "notes.txt", "content": "new\nkeep\nextra\n"}
    tracker = prepare_file_edit_tracker(
        call_id="call-write",
        tool_name="write_file",
        tool=None,
        workspace=tmp_path,
        params=params,
    )

    assert tracker is not None
    start = build_file_edit_start_event(tracker, params)
    assert start == {
        "version": 1,
        "call_id": "call-write",
        "tool": "write_file",
        "path": "notes.txt",
        "phase": "start",
        "added": 2,
        "deleted": 1,
        "approximate": True,
        "status": "editing",
    }

    target.write_text("new\nkeep\nextra\n", encoding="utf-8")
    end = build_file_edit_end_event(tracker)
    assert end["phase"] == "end"
    assert end["status"] == "done"
    assert end["approximate"] is False
    assert (end["added"], end["deleted"]) == (2, 1)


def test_binary_file_is_reported_but_not_counted(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01before")
    tracker = prepare_file_edit_tracker(
        call_id="call-bin",
        tool_name="edit_file",
        tool=None,
        workspace=tmp_path,
        params={"path": "data.bin", "old_text": "before", "new_text": "after"},
    )

    assert tracker is not None
    assert not read_file_snapshot(target).countable
    target.write_bytes(b"\x00\x01after")
    event = build_file_edit_end_event(tracker)
    assert event["binary"] is True
    assert (event["added"], event["deleted"]) == (0, 0)


def test_untracked_tools_do_not_prepare_file_edit_tracker(tmp_path: Path) -> None:
    assert prepare_file_edit_tracker(
        call_id="call-exec",
        tool_name="exec",
        tool=None,
        workspace=tmp_path,
        params={"path": "created-by-shell.txt"},
    ) is None
