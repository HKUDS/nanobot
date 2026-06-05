from __future__ import annotations

import asyncio

from blackcat.agent.tools.apply_patch import ApplyPatchTool


def test_apply_patch_edits_replace(tmp_path):
    target = tmp_path / "calc.py"
    target.write_text("def add(a, b):\n    return a + b\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "calc.py",
                    "action": "replace",
                    "old_text": "    return a + b",
                    "new_text": "    return a - b",
                }
            ]
        )
    )

    assert "update calc.py" in result
    assert target.read_text() == "def add(a, b):\n    return a - b\n"


def test_apply_patch_edits_add_new_file(tmp_path):
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "config.py",
                    "action": "add",
                    "new_text": "DEBUG = True",
                }
            ]
        )
    )

    assert "add config.py" in result
    assert (tmp_path / "config.py").read_text() == "DEBUG = True\n"


def test_apply_patch_edits_preserves_new_file_trailing_blank_lines(tmp_path):
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "notes.txt",
                    "action": "add",
                    "new_text": "one\n\n",
                }
            ]
        )
    )

    assert "add notes.txt" in result
    assert (tmp_path / "notes.txt").read_text() == "one\n\n"


def test_apply_patch_edits_add_to_existing_file(tmp_path):
    target = tmp_path / "log.py"
    target.write_text("import logging\n\nlogger = logging.getLogger(__name__)\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "log.py",
                    "action": "add",
                    "new_text": "def debug(msg):\n    logger.debug(msg)",
                }
            ]
        )
    )

    assert "update log.py" in result
    assert (
        target.read_text()
        == "import logging\n\nlogger = logging.getLogger(__name__)\ndef debug(msg):\n    logger.debug(msg)\n"
    )


def test_apply_patch_edits_add_to_existing_file_without_final_newline(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("alpha", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "notes.txt",
                    "action": "add",
                    "new_text": "beta",
                }
            ]
        )
    )

    assert "update notes.txt" in result
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_apply_patch_edits_add_to_existing_crlf_file_without_final_newline(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_bytes(b"alpha\r\nbravo")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "notes.txt",
                    "action": "add",
                    "new_text": "charlie",
                }
            ]
        )
    )

    assert "update notes.txt" in result
    assert target.read_bytes() == b"alpha\r\nbravo\r\ncharlie\r\n"


def test_apply_patch_edits_add_to_existing_file_respects_leading_newline(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("alpha", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "notes.txt",
                    "action": "add",
                    "new_text": "\nbeta",
                }
            ]
        )
    )

    assert "update notes.txt" in result
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_apply_patch_rejects_delete_action(tmp_path):
    target = tmp_path / "utils.py"
    target.write_text("def unused():\n    pass\ndef used():\n    return 1\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "utils.py",
                    "action": "delete",
                    "old_text": "def unused():\n    pass\n",
                }
            ]
        )
    )

    assert "unknown action: delete" in result
    assert target.read_text() == "def unused():\n    pass\ndef used():\n    return 1\n"


def test_apply_patch_edits_batch_multiple_files(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("X = 1\n")
    b = tmp_path / "b.py"
    b.write_text("from a import X\nprint(X)\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "a.py",
                    "action": "replace",
                    "old_text": "X = 1",
                    "new_text": "Y = 1",
                },
                {
                    "path": "b.py",
                    "action": "replace",
                    "old_text": "from a import X",
                    "new_text": "from a import Y",
                },
            ]
        )
    )

    assert "update a.py" in result
    assert "update b.py" in result
    assert a.read_text() == "Y = 1\n"
    assert b.read_text() == "from a import Y\nprint(X)\n"


def test_apply_patch_edits_rejects_ambiguous_old_text(tmp_path):
    target = tmp_path / "repeated.txt"
    target.write_text("target\nmiddle\ntarget\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "repeated.txt",
                    "action": "replace",
                    "old_text": "target",
                    "new_text": "changed",
                }
            ]
        )
    )

    assert "old_text appears multiple times" in result
    assert target.read_text() == "target\nmiddle\ntarget\n"


def test_apply_patch_edits_dry_run_validates_without_writing(tmp_path):
    target = tmp_path / "dry.txt"
    target.write_text("before\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "dry.txt",
                    "action": "replace",
                    "old_text": "before",
                    "new_text": "after",
                },
                {
                    "path": "added.txt",
                    "action": "add",
                    "new_text": "new",
                },
            ],
            dry_run=True,
        )
    )

    assert "Patch dry-run succeeded" in result
    assert target.read_text() == "before\n"
    assert not (tmp_path / "added.txt").exists()


def test_apply_patch_edits_allows_absolute_and_parent_paths_when_unrestricted(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    absolute_target = outside / "absolute.txt"
    parent_target = outside / "parent.txt"
    tool = ApplyPatchTool(workspace=workspace, restrict_to_workspace=False)

    absolute = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": str(absolute_target),
                    "action": "add",
                    "new_text": "absolute",
                }
            ]
        )
    )
    parent = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "../outside/parent.txt",
                    "action": "add",
                    "new_text": "parent",
                }
            ]
        )
    )

    assert "Patch applied" in absolute
    assert "Patch applied" in parent
    assert absolute_target.read_text() == "absolute\n"
    assert parent_target.read_text() == "parent\n"


def test_apply_patch_edits_rejects_outside_paths_when_restricted(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    tool = ApplyPatchTool(workspace=workspace, allowed_dir=workspace)

    absolute = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": str(outside / "absolute.txt"),
                    "action": "add",
                    "new_text": "nope",
                }
            ]
        )
    )
    parent = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "../outside/parent.txt",
                    "action": "add",
                    "new_text": "nope",
                }
            ]
        )
    )

    assert "outside allowed directory" in absolute
    assert "outside allowed directory" in parent
    assert not (outside / "absolute.txt").exists()
    assert not (outside / "parent.txt").exists()


def test_apply_patch_legacy_extra_allowed_dirs_are_read_only(tmp_path):
    workspace = tmp_path / "workspace"
    skills = tmp_path / "skills"
    workspace.mkdir()
    skills.mkdir()
    target = skills / "demo.md"
    target.write_text("before\n", encoding="utf-8")
    tool = ApplyPatchTool(
        workspace=workspace,
        allowed_dir=workspace,
        extra_allowed_dirs=[skills],
    )

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": str(target),
                    "action": "replace",
                    "old_text": "before",
                    "new_text": "after",
                }
            ]
        )
    )

    assert "outside allowed directory" in result
    assert target.read_text(encoding="utf-8") == "before\n"


def test_apply_patch_media_dir_is_read_only_by_default(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    media = tmp_path / "media"
    workspace.mkdir()
    media.mkdir()
    target = media / "demo.md"
    target.write_text("before\n", encoding="utf-8")
    monkeypatch.setattr("nanobot.agent.tools.path_utils.get_media_dir", lambda: media)
    tool = ApplyPatchTool(workspace=workspace, allowed_dir=workspace)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": str(target),
                    "action": "replace",
                    "old_text": "before",
                    "new_text": "after",
                }
            ]
        )
    )

    assert "outside allowed directory" in result
    assert target.read_text(encoding="utf-8") == "before\n"


def test_apply_patch_allows_explicit_extra_write_allowed_dirs_when_restricted(tmp_path):
    workspace = tmp_path / "workspace"
    writable = tmp_path / "writable"
    workspace.mkdir()
    writable.mkdir()
    target = writable / "allowed.txt"
    tool = ApplyPatchTool(
        workspace=workspace,
        allowed_dir=workspace,
        extra_write_allowed_dirs=[writable],
    )

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": str(target),
                    "action": "add",
                    "new_text": "allowed",
                }
            ]
        )
    )

    assert "Patch applied" in result
    assert target.read_text(encoding="utf-8") == "allowed\n"


def test_apply_patch_edits_reports_invalid_edit_shapes(tmp_path):
    tool = ApplyPatchTool(workspace=tmp_path)

    missing_path = asyncio.run(tool.execute(edits=[{"action": "add", "new_text": "x"}]))
    missing_action = asyncio.run(tool.execute(edits=[{"path": "x.txt", "new_text": "x"}]))
    non_object = asyncio.run(tool.execute(edits=["not an object"]))  # type: ignore[list-item]

    assert "path required for edit" in missing_path
    assert "action required for edit: x.txt" in missing_action
    assert "each edit must be an object" in non_object


def test_apply_patch_edits_rolls_back_when_late_operation_fails(tmp_path):
    first = tmp_path / "first.txt"
    first.write_text("before\n")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "first.txt",
                    "action": "replace",
                    "old_text": "before",
                    "new_text": "after",
                },
                {
                    "path": "missing.txt",
                    "action": "replace",
                    "old_text": "remove me",
                    "new_text": "removed",
                },
            ]
        )
    )

    assert "file to update does not exist: missing.txt" in result
    assert first.read_text() == "before\n"
