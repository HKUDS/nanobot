from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from nanobot.agent.tools.apply_patch import ApplyPatchTool
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.utils.file_edit_events import (
    FileDiff,
    FileEditResult,
    build_file_edit_end_event,
    build_file_edit_start_event,
    build_unified_diff_payload,
    line_diff_stats,
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


@pytest.mark.parametrize("position", [0, 3000, 6000])
@pytest.mark.parametrize(
    ("before_text", "after_text", "expected"),
    [("old\n", "new\n", (1, 1)), ("", "new\n", (1, 0)), ("old\n", "", (0, 1))],
)
def test_line_diff_stats_small_edit_in_repeated_lines(
    position: int, before_text: str, after_text: str, expected: tuple[int, int],
) -> None:
    prefix = "same\n" * position
    suffix = "same\n" * (6000 - position)
    assert line_diff_stats(prefix + before_text + suffix, prefix + after_text + suffix) == expected


def test_sparse_edits_in_repeated_lines_have_compact_diff() -> None:
    middle = "same,0\n" * 6000
    before = "obsolete,1\n" + middle + "obsolete,2\n"
    after = "current,1\n" + middle + "current,2\n"
    assert line_diff_stats(before, after) == (2, 2)
    payload = build_unified_diff_payload(before, after)
    assert payload is not None and not payload["truncated"]
    body = payload["text"].splitlines()[2:]
    assert sum(line.startswith("@@") for line in body) == 2
    assert sum(line.startswith("+") for line in body) == 2
    assert sum(line.startswith("-") for line in body) == 2
    assert body.count(" same,0") == 6


@pytest.mark.parametrize(("before", "after", "expected"), [
    ("", "new\n", "@@ -0,0 +1 @@\n+new"),
    ("old\n", "", "@@ -1 +0,0 @@\n-old"),
    ("keep\n", "keep\nnew\n", "@@ -1,0 +2 @@\n+new"),
    ("keep\nold\n", "keep\n", "@@ -2 +1,0 @@\n-old"),
])
def test_unified_diff_empty_ranges(before: str, after: str, expected: str) -> None:
    payload = build_unified_diff_payload(before, after, context_lines=0)
    assert payload is not None
    assert payload["text"] == "--- before\n+++ after\n" + expected


@pytest.mark.parametrize("gap", [0, 5, 6, 7])
def test_unified_diff_groups_changes_by_context(gap: int) -> None:
    middle = "".join(f"keep {i}\n" for i in range(gap))
    payload = build_unified_diff_payload("old\n" + middle + "old\n", "new\n" + middle + "new\n")
    assert payload is not None
    assert payload["text"].count("@@ -") == (2 if gap > 6 else 1)


def test_file_edit_result_copies_and_serializes_only_observation(tmp_path: Path) -> None:
    result = FileEditResult("Patch applied", {tmp_path: FileDiff.from_text("old", "new")})
    assert type(deepcopy(result)) is str
    assert json.loads(json.dumps({"content": result})) == {"content": "Patch applied"}
    assert result.file_diffs


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_state", ["before", "after"])
async def test_activity_recomputes_diff_when_snapshots_changed(tmp_path: Path, changed_state: str) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    tool = _edit_tool(tmp_path)
    params = {"path": "notes.txt", "old_text": "old", "new_text": "new"}
    [tracker] = prepare_file_edit_trackers(
        call_id="call-edit", tool_name="edit_file", tool=tool, workspace=tmp_path, params=params,
    )
    if changed_state == "before":
        target.write_text("old\nexternal\n", encoding="utf-8")
    result = await tool.execute(**params)
    assert isinstance(result, FileEditResult)
    if changed_state == "after":
        target.write_text("new\nexternal\n", encoding="utf-8")
    event = build_file_edit_end_event(tracker, diff=result.file_diffs[target.resolve()])
    assert (event["added"], event["deleted"]) == (2, 1)
    assert "+external" in event["diff"]["text"]


def test_write_file_start_tracks_snapshot_and_end_emits_exact_diff(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("old\nkeep\n", encoding="utf-8")
    params = {"path": "notes.txt", "content": "new\nkeep\nextra\n"}
    trackers = prepare_file_edit_trackers(
        call_id="call-write",
        tool_name="write_file",
        tool=_write_tool(tmp_path),
        workspace=tmp_path,
        params=params,
    )
    [tracker] = trackers
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
    trackers = prepare_file_edit_trackers(
        call_id="call-bin",
        tool_name="edit_file",
        tool=_edit_tool(tmp_path),
        workspace=tmp_path,
        params={"path": "data.bin", "old_text": "before", "new_text": "after"},
    )
    [tracker] = trackers
    assert not read_file_snapshot(target).countable
    target.write_bytes(b"\x00\x01after")
    event = build_file_edit_end_event(tracker)
    assert event["binary"] is True
    assert (event["added"], event["deleted"]) == (0, 0)
    assert "diff" not in event


def test_binary_before_file_is_reported_but_not_counted(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01before")
    trackers = prepare_file_edit_trackers(
        call_id="call-bin",
        tool_name="write_file",
        tool=_write_tool(tmp_path),
        workspace=tmp_path,
        params={"path": "data.bin", "content": "after\n"},
    )
    [tracker] = trackers
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
    trackers = prepare_file_edit_trackers(
        call_id="call-large",
        tool_name="write_file",
        tool=_write_tool(tmp_path),
        workspace=tmp_path,
        params=params,
    )
    [tracker] = trackers
    target.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    event = build_file_edit_end_event(tracker)
    assert event["binary"] is True
    assert event["added"] == 0
    assert event["deleted"] == 0
    assert "diff" not in event


def test_untracked_tools_do_not_prepare_file_edit_trackers(tmp_path: Path) -> None:
    assert prepare_file_edit_trackers(
        call_id="call-exec",
        tool_name="exec",
        tool=None,
        workspace=tmp_path,
        params={"path": "created-by-shell.txt"},
    ) == []
