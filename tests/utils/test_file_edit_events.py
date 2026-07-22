from __future__ import annotations

from pathlib import Path

from nanobot.agent.tools.apply_patch import ApplyPatchTool
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.utils.file_edit_events import (
    build_file_edit_end_event,
    build_file_edit_start_event,
    build_unified_diff_payload,
    line_diff_stats,
    prepare_file_edit_tracker,
    prepare_file_edit_trackers,
    read_file_snapshot,
)


def _write_tool(workspace: Path) -> WriteFileTool:
    return WriteFileTool(workspace=workspace)


def _edit_tool(workspace: Path) -> EditFileTool:
    return EditFileTool(workspace=workspace)


def _patch_tool(workspace: Path) -> ApplyPatchTool:
    return ApplyPatchTool(workspace=workspace)


def test_line_diff_stats_counts_replacements_insertions_and_deletions() -> None:
    added, deleted = line_diff_stats("a\nb\nc\n", "a\nB\nc\nd\n")
    assert (added, deleted) == (2, 1)


def test_line_diff_stats_normalizes_crlf() -> None:
    assert line_diff_stats("a\r\nb\r\n", "a\nb\nc\n") == (1, 0)


def test_line_diff_stats_counts_new_file_crlf_lines_once() -> None:
    assert line_diff_stats("", "a\r\nb\r\n") == (2, 0)


def test_write_file_start_tracks_snapshot_and_end_emits_exact_diff(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("old\nkeep\n", encoding="utf-8")
    params = {"path": "notes.txt", "content": "new\nkeep\nextra\n"}
    tracker = prepare_file_edit_tracker(
        call_id="call-write",
        tool_name="write_file",
        tool=_write_tool(tmp_path),
        workspace=tmp_path,
        params=params,
    )

    assert tracker is not None
    start = build_file_edit_start_event(tracker)
    assert start == {
        "version": 1,
        "call_id": "call-write",
        "tool": "write_file",
        "path": "notes.txt",
        "absolute_path": (tmp_path / "notes.txt").resolve().as_posix(),
        "phase": "start",
        "added": 0,
        "deleted": 0,
        "approximate": True,
        "status": "editing",
    }

    target.write_text("new\nkeep\nextra\n", encoding="utf-8")
    end = build_file_edit_end_event(tracker)
    assert end["phase"] == "end"
    assert end["status"] == "done"
    assert end["approximate"] is False
    assert (end["added"], end["deleted"]) == (2, 1)
    assert end["diff"]["format"] == "unified"
    assert "hunks" not in end["diff"]
    diff_text = end["diff"]["text"]
    assert "--- notes.txt" in diff_text
    assert "+++ notes.txt" in diff_text
    assert "@@ " in diff_text
    assert "-old" in diff_text
    assert "+new" in diff_text
    assert "+extra" in diff_text


def test_unified_diff_payload_truncates_large_diffs() -> None:
    before = "\n".join(f"old {i}" for i in range(12))
    after = "\n".join(f"new {i}" for i in range(12))

    diff = build_unified_diff_payload(before, after, context_lines=0, max_lines=5)

    assert diff is not None
    assert diff["truncated"] is True
    assert "hunks" not in diff
    body_lines = [
        line for line in diff["text"].splitlines()
        if line.startswith((" ", "+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert len(body_lines) == 5


def test_binary_file_is_reported_but_not_counted(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01before")
    tracker = prepare_file_edit_tracker(
        call_id="call-bin",
        tool_name="edit_file",
        tool=_edit_tool(tmp_path),
        workspace=tmp_path,
        params={"path": "data.bin", "old_text": "before", "new_text": "after"},
    )

    assert tracker is not None
    assert not read_file_snapshot(target).countable
    target.write_bytes(b"\x00\x01after")
    event = build_file_edit_end_event(tracker)
    assert event["binary"] is True
    assert (event["added"], event["deleted"]) == (0, 0)
    assert "diff" not in event


def test_binary_before_file_is_reported_but_not_counted(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01before")
    tracker = prepare_file_edit_tracker(
        call_id="call-bin",
        tool_name="write_file",
        tool=_write_tool(tmp_path),
        workspace=tmp_path,
        params={"path": "data.bin", "content": "after\n"},
    )

    assert tracker is not None
    target.write_text("after\n", encoding="utf-8")
    event = build_file_edit_end_event(tracker)
    assert event["binary"] is True
    assert (event["added"], event["deleted"]) == (0, 0)
    assert "diff" not in event


def test_apply_patch_prepares_trackers_for_each_touched_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    existing = tmp_path / "src" / "existing.py"
    existing.write_text("old\nkeep\n", encoding="utf-8")

    edits = [
        {"path": "src/new.py", "action": "add", "new_text": "fresh"},
        {"path": "src/existing.py", "action": "replace", "old_text": "old", "new_text": "new"},
    ]

    trackers = prepare_file_edit_trackers(
        call_id="call-patch",
        tool_name="apply_patch",
        tool=_patch_tool(tmp_path),
        workspace=tmp_path,
        params={"edits": edits},
    )

    assert [tracker.display_path for tracker in trackers] == [
        "src/new.py",
        "src/existing.py",
    ]

    (tmp_path / "src" / "new.py").write_text("fresh\n", encoding="utf-8")
    existing.write_text("new\nkeep\n", encoding="utf-8")

    events = [build_file_edit_end_event(tracker) for tracker in trackers]
    by_path = {event["path"]: event for event in events}
    assert (by_path["src/new.py"]["added"], by_path["src/new.py"]["deleted"]) == (1, 0)
    assert (by_path["src/existing.py"]["added"], by_path["src/existing.py"]["deleted"]) == (1, 1)
    assert by_path["src/new.py"]["diff"]["format"] == "unified"
    assert by_path["src/existing.py"]["diff"]["format"] == "unified"


def test_apply_patch_trackers_use_normalized_patch_paths(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("old\n", encoding="utf-8")

    trackers = prepare_file_edit_trackers(
        call_id="call-patch",
        tool_name="apply_patch",
        tool=_patch_tool(tmp_path),
        workspace=tmp_path,
        params={
            "edits": [
                {"path": " file.txt ", "action": "replace", "old_text": "old", "new_text": "new"},
                {"path": "bad\0.txt", "action": "add", "new_text": "ignored"},
            ],
        },
    )

    assert [tracker.display_path for tracker in trackers] == ["file.txt"]
    assert trackers[0].path == (tmp_path / "file.txt").resolve()


def test_apply_patch_dry_run_does_not_prepare_file_edit_trackers(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("old\n", encoding="utf-8")

    trackers = prepare_file_edit_trackers(
        call_id="call-patch",
        tool_name="apply_patch",
        tool=_patch_tool(tmp_path),
        workspace=tmp_path,
        params={
            "dry_run": True,
            "edits": [
                {"path": "file.txt", "action": "replace", "old_text": "old", "new_text": "new"}
            ],
        },
    )

    assert trackers == []


def test_oversized_file_is_reported_but_not_counted(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    params = {"path": "large.txt", "content": "x"}
    tracker = prepare_file_edit_tracker(
        call_id="call-large",
        tool_name="write_file",
        tool=_write_tool(tmp_path),
        workspace=tmp_path,
        params=params,
    )

    assert tracker is not None
    target.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    event = build_file_edit_end_event(tracker)
    assert event["binary"] is True
    assert event["added"] == 0
    assert event["deleted"] == 0
    assert "diff" not in event


def test_untracked_tools_do_not_prepare_file_edit_tracker(tmp_path: Path) -> None:
    assert prepare_file_edit_tracker(
        call_id="call-exec",
        tool_name="exec",
        tool=None,
        workspace=tmp_path,
        params={"path": "created-by-shell.txt"},
    ) is None
