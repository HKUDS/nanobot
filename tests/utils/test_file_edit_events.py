from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from nanobot.utils.file_edit_events import (
    build_file_edit_end_event,
    build_file_edit_start_event,
    line_diff_stats,
    prepare_file_edit_tracker,
    read_file_snapshot,
    StreamingFileEditTracker,
)


def test_line_diff_stats_counts_replacements_insertions_and_deletions() -> None:
    added, deleted = line_diff_stats("a\nb\nc\n", "a\nB\nc\nd\n")
    assert (added, deleted) == (2, 1)


def test_line_diff_stats_normalizes_crlf() -> None:
    assert line_diff_stats("a\r\nb\r\n", "a\nb\nc\n") == (1, 0)


def test_line_diff_stats_counts_new_file_crlf_lines_once() -> None:
    assert line_diff_stats("", "a\r\nb\r\n") == (2, 0)


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
        "absolute_path": (tmp_path / "notes.txt").resolve().as_posix(),
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


def test_oversized_write_file_end_uses_known_content_for_exact_count(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    params = {"path": "large.txt", "content": "x" * (2 * 1024 * 1024 + 1)}
    tracker = prepare_file_edit_tracker(
        call_id="call-large",
        tool_name="write_file",
        tool=None,
        workspace=tmp_path,
        params=params,
    )

    assert tracker is not None
    target.write_text(params["content"], encoding="utf-8")
    event = build_file_edit_end_event(tracker, params)
    assert event.get("binary") is not True
    assert event["added"] == 1
    assert event["deleted"] == 0


def test_streaming_write_file_tracker_emits_live_line_counts(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-live",
            "name": "write_file",
            "arguments_delta": '{"path":"notes.md","content":"',
        })
        await tracker.update({
            "index": 0,
            "arguments_delta": "line\\n" * 24,
        })

    asyncio.run(run())

    assert events[0] == {
        "version": 1,
        "call_id": "call-live",
        "tool": "write_file",
        "path": "notes.md",
        "absolute_path": (tmp_path / "notes.md").resolve().as_posix(),
        "phase": "start",
        "added": 0,
        "deleted": 0,
        "approximate": True,
        "status": "editing",
    }
    assert events[-1]["path"] == "notes.md"
    assert events[-1]["status"] == "editing"
    assert events[-1]["approximate"] is True
    assert events[-1]["added"] == 24
    assert events[-1]["deleted"] == 0


def test_streaming_write_file_tracker_emits_pending_before_path(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-live",
            "name": "write_file",
            "arguments_delta": '{"content":"line\\n',
        })
        await tracker.update({
            "index": 0,
            "arguments_delta": 'more\\n","path":"late.md"',
        })

    asyncio.run(run())

    assert events[0] == {
        "version": 1,
        "call_id": "call-live",
        "tool": "write_file",
        "path": "",
        "phase": "start",
        "added": 1,
        "deleted": 0,
        "approximate": True,
        "status": "editing",
        "pending": True,
    }
    assert events[-1]["path"] == "late.md"
    assert events[-1].get("pending") is not True
    assert events[-1]["added"] == 2


def test_streaming_write_file_tracker_flushes_small_pending_count(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-live",
            "name": "write_file",
            "arguments_delta": '{"path":"small.md","content":"one\\n',
        })
        await tracker.flush()

    asyncio.run(run())
    assert events
    assert events[-1]["path"] == "small.md"
    assert events[-1]["added"] == 1


def test_streaming_write_file_tracker_normalizes_crlf_line_counts(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-live",
            "name": "write_file",
            "arguments_delta": '{"path":"windows.txt","content":"one\\r\\ntwo\\r\\n',
        })
        await tracker.flush()

    asyncio.run(run())
    assert events[-1]["path"] == "windows.txt"
    assert events[-1]["added"] == 2


def test_streaming_write_file_tracker_counts_unicode_escaped_newlines(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-live",
            "name": "write_file",
            "arguments_delta": '{"path":"unicode.txt","content":"one\\u000atwo',
        })
        await tracker.flush()

    asyncio.run(run())
    assert events[-1]["path"] == "unicode.txt"
    assert events[-1]["added"] == 2


def test_streaming_edit_file_tracker_emits_live_line_counts(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("old\nkeep\n", encoding="utf-8")
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-edit",
            "name": "edit_file",
            "arguments_delta": '{"path":"notes.md","old_text":"old\\nkeep","new_text":"',
        })
        await tracker.update({
            "index": 0,
            "arguments_delta": "new\\nkeep\\nextra\\n" * 8,
        })

    asyncio.run(run())

    assert events[0] == {
        "version": 1,
        "call_id": "call-edit",
        "tool": "edit_file",
        "path": "notes.md",
        "absolute_path": (tmp_path / "notes.md").resolve().as_posix(),
        "phase": "start",
        "added": 0,
        "deleted": 2,
        "approximate": True,
        "status": "editing",
    }
    assert events[-1]["path"] == "notes.md"
    assert events[-1]["status"] == "editing"
    assert events[-1]["approximate"] is True
    assert events[-1]["added"] == 24
    assert events[-1]["deleted"] == 2


def test_streaming_tracker_applies_canonical_call_id_to_final_tool(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "name": "write_file",
            "arguments_delta": '{"path":"matched.md","content":"one\\n',
        })
        final = SimpleNamespace(
            id="provider-final-id",
            name="write_file",
            arguments={"path": "matched.md", "content": "one\n"},
        )
        tracker.apply_final_call_ids([final])
        assert final.id == "idx:0"

    asyncio.run(run())


def test_streaming_edit_file_tracker_flushes_small_pending_count(tmp_path: Path) -> None:
    target = tmp_path / "small.py"
    target.write_text("old\n", encoding="utf-8")
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-edit",
            "name": "edit_file",
            "arguments_delta": '{"path":"small.py","old_text":"old\\n","new_text":"new\\nextra',
        })
        await tracker.flush()

    asyncio.run(run())
    assert events
    assert events[-1]["path"] == "small.py"
    assert events[-1]["added"] == 2
    assert events[-1]["deleted"] == 1


def test_streaming_write_file_tracker_errors_unmatched_live_edits(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "call-live",
            "name": "write_file",
            "arguments_delta": '{"path":"aborted.md","content":"one\\n',
        })
        await tracker.error_unmatched([], "Tool call did not complete.")

    asyncio.run(run())
    assert events[-1]["path"] == "aborted.md"
    assert events[-1]["phase"] == "error"
    assert events[-1]["status"] == "error"


def test_streaming_write_file_tracker_keeps_matched_final_tool_call(tmp_path: Path) -> None:
    events: list[dict] = []

    async def emit(batch: list[dict]) -> None:
        events.extend(batch)

    async def run() -> None:
        tracker = StreamingFileEditTracker(workspace=tmp_path, tools={}, emit=emit)
        await tracker.update({
            "index": 0,
            "call_id": "idx-only",
            "name": "write_file",
            "arguments_delta": '{"path":"matched.md","content":"one\\n',
        })
        await tracker.error_unmatched([
            SimpleNamespace(
                id="final-call",
                name="write_file",
                arguments={"path": "matched.md", "content": "one\n"},
            )
        ], "Tool call did not complete.")

    asyncio.run(run())
    assert events
    assert all(event["status"] == "editing" for event in events)


def test_untracked_tools_do_not_prepare_file_edit_tracker(tmp_path: Path) -> None:
    assert prepare_file_edit_tracker(
        call_id="call-exec",
        tool_name="exec",
        tool=None,
        workspace=tmp_path,
        params={"path": "created-by-shell.txt"},
    ) is None
