from __future__ import annotations

import asyncio

from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool


def test_read_file_force_bypasses_dedup(tmp_path):
    target = tmp_path / "data.txt"
    target.write_text("alpha\n")
    tool = ReadFileTool(workspace=tmp_path)

    first = asyncio.run(tool.execute(path=str(target)))
    second = asyncio.run(tool.execute(path=str(target)))
    forced = asyncio.run(tool.execute(path=str(target), force=True))

    assert "alpha" in first
    assert "unchanged" in second.lower()
    assert "alpha" in forced
    assert "unchanged" not in forced.lower()


def test_edit_file_can_select_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("one\nsame\ntwo\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        occurrence=2,
    ))

    assert "Successfully edited" in result
    assert target.read_text() == "one\nsame\ntwo\nchanged\n"


def test_edit_file_expected_replacements_guards_replace_all(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        replace_all=True,
        expected_replacements=1,
    ))

    assert "expected 1 replacements but would make 2" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_expected_replacements_allows_replace_all_when_count_matches(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        replace_all=True,
        expected_replacements=2,
    ))

    assert "Successfully edited" in result
    assert target.read_text() == "changed\nchanged\n"


def test_edit_file_can_select_nearest_line_hint(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("one\nsame\ntwo\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        line_hint=4,
    ))

    assert "Successfully edited" in result
    assert target.read_text() == "one\nsame\ntwo\nchanged\n"


def test_edit_file_rejects_unique_match_far_from_line_hint(tmp_path):
    target = tmp_path / "wrong-line.txt"
    target.write_text("one\nsame\ntwo\nother\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        line_hint=20,
    ))

    assert "line_hint 20 does not match the old_text location" in result
    assert "old_text appears at line 2" in result
    assert target.read_text() == "one\nsame\ntwo\nother\n"


def test_edit_file_target_line_selects_matching_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("one\nsame\ntwo\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        target_line=4,
    ))

    assert "Successfully edited" in result
    assert target.read_text() == "one\nsame\ntwo\nchanged\n"


def test_edit_file_target_line_rejects_unique_match_on_wrong_line(tmp_path):
    target = tmp_path / "wrong-line.txt"
    target.write_text("one\nsame\ntwo\nother\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        target_line=4,
    ))

    assert "target_line 4 does not match the old_text location" in result
    assert "old_text appears at line 2" in result
    assert target.read_text() == "one\nsame\ntwo\nother\n"


def test_edit_file_target_line_can_cover_multiline_match(tmp_path):
    target = tmp_path / "block.txt"
    target.write_text("before\nstart\nmiddle\nend\nafter\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="start\nmiddle\nend",
        new_text="start\nchanged\nend",
        target_line=3,
    ))

    assert "Successfully edited" in result
    assert target.read_text() == "before\nstart\nchanged\nend\nafter\n"


def test_edit_file_target_start_line_rejects_context_that_starts_too_early(tmp_path):
    target = tmp_path / "block.txt"
    target.write_text("before\nstart\nmiddle\nend\nafter\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="before\nstart\nmiddle",
        new_text="before\nchanged\nmiddle",
        target_line=2,
        target_start_line=2,
    ))

    assert "target_start_line 2 does not match the old_text start" in result
    assert target.read_text() == "before\nstart\nmiddle\nend\nafter\n"


def test_edit_file_target_start_line_allows_exact_block_start(tmp_path):
    target = tmp_path / "block.txt"
    target.write_text("before\nstart\nmiddle\nend\nafter\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="start\nmiddle\nend",
        new_text="start\nchanged\nend",
        target_line=3,
        target_start_line=2,
    ))

    assert "Successfully edited" in result
    assert target.read_text() == "before\nstart\nchanged\nend\nafter\n"


def test_edit_file_target_line_error_wins_when_start_line_matches(tmp_path):
    target = tmp_path / "block.txt"
    target.write_text("before\nstart\nmiddle\nend\nafter\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="start\nmiddle",
        new_text="changed\nmiddle",
        target_line=4,
        target_start_line=2,
    ))

    assert "target_line 4 does not match the old_text location" in result
    assert target.read_text() == "before\nstart\nmiddle\nend\nafter\n"


def test_edit_file_can_edit_ipynb_as_json(tmp_path):
    target = tmp_path / "analysis.ipynb"
    target.write_text('{"cells": []}')
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text='"cells": []',
        new_text='"cells": [{"cell_type": "markdown", "source": "hi"}]',
    ))

    assert "Successfully edited" in result
    assert '"source": "hi"' in target.read_text()


def test_edit_file_multiple_match_hint_mentions_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
    ))

    assert "old_text appears 2 times" in result
    assert "occurrence" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_rejects_ambiguous_line_hint(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nmiddle\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        line_hint=2,
    ))

    assert "line_hint 2 is ambiguous" in result
    assert target.read_text() == "same\nmiddle\nsame\n"


def test_edit_file_rejects_occurrence_with_replace_all(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        occurrence=1,
        replace_all=True,
    ))

    assert "occurrence cannot be used with replace_all" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_rejects_line_hint_with_replace_all(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        line_hint=1,
        replace_all=True,
    ))

    assert "line_hint cannot be used with replace_all" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_rejects_line_hint_with_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        occurrence=1,
        line_hint=1,
    ))

    assert "line_hint cannot be used with occurrence" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_rejects_target_line_with_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        occurrence=1,
        target_line=1,
    ))

    assert "target_line cannot be used with occurrence" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_rejects_target_start_line_with_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\nsame\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        occurrence=1,
        target_start_line=1,
    ))

    assert "target_start_line cannot be used with occurrence" in result
    assert target.read_text() == "same\nsame\n"


def test_edit_file_rejects_zero_occurrence(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        occurrence=0,
    ))

    assert "occurrence must be >= 1" in result
    assert target.read_text() == "same\n"


def test_edit_file_rejects_zero_line_hint(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        line_hint=0,
    ))

    assert "line_hint must be >= 1" in result
    assert target.read_text() == "same\n"


def test_edit_file_rejects_zero_target_line(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        target_line=0,
    ))

    assert "target_line must be >= 1" in result
    assert target.read_text() == "same\n"


def test_edit_file_rejects_zero_target_start_line(tmp_path):
    target = tmp_path / "duplicate.txt"
    target.write_text("same\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        path=str(target),
        old_text="same",
        new_text="changed",
        target_start_line=0,
    ))

    assert "target_start_line must be >= 1" in result
    assert target.read_text() == "same\n"
