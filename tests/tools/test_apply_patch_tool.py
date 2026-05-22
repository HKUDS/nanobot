from __future__ import annotations

import asyncio

from nanobot.agent.tools.apply_patch import ApplyPatchTool


def test_apply_patch_adds_file(tmp_path):
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Add File: hello.txt
+Hello
+world
*** End Patch
"""
    ))

    assert "Patch applied" in result
    assert (tmp_path / "hello.txt").read_text() == "Hello\nworld\n"


def test_apply_patch_updates_multiple_hunks(tmp_path):
    target = tmp_path / "multi.txt"
    target.write_text("line1\nline2\nline3\nline4\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: multi.txt
@@
-line2
+changed2
@@
-line4
+changed4
*** End Patch
"""
    ))

    assert "update multi.txt" in result
    assert "(+2/-2)" in result
    assert target.read_text() == "line1\nchanged2\nline3\nchanged4\n"


def test_apply_patch_dry_run_validates_without_writing(tmp_path):
    target = tmp_path / "dry.txt"
    target.write_text("before\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: dry.txt
@@
-before
+after
*** Add File: added.txt
+new
*** End Patch
""",
        dry_run=True,
    ))

    assert "Patch dry-run succeeded" in result
    assert "- update dry.txt (+1/-1)" in result
    assert "- add added.txt (+1/-0)" in result
    assert target.read_text() == "before\n"
    assert not (tmp_path / "added.txt").exists()


def test_apply_patch_applies_repeated_update_sections_sequentially(tmp_path):
    target = tmp_path / "repeat.txt"
    target.write_text("one\ntwo\nthree\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: repeat.txt
@@
-one
+ONE
*** Update File: repeat.txt
@@
-three
+THREE
*** End Patch
"""
    ))

    assert result.count("update repeat.txt") == 2
    assert target.read_text() == "ONE\ntwo\nTHREE\n"


def test_apply_patch_ignores_standard_no_newline_marker(tmp_path):
    target = tmp_path / "plain.txt"
    target.write_text("before")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: plain.txt
@@ -1,1 +1,1 @@
-before
\\ No newline at end of file
+after
\\ No newline at end of file
*** End Patch
"""
    ))

    assert "update plain.txt" in result
    assert target.read_text() == "after\n"


def test_apply_patch_rejects_empty_hunk(tmp_path):
    target = tmp_path / "plain.txt"
    target.write_text("before\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: plain.txt
@@
*** End Patch
"""
    ))

    assert "hunk is empty" in result
    assert target.read_text() == "before\n"


def test_apply_patch_uses_unified_diff_line_hint(tmp_path):
    target = tmp_path / "repeated.txt"
    target.write_text("target\nmiddle\ntarget\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: repeated.txt
@@ -3,1 +3,1 @@
-target
+changed
*** End Patch
"""
    ))

    assert "update repeated.txt" in result
    assert target.read_text() == "target\nmiddle\nchanged\n"


def test_apply_patch_line_hint_does_not_fallback_to_earlier_match(tmp_path):
    target = tmp_path / "repeated.txt"
    target.write_text("target\nmiddle\nother\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: repeated.txt
@@ -3,1 +3,1 @@
-target
+changed
*** End Patch
"""
    ))

    assert "hunk does not match repeated.txt" in result
    assert target.read_text() == "target\nmiddle\nother\n"


def test_apply_patch_mismatch_reports_best_match(tmp_path):
    target = tmp_path / "near.txt"
    target.write_text("alpha\nbeta\ngamma\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: near.txt
@@ -2,1 +2,1 @@
-betx
+delta
*** End Patch
"""
    ))

    assert "hunk does not match near.txt" in result
    assert "Best match" in result
    assert "line 2" in result
    assert target.read_text() == "alpha\nbeta\ngamma\n"


def test_apply_patch_moves_and_updates_file(tmp_path):
    source = tmp_path / "old" / "name.txt"
    source.parent.mkdir()
    source.write_text("old content\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: old/name.txt
*** Move to: renamed/dir/name.txt
@@
-old content
+new content
*** End Patch
"""
    ))

    assert "move old/name.txt -> renamed/dir/name.txt" in result
    assert not source.exists()
    assert (tmp_path / "renamed" / "dir" / "name.txt").read_text() == "new content\n"


def test_apply_patch_deletes_file(tmp_path):
    target = tmp_path / "obsolete.txt"
    target.write_text("remove me\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Delete File: obsolete.txt
*** End Patch
"""
    ))

    assert "delete obsolete.txt" in result
    assert not target.exists()


def test_apply_patch_rejects_absolute_and_parent_paths(tmp_path):
    tool = ApplyPatchTool(workspace=tmp_path)

    absolute = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Add File: /tmp/owned.txt
+nope
*** End Patch
"""
    ))
    parent = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Add File: ../owned.txt
+nope
*** End Patch
"""
    ))

    assert "must be relative" in absolute
    assert "must not contain '..'" in parent
    assert not (tmp_path.parent / "owned.txt").exists()


def test_apply_patch_does_not_overwrite_existing_file_with_add(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("keep me\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Add File: existing.txt
+replace me
*** End Patch
"""
    ))

    assert "file to add already exists" in result
    assert target.read_text() == "keep me\n"


def test_apply_patch_rolls_back_when_late_operation_fails(tmp_path):
    first = tmp_path / "first.txt"
    first.write_text("before\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(
        patch="""*** Begin Patch
*** Update File: first.txt
@@
-before
+after
*** Delete File: missing.txt
*** End Patch
"""
    ))

    assert "file to delete does not exist" in result
    assert first.read_text() == "before\n"
