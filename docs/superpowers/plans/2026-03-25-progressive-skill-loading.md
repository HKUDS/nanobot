# Progressive Skill Loading — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop injecting full SKILL.md content for trigger-matched skills; show summary-only with file paths, agent uses `read_file` on demand.

**Architecture:** Modify `build_skills_summary()` to accept a `matched` parameter that highlights trigger-matched skills with a star marker and their SKILL.md path. Change `build_system_prompt()` to only fully inject `always=true` skills; trigger-matched skills go to the summary section. Update the prompt template to instruct the agent to `read_file` matched skills.

**Tech Stack:** Python 3.10+, pytest, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-03-25-progressive-skill-loading-design.md`

---

### Task 1: Update `build_skills_summary()` to support matched skills

**Files:**
- Modify: `nanobot/context/skills.py:143-160`
- Test: `tests/test_context_skills.py` (new tests), `tests/integration/test_context_skills.py` (update), `tests/test_token_reduction.py` (update)

- [ ] **Step 1: Write failing tests for the new matched parameter**

Create `tests/test_progressive_skills.py`:

```python
"""Tests for progressive skill loading — summary-only for trigger-matched skills."""

from __future__ import annotations

from pathlib import Path

from nanobot.context.skills import SkillsLoader


def _create_skill(
    workspace: Path, name: str, description: str, *, always: bool = False,
    triggers: list[str] | None = None,
) -> Path:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if always:
        frontmatter_lines.append("always: true")
    if triggers:
        frontmatter_lines.append("triggers:")
        for t in triggers:
            frontmatter_lines.append(f"  - {t}")
    frontmatter_lines.append("---")
    content = "\n".join(frontmatter_lines) + "\n\n# Full content\n" + "x" * 200
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


def test_matched_skills_highlighted_in_summary(tmp_path: Path) -> None:
    """Matched skills appear with star marker in summary."""
    _create_skill(tmp_path, "obsidian-cli", "Obsidian CLI tool", triggers=["obsidian"])
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary(matched=["obsidian-cli"])

    assert "★" in summary
    assert "obsidian-cli" in summary
    assert "Matched for this message" in summary


def test_unmatched_skills_in_other_section(tmp_path: Path) -> None:
    """Non-matched skills appear in 'Other available' section."""
    _create_skill(tmp_path, "weather", "Check weather")
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary(matched=[])

    assert "Other available skills" in summary
    assert "weather" in summary
    assert "★" not in summary


def test_matched_skills_include_path(tmp_path: Path) -> None:
    """Matched skills include SKILL.md path for read_file."""
    _create_skill(tmp_path, "my-skill", "A skill", triggers=["mytest"])
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary(matched=["my-skill"])

    assert "SKILL.md" in summary
    assert "Path:" in summary


def test_always_skills_excluded_from_summary(tmp_path: Path) -> None:
    """Always-on skills don't appear in summary (already fully injected)."""
    _create_skill(tmp_path, "always-skill", "Always loaded", always=True)
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary(matched=[])

    assert "always-skill" not in summary


def test_no_matched_no_matched_section(tmp_path: Path) -> None:
    """When matched=[] or None, no 'Matched' section appears."""
    _create_skill(tmp_path, "some-skill", "A skill")
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary(matched=None)

    assert "Matched for this message" not in summary
    assert "some-skill" in summary


def test_backward_compat_no_matched_param(tmp_path: Path) -> None:
    """Calling build_skills_summary() without matched still works."""
    _create_skill(tmp_path, "compat-skill", "Backward compat")
    loader = SkillsLoader(tmp_path)

    summary = loader.build_skills_summary()

    assert "compat-skill" in summary
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/C95071414/Documents/nanobot-progressive-skills
pytest tests/test_progressive_skills.py -v --cache-clear
```

Expected: FAIL — `build_skills_summary()` doesn't accept `matched` parameter, and output format doesn't match new assertions.

- [ ] **Step 3: Implement the new `build_skills_summary()`**

In `nanobot/context/skills.py`, replace the existing `build_skills_summary()` method (lines 143-160) with:

```python
    def build_skills_summary(self, matched: list[str] | None = None) -> str:
        """Build a compact listing of all skills with matched skills highlighted.

        Skills in *matched* are shown first with a ★ marker and their SKILL.md
        file path so the agent can ``read_file`` them.  Always-on skills are
        excluded (they are already fully injected into the system prompt).

        When *matched* is ``None`` or empty, all skills appear in a single
        "Other available skills" section — backward-compatible with the previous
        format.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        matched_set = set(matched or [])
        always_set = set(self.get_always_skills())

        matched_lines: list[str] = []
        other_lines: list[str] = []

        for s in all_skills:
            name = s["name"]
            if name in always_set:
                continue  # already fully injected
            desc = self._get_skill_description(name)
            skill_meta = self._get_skill_meta(name)
            available = self._check_requirements(skill_meta)
            status = "✓" if available else "✗"

            if name in matched_set:
                skill_path = s.get("path", "")
                matched_lines.append(f"- ★ **{name}**: {desc}\n  Path: {skill_path}")
            else:
                other_lines.append(f"- {status} **{name}**: {desc}")

        parts: list[str] = []
        if matched_lines:
            parts.append("**Matched for this message:**\n" + "\n".join(matched_lines))
        if other_lines:
            parts.append("**Other available skills:**\n" + "\n".join(other_lines))

        return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_progressive_skills.py -v --cache-clear
```

Expected: all PASS

- [ ] **Step 5: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 6: Commit**

```bash
git add nanobot/context/skills.py tests/test_progressive_skills.py
git commit -m "feat: add matched parameter to build_skills_summary for progressive loading"
```

---

### Task 2: Update existing tests for new summary format

**Files:**
- Modify: `tests/integration/test_context_skills.py:75-102`
- Modify: `tests/test_token_reduction.py:154-177`

- [ ] **Step 1: Update `tests/integration/test_context_skills.py`**

In `TestSkillsSummary.test_summary_includes_workspace_skill` (line 84), change:

```python
        assert "Available Skills" in summary
```

to:

```python
        assert "Other available skills" in summary
```

The other two tests (`test_summary_empty_when_no_workspace_skills_and_no_builtins` and `test_summary_contains_description`) don't assert on the section header, so they should pass without changes.

- [ ] **Step 2: Update `tests/test_token_reduction.py`**

In `test_skills_summary_is_compact` (line 169), the call `loader.build_skills_summary()` uses no `matched` parameter, so all skills go to "Other available" section. The one-line-per-skill assertions (lines 174-177) should still pass because non-matched skills are still one line each.

Run the test to verify:

```bash
pytest tests/test_token_reduction.py::test_skills_summary_is_compact -v --cache-clear
```

If it passes, no change needed. If it fails (e.g., the header line count changed), update the assertion.

- [ ] **Step 3: Run full test suite**

```bash
make test
```

Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_context_skills.py tests/test_token_reduction.py
git commit -m "test: update existing tests for new skills summary format"
```

---

### Task 3: Change `build_system_prompt()` to only inject always-on skills

**Files:**
- Modify: `nanobot/context/context.py:151-164`

- [ ] **Step 1: Modify `build_system_prompt()`**

In `nanobot/context/context.py`, replace lines 151-164:

```python
        # Skills - progressive loading
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

with:

```python
        # Skills - progressive loading
        # 1. Always-on skills only: full content injection
        always_skills = self.skills.get_always_skills()
        if always_skills:
            active_content = self.skills.load_skills_for_context(always_skills)
            if active_content:
                parts.append(f"# Active Skills\n\n{active_content}")

        # 2. Unified summary — matched skills highlighted, all others listed
        matched_skills = skill_names or []
        skills_summary = self.skills.build_skills_summary(matched=matched_skills)
        if skills_summary:
            parts.append(prompts.render("skills_header", skills_summary=skills_summary))
```

- [ ] **Step 2: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 3: Run full test suite**

```bash
make test
```

- [ ] **Step 4: Commit**

```bash
git add nanobot/context/context.py
git commit -m "feat: only inject always-on skills; trigger-matched skills go to summary"
```

---

### Task 4: Update the skills prompt template

**Files:**
- Modify: `nanobot/templates/prompts/skills_header.md`

- [ ] **Step 1: Replace the template content**

Replace the contents of `nanobot/templates/prompts/skills_header.md` with:

```markdown
# Skills

Skills extend your capabilities. Skills marked with ★ matched this message —
use read_file on their path to load full instructions before using them.
Other skills are available on request.

{skills_summary}
```

- [ ] **Step 2: Run prompt manifest check**

```bash
make prompt-check
```

The prompt manifest tracks hashes of template files. After modifying the template, the manifest needs regeneration:

```bash
python scripts/update_prompt_manifest.py
```

Then verify:

```bash
make prompt-check
```

- [ ] **Step 3: Run full validation**

```bash
make check
```

- [ ] **Step 4: Commit**

```bash
git add nanobot/templates/prompts/skills_header.md
git add -A  # include prompt manifest if updated
git commit -m "feat: update skills template to instruct read_file for matched skills"
```

---

### Task 5: Add size-exception comment to skills.py

**Files:**
- Modify: `nanobot/context/skills.py:1-5`

- [ ] **Step 1: Add the size-exception comment**

At the top of `nanobot/context/skills.py`, after the module docstring and `from __future__ import annotations`, add:

```python
# size-exception: skill discovery + matching + summary are tightly coupled;
# extraction deferred until file approaches 600 LOC
```

- [ ] **Step 2: Commit**

```bash
git add nanobot/context/skills.py
git commit -m "chore: add size-exception comment to skills.py (521 LOC, pre-existing)"
```

---

### Task 6: Final validation

- [ ] **Step 1: Run full CI pipeline**

```bash
make check
```

Expected: lint + typecheck + import-check + prompt-check + test all PASS

- [ ] **Step 2: Verify token reduction**

Quick sanity check — build a system prompt with matched skills and verify it's shorter than before:

```bash
python -c "
from pathlib import Path
from nanobot.context.skills import SkillsLoader

loader = SkillsLoader(workspace=Path.home() / '.nanobot' / 'workspace')
matched = loader.detect_relevant_skills('Summarize notes in Obsidian')
print(f'Matched: {matched}')

# Old way: full content
old = loader.load_skills_for_context(matched)
print(f'Old (full injection): {len(old)} chars')

# New way: summary only
new = loader.build_skills_summary(matched=matched)
print(f'New (summary only): {len(new)} chars')
print(f'Reduction: {len(old) - len(new)} chars ({100*(len(old)-len(new))//len(old)}%)')
"
```

Expected: significant reduction (1000+ chars → ~200 chars for the summary)

- [ ] **Step 3: Verify no stale references**

```bash
grep -rn "active_skills.*requested_skills\|load_skills_for_context.*requested" nanobot/ --include="*.py"
```

Expected: no matches (the old pattern of merging requested skills into active is gone)

- [ ] **Step 4: Commit any final fixups**

```bash
git add -A
git commit -m "chore: final validation for progressive skill loading"
```
