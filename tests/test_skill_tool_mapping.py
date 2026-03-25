"""Tests for skill tool mapping (detection, rewrite, preamble)."""

from __future__ import annotations

from nanobot.context.skills import (
    CLAUDE_TOOL_MAPPING,
    _build_skill_preamble,
    _detect_skill_tools,
    _rewrite_skill_content,
)


def test_mapping_has_expected_keys():
    """All Claude Code tool names are present."""
    expected = {
        "Bash",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "Agent",
        "TodoWrite",
        "TodoRead",
        "ListDir",
        "AskUserQuestion",
    }
    assert set(CLAUDE_TOOL_MAPPING.keys()) == expected


def test_mapping_values_are_tuples():
    """Each mapping value is a (tool_name, hint) tuple."""
    for key, value in CLAUDE_TOOL_MAPPING.items():
        assert isinstance(value, tuple), f"{key} value is not a tuple"
        assert len(value) == 2, f"{key} tuple length is not 2"
        assert isinstance(value[0], str), f"{key} tool name is not str"
        assert isinstance(value[1], str), f"{key} hint is not str"


class TestDetectSkillTools:
    """Tests for _detect_skill_tools()."""

    def test_detects_bash_code_blocks(self):
        content = "Run this:\n```bash\ncurl http://example.com\n```"
        result = _detect_skill_tools(content)
        assert "__bash_blocks__" in result

    def test_detects_shell_code_blocks(self):
        content = "Run this:\n```shell\necho hello\n```"
        result = _detect_skill_tools(content)
        assert "__bash_blocks__" in result

    def test_detects_sh_code_blocks(self):
        content = "Run this:\n```sh\necho hello\n```"
        result = _detect_skill_tools(content)
        assert "__bash_blocks__" in result

    def test_detects_safe_tool_name_bash(self):
        content = "Use the `Bash` tool to run commands."
        result = _detect_skill_tools(content)
        assert "Bash" in result

    def test_detects_safe_tool_name_grep(self):
        content = "Use `Grep` to search files."
        result = _detect_skill_tools(content)
        assert "Grep" in result

    def test_detects_safe_tool_name_webfetch(self):
        content = "Call the WebFetch tool to download the page."
        result = _detect_skill_tools(content)
        assert "WebFetch" in result

    def test_does_not_detect_bare_bash_in_prose(self):
        """Bare 'Bash' without backticks or 'tool' context is not detected."""
        content = "Bash is great for scripting."
        result = _detect_skill_tools(content)
        assert "Bash" not in result

    def test_does_not_detect_lowercase_tool_names(self):
        """Case-sensitive: lowercase variants are not detected."""
        content = "Use `bash` to run and `read` to view."
        result = _detect_skill_tools(content)
        assert "Bash" not in result
        assert "Read" not in result

    def test_detects_combined_bash_blocks_and_tools(self):
        """Bash blocks plus tool names detected together."""
        content = "Use `Grep`:\n```bash\ngrep -r pattern .\n```"
        result = _detect_skill_tools(content)
        assert "__bash_blocks__" in result
        assert "Grep" in result

    def test_does_not_detect_read_in_plain_english(self):
        content = "Read the documentation carefully before proceeding."
        result = _detect_skill_tools(content)
        assert "Read" not in result

    def test_detects_read_in_backticks(self):
        content = "Use `Read` to view the file."
        result = _detect_skill_tools(content)
        assert "Read" in result

    def test_detects_read_as_tool_reference(self):
        content = "the Read tool can view files."
        result = _detect_skill_tools(content)
        assert "Read" in result

    def test_detects_write_followed_by_tool(self):
        content = "Use the Write tool to create files."
        result = _detect_skill_tools(content)
        assert "Write" in result

    def test_does_not_detect_write_in_plain_english(self):
        content = "Write your notes in the journal."
        result = _detect_skill_tools(content)
        assert "Write" not in result

    def test_does_not_detect_edit_in_plain_english(self):
        content = "Edit the configuration file manually."
        result = _detect_skill_tools(content)
        assert "Edit" not in result

    def test_detects_edit_in_backticks(self):
        content = "Call `Edit` with the file path."
        result = _detect_skill_tools(content)
        assert "Edit" in result

    def test_empty_content_returns_empty(self):
        result = _detect_skill_tools("")
        assert result == {}

    def test_no_tool_references_returns_empty(self):
        content = "This skill helps you manage your calendar."
        result = _detect_skill_tools(content)
        assert result == {}

    def test_nanobot_native_names_not_flagged_as_claude(self):
        content = "Use the `exec` tool to run grep."
        result = _detect_skill_tools(content)
        assert "exec" not in result
        assert "Bash" not in result

    def test_multiple_tools_detected(self):
        content = "Use `Bash` to run commands and `WebFetch` to download."
        result = _detect_skill_tools(content)
        assert "Bash" in result
        assert "WebFetch" in result


class TestRewriteSkillContent:
    """Tests for _rewrite_skill_content()."""

    def test_rewrites_backtick_bash(self):
        content = "Use `Bash` to run commands."
        detected = {"Bash": "use the `exec` tool"}
        result = _rewrite_skill_content(content, detected)
        assert "`exec`" in result
        assert "`Bash`" not in result

    def test_rewrites_the_bash_tool(self):
        content = "the Bash tool runs shell commands."
        detected = {"Bash": "use the `exec` tool"}
        result = _rewrite_skill_content(content, detected)
        assert "the exec tool" in result

    def test_does_not_rewrite_inside_code_blocks(self):
        content = "Use `Bash`:\n```bash\nBash is great\n```\nMore `Bash` usage."
        detected = {"Bash": "use the `exec` tool"}
        result = _rewrite_skill_content(content, detected)
        # Prose sections rewritten
        assert result.startswith("Use `exec`")
        assert result.endswith("More `exec` usage.")
        # Code block preserved
        assert "Bash is great" in result

    def test_rewrites_multiple_tools(self):
        content = "Use `Bash` and `WebFetch` together."
        detected = {
            "Bash": "use the `exec` tool",
            "WebFetch": "use the `web_fetch` tool",
        }
        result = _rewrite_skill_content(content, detected)
        assert "`exec`" in result
        assert "`web_fetch`" in result
        assert "`Bash`" not in result
        assert "`WebFetch`" not in result

    def test_no_detections_returns_unchanged(self):
        content = "This is plain text with no tools."
        result = _rewrite_skill_content(content, {})
        assert result == content

    def test_bash_blocks_key_does_not_rewrite(self):
        content = "Run this:\n```bash\ncurl example.com\n```"
        detected = {"__bash_blocks__": "use the `exec` tool"}
        result = _rewrite_skill_content(content, detected)
        # __bash_blocks__ is synthetic, not a tool name — no rewriting
        assert result == content

    def test_rewrites_read_in_backticks_only(self):
        content = "Read the docs. Use `Read` for files."
        detected = {"Read": "use the `read_file` tool"}
        result = _rewrite_skill_content(content, detected)
        assert "Read the docs" in result  # prose unchanged
        assert "`read_file`" in result  # backtick reference rewritten

    def test_rewrites_the_edit_tool_ambiguous(self):
        content = "the Edit tool can modify files."
        detected = {"Edit": "use the `edit_file` tool"}
        result = _rewrite_skill_content(content, detected)
        assert "the edit_file tool" in result

    def test_preserves_nested_code_blocks(self):
        content = "Text `Bash` here.\n````python\n```bash\ninner\n```\n````\nMore `Bash`."
        detected = {"Bash": "use the `exec` tool"}
        result = _rewrite_skill_content(content, detected)
        assert result.startswith("Text `exec`")
        assert result.endswith("More `exec`.")
        assert "```bash\ninner\n```" in result  # inner block preserved


class TestBuildSkillPreamble:
    """Tests for _build_skill_preamble()."""

    def test_bash_blocks_only(self):
        detected = {"__bash_blocks__": "use the `exec` tool"}
        result = _build_skill_preamble(detected)
        assert "## Tool Instructions" in result
        assert "`exec`" in result
        assert result.count("\n- ") == 1  # single instruction line

    def test_tool_mapping_only(self):
        detected = {"Grep": "use the `exec` tool with `grep` or `rg`"}
        result = _build_skill_preamble(detected)
        assert "## Tool Instructions" in result
        assert "`Grep`" in result
        assert "`exec`" in result

    def test_bash_blocks_and_bash_tool_no_duplicate(self):
        detected = {
            "__bash_blocks__": "use the `exec` tool",
            "Bash": "use the `exec` tool",
        }
        result = _build_skill_preamble(detected)
        # Should not have two separate lines both saying "use exec"
        lines = [ln for ln in result.split("\n") if ln.startswith("- ")]
        assert len(lines) == 1

    def test_multiple_tools(self):
        detected = {
            "__bash_blocks__": "use the `exec` tool",
            "Grep": "use the `exec` tool with `grep` or `rg`",
            "WebFetch": "use the `web_fetch` tool",
        }
        result = _build_skill_preamble(detected)
        lines = [ln for ln in result.split("\n") if ln.startswith("- ")]
        assert len(lines) == 3

    def test_empty_detected_returns_empty(self):
        result = _build_skill_preamble({})
        assert result == ""

    def test_preamble_uses_original_claude_names(self):
        detected = {
            "Grep": "use the `exec` tool with `grep` or `rg`",
            "WebFetch": "use the `web_fetch` tool",
        }
        result = _build_skill_preamble(detected)
        assert "`Grep`" in result
        assert "`WebFetch`" in result
