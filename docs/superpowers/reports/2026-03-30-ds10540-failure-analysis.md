# DS10540 Failure Analysis: Nanobot Agent vs Claude Code

> Investigation report: nanobot answered from its own memory instead of accessing Obsidian.
> Date: 2026-03-30
> Trace ID: `501bc1ca50489e57d719c1ddc162a671`

---

## 1. Incident Summary

**User request**: "Summarize details in Obsidian for project DS10540"

**Expected behavior**: Load the `obsidian-cli` skill, use Obsidian CLI commands to browse/read vault content for DS10540, summarize actual Obsidian data.

**Actual behavior**: Ran `nanobot memory inspect --query "DS10540"` via `exec`, summarized nanobot's own memory database as if it were Obsidian content.

**Impact**: Confidently wrong answer. User received a summary of what nanobot *remembers* about DS10540 from prior conversations — not what's actually in the Obsidian vault.

---

## 2. Trace Reconstruction (from Langfuse)

| Step | Observation | Details |
|------|------------|---------|
| Context build | 3,422ms memory retrieval | 6 memory results retrieved for system prompt |
| LLM Call 1 | gpt-4o-mini, 8,029 input tokens, 23 output tokens | Model chose `exec("nanobot memory inspect --query \"DS10540\"")` |
| Tool execution | 6,922ms | Returned nanobot's own memory: 56 events, 21 profile items, "Top Memories" table |
| LLM Call 2 | 8,638 input tokens, 133 output tokens | Summarized memory data as if it were Obsidian content |
| Post-turn | Micro-extraction | Saved 4 new memory events (compounding the error) |

**Total**: 2 LLM calls, 1 tool call, 28.5s, $0.00012. No guardrails fired.

---

## 3. The Five Structural Problems

### Problem A: The Identity Prompt Instructs the Wrong Behavior (CRITICAL)

**File**: `nanobot/templates/prompts/identity.md`, lines 29-35

```markdown
## Memory
- Use `exec` to run `nanobot memory inspect --query "keyword"` to search past events.

## Using Your Memory Context
- Prefer memory over general knowledge; use it directly if it answers the question.
- Answer from memory first; use tools only for what memory doesn't cover.
```

**This is the smoking gun.** The system prompt explicitly tells the model to:
1. Use `nanobot memory inspect` via `exec` to search past events
2. **Prefer memory over tools**
3. **Answer from memory first**

When gpt-4o-mini sees "DS10540" and the instruction "Answer from memory first; use tools only for what memory doesn't cover," it does exactly that — runs `nanobot memory inspect` and presents the result. The model is *following instructions*, not misbehaving.

### Problem B: Skill Loading Is Optional, Not Mandatory

**Files**: `nanobot/templates/prompts/skills_header.md`, `nanobot/tools/builtin/skills.py`

The `skills_header.md` says:
```
If the user's request matches a skill topic, call load_skill(name) as your FIRST action
```

And the `load_skill` tool description says:
```
IMPORTANT: When the user's request relates to a topic in the Skills section
of your system prompt, call this tool FIRST before taking any other action.
```

But these are **soft instructions in a prompt** — they compete with the "answer from memory first" instruction in `identity.md`. A weak model (gpt-4o-mini) sees two competing instructions and picks the one that's simpler to execute. There's no structural enforcement.

### Problem C: No Guardrail for "Wrong Data Source"

**File**: `nanobot/agent/turn_guardrails.py`

The five guardrails detect:
1. **EmptyResultRecovery** — empty tool results
2. **RepeatedStrategyDetection** — same tool/args called 3+ times
3. **SkillTunnelVision** — exec-only with no data at iteration >= 3
4. **NoProgressBudget** — no useful data after 4+ iterations
5. **FailureEscalation** — tool failure count thresholds

None detect "used nanobot's own memory when the user asked for an external data source." The tool call **succeeded** with **non-empty data**, so every guardrail was silent.

### Problem D: The exec Tool Is Too Generic

**File**: `nanobot/tools/builtin/shell.py`, lines 100-104

```python
name = "exec"
description = (
    "Execute a shell command. Use for skill commands, system operations,"
    " or when no specific tool fits. Check skill decision guides for which command to use."
)
```

This is a catch-all — it runs anything, including `nanobot memory inspect`. There's no way for the guardrail layer to distinguish "exec running an obsidian command" from "exec running nanobot's own CLI". It's all just `exec`.

### Problem E: Skills Summary Lacks Trigger Enforcement

**File**: `nanobot/context/skills.py`, `build_skills_summary()`

The skills summary is a flat list:
```
- ✓ **obsidian-cli**: Skill for the official Obsidian CLI (v1.12+)...
```

The model must pattern-match "Obsidian" in the user message to "obsidian-cli" in the skills list. gpt-4o-mini failed this pattern match because the competing "answer from memory first" instruction won.

Meanwhile, the `obsidian-cli` skill frontmatter already contains trigger keywords:
```yaml
triggers:
  - obsidian
  - vault
  - daily note
  - obsidian cli
```

This trigger data exists but is **completely unused** — it's never checked against the user message.

---

## 4. Comparison: How Claude Code Solves These Same Problems

Claude Code faces the same challenge — user asks about an external system, skills are available, the agent needs to pick the right approach. Here's how its architecture differs:

### 4a. Skill System Is Structurally Enforced, Not Prompt-Suggested

Claude Code's system prompt says:
```
IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.
This is not negotiable. This is not optional. You cannot rationalize your way out of this.
```

And includes a **red flags table** that catches rationalizations:
```
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first"      | Skill check comes BEFORE clarifying questions. |
| "Let me explore first"           | Skills tell you HOW to explore. Check first. |
```

**Key difference**: Skill invocation isn't a suggestion — it's backed by a dedicated `Skill` tool that's structurally separate from general execution, and the instructions escalate urgency with "EXTREMELY_IMPORTANT" framing and anti-rationalization rules.

### 4b. No "Memory First" Instruction

Claude Code has memory (auto-memory system), but its instructions say:
> Memory records can become stale over time. Use memory as context for what was true at a given point in time. Before answering the user or building assumptions based solely on information in memory records, verify that the memory is still correct and up-to-date by reading the current state of the files or resources.

**Key difference**: Memory is context, not an answer source. The agent is told to **verify against current state**, not to "prefer memory over tools."

### 4c. Dedicated Tools Instead of Generic exec

Claude Code has purpose-specific tools: `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `Agent`, `Skill`. Each has a clear description of when to use it AND when NOT to use it.

**Key difference**: When a user mentions a skill, Claude Code invokes the `Skill` tool — not a generic exec. The skill system is a first-class tool with its own entry point, not a command passed through a shell executor.

### 4d. Stronger Negative Selection in Tool Descriptions

Claude Code tool descriptions include anti-patterns:
```
- If you want to read a specific file path, use the Read tool... NOT the Agent tool
- To read files use Read instead of cat, head, tail, or sed
```

**Key difference**: Tools don't just say what they do — they say what they *should not* be used for. This creates exclusion zones that prevent the "any tool will do" reasoning gpt-4o-mini exhibited.

### 4e. Multi-Agent Architecture for Complex Tasks

Claude Code delegates to specialized subagents (Explore, Plan, etc.) that have focused toolsets. A general-purpose agent researching Obsidian content would use appropriate tools within its scope.

**Key difference**: Nanobot sends everything through a single agent loop. There's no way to constrain the tool palette for a specific subtask.

---

## 5. Root Cause Hierarchy

```
Root Cause 1 (CRITICAL): identity.md instructs "prefer memory -> answer from memory first"
  |-- This directly caused the model to use nanobot memory inspect
  |-- Competing with skills_header.md's "load skill FIRST"
  '-- gpt-4o-mini resolved the conflict by choosing the simpler path

Root Cause 2 (HIGH): Skill loading is prompt-enforced, not structurally enforced
  |-- No code-level gate that checks "does this query match a skill trigger?"
  '-- The model can skip skill loading with zero structural consequence

Root Cause 3 (MEDIUM): exec is too generic -- conflates skill commands with system commands
  |-- "nanobot memory inspect" and "obsidian search" are both just exec calls
  '-- Guardrails can't distinguish data sources

Root Cause 4 (LOW): No guardrail for "answered from wrong source"
  |-- All guardrails focus on tool failure/empty results
  '-- A successful result from the wrong source passes all checks
```

---

## 6. Proposed Solutions

### Solution 1: Fix the Identity Prompt (Critical, immediate)

**File to change**: `nanobot/templates/prompts/identity.md`

**Remove** the "answer from memory first" instruction. Replace with:

```markdown
## Memory
- Your memory context is automatically included in this prompt (see the Memory section).
- Memory provides background context -- it does NOT replace accessing external systems.
- When the user asks about content in an external system (Obsidian, GitHub, etc.),
  you MUST access that system directly. Memory may be stale or incomplete.
- Use `exec` to run `nanobot memory inspect --query "keyword"` ONLY when the user
  asks about past conversations or what you remember -- never as a substitute for
  reading actual data from external tools.

## Using Your Memory Context
- Use memory as supporting context, not as a primary data source.
- Cite values verbatim -- do not paraphrase names, numbers, or technical terms.
- When memory and external data conflict, trust the external data source.
```

**Why**: This is the #1 cause. The current prompt actively instructs the wrong behavior.

**Effort**: 5 minutes. **Impact**: Critical.

### Solution 2: Add Skill Trigger Matching to the Context Builder (High, structural)

**Files to change**: `nanobot/context/context.py`, `nanobot/context/skills.py`

Add a pre-turn skill trigger check using the existing `triggers` frontmatter:

```python
# In SkillsLoader
def match_triggers(self, user_message: str) -> list[str]:
    """Check if user message matches any skill triggers."""
    matched = []
    msg_lower = user_message.lower()
    for skill in self.list_skills():
        meta = self.get_skill_metadata(skill["name"])
        if not meta:
            continue
        triggers = meta.get("triggers", [])
        for trigger in triggers:
            if trigger.lower() in msg_lower:
                matched.append(skill["name"])
                break
    return matched
```

When triggers match, inject a stronger instruction into the system prompt:

```markdown
## SKILL MATCH DETECTED

The user's request mentions "obsidian" which matches the **obsidian-cli** skill.
You MUST call `load_skill("obsidian-cli")` as your FIRST action before taking
any other action. Do NOT use memory or other tools to answer this request
without loading the skill first.
```

**Why**: The obsidian-cli skill already has `triggers: [obsidian, vault, daily note, obsidian cli]` in its frontmatter — this data exists but is completely unused. This is what Claude Code's superpowers system does: it doesn't just list skills, it **detects** when they apply and **forces** invocation.

**Effort**: 2-3 hours. **Impact**: High.

### Solution 3: Add a "Skill Not Loaded" Guardrail (Medium, defensive)

**File to change**: `nanobot/agent/turn_guardrails.py`

A new guardrail that fires when:
- The user message contains a known skill trigger keyword
- No `load_skill` call has been made this turn
- A tool call was made (the agent is acting without the skill)

```python
class SkillNotLoaded:
    """Fires when the agent acts on a skill-related request without loading the skill."""

    name = "skill_not_loaded"

    def check(self, all_attempts, latest_results, *, iteration, **kw):
        if iteration > 1:
            return None  # only check on first tool call

        has_load_skill = any(r.tool_name == "load_skill" for r in all_attempts)
        if has_load_skill:
            return None

        matched_triggers = kw.get("matched_skill_triggers")
        if not matched_triggers:
            return None

        skill_names = ", ".join(matched_triggers)
        return Intervention(
            source=self.name,
            message=(
                f"STOP: The user's request matches skill(s): {skill_names}. "
                "You haven't loaded the skill yet. Call load_skill() FIRST to get "
                "the correct instructions for handling this request. Do NOT use "
                "memory or general tools as a substitute for skill-specific commands."
            ),
            severity="override",
            strategy_tag="load_skill_first",
        )
```

**Why**: Reactive safety net. Even if the prompt fix (Solution 1) works for strong models, weak models may still skip skill loading. The guardrail catches it after the first wrong tool call.

**Effort**: 1-2 hours. **Impact**: Medium.

### Solution 4: Separate Memory Inspect from exec (Low, cleanliness)

Register `nanobot memory inspect` as a dedicated `memory_inspect` tool rather than routing it through `exec`. This would:
- Give it a clear description: "Search YOUR OWN past conversation memories. Do NOT use for accessing external systems."
- Let guardrails distinguish memory lookups from external tool commands
- Remove the ambiguity of `exec` running both internal and external commands

**Effort**: 1 hour. **Impact**: Low (cleanliness improvement).

---

## 7. Priority and Implementation Order

| # | Solution | Effort | Impact | Implements |
|---|----------|--------|--------|------------|
| 1 | Fix identity.md prompt | 5 min | Critical | Removes the instruction that caused the failure |
| 2 | Skill trigger matching | 2-3 hrs | High | Structural prevention using existing frontmatter data |
| 3 | SkillNotLoaded guardrail | 1-2 hrs | Medium | Defensive layer for weak models |
| 4 | Separate memory_inspect tool | 1 hr | Low | Cleanliness, helps guardrail layer distinguish sources |

**Solutions 1+2 together would have prevented this failure entirely.** Solution 3 adds defense in depth for weaker models. Solution 4 is a cleanliness improvement.

---

## 8. Broader Lessons

### For Prompt Architecture

1. **Competing instructions are bugs.** "Answer from memory first" and "load skill FIRST" cannot coexist. When two instructions conflict, the model picks whichever is simpler — usually the wrong one.

2. **Soft instructions don't work for weak models.** "IMPORTANT: call load_skill FIRST" is a suggestion, not a gate. Structural enforcement (trigger matching + guardrails) is needed for model-agnostic reliability.

3. **Tool descriptions need negative selection.** "Execute a shell command" is too broad. Tools should say what they're NOT for, creating exclusion zones that prevent misuse.

### For the Guardrail Layer

4. **Guardrails only catch failure patterns, not success-from-wrong-source.** The entire guardrail suite assumes that a successful, non-empty tool result is correct. A new category of guardrail is needed: "did the agent use the right source for this request?"

5. **Skill trigger data is unused gold.** The obsidian-cli skill already declares `triggers: [obsidian, vault, daily note]`. This metadata should drive both prompt injection (Solution 2) and guardrail checks (Solution 3).

### For the Cognitive Architecture

6. **The identity prompt is the highest-authority instruction.** It's the first thing the model reads. When it says "prefer memory," that instruction overrides everything that comes later in the prompt. The identity section must be carefully reviewed for instructions that could conflict with skill/tool usage.

7. **The feedback loop failed silently.** The micro-extractor saved 4 new memory events from this interaction — compounding the error. A wrong answer became "learned" facts. Future queries about DS10540 will now have even more memory data pulling the model toward the wrong approach.
