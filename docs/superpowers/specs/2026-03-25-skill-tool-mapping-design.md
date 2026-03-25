# Skill Tool Mapping — Design Spec

**Date:** 2026-03-25
**Status:** Draft
**Problem:** Nanobot loads Claude Code skills (SKILL.md) authored by third parties, but GPT-4o doesn't know which nanobot tools to use to act on the instructions. The agent sees bash commands and CLI references but has no implicit tool binding like Claude Code does.

---

## Context

### The Gap

Claude Code skills assume a runtime where tool binding is automatic. When a skill shows a `bash` code block, Claude inherently knows to use its `Bash` tool. GPT-4o running inside nanobot has an `exec` tool but nothing connects "bash code blocks in skill instructions" to "call `exec`."

Evidence: The obsidian-cli skill (440 lines) was loaded successfully via `load_skill`. GPT-4o read it but called `message` 3x announcing intent instead of calling `exec`. This pattern repeated across multiple session attempts.

### Ecosystem Research

| Project | Strategy |
|---------|----------|
| **GSD** | Build-time rewriting — explicit mapping tables transform skill files at install time |
| **Superpowers** | Prompt-level adaptation — injects mapping instructions at session bootstrap |
| **OpenClaw** | No translation — requires its own tool vocabulary |

Nanobot adopts a hybrid: **runtime rewriting + dynamic preamble** in `LoadSkillTool.execute()`.

### Constraints

- Skills follow standard Claude Code SKILL.md format with YAML frontmatter
- Skills are authored by third parties — they will never include nanobot-specific fields
- The `tools:` frontmatter field is not part of the Claude Code spec and cannot be relied upon
- The agent runs on GPT-4o/GPT-4o-mini, not Claude

---

## Design

### Approach: Runtime Detection + Rewrite + Dynamic Preamble

When `load_skill` returns content, the framework:

1. **Detects** which Claude Code tool names and bash code blocks are present
2. **Rewrites** Claude Code tool names in prose to nanobot equivalents
3. **Builds a dynamic preamble** listing only the relevant tool instructions
4. Returns `preamble + rewritten content`

Skills that already use nanobot-native tool names (e.g., the `memory` skill) pass through unchanged.

### Global Mapping Dict

A module-level constant in `nanobot/context/skills.py`:

```python
CLAUDE_TOOL_MAPPING: dict[str, tuple[str, str]] = {
    "Bash": ("exec", "use the `exec` tool"),
    "Read": ("read_file", "use the `read_file` tool"),
    "Write": ("write_file", "use the `write_file` tool"),
    "Edit": ("edit_file", "use the `edit_file` tool"),
    "Glob": ("exec", "use the `exec` tool with `find` or `ls`"),
    "Grep": ("exec", "use the `exec` tool with `grep` or `rg`"),
    "WebFetch": ("web_fetch", "use the `web_fetch` tool"),
    "WebSearch": ("web_search", "use the `web_search` tool"),
    "Agent": ("delegate", "use the `delegate` tool (approximate — nanobot delegation, not autonomous sub-agents)"),
    "TodoWrite": ("write_scratchpad", "use the `write_scratchpad` tool"),
    "TodoRead": ("read_scratchpad", "use the `read_scratchpad` tool"),
    "ListDir": ("list_dir", "use the `list_dir` tool"),
    "AskUserQuestion": ("message", "use the `message` tool to ask the user"),
}
```

Keys are Claude Code tool names (case-sensitive, matched with word boundaries). Values are `(nanobot_tool_name, usage_hint)` — the tool name is used for text rewriting, the hint for the preamble.

**Note:** `Agent` → `delegate` is an approximate mapping. Claude Code's `Agent` spawns autonomous sub-agents; nanobot's `delegate` is multi-agent routing. Skills expecting full sub-agent autonomy may not behave identically.

### Detection Logic

`_detect_skill_tools(content: str) -> dict[str, str]`

Scans skill content and returns a dict of detected source → preamble hint.

**What it detects:**

1. **Bash code blocks** — regex for ` ```bash `, ` ```shell `, ` ```sh `. If found, adds synthetic `__bash_blocks__` key.

2. **Claude Code tool names** — word-boundary regex against `CLAUDE_TOOL_MAPPING` keys, with safeguards for ambiguous English words:
   - **Safe names** (match on `\b` alone): `Bash`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `Agent`, `TodoWrite`, `AskUserQuestion`
   - **Ambiguous names** (require context): `Read`, `Write`, `Edit` — only match when in backticks (`` `Read` ``), preceded by "the" (`the Read tool`), or followed by "tool" (`Read tool`)

**Design principle:** Under-matching is preferred over false positives. A missed tool reference means the agent doesn't get a mapping hint — it may still figure it out. A false positive rewrites prose incorrectly and confuses the agent. When in doubt, don't match.

3. **Nanobot-native tool names** — if the skill already mentions `exec`, `read_file`, etc., those are noted for the preamble (to confirm availability) but not rewritten.

### Rewrite Logic

`_rewrite_skill_content(content: str, detected: dict[str, str]) -> str`

Replaces Claude Code tool names with nanobot equivalents in prose sections only.

**Rewrite rules:**
- `` `Bash` `` → `` `exec` ``
- `the Bash tool` → `the exec tool`
- Same patterns for all detected Claude Code tool names

**Skips content inside fenced code blocks** to avoid corrupting bash commands or example output. Implementation uses a state-machine approach: track open/close of fenced blocks (3+ backticks, with optional info string), only rewrite prose sections outside fences, reassemble. Indented code blocks (4-space prefix) are not tracked — only fenced blocks. Nested fences (4-backtick outer containing 3-backtick inner) are handled by matching fence length on close.

**Bash code blocks are left as-is** — only the preamble instructs the agent to use `exec` for them.

### Preamble Generation

`_build_skill_preamble(detected: dict[str, str]) -> str`

Builds a concise, dynamic preamble from detection results.

**Output format:**

```markdown
## Tool Instructions

- To run the bash/CLI commands in these instructions, use the `exec` tool
- `Grep` → use the `exec` tool with `grep` or `rg`
- `WebFetch` → use the `web_fetch` tool
```

**Rules:**
- Bash code blocks line comes first (most common, most important)
- Claude Code tool mappings follow, one per line, only for detected tools
- Preamble uses the original Claude Code name as the key (e.g., `` `Grep` → ``), since the content has been rewritten — this helps the agent understand what was mapped
- If bash blocks AND `Bash` tool name are both detected, they merge (no duplication)
- If nothing detected, returns empty string (no preamble)

**Token budget:** 3-6 lines typical, ~50-100 tokens. Worst case ~150 tokens.

### Integration Points

**`LoadSkillTool.execute()`** (`nanobot/tools/builtin/skills.py`):

```python
content = self._loader.load_skill(name)
# ... error handling ...
stripped = self._loader._strip_frontmatter(content)
transformed = self._loader.transform_for_agent(stripped)  # new
return ToolResult.ok(transformed)
```

**`SkillsLoader.load_skills_for_context()`** (`nanobot/context/skills.py`):

```python
content = self._strip_frontmatter(content)
content = self.transform_for_agent(content)  # new
parts.append(f"### Skill: {name}\n\n{content}")
```

**New public method on `SkillsLoader`:**

```python
def transform_for_agent(self, content: str) -> str:
    """Detect Claude Code tool references and transform for nanobot agent."""
    detected = _detect_skill_tools(content)
    if not detected:
        return content
    rewritten = _rewrite_skill_content(content, detected)
    preamble = _build_skill_preamble(detected)
    return f"{preamble}\n\n---\n\n{rewritten}"
```

Both paths (on-demand via `load_skill` tool and always-on via system prompt injection) get the same transformation.

---

## File Impact

**Files modified:**

| File | Change | LOC added |
|------|--------|-----------|
| `nanobot/context/skills.py` | `CLAUDE_TOOL_MAPPING` constant, `_detect_skill_tools()`, `_rewrite_skill_content()`, `_build_skill_preamble()`, `transform_for_agent()` method | ~80-100 |
| `nanobot/tools/builtin/skills.py` | One line: call `transform_for_agent()` | ~1 |

**Files created:**

| File | Purpose | LOC |
|------|---------|-----|
| `tests/test_skill_tool_mapping.py` | Unit tests for detection, rewrite, preamble, integration | ~120-150 |

**Boundary compliance:**
- All new code in `context/` — skill loading is context's bounded context
- `LoadSkillTool` already depends on `SkillsLoader` — no new coupling
- No new cross-package imports
- `skills.py` grows from 381 to ~470 LOC — under 500 limit
- `__init__.py` exports unchanged

---

## Testing Strategy

Unit tests in `tests/test_skill_tool_mapping.py`:

**Detection:**
- Content with ` ```bash ` blocks → detects `__bash_blocks__`
- Content with `` `Bash` `` → detects `Bash`
- Content with plain English "Read the docs" → does NOT detect `Read`
- Content with `` `Read` `` or "the Read tool" → detects `Read`
- Content with no tool references → returns empty dict
- Content with nanobot-native names → not flagged

**Rewrite:**
- `` `Bash` `` in prose → replaced with `` `exec` ``
- `Bash` inside a fenced code block → NOT replaced
- Multiple tool names → all replaced
- No detections → content unchanged

**Preamble:**
- Bash blocks only → single `exec` line
- Bash blocks + `Bash` name → no duplicate
- Multiple tools → one line per tool
- Nothing detected → empty string

**Integration (`transform_for_agent`):**
- Obsidian-cli content → preamble mentions `exec`
- Memory skill content → no preamble (nanobot-native)
- Weather skill content → preamble mentions `exec`, `web_fetch` untouched

No new test dependencies. Pure string-in, string-out functions.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| No `tools:` frontmatter field | Framework-only detection | Skills are third-party, field not in Claude Code spec |
| Runtime rewriting (not install-time) | Drop-in skill support | No install step, upstream updates work automatically |
| Preamble for bash blocks, rewrite for tool names | Balance reliability + readability | Code blocks stay readable, tool names become native |
| Map unmapped tools to closest equivalent | Complete coverage | `Glob` → `exec` with `find`, etc. |
| Dynamic preamble (not static) | Token efficiency | GPT-4o has limited attention, shorter = more reliable |
| Detection in `skills.py`, not a new module | Co-location | One dict, four functions — doesn't warrant a new file |
| Both `load_skill` and `load_skills_for_context` paths | Consistent behavior | Always-on and on-demand skills both get transformed |
