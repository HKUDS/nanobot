"""Tests for enhanced filesystem tools: ReadFileTool, EditFileTool, ListDirTool."""

import pytest

from nanobot.agent.tools.filesystem import (
    CopyFileTool,
    EditFileTool,
    ListDirTool,
    MoveFileTool,
    ReadFileTool,
    WriteFileTool,
)

# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------

class TestReadFileTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.fixture()
    def sample_file(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
        return f

    @pytest.mark.asyncio
    async def test_basic_read_has_line_numbers(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file))
        assert "1| line 1" in result
        assert "20| line 20" in result

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file), offset=5, limit=3)
        assert "5| line 5" in result
        assert "7| line 7" in result
        assert "8| line 8" not in result
        assert "Use offset=8 to continue" in result

    @pytest.mark.asyncio
    async def test_offset_beyond_end(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file), offset=999)
        assert "Error" in result
        assert "beyond end" in result

    @pytest.mark.asyncio
    async def test_end_of_file_marker(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file), offset=1, limit=9999)
        assert "End of file" in result

    @pytest.mark.asyncio
    async def test_empty_file(self, tool, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = await tool.execute(path=str(f))
        assert "Empty file" in result

    @pytest.mark.asyncio
    async def test_image_file_returns_multimodal_blocks(self, tool, tmp_path):
        f = tmp_path / "pixel.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-data")

        result = await tool.execute(path=str(f))

        assert isinstance(result, list)
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert result[0]["_meta"]["path"] == str(f)
        assert result[1] == {"type": "text", "text": f"(Image file: {f})"}

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool, tmp_path):
        result = await tool.execute(path=str(tmp_path / "nope.txt"))
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_workspace_relative_builtin_skill_read_falls_back_to_packaged_skill(self, tool):
        result = await tool.execute(path="skills/cron/SKILL.md", limit=5)

        assert "Error" not in result
        assert "cron" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_path_returns_clear_error(self, tool):
        result = await tool.execute()
        assert result == "Error reading file: Unknown path"

    @pytest.mark.asyncio
    async def test_char_budget_trims(self, tool, tmp_path):
        """When the selected slice exceeds _MAX_CHARS the output is trimmed."""
        f = tmp_path / "big.txt"
        # Each line is ~110 chars, 2000 lines ≈ 220 KB > 128 KB limit
        f.write_text("\n".join("x" * 110 for _ in range(2000)), encoding="utf-8")
        result = await tool.execute(path=str(f))
        assert len(result) <= ReadFileTool._MAX_CHARS + 500  # small margin for footer
        assert "Use offset=" in result

    @pytest.mark.asyncio
    async def test_oversized_file_is_rejected_before_read(self, tool, tmp_path, monkeypatch):
        f = tmp_path / "huge.txt"
        with f.open("wb") as stream:
            stream.truncate(ReadFileTool._MAX_FILE_SIZE_BYTES + 1)

        def fail_read_bytes(self):
            raise AssertionError("oversized file content should not be loaded")

        monkeypatch.setattr(type(f), "read_bytes", fail_read_bytes)

        result = await tool.execute(path=str(f))

        assert "File too large to read" in result
        assert "Maximum is 100 MiB" in result


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------

class TestEditFileTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_exact_match(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="world", new_text="earth")
        assert "Successfully" in result
        assert f.read_text() == "hello earth"

    @pytest.mark.asyncio
    async def test_identical_replacement_returns_clear_error(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")

        result = await tool.execute(path=str(f), old_text="world", new_text="world")

        assert result == "Error: new_text must be different from old_text."
        assert f.read_text(encoding="utf-8") == "hello world"

    @pytest.mark.asyncio
    async def test_crlf_normalisation(self, tool, tmp_path):
        f = tmp_path / "crlf.py"
        f.write_bytes(b"line1\r\nline2\r\nline3")
        result = await tool.execute(
            path=str(f), old_text="line1\nline2", new_text="LINE1\nLINE2",
        )
        assert "Successfully" in result
        raw = f.read_bytes()
        assert b"LINE1" in raw
        # CRLF line endings should be preserved throughout the file
        assert b"\r\n" in raw

    @pytest.mark.asyncio
    async def test_trim_fallback(self, tool, tmp_path):
        f = tmp_path / "indent.py"
        f.write_text("    def foo():\n        pass\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="def foo():\n    pass", new_text="def bar():\n    return 1",
        )
        assert "Successfully" in result
        assert "bar" in f.read_text()

    @pytest.mark.asyncio
    async def test_ambiguous_match(self, tool, tmp_path):
        f = tmp_path / "dup.py"
        f.write_text("aaa\nbbb\naaa\nbbb\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="aaa\nbbb", new_text="xxx")
        assert "appears" in result.lower() or "Warning" in result

    @pytest.mark.asyncio
    async def test_replace_all(self, tool, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text("foo bar foo bar foo", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="foo", new_text="baz", replace_all=True,
        )
        assert "Successfully" in result
        assert f.read_text() == "baz bar baz bar baz"

    @pytest.mark.asyncio
    async def test_not_found(self, tool, tmp_path):
        f = tmp_path / "nf.py"
        f.write_text("hello", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="xyz", new_text="abc")
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_missing_new_text_returns_clear_error(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="hello")
        assert result == "Error editing file: Unknown new_text"


# ---------------------------------------------------------------------------
# ListDirTool
# ---------------------------------------------------------------------------

class TestListDirTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ListDirTool(workspace=tmp_path)

    @pytest.fixture()
    def populated_dir(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("pass")
        (tmp_path / "src" / "utils.py").write_text("pass")
        (tmp_path / "README.md").write_text("hi")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        return tmp_path

    @pytest.mark.asyncio
    async def test_basic_list(self, tool, populated_dir):
        result = await tool.execute(path=str(populated_dir))
        assert "README.md" in result
        assert "src" in result
        # .git and node_modules should be ignored
        assert ".git" not in result
        assert "node_modules" not in result

    @pytest.mark.asyncio
    async def test_recursive(self, tool, populated_dir):
        result = await tool.execute(path=str(populated_dir), recursive=True)
        # Normalize path separators for cross-platform compatibility
        normalized = result.replace("\\", "/")
        assert "src/main.py" in normalized
        assert "src/utils.py" in normalized
        assert "README.md" in result
        # Ignored dirs should not appear
        assert ".git" not in result
        assert "node_modules" not in result

    @pytest.mark.asyncio
    async def test_max_entries_truncation(self, tool, tmp_path):
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text("x")
        result = await tool.execute(path=str(tmp_path), max_entries=3)
        assert "truncated" in result
        assert "3 of 10" in result

    @pytest.mark.asyncio
    async def test_empty_dir(self, tool, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        result = await tool.execute(path=str(d))
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, tool, tmp_path):
        result = await tool.execute(path=str(tmp_path / "nope"))
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_missing_path_returns_clear_error(self, tool):
        result = await tool.execute()
        assert result == "Error listing directory: Unknown path"


# ---------------------------------------------------------------------------
# CopyFileTool
# ---------------------------------------------------------------------------

class TestCopyFileTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return CopyFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_basic_copy(self, tool, tmp_path):
        src = tmp_path / "tmp" / "test.txt"
        src.parent.mkdir()
        src.write_text("hello", encoding="utf-8")

        result = await tool.execute(source=str(src), destination=str(tmp_path / "test2.txt"))

        assert "Successfully copied" in result
        assert (tmp_path / "test2.txt").read_text(encoding="utf-8") == "hello"
        # Source is left in place.
        assert src.read_text(encoding="utf-8") == "hello"

    @pytest.mark.asyncio
    async def test_copy_preserves_binary(self, tool, tmp_path):
        src = tmp_path / "pixel.png"
        blob = b"\x89PNG\r\n\x1a\n\x00\xff\xfe\x01"
        src.write_bytes(blob)

        result = await tool.execute(source=str(src), destination=str(tmp_path / "copy.png"))

        assert "Successfully copied" in result
        assert (tmp_path / "copy.png").read_bytes() == blob

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tool, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("x", encoding="utf-8")

        result = await tool.execute(
            source=str(src), destination=str(tmp_path / "nested" / "deep" / "a.txt")
        )

        assert "Successfully copied" in result
        assert (tmp_path / "nested" / "deep" / "a.txt").read_text(encoding="utf-8") == "x"

    @pytest.mark.asyncio
    async def test_source_not_found(self, tool, tmp_path):
        result = await tool.execute(
            source=str(tmp_path / "nope.txt"), destination=str(tmp_path / "out.txt")
        )
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_source_directory_rejected(self, tool, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        result = await tool.execute(source=str(d), destination=str(tmp_path / "out.txt"))
        assert "Error" in result
        assert "directory" in result.lower()
        assert not (tmp_path / "out.txt").exists()

    @pytest.mark.asyncio
    async def test_existing_destination_needs_overwrite(self, tool, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("new", encoding="utf-8")
        dst = tmp_path / "b.txt"
        dst.write_text("old", encoding="utf-8")

        result = await tool.execute(source=str(src), destination=str(dst))

        assert "Error" in result
        assert "already exists" in result
        assert dst.read_text(encoding="utf-8") == "old"

    @pytest.mark.asyncio
    async def test_overwrite_replaces_destination(self, tool, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("new", encoding="utf-8")
        dst = tmp_path / "b.txt"
        dst.write_text("old", encoding="utf-8")

        result = await tool.execute(source=str(src), destination=str(dst), overwrite=True)

        assert "Successfully copied" in result
        assert dst.read_text(encoding="utf-8") == "new"

    @pytest.mark.asyncio
    async def test_same_source_and_destination_rejected(self, tool, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("x", encoding="utf-8")
        result = await tool.execute(source=str(src), destination=str(src), overwrite=True)
        assert "Error" in result
        assert "same file" in result

    @pytest.mark.asyncio
    async def test_missing_args_return_clear_error(self, tool, tmp_path):
        result = await tool.execute(source=str(tmp_path / "a.txt"))
        assert result == "Error copying file: Unknown destination"

    @pytest.mark.asyncio
    async def test_copy_blocked_outside_workspace(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        src = workspace / "a.txt"
        src.write_text("secret", encoding="utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()

        tool = CopyFileTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(source=str(src), destination=str(outside / "leak.txt"))

        assert "Error" in result
        assert "outside" in result.lower()
        assert not (outside / "leak.txt").exists()


# ---------------------------------------------------------------------------
# MoveFileTool
# ---------------------------------------------------------------------------

class TestMoveFileTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return MoveFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_basic_move(self, tool, tmp_path):
        src = tmp_path / "tmp" / "test.txt"
        src.parent.mkdir()
        src.write_text("hello", encoding="utf-8")
        dst = tmp_path / "test2.txt"

        result = await tool.execute(source=str(src), destination=str(dst))

        assert "Successfully moved" in result
        assert dst.read_text(encoding="utf-8") == "hello"
        # Original is gone.
        assert not src.exists()

    @pytest.mark.asyncio
    async def test_source_not_found(self, tool, tmp_path):
        result = await tool.execute(
            source=str(tmp_path / "nope.txt"), destination=str(tmp_path / "out.txt")
        )
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_existing_destination_needs_overwrite(self, tool, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("new", encoding="utf-8")
        dst = tmp_path / "b.txt"
        dst.write_text("old", encoding="utf-8")

        result = await tool.execute(source=str(src), destination=str(dst))

        assert "Error" in result
        assert "already exists" in result
        assert src.exists()
        assert dst.read_text(encoding="utf-8") == "old"

    @pytest.mark.asyncio
    async def test_overwrite_replaces_destination(self, tool, tmp_path):
        src = tmp_path / "a.txt"
        src.write_text("new", encoding="utf-8")
        dst = tmp_path / "b.txt"
        dst.write_text("old", encoding="utf-8")

        result = await tool.execute(source=str(src), destination=str(dst), overwrite=True)

        assert "Successfully moved" in result
        assert dst.read_text(encoding="utf-8") == "new"
        assert not src.exists()

    @pytest.mark.asyncio
    async def test_missing_args_return_clear_error(self, tool, tmp_path):
        result = await tool.execute(source=str(tmp_path / "a.txt"))
        assert result == "Error moving file: Unknown destination"

    @pytest.mark.asyncio
    async def test_move_blocked_when_source_outside_workspace(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        src = outside / "secret.txt"
        src.write_text("top secret", encoding="utf-8")

        tool = MoveFileTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(source=str(src), destination=str(workspace / "here.txt"))

        assert "Error" in result
        assert "outside" in result.lower()
        # A move must not delete a file it is not allowed to touch.
        assert src.exists()


# ---------------------------------------------------------------------------
# Workspace restriction + extra read/write allowed dirs
# ---------------------------------------------------------------------------

class TestWorkspaceRestriction:

    @pytest.mark.asyncio
    async def test_read_blocked_outside_workspace(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("top secret")

        tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(path=str(secret))
        assert "Error" in result
        assert "outside" in result.lower()

    @pytest.mark.asyncio
    async def test_read_allowed_with_extra_dir(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("# Test Skill\nDo something.")

        tool = ReadFileTool(
            workspace=workspace, allowed_dir=workspace,
            extra_read_allowed_dirs=[skills_dir],
        )
        result = await tool.execute(path=str(skill_file))
        assert "Test Skill" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_read_allowed_in_media_dir(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        media_dir = tmp_path / "media"
        media_dir.mkdir()
        media_file = media_dir / "photo.txt"
        media_file.write_text("shared media", encoding="utf-8")

        monkeypatch.setattr("nanobot.agent.tools.path_utils.get_media_dir", lambda: media_dir)

        tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(path=str(media_file))
        assert "shared media" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_write_blocked_in_media_dir_by_default(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        media_dir = tmp_path / "media"
        media_dir.mkdir()

        monkeypatch.setattr("nanobot.agent.tools.path_utils.get_media_dir", lambda: media_dir)

        tool = WriteFileTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(path=str(media_dir / "hack.txt"), content="pwned")
        assert "Error" in result
        assert "outside" in result.lower()
        assert not (media_dir / "hack.txt").exists()

    @pytest.mark.asyncio
    async def test_legacy_extra_allowed_dirs_does_not_widen_write(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        tool = WriteFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_allowed_dirs=[skills_dir],
        )
        result = await tool.execute(path=str(skills_dir / "hack.txt"), content="pwned")
        assert "Error" in result
        assert "outside" in result.lower()
        assert not (skills_dir / "hack.txt").exists()

    @pytest.mark.asyncio
    async def test_write_allowed_with_extra_write_dir(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        writable = tmp_path / "writable"
        writable.mkdir()

        tool = WriteFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_write_allowed_dirs=[writable],
        )
        result = await tool.execute(path=str(writable / "ok.txt"), content="allowed")
        assert "Successfully wrote" in result
        assert (writable / "ok.txt").read_text(encoding="utf-8") == "allowed"

    @pytest.mark.asyncio
    async def test_extra_write_allowed_files_allow_only_exact_file(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        allowed_file = outside / "allowed.txt"
        child_path = allowed_file / "child.txt"

        tool = WriteFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_write_allowed_files=[allowed_file],
        )

        exact = await tool.execute(path=str(allowed_file), content="allowed")
        child = await tool.execute(path=str(child_path), content="blocked")

        assert "Successfully wrote" in exact
        assert allowed_file.read_text(encoding="utf-8") == "allowed"
        assert "Error" in child
        assert "outside" in child.lower()
        assert not child_path.exists()

    @pytest.mark.asyncio
    async def test_read_still_blocked_for_unrelated_dir(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        unrelated = tmp_path / "other"
        unrelated.mkdir()
        secret = unrelated / "secret.txt"
        secret.write_text("nope")

        tool = ReadFileTool(
            workspace=workspace, allowed_dir=workspace,
            extra_allowed_dirs=[skills_dir],
        )
        result = await tool.execute(path=str(secret))
        assert "Error" in result
        assert "outside" in result.lower()

    @pytest.mark.asyncio
    async def test_workspace_file_still_readable_with_extra_dirs(self, tmp_path):
        """Adding extra_allowed_dirs must not break normal workspace reads."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        ws_file = workspace / "README.md"
        ws_file.write_text("hello from workspace")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        tool = ReadFileTool(
            workspace=workspace, allowed_dir=workspace,
            extra_allowed_dirs=[skills_dir],
        )
        result = await tool.execute(path=str(ws_file))
        assert "hello from workspace" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_edit_blocked_in_extra_dir(self, tmp_path):
        """edit_file must not be able to modify files in extra_allowed_dirs."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "weather" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("# Weather\nOriginal content.")

        tool = EditFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_allowed_dirs=[skills_dir],
        )
        result = await tool.execute(
            path=str(skill_file),
            old_text="Original content.",
            new_text="Hacked content.",
        )
        assert "Error" in result
        assert "outside" in result.lower()
        assert skill_file.read_text() == "# Weather\nOriginal content."

    @pytest.mark.asyncio
    async def test_edit_allowed_with_extra_write_dir(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        writable = tmp_path / "writable"
        writable.mkdir()
        target = writable / "note.txt"
        target.write_text("before\n", encoding="utf-8")

        tool = EditFileTool(
            workspace=workspace,
            allowed_dir=workspace,
            extra_write_allowed_dirs=[writable],
        )
        result = await tool.execute(
            path=str(target),
            old_text="before",
            new_text="after",
        )
        assert "Successfully edited" in result
        assert target.read_text(encoding="utf-8") == "after\n"
