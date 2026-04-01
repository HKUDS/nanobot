# Skill Filtering by Sender & Channel — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter which skills appear in the agent's system prompt based on sender_name and channel_name, using include/exclude lists with glob pattern matching.

**Architecture:** Add a `SkillsConfig` to `AgentDefaults` with default + per-sender + per-channel include/exclude rules. `ContextBuilder.build_system_prompt()` receives sender/channel context and applies filtering before building the skills summary XML. `SkillsLoader` stays unchanged — it discovers skills; filtering is a context-layer concern.

**Tech Stack:** Python stdlib `fnmatch` for glob matching. Pydantic for config schema.

**Priority rules:** channel config > sender config > default config. Channel match is "full override" — if a channel config matches, it completely replaces default+sender rules (no merge). Sender config merges with default: sender's exclude extends default exclude; sender's include, if present, replaces default include.

---

## Chunk 1: Core Implementation

### Task 1: Config Schema — `SkillsFilterConfig` and `SkillsConfig`

**Files:**
- Modify: `nanobot/config/schema.py` (add two Pydantic models + wire into `AgentDefaults`)

- [ ] **Step 1: Write the failing test**

Create `tests/agent/test_skill_filtering.py`:

```python
"""Tests for skill filtering by sender/channel."""

import pytest
from nanobot.config.schema import AgentDefaults, SkillsConfig, SkillsFilterConfig


class TestSkillsFilterConfig:
    def test_default_includes_all(self):
        cfg = SkillsFilterConfig()
        assert cfg.include == ["*"]
        assert cfg.exclude == []

    def test_custom_include_exclude(self):
        cfg = SkillsFilterConfig(include=["coding-*"], exclude=["ljg-*"])
        assert cfg.include == ["coding-*"]
        assert cfg.exclude == ["ljg-*"]


class TestSkillsConfig:
    def test_defaults_empty(self):
        cfg = SkillsConfig()
        assert cfg.senders == {}
        assert cfg.channels == {}
        assert cfg.include == ["*"]
        assert cfg.exclude == []

    def test_sender_config(self):
        cfg = SkillsConfig(senders={"petch": SkillsFilterConfig(exclude=["coding-*"])})
        assert "petch" in cfg.senders
        assert cfg.senders["petch"].exclude == ["coding-*"]

    def test_channel_config(self):
        cfg = SkillsConfig(channels={"develop": SkillsFilterConfig(include=["coding-*"])})
        assert cfg.channels["develop"].include == ["coding-*"]


class TestAgentDefaultsSkills:
    def test_has_skills_config(self):
        defaults = AgentDefaults()
        assert isinstance(defaults.skills, SkillsConfig)

    def test_from_dict(self):
        data = {
            "skills": {
                "exclude": ["peppa-*"],
                "senders": {
                    "petch": {"exclude": ["coding-*", "ljg-*"]}
                },
                "channels": {
                    "develop": {"include": ["coding-*"]}
                }
            }
        }
        defaults = AgentDefaults.model_validate(data)
        assert defaults.skills.exclude == ["peppa-*"]
        assert "petch" in defaults.skills.senders
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py -v`
Expected: FAIL — `SkillsConfig` and `SkillsFilterConfig` not found

- [ ] **Step 3: Write implementation**

In `nanobot/config/schema.py`, add before `AgentDefaults`:

```python
class SkillsFilterConfig(Base):
    """Include/exclude filter for skills (supports glob patterns)."""
    include: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)


class SkillsConfig(SkillsFilterConfig):
    """Skills filtering configuration with per-sender and per-channel overrides."""
    senders: dict[str, SkillsFilterConfig] = Field(default_factory=dict)
    channels: dict[str, SkillsFilterConfig] = Field(default_factory=dict)
```

In `AgentDefaults`, add field:

```python
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/config/schema.py tests/agent/test_skill_filtering.py
git commit -m "feat: add SkillsFilterConfig and SkillsConfig to config schema"
```

---

### Task 2: Filter Function — `filter_skill_names()`

**Files:**
- Modify: `nanobot/agent/skills.py` (add pure function)
- Modify: `tests/agent/test_skill_filtering.py` (add tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/agent/test_skill_filtering.py`:

```python
from nanobot.agent.skills import filter_skill_names


class TestFilterSkillNames:
    def test_include_all_no_exclude(self):
        names = ["coding", "weather", "ljg-card"]
        assert filter_skill_names(names, ["*"], []) == ["coding", "weather", "ljg-card"]

    def test_exclude_glob(self):
        names = ["coding", "weather", "ljg-card", "ljg-learn"]
        result = filter_skill_names(names, ["*"], ["ljg-*"])
        assert result == ["coding", "weather"]

    def test_include_glob(self):
        names = ["coding", "coding-agent", "weather", "ljg-card"]
        result = filter_skill_names(names, ["coding*"], [])
        assert result == ["coding", "coding-agent"]

    def test_include_and_exclude(self):
        names = ["coding", "coding-agent", "weather"]
        result = filter_skill_names(names, ["*"], ["weather"])
        assert result == ["coding", "coding-agent"]

    def test_exact_match(self):
        names = ["coding", "weather"]
        result = filter_skill_names(names, ["coding"], [])
        assert result == ["coding"]

    def test_empty_input(self):
        assert filter_skill_names([], ["*"], ["ljg-*"]) == []

    def test_exclude_overrides_include(self):
        names = ["coding", "coding-agent"]
        result = filter_skill_names(names, ["coding*"], ["coding-agent"])
        assert result == ["coding"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py::TestFilterSkillNames -v`
Expected: FAIL — `filter_skill_names` not found

- [ ] **Step 3: Write implementation**

In `nanobot/agent/skills.py`, add at module level (after imports):

```python
from fnmatch import fnmatch


def filter_skill_names(
    names: list[str], include: list[str], exclude: list[str],
) -> list[str]:
    """Filter skill names by include/exclude glob patterns.

    A name passes if it matches any include pattern AND matches no exclude pattern.
    """
    def _matches_any(name: str, patterns: list[str]) -> bool:
        return any(fnmatch(name, p) for p in patterns)

    return [
        n for n in names
        if _matches_any(n, include) and not _matches_any(n, exclude)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/agent/skills.py tests/agent/test_skill_filtering.py
git commit -m "feat: add filter_skill_names() with glob pattern matching"
```

---

### Task 3: Resolve Filter — `resolve_skill_filter()`

**Files:**
- Modify: `nanobot/agent/skills.py` (add resolver function)
- Modify: `tests/agent/test_skill_filtering.py` (add tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/agent/test_skill_filtering.py`:

```python
from nanobot.agent.skills import resolve_skill_filter
from nanobot.config.schema import SkillsConfig, SkillsFilterConfig


class TestResolveSkillFilter:
    def test_default_only(self):
        cfg = SkillsConfig(exclude=["peppa-*"])
        inc, exc = resolve_skill_filter(cfg)
        assert inc == ["*"]
        assert exc == ["peppa-*"]

    def test_sender_merges_with_default(self):
        cfg = SkillsConfig(
            exclude=["peppa-*"],
            senders={"petch": SkillsFilterConfig(exclude=["coding-*", "ljg-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="petch")
        assert inc == ["*"]
        # sender exclude extends default exclude
        assert set(exc) == {"peppa-*", "coding-*", "ljg-*"}

    def test_sender_include_replaces_default(self):
        cfg = SkillsConfig(
            senders={"petch": SkillsFilterConfig(include=["weather", "peppa-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="petch")
        assert inc == ["weather", "peppa-*"]

    def test_channel_overrides_everything(self):
        cfg = SkillsConfig(
            exclude=["peppa-*"],
            senders={"haibin": SkillsFilterConfig(exclude=["ljg-*"])},
            channels={"develop": SkillsFilterConfig(include=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="haibin", channel_name="develop")
        # channel is full override
        assert inc == ["coding-*"]
        assert exc == []

    def test_unknown_sender_uses_default(self):
        cfg = SkillsConfig(
            exclude=["peppa-*"],
            senders={"petch": SkillsFilterConfig(exclude=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="stranger")
        assert inc == ["*"]
        assert exc == ["peppa-*"]

    def test_unknown_channel_falls_to_sender(self):
        cfg = SkillsConfig(
            senders={"haibin": SkillsFilterConfig(exclude=["peppa-*"])},
            channels={"develop": SkillsFilterConfig(include=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="haibin", channel_name="general")
        assert inc == ["*"]
        assert exc == ["peppa-*"]

    def test_no_sender_no_channel(self):
        cfg = SkillsConfig()
        inc, exc = resolve_skill_filter(cfg)
        assert inc == ["*"]
        assert exc == []

    def test_case_insensitive_sender(self):
        cfg = SkillsConfig(
            senders={"petch": SkillsFilterConfig(exclude=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="Petch")
        assert "coding-*" in exc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py::TestResolveSkillFilter -v`
Expected: FAIL — `resolve_skill_filter` not found

- [ ] **Step 3: Write implementation**

In `nanobot/agent/skills.py`, add:

```python
def resolve_skill_filter(
    config: "SkillsConfig",
    sender_name: str | None = None,
    channel_name: str | None = None,
) -> tuple[list[str], list[str]]:
    """Resolve effective (include, exclude) from config + sender + channel.

    Priority: channel (full override) > sender (merge with default) > default.
    """
    # Channel: full override, no merge
    if channel_name:
        key = channel_name.lower()
        for k, v in config.channels.items():
            if k.lower() == key:
                return list(v.include), list(v.exclude)

    # Start from default
    include = list(config.include)
    exclude = list(config.exclude)

    # Sender: merge (include replaces if non-wildcard, exclude extends)
    if sender_name:
        key = sender_name.lower()
        for k, v in config.senders.items():
            if k.lower() == key:
                if v.include != ["*"]:
                    include = list(v.include)
                exclude = list(set(exclude) | set(v.exclude))
                break

    return include, exclude
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/agent/skills.py tests/agent/test_skill_filtering.py
git commit -m "feat: add resolve_skill_filter() with channel>sender>default priority"
```

---

## Chunk 2: Integration

### Task 4: Wire Filtering into ContextBuilder

**Files:**
- Modify: `nanobot/agent/context.py` (`build_system_prompt` accepts skills config + channel_name)
- Modify: `nanobot/agent/skills.py` (`build_skills_summary` and `get_always_skills` accept allowed_names)

- [ ] **Step 1: Add `allowed_names` parameter to `SkillsLoader.build_skills_summary()`**

In `nanobot/agent/skills.py`, modify `build_skills_summary`:

```python
def build_skills_summary(self, allowed_names: set[str] | None = None) -> str:
    """Build a summary of all skills (name, description, path, availability)."""
    all_skills = self.list_skills(filter_unavailable=False)
    if allowed_names is not None:
        all_skills = [s for s in all_skills if s["name"] in allowed_names]
    if not all_skills:
        return ""
    # ... rest unchanged
```

- [ ] **Step 2: Add `allowed_names` parameter to `SkillsLoader.get_always_skills()`**

In `nanobot/agent/skills.py`, modify `get_always_skills`:

```python
def get_always_skills(self, allowed_names: set[str] | None = None) -> list[str]:
    """Get skills marked as always=true that meet requirements."""
    result = []
    for s in self.list_skills(filter_unavailable=True):
        if allowed_names is not None and s["name"] not in allowed_names:
            continue
        meta = self.get_skill_metadata(s["name"]) or {}
        skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
        if skill_meta.get("always") or meta.get("always"):
            result.append(s["name"])
    return result
```

- [ ] **Step 3: Modify `ContextBuilder` to accept and use skills config**

In `nanobot/agent/context.py`:

```python
# Add import at top
from nanobot.agent.skills import filter_skill_names, resolve_skill_filter

# Modify __init__ to accept skills_config
def __init__(self, workspace: Path, timezone: str | None = None, skills_config=None):
    self.workspace = workspace
    self.timezone = timezone
    self.memory = MemoryStore(workspace)
    self.skills = SkillsLoader(workspace)
    self.skills_config = skills_config  # SkillsConfig | None

# Modify build_system_prompt to add channel_name param and filter
def build_system_prompt(
    self, skill_names: list[str] | None = None,
    sender_name: str | None = None,
    channel_name: str | None = None,
) -> str:
    """Build the system prompt from identity, bootstrap files, memory, and skills."""
    parts = [self._get_identity()]

    bootstrap = self._load_bootstrap_files(sender_name)
    if bootstrap:
        parts.append(bootstrap)

    memory = self.memory.get_memory_context()
    if memory:
        parts.append(f"# Memory\n\n{memory}")

    # Compute allowed skill names from filter config
    allowed_names: set[str] | None = None
    if self.skills_config:
        inc, exc = resolve_skill_filter(self.skills_config, sender_name, channel_name)
        all_names = [s["name"] for s in self.skills.list_skills(filter_unavailable=False)]
        filtered = filter_skill_names(all_names, inc, exc)
        allowed_names = set(filtered)

    always_skills = self.skills.get_always_skills(allowed_names)
    if always_skills:
        always_content = self.skills.load_skills_for_context(always_skills)
        if always_content:
            parts.append(f"# Active Skills\n\n{always_content}")

    skills_summary = self.skills.build_skills_summary(allowed_names)
    if skills_summary:
        parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

    soul_anchor = self._load_soul_anchor(sender_name)
    if soul_anchor:
        parts.append(f"# Remember\n\n{soul_anchor}")

    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Pass `channel_name` to `build_system_prompt` in `build_messages`**

In `nanobot/agent/context.py`, modify `build_messages`:

```python
return [
    {"role": "system", "content": self.build_system_prompt(
        skill_names, sender_name=sender_name, channel_name=channel_name,
    )},
    *history,
    {"role": current_role, "content": merged},
]
```

- [ ] **Step 5: Run all existing tests to ensure no regressions**

Run: `cd /root/git_code/nanobot && python -m pytest tests/ -v --timeout=30`
Expected: ALL PASS (new params are optional with None defaults)

- [ ] **Step 6: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/agent/skills.py nanobot/agent/context.py
git commit -m "feat: wire skill filtering into ContextBuilder and SkillsLoader"
```

---

### Task 5: Wire Skills Config into AgentLoop

**Files:**
- Modify: `nanobot/agent/loop.py` (pass skills_config to ContextBuilder)
- Modify: `nanobot/nanobot.py` (pass skills_config in SDK path)

- [ ] **Step 1: Pass skills_config to ContextBuilder in AgentLoop.__init__**

In `nanobot/agent/loop.py`, modify the `__init__`:

```python
# Add parameter
def __init__(
    self,
    ...
    skills_config=None,  # SkillsConfig | None
    ...
):
    ...
    self.context = ContextBuilder(workspace, timezone=timezone, skills_config=skills_config)
```

- [ ] **Step 2: Pass skills_config from all AgentLoop construction sites**

In `nanobot/cli/commands.py`, at each `AgentLoop(...)` call, add:

```python
    skills_config=config.agents.defaults.skills if config.agents.defaults.skills.senders or config.agents.defaults.skills.exclude or config.agents.defaults.skills.channels else None,
```

Simpler approach — just always pass it:

```python
    skills_config=config.agents.defaults.skills,
```

Same for `nanobot/nanobot.py`:

```python
    skills_config=defaults.skills,
```

- [ ] **Step 3: Run full test suite**

Run: `cd /root/git_code/nanobot && python -m pytest tests/ -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/agent/loop.py nanobot/cli/commands.py nanobot/nanobot.py
git commit -m "feat: pass SkillsConfig through AgentLoop to ContextBuilder"
```

---

### Task 6: Integration Test

**Files:**
- Modify: `tests/agent/test_skill_filtering.py` (add integration test)

- [ ] **Step 1: Write integration test**

Append to `tests/agent/test_skill_filtering.py`:

```python
from pathlib import Path
from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import SkillsConfig, SkillsFilterConfig


class TestSkillFilteringIntegration:
    """Integration: ContextBuilder respects skills filtering."""

    def _make_workspace(self, tmp_path: Path, skill_names: list[str]) -> Path:
        ws = tmp_path / "workspace"
        ws.mkdir()
        skills_dir = ws / "skills"
        skills_dir.mkdir()
        for name in skill_names:
            skill_dir = skills_dir / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {name} skill\n---\n# {name}\nDo {name} stuff.\n"
            )
        # Minimal bootstrap files
        (ws / "memory").mkdir()
        return ws

    def test_no_config_includes_all(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        ctx = ContextBuilder(ws)
        prompt = ctx.build_system_prompt()
        assert "coding" in prompt
        assert "weather" in prompt
        assert "ljg-card" in prompt

    def test_exclude_filters_skills(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card", "ljg-learn"])
        cfg = SkillsConfig(exclude=["ljg-*"])
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt()
        assert "coding" in prompt
        assert "weather" in prompt
        assert "ljg-card" not in prompt
        assert "ljg-learn" not in prompt

    def test_sender_exclude(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        cfg = SkillsConfig(
            senders={"petch": SkillsFilterConfig(exclude=["coding*", "ljg-*"])}
        )
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt(sender_name="petch")
        assert "weather" in prompt
        assert "coding" not in prompt
        assert "ljg-card" not in prompt

    def test_channel_override(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        cfg = SkillsConfig(
            channels={"develop": SkillsFilterConfig(include=["coding*"])}
        )
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt(sender_name="haibin", channel_name="develop")
        assert "coding" in prompt
        assert "weather" not in prompt
        assert "ljg-card" not in prompt

    def test_sender_with_no_matching_channel_uses_sender(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        cfg = SkillsConfig(
            senders={"haibin": SkillsFilterConfig(exclude=["ljg-*"])},
            channels={"develop": SkillsFilterConfig(include=["coding*"])}
        )
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt(sender_name="haibin", channel_name="general")
        assert "coding" in prompt
        assert "weather" in prompt
        assert "ljg-card" not in prompt
```

- [ ] **Step 2: Run integration tests**

Run: `cd /root/git_code/nanobot && python -m pytest tests/agent/test_skill_filtering.py::TestSkillFilteringIntegration -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /root/git_code/nanobot && python -m pytest tests/ -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /root/git_code/nanobot
git add tests/agent/test_skill_filtering.py
git commit -m "test: add integration tests for skill filtering"
```

---

## Summary

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | +`SkillsFilterConfig`, +`SkillsConfig`, wire into `AgentDefaults` |
| `nanobot/agent/skills.py` | +`filter_skill_names()`, +`resolve_skill_filter()`, `build_skills_summary(allowed_names)`, `get_always_skills(allowed_names)` |
| `nanobot/agent/context.py` | `__init__` accepts `skills_config`, `build_system_prompt` accepts `channel_name`, filters before building |
| `nanobot/agent/loop.py` | Pass `skills_config` to `ContextBuilder` |
| `nanobot/cli/commands.py` | Pass `skills_config` at all `AgentLoop()` call sites |
| `nanobot/nanobot.py` | Pass `skills_config` at SDK `AgentLoop()` call site |
| `tests/agent/test_skill_filtering.py` | Unit + integration tests |

**Estimated new code:** ~80 lines implementation + ~150 lines tests

**Config example for your use case:**
```json
{
  "agents": {
    "defaults": {
      "skills": {
        "senders": {
          "petch": { "exclude": ["coding-*", "ljg-*", "khb-*", "systematic-debugging"] }
        },
        "channels": {
          "develop": { "include": ["coding*", "skill-creator", "systematic-debugging", "todo"] }
        }
      }
    }
  }
}
```
