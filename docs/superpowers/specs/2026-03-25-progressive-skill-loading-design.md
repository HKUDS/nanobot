# Progressive Skill Loading — Design Spec

**Date:** 2026-03-25
**Topic:** Stop injecting full SKILL.md content for trigger-matched skills; use summary-only with on-demand loading via read_file
**Status:** Draft

---

## Problem Statement

When a user message triggers skill matching, all matched skills (up to 4) get their
**full SKILL.md content** injected into the system prompt. For example, "Summarize notes
from project DS10540 in Obsidian" matches 4 skills totaling 1300+ lines of reference
documentation. This content floods the system prompt, dilutes the LLM's attention, and
causes the agent to ignore skill instructions in favor of simpler tools like `list_dir`.

The `skills_header.md` template already tells the agent to "use read_file to load full
instructions," but this only applies to the **available skills** summary section. Trigger-
matched skills bypass this and get full injection.

### Evidence

In testing, the agent was given `exec` access and the obsidian-cli skill (440 lines of
CLI reference) was injected into the system prompt. The agent ignored the CLI instructions
and used `list_dir` to browse the filesystem instead. Only after exhausting `list_dir`
did it fall back to `exec` with the obsidian CLI — the skill instructions were drowned
in 1300+ lines of context from 4 simultaneously-injected skills.

### How Claude Code handles this

Claude Code uses two-stage loading:
1. **System prompt**: short name + one-line description of each capability
2. **On invocation**: full content loaded into conversation when actually needed

The agent decides what to use based on the short description, then gets full instructions
only for what it chose.

---

## Design: Summary-only for trigger matches, full injection only for always-on

### Principle

**Skill content is loaded on demand, not preloaded.** Trigger-matched skills appear in
the summary section with a highlighted marker and their file path. The agent uses
`read_file` to load full instructions for the skill it decides to use. Only skills
explicitly marked `always: true` get full injection.

### Before

```
System prompt:
  # Active Skills
  ### Skill: obsidian-cli
  [440 lines of CLI reference]
  ### Skill: obsidian-bases
  [497 lines]
  ### Skill: obsidian-markdown
  [196 lines]
  ### Skill: project-plan
  [~100 lines]

  # Skills
  - checkmark github: Interact with GitHub...
  - checkmark weather: Check weather...
```

### After

```
System prompt:
  # Active Skills                    (only always=true skills, if any)
  ### Skill: memory
  [15 lines — memory system instructions]

  # Skills
  Skills marked with a star matched this message — use read_file on their
  path to load full instructions before using them.

  **Matched for this message:**
  - star obsidian-cli: Skill for the official Obsidian CLI (v1.12+)
    Path: ~/.nanobot/workspace/skills/obsidian-skills/skills/obsidian-cli/SKILL.md
  - star obsidian-bases: Work with Obsidian Bases databases
    Path: ~/.nanobot/workspace/skills/obsidian-skills/skills/obsidian-bases/SKILL.md
  - star obsidian-markdown: Obsidian-flavored Markdown reference
    Path: ~/.nanobot/workspace/skills/obsidian-skills/skills/obsidian-markdown/SKILL.md
  - star project-plan: Project planning templates
    Path: nanobot/skills/project-plan/SKILL.md

  **Other available skills:**
  - checkmark github: Interact with GitHub using the gh CLI
  - checkmark weather: Check weather conditions
```

---

## Section 1: Changes to `nanobot/context/context.py`

### `build_system_prompt()` (lines 151-164)

**Current code:**

```python
# 1. Active skills: always-loaded + requested/matched for this turn
always_skills = self.skills.get_always_skills()
requested_skills = skill_names or []
active_skills = list(dict.fromkeys([*always_skills, *requested_skills]))
if active_skills:
    active_content = self.skills.load_skills_for_context(active_skills)
    if active_content:
        parts.append(f"# Active Skills\n\n{active_content}")

# 2. Available skills: only show summary (agent uses read_file to load)
skills_summary = self.skills.build_skills_summary()
if skills_summary:
    parts.append(prompts.render("skills_header", skills_summary=skills_summary))
```

**New code:**

```python
# 1. Always-on skills only: full content injection
always_skills = self.skills.get_always_skills()
if always_skills:
    active_content = self.skills.load_skills_for_context(always_skills)
    if active_content:
        parts.append(f"# Active Skills\n\n{active_content}")

# 2. Unified skill summary — matched skills highlighted, all others listed
matched_skills = skill_names or []
skills_summary = self.skills.build_skills_summary(matched=matched_skills)
if skills_summary:
    parts.append(prompts.render("skills_header", skills_summary=skills_summary))
```

The key change: `skill_names` (trigger-matched) no longer join `active_skills` for
full injection. They go to the summary section via the `matched` parameter.

---

## Section 2: Changes to `nanobot/context/skills.py`

### `build_skills_summary()` (lines 143-160)

Add a `matched` parameter. Matched skills appear first with a star marker and their
SKILL.md file path (so the agent can `read_file` them). Always-on skills are excluded
from the summary since they're already fully injected.

**Current signature:**

```python
def build_skills_summary(self) -> str:
```

**New signature:**

```python
def build_skills_summary(self, matched: list[str] | None = None) -> str:
```

**Logic:**

```python
def build_skills_summary(self, matched: list[str] | None = None) -> str:
    all_skills = self.list_skills(filter_unavailable=False)
    if not all_skills:
        return ""

    matched_set = set(matched or [])
    always_set = set(self.get_always_skills())

    matched_lines: list[str] = []
    other_lines: list[str] = []

    for skill in all_skills:
        name = skill["name"]
        if name in always_set:
            continue  # already fully injected
        desc = self._get_skill_description(name)
        skill_meta = self._get_skill_meta(name)
        available = self._check_requirements(skill_meta)
        status = "checkmark" if available else "x"

        if name in matched_set:
            # skill["path"] is already the full SKILL.md file path
            skill_path = skill.get("path", "")
            matched_lines.append(
                f"- star **{name}**: {desc}\n  Path: {skill_path}"
            )
        else:
            other_lines.append(f"- {status} **{name}**: {desc}")

    parts: list[str] = []
    if matched_lines:
        parts.append("**Matched for this message:**\n" + "\n".join(matched_lines))
    if other_lines:
        parts.append("**Other available skills:**\n" + "\n".join(other_lines))

    return "\n\n".join(parts)
```

Note: The actual emoji characters (star, checkmark, x) should be used in the real
implementation — they are written as words here for spec readability.

### Skill path in `list_skills()` return value

`list_skills()` returns `path` as the full SKILL.md file path (e.g.,
`~/.nanobot/workspace/skills/obsidian-skills/skills/obsidian-cli/SKILL.md`).
Use `skill["path"]` directly — no path manipulation needed.

---

## Section 3: Changes to `nanobot/templates/prompts/skills_header.md`

**Current content:**

```markdown
# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md
file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try
installing them with apt/brew.

{skills_summary}
```

**New content:**

```markdown
# Skills

Skills extend your capabilities. Skills marked with star matched this message —
use read_file on their path to load full instructions before using them.
Other skills are available on request.

{skills_summary}
```

The key change: explicit instruction to `read_file` the matched skill's path before
attempting to use it. This is the behavioral nudge that was missing — the agent now
has a clear instruction to load skill content rather than guessing from the description.

---

## Section 4: Testing

### Test 1: Trigger-matched skills go to summary, not full injection

```python
def test_matched_skills_not_fully_injected(tmp_path):
    """Trigger-matched skills appear in summary, not as full content."""
    loader = SkillsLoader(workspace=tmp_path)
    # Create a test skill with substantial content
    skill_dir = tmp_path / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test\ntriggers:\n  - test\n---\n"
        "# Full content\n" + "x" * 500
    )
    # Detect skills (should match)
    matched = loader.detect_relevant_skills("test something")
    assert "test-skill" in matched

    # Build system prompt — full content should NOT be present
    # Summary should contain the skill name with star marker
    summary = loader.build_skills_summary(matched=matched)
    assert "test-skill" in summary
    assert "x" * 500 not in summary  # full content not in summary
```

### Test 2: Always-on skills still get full injection

```python
def test_always_skills_still_fully_injected(tmp_path):
    """Skills with always=true get full content injection."""
    loader = SkillsLoader(workspace=tmp_path)
    skill_dir = tmp_path / "skills" / "always-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: always-skill\ndescription: Always\nalways: true\n---\n"
        "# Always loaded content"
    )
    always = loader.get_always_skills()
    assert "always-skill" in always

    content = loader.load_skills_for_context(always)
    assert "Always loaded content" in content
```

### Test 3: Matched skills include file path

```python
def test_matched_skills_include_path(tmp_path):
    """Matched skills in summary include SKILL.md path for read_file."""
    loader = SkillsLoader(workspace=tmp_path)
    skill_dir = tmp_path / "skills" / "path-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: path-skill\ndescription: Has path\ntriggers:\n  - pathtest\n---\n"
        "# Content"
    )
    matched = loader.detect_relevant_skills("pathtest something")
    summary = loader.build_skills_summary(matched=matched)
    assert "SKILL.md" in summary  # path is included
```

### Test 4: Always-on skills excluded from summary

```python
def test_always_skills_excluded_from_summary(tmp_path):
    """Always-on skills don't appear in summary (already fully injected)."""
    loader = SkillsLoader(workspace=tmp_path)
    skill_dir = tmp_path / "skills" / "always-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: always-skill\ndescription: Always\nalways: true\n---\n# Content"
    )
    summary = loader.build_skills_summary(matched=[])
    assert "always-skill" not in summary
```

---

## Section 5: Existing tests that need updating

The summary format change breaks existing assertions:

- **`tests/integration/test_context_skills.py`** (lines ~81, 90, 100): Assert
  `"Available Skills" in summary`. Update to match new section headers
  (`"Matched for this message"` and/or `"Other available skills"`).

- **`tests/test_token_reduction.py`** (lines ~154-177): `test_skills_summary_is_compact`
  asserts one-line-per-skill format. Update to account for the two-section layout
  (matched vs other). When `matched=None`, output should still be compact single-section.

---

## Section 6: Files changed

| File | Change |
|------|--------|
| `nanobot/context/context.py:151-164` | Only `always_skills` get full injection; trigger-matched skills go to summary via `matched` parameter |
| `nanobot/context/skills.py:143-160` | `build_skills_summary()` gains `matched` parameter; matched skills shown first with star + file path; add `# size-exception: progressive loading refactor` comment |
| `nanobot/templates/prompts/skills_header.md` | Updated instructions: read_file matched skills before using them |
| `tests/test_context_skills.py` | 4 new tests for progressive loading behavior |
| `tests/integration/test_context_skills.py` | Update summary format assertions |
| `tests/test_token_reduction.py` | Update compact summary assertions |

---

## Section 7: What doesn't change

- **`detect_relevant_skills()`** — trigger matching and scoring logic unchanged
- **`load_skills_for_context()`** — still used for `always: true` skills
- **`load_skill()`** — still available for internal use
- **Skill discovery, metadata parsing, custom tool registration** — unchanged
- **`max_skills=4`** default limit on trigger detection — unchanged
- **Custom tool loading (`discover_tools`)** — skill tools are registered regardless of
  whether the skill content is fully injected or summarized

---

## Section 8: Migration and backward compatibility

No breaking changes. The behavioral difference:

- **Before**: Agent sees full skill content in system prompt, may ignore it
- **After**: Agent sees short description + path, must `read_file` to get instructions

Skills with `always: true` are unaffected. The `read_file` tool is always available.

The agent will make one extra tool call per skill use (to load the SKILL.md). This is
a small cost relative to the token savings in the system prompt (~1000+ tokens saved
per matched skill that isn't loaded).

---

## Out of scope

- Skill token budget / truncation — the summary approach eliminates the need
- Skill priority / ranking within the summary — all matched skills get equal treatment
- Caching loaded skill content across turns — the LLM context handles this naturally

### `skills.py` size (521 LOC)

The file is already over the 500 LOC hard limit (pre-existing). This change replaces
~15 lines of `build_skills_summary()` with ~25 lines — net growth of ~10 lines. Adding
a `# size-exception: skill discovery + matching + summary are tightly coupled` comment
is appropriate because the methods in this file share internal state (cache, metadata
parsing, trigger extraction) that would create artificial indirection if split. A full
extraction should happen when the file approaches 600 LOC, not as part of this change.
