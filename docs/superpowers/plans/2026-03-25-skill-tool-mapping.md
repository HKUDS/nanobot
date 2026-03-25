# Skill Tool Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bridge Claude Code skills to nanobot's tool vocabulary so GPT-4o knows which nanobot tools to use when acting on skill instructions.

**Architecture:** Runtime detection + rewrite + dynamic preamble in `SkillsLoader.transform_for_agent()`. Three private helper functions (`_detect_skill_tools`, `_rewrite_skill_content`, `_build_skill_preamble`) plus one public method, all in `nanobot/context/skills.py`. One-line integration change in `LoadSkillTool.execute()`.

**Tech Stack:** Python 3.10+, regex, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-skill-tool-mapping-design.md`

---

### Task 1: Add CLAUDE_TOOL_MAPPING constant

**Files:**
- Modify: `nanobot/context/skills.py:25-29` (after existing constants)
- Test: `tests/test_skill_tool_mapping.py` (create)

- [ ] **Step 1: Write the test for mapping constant**

```python
"""Tests for skill tool mapping (detection, rewrite, preamble)."""

from __future__ import annotations

from nanobot.context.skills import CLAUDE_TOOL_MAPPING


def test_mapping_has_expected_keys():
    """All Claude Code tool names are present."""
    expected = {
        "Bash", "Read", "Write", "Edit", "Glob", "Grep",
        "WebFetch", "WebSearch", "Agent", "TodoWrite", "TodoRead",
        "ListDir", "AskUserQuestion",
    }
    assert set(CLAUDE_TOOL_MAPPING.keys()) == expected


def test_mapping_values_are_tuples():
    """Each mapping value is a (tool_name, hint) tuple."""
    for key, value in CLAUDE_TOOL_MAPPING.items():
        assert isinstance(value, tuple), f"{key} value is not a tuple"
        assert len(value) == 2, f"{key} tuple length is not 2"
        assert isinstance(value[0], str), f"{key} tool name is not str"
        assert isinstance(value[1], str), f"{key} hint is not str"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_tool_mapping.py -v`
Expected: FAIL with `ImportError` — `CLAUDE_TOOL_MAPPING` does not exist yet.

- [ ] **Step 3: Add the mapping constant to skills.py**

Add after line 29 (after `_which_cache`) in `nanobot/context/skills.py`:

```python
# Claude Code → nanobot tool mapping.
# Keys: Claude Code tool names (case-sensitive, matched with word boundaries).
# Values: (nanobot_tool, usage_hint) — tool name for text rewriting, hint for preamble.
CLAUDE_TOOL_MAPPING: dict[str, tuple[str, str]] = {
    "Bash": ("exec", "use the `exec` tool"),
    "Read": ("read_file", "use the `read_file` tool"),
    "Write": ("write_file", "use the `write_file` tool"),
    "Edit": ("edit_file", "use the `edit_file` tool"),
    "Glob": ("exec", "use the `exec` tool with `find` or `ls`"),
    "Grep": ("exec", "use the `exec` tool with `grep` or `rg`"),
    "WebFetch": ("web_fetch", "use the `web_fetch` tool"),
    "WebSearch": ("web_search", "use the `web_search` tool"),
    "Agent": (
        "delegate",
        "use the `delegate` tool (approximate — nanobot delegation, not autonomous sub-agents)",
    ),
    "TodoWrite": ("write_scratchpad", "use the `write_scratchpad` tool"),
    "TodoRead": ("read_scratchpad", "use the `read_scratchpad` tool"),
    "ListDir": ("list_dir", "use the `list_dir` tool"),
    "AskUserQuestion": ("message", "use the `message` tool to ask the user"),
}
```

Also add `CLAUDE_TOOL_MAPPING` to the module's `__init__.py` exports if `skills.py` has an `__all__`. If not, no action needed — it's imported directly from the module.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_tool_mapping.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/context/skills.py tests/test_skill_tool_mapping.py
git commit -m "feat: add CLAUDE_TOOL_MAPPING constant for skill-tool bridge"
```

---

### Task 2: Implement `_detect_skill_tools()`

**Files:**
- Modify: `nanobot/context/skills.py` (add function after the constants)
- Test: `tests/test_skill_tool_mapping.py` (add detection tests)

- [ ] **Step 1: Write detection tests**

Append to `tests/test_skill_tool_mapping.py`:

```python
from nanobot.context.skills import _detect_skill_tools


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
        # exec is nanobot-native, not a Claude Code tool name
        assert "exec" not in result
        assert "Bash" not in result

    def test_multiple_tools_detected(self):
        content = "Use `Bash` to run commands and `WebFetch` to download."
        result = _detect_skill_tools(content)
        assert "Bash" in result
        assert "WebFetch" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestDetectSkillTools -v`
Expected: FAIL — `_detect_skill_tools` does not exist.

- [ ] **Step 3: Implement `_detect_skill_tools()`**

Add to `nanobot/context/skills.py` after the constants, before `class SkillsLoader`:

```python
def _detect_skill_tools(content: str) -> dict[str, str]:
    """Scan skill content for Claude Code tool references and bash code blocks.

    Returns a dict mapping detected source → preamble hint string.
    The synthetic key ``__bash_blocks__`` indicates bash/shell/sh fenced blocks.
    """
    detected: dict[str, str] = {}

    # 1. Bash code blocks
    if re.search(r"```(?:bash|shell|sh)\b", content):
        detected["__bash_blocks__"] = "use the `exec` tool"

    # 2. Claude Code tool names — detection uses the SAME patterns as rewrite
    # to avoid detecting names we can't reliably rewrite (e.g., bare "Bash" in prose).
    for tool_name, (_nanobot_name, hint) in CLAUDE_TOOL_MAPPING.items():
        # Both safe and ambiguous names use contextual matching:
        # backtick-wrapped, "the X tool", or "X tool".
        pattern = rf"`{tool_name}`|the\s+{tool_name}\s+tool|\b{tool_name}\s+tool\b"
        if re.search(pattern, content):
            detected[tool_name] = hint

    return detected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestDetectSkillTools -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/context/skills.py tests/test_skill_tool_mapping.py
git commit -m "feat: add _detect_skill_tools() for Claude Code tool detection"
```

---

### Task 3: Implement `_rewrite_skill_content()`

**Files:**
- Modify: `nanobot/context/skills.py` (add function after `_detect_skill_tools`)
- Test: `tests/test_skill_tool_mapping.py` (add rewrite tests)

- [ ] **Step 1: Write rewrite tests**

Append to `tests/test_skill_tool_mapping.py`:

```python
from nanobot.context.skills import _rewrite_skill_content


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestRewriteSkillContent -v`
Expected: FAIL — `_rewrite_skill_content` does not exist.

- [ ] **Step 3: Implement `_rewrite_skill_content()`**

Add to `nanobot/context/skills.py` after `_detect_skill_tools`:

```python
def _rewrite_skill_content(content: str, detected: dict[str, str]) -> str:
    """Replace Claude Code tool names with nanobot equivalents in prose sections.

    Fenced code blocks are preserved — only prose outside fences is rewritten.
    The synthetic ``__bash_blocks__`` key is skipped (it drives the preamble, not rewrites).
    """
    # Filter to only Claude Code tool names (skip __bash_blocks__ and other synthetic keys)
    tool_names = [k for k in detected if k in CLAUDE_TOOL_MAPPING]
    if not tool_names:
        return content

    # Split into prose and code-block segments using a state machine.
    segments = _split_fenced_blocks(content)

    # Rewrite only prose segments (odd indices are code blocks after split).
    for i, (is_code, text) in enumerate(segments):
        if is_code:
            continue
        for tool_name in tool_names:
            nanobot_name = CLAUDE_TOOL_MAPPING[tool_name][0]
            # Same contextual patterns for all tool names (safe and ambiguous):
            # backtick-wrapped, "the X tool", or "X tool".
            text = re.sub(rf"`{tool_name}`", f"`{nanobot_name}`", text)
            text = re.sub(
                rf"\bthe\s+{tool_name}\s+tool\b", f"the {nanobot_name} tool", text
            )
            text = re.sub(
                rf"\b{tool_name}\s+tool\b", f"{nanobot_name} tool", text
            )
        segments[i] = (False, text)

    return "".join(text for _, text in segments)


def _split_fenced_blocks(content: str) -> list[tuple[bool, str]]:
    """Split markdown content into (is_code, text) segments.

    Uses a state machine to track fenced code blocks (3+ backticks).
    Handles nested fences by matching fence length on close.
    """
    segments: list[tuple[bool, str]] = []
    fence_pattern = re.compile(r"^(`{3,})\s*(\w*)\s*$", re.MULTILINE)
    pos = 0
    open_fence: str | None = None  # The backtick string that opened the current block

    for match in fence_pattern.finditer(content):
        backticks = match.group(1)
        if open_fence is None:
            # Opening a code block — flush prose before it
            if match.start() > pos:
                segments.append((False, content[pos : match.start()]))
            open_fence = backticks
            pos = match.start()
        elif len(backticks) >= len(open_fence) and not match.group(2):
            # Closing a code block — fence length must match or exceed opener,
            # and closing fence must have no info string.
            segments.append((True, content[pos : match.end()]))
            pos = match.end()
            open_fence = None

    # Remaining content
    if pos < len(content):
        segments.append((open_fence is not None, content[pos:]))

    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestRewriteSkillContent -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/context/skills.py tests/test_skill_tool_mapping.py
git commit -m "feat: add _rewrite_skill_content() with code block preservation"
```

---

### Task 4: Implement `_build_skill_preamble()`

**Files:**
- Modify: `nanobot/context/skills.py` (add function after `_split_fenced_blocks`)
- Test: `tests/test_skill_tool_mapping.py` (add preamble tests)

- [ ] **Step 1: Write preamble tests**

Append to `tests/test_skill_tool_mapping.py`:

```python
from nanobot.context.skills import _build_skill_preamble


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
        lines = [l for l in result.split("\n") if l.startswith("- ")]
        assert len(lines) == 1

    def test_multiple_tools(self):
        detected = {
            "__bash_blocks__": "use the `exec` tool",
            "Grep": "use the `exec` tool with `grep` or `rg`",
            "WebFetch": "use the `web_fetch` tool",
        }
        result = _build_skill_preamble(detected)
        lines = [l for l in result.split("\n") if l.startswith("- ")]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestBuildSkillPreamble -v`
Expected: FAIL — `_build_skill_preamble` does not exist.

- [ ] **Step 3: Implement `_build_skill_preamble()`**

Add to `nanobot/context/skills.py` after `_split_fenced_blocks`:

```python
def _build_skill_preamble(detected: dict[str, str]) -> str:
    """Build a dynamic preamble from detected tool references.

    Returns an empty string if nothing was detected.
    """
    if not detected:
        return ""

    lines: list[str] = []
    has_bash_blocks = "__bash_blocks__" in detected
    has_bash_tool = "Bash" in detected

    # Bash blocks / Bash tool — merge into a single line
    if has_bash_blocks or has_bash_tool:
        lines.append("- To run the bash/CLI commands in these instructions, use the `exec` tool")

    # Other Claude Code tool mappings
    for key, hint in detected.items():
        if key in ("__bash_blocks__", "Bash"):
            continue  # already handled above
        lines.append(f"- `{key}` \u2192 {hint}")

    if not lines:
        return ""

    return "## Tool Instructions\n\n" + "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestBuildSkillPreamble -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/context/skills.py tests/test_skill_tool_mapping.py
git commit -m "feat: add _build_skill_preamble() for dynamic tool instructions"
```

---

### Task 5: Add `transform_for_agent()` method and integrate

**Files:**
- Modify: `nanobot/context/skills.py:127-144` (add method, update `load_skills_for_context`)
- Modify: `nanobot/tools/builtin/skills.py:53` (call `transform_for_agent`)
- Test: `tests/test_skill_tool_mapping.py` (add integration tests)

- [ ] **Step 1: Write integration tests**

Append to `tests/test_skill_tool_mapping.py`:

```python
from pathlib import Path
from unittest.mock import patch

from nanobot.context.skills import SkillsLoader


class TestTransformForAgent:
    """Integration tests for SkillsLoader.transform_for_agent()."""

    def setup_method(self):
        self.loader = SkillsLoader(workspace=Path("/tmp/fake"))

    def test_content_with_bash_blocks_gets_preamble(self):
        content = "# Weather\n\n```bash\ncurl wttr.in\n```"
        result = self.loader.transform_for_agent(content)
        assert result.startswith("## Tool Instructions")
        assert "`exec`" in result
        assert "```bash\ncurl wttr.in\n```" in result

    def test_content_with_claude_tool_names_gets_rewritten(self):
        content = "Use `Bash` to run and `WebFetch` to download."
        result = self.loader.transform_for_agent(content)
        assert "`exec`" in result
        assert "`web_fetch`" in result
        assert "`Bash`" not in result.split("---", 1)[-1]  # not in rewritten content

    def test_nanobot_native_content_unchanged(self):
        content = "Use the `exec` tool to run grep.\nUse `edit_file` for changes."
        result = self.loader.transform_for_agent(content)
        assert result == content  # no preamble, no rewriting

    def test_empty_content_unchanged(self):
        result = self.loader.transform_for_agent("")
        assert result == ""

    def test_mixed_bash_blocks_and_tool_names(self):
        content = "Use `Grep`:\n```bash\ngrep -r pattern .\n```"
        result = self.loader.transform_for_agent(content)
        assert "## Tool Instructions" in result
        assert "`exec`" in result
        assert "`Grep`" in result.split("---", 1)[0]  # original name in preamble
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestTransformForAgent -v`
Expected: FAIL — `transform_for_agent` does not exist on `SkillsLoader`.

- [ ] **Step 3: Add `transform_for_agent()` method to `SkillsLoader`**

Add to `nanobot/context/skills.py` in the `SkillsLoader` class, after `load_skills_for_context()` (after line 144):

```python
    def transform_for_agent(self, content: str) -> str:
        """Detect Claude Code tool references and transform for nanobot agent.

        Rewrites Claude Code tool names to nanobot equivalents and prepends
        a dynamic preamble listing the tool instructions.  Returns content
        unchanged if no Claude Code references are detected.
        """
        detected = _detect_skill_tools(content)
        if not detected:
            return content
        rewritten = _rewrite_skill_content(content, detected)
        preamble = _build_skill_preamble(detected)
        if not preamble:
            return rewritten
        return f"{preamble}\n\n---\n\n{rewritten}"
```

- [ ] **Step 4: Update `load_skills_for_context()` to call `transform_for_agent()`**

In `nanobot/context/skills.py`, change `load_skills_for_context()` (line 141):

Before:
```python
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
```

After:
```python
                content = self._strip_frontmatter(content)
                content = self.transform_for_agent(content)
                parts.append(f"### Skill: {name}\n\n{content}")
```

- [ ] **Step 5: Update `LoadSkillTool.execute()` to call `transform_for_agent()`**

In `nanobot/tools/builtin/skills.py`, change line 53:

Before:
```python
        stripped = self._loader._strip_frontmatter(content)
        return ToolResult.ok(stripped)
```

After:
```python
        stripped = self._loader._strip_frontmatter(content)
        transformed = self._loader.transform_for_agent(stripped)
        return ToolResult.ok(transformed)
```

- [ ] **Step 6: Run integration tests**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestTransformForAgent -v`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `make lint && make typecheck && make test`
Expected: PASS — no regressions.

- [ ] **Step 8: Commit**

```bash
git add nanobot/context/skills.py nanobot/tools/builtin/skills.py tests/test_skill_tool_mapping.py
git commit -m "feat: integrate skill-tool mapping into load_skill and always-on paths"
```

---

### Task 6: Verify with real skill content

**Files:**
- Test: `tests/test_skill_tool_mapping.py` (add real-content tests)

- [ ] **Step 1: Write tests using real skill content patterns**

Append to `tests/test_skill_tool_mapping.py`:

```python
class TestRealSkillContent:
    """Tests against realistic skill content patterns."""

    def setup_method(self):
        self.loader = SkillsLoader(workspace=Path("/tmp/fake"))

    def test_obsidian_cli_pattern(self):
        """Obsidian-cli style: bash blocks, no Claude Code tool names."""
        content = (
            "# Obsidian CLI\n\n"
            "## Daily Notes\n\n"
            "```bash\n"
            "obsidian daily:read\n"
            "obsidian search query=\"keyword\"\n"
            "```\n\n"
            "## File Operations\n\n"
            "```bash\n"
            "obsidian read path=\"notes/todo.md\"\n"
            "```"
        )
        result = self.loader.transform_for_agent(content)
        assert "## Tool Instructions" in result
        assert "`exec`" in result
        # "read" in the bash block should NOT be detected as Claude's Read tool
        assert "read_file" not in result

    def test_memory_skill_pattern(self):
        """Memory skill style: already uses nanobot tool names."""
        content = (
            "# Memory\n\n"
            "Use the `exec` tool to run grep.\n"
            "Write important facts using `edit_file` or `write_file`.\n\n"
            "```bash\n"
            "grep -i \"keyword\" memory/HISTORY.md\n"
            "```"
        )
        result = self.loader.transform_for_agent(content)
        # Should only add bash block preamble, no tool name rewriting
        assert "## Tool Instructions" in result
        assert "To run the bash/CLI" in result
        # Nanobot names should still be present, unchanged
        assert "`exec`" in result
        assert "`edit_file`" in result

    def test_weather_skill_pattern(self):
        """Weather skill style: bash blocks + nanobot-native web_fetch."""
        content = (
            "# Weather\n\n"
            "```bash\n"
            "curl -s \"wttr.in/London?format=3\"\n"
            "```\n\n"
            "When calling `web_fetch`:\n"
            "```json\n"
            "{\"url\": \"https://wttr.in/Montreal?format=3\"}\n"
            "```"
        )
        result = self.loader.transform_for_agent(content)
        assert "## Tool Instructions" in result
        assert "To run the bash/CLI" in result
        assert "`web_fetch`" in result  # preserved, not rewritten

    def test_skill_with_claude_tool_names(self):
        """Hypothetical skill using Claude Code tool names."""
        content = (
            "# Code Review\n\n"
            "Use `Read` to view the source file.\n"
            "Use `Grep` to search for patterns.\n"
            "Then use the Edit tool to make changes.\n"
        )
        result = self.loader.transform_for_agent(content)
        assert "## Tool Instructions" in result
        # Content section should have rewritten names
        content_section = result.split("---", 1)[-1]
        assert "`read_file`" in content_section
        assert "`Grep`" not in content_section or "exec" in content_section
        assert "edit_file tool" in content_section
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_skill_tool_mapping.py::TestRealSkillContent -v`
Expected: PASS

- [ ] **Step 3: Run full validation**

Run: `make check`
Expected: PASS — full validation including lint, typecheck, import-check, tests.

- [ ] **Step 4: Commit**

```bash
git add tests/test_skill_tool_mapping.py
git commit -m "test: add real-content skill-tool mapping tests"
```

---

### Task 7: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md` (remove obsolete `tools:` field documentation)

- [ ] **Step 1: Remove `tools: [tool_name]` from CLAUDE.md skill documentation**

In `CLAUDE.md`, the "Adding a New Skill" section mentions `tools: [tool_name]` as optional frontmatter. This field is not part of the Claude Code spec and is not used by the framework. Remove it.

Before:
```yaml
---
name: your-skill
description: What it does
tools: [tool_name]  # optional custom tools
---
```

After:
```yaml
---
name: your-skill
description: What it does
---
```

- [ ] **Step 2: Add a note about skill-tool mapping**

In the same section, add after point 3 (auto-discovered by SkillsLoader):

```
4. **Tool mapping**: Skills written for Claude Code are automatically transformed
   at load time — Claude Code tool names (Bash, Read, Write, etc.) are rewritten to
   nanobot equivalents and a tool-instruction preamble is prepended. No skill-side
   changes needed. See `docs/superpowers/specs/2026-03-25-skill-tool-mapping-design.md`.
```

- [ ] **Step 3: Run lint**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update skill docs — remove unused tools field, add mapping note"
```
