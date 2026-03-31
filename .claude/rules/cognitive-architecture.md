# Nanobot Cognitive Architecture

> Living document. Governs the agent's cognitive core design.
> Companion to `architecture.md` (system-wide structure and module boundaries).
> Last updated: 2026-03-28.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Governing Design Patterns](#governing-design-patterns)
3. [The Cognitive Loop (TurnRunner)](#the-cognitive-loop)
4. [The Guardrail Layer](#the-guardrail-layer)
5. [The Prompt Layer (Context Architecture)](#the-prompt-layer)
6. [The Memory Interface (Three-Tier Model)](#the-memory-interface)
7. [Entry Layer and Composition](#entry-layer-and-composition)
8. [Structural Patterns for Long-Term Stability](#structural-patterns)
9. [Extension Points](#extension-points)
10. [Testing Strategy](#testing-strategy)
11. [Observability](#observability)
12. [Appendix A: Approach Selection](#appendix-a)
13. [Appendix B: How the Three Layers Work Together](#appendix-b)

---

<a id="architecture-overview"></a>
## 1. Architecture Overview

The agent cognitive core has four architectural layers, each with a single responsibility:

```
┌─────────────────────────────────────────────────────────────┐
│                      ENTRY LAYER                             │
│  Receives messages, manages sessions, delivers responses     │
│  (MessageProcessor)                                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    COGNITIVE LOOP                             │
│  Simple tool-use loop with guardrail checkpoints             │
│  (TurnRunner)                                                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   GUARDRAIL LAYER                             │
│  Modular, independent checks that fire on failure patterns   │
│  (GuardrailChain)                                            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   PROMPT LAYER                                │
│  System prompt architecture + tool descriptions + skills     │
│  (ContextBuilder)                                            │
└─────────────────────────────────────────────────────────────┘

  Consumed by all layers:
  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
  │  Memory    │ │   Tools    │ │ Providers  │ │ Observ.    │
  │  (3-tier)  │ │ (registry) │ │   (LLM)    │ │ (Langfuse) │
  └────────────┘ └────────────┘ └────────────┘ └────────────┘
```

---

<a id="governing-design-patterns"></a>
## 2. Governing Design Patterns

These are the patterns that keep the codebase stable as it evolves. Every future change
must satisfy them.

### Pattern 1: The Loop Is Dumb, The Prompt Is Smart

The cognitive loop is a mechanical executor — it calls the LLM, runs tools, and checks
guardrails. It has no domain knowledge, no task understanding, no strategy. All intelligence
lives in what the LLM sees: the system prompt, tool descriptions, skill content, and
memory context.

**Rationale:** Code is rigid and expensive to change. Prompts are flexible and cheap to
iterate. When the agent makes a bad decision, the fix is a prompt adjustment, not a code
change. This also means the loop rarely needs modification — it is the most stable component.

**Enforcement:** The loop must never contain:
- Task-type detection (no `_needs_planning()` keyword heuristics)
- Domain-specific logic (no "if obsidian then..." branching)
- Model-specific behavior (no "if gpt-4o then..." branching)
- Strategy selection (no "choose between search and browse")

### Pattern 2: Guardrails Are Plugins, Not States

Each guardrail is an independent module that receives the current iteration context and
returns either `None` (no intervention) or an `Intervention` (a system message to inject).
Guardrails are composed into a chain. Adding or removing a guardrail never changes the loop.

**Rationale:** The previous ReflectPhase accumulated 7 different nudge types in one class
because the only extension point was "add another elif branch." The plugin pattern prevents
this — each behavior is its own module with its own tests.

**Enforcement:** Guardrails must:
- Be stateless pure functions (receive context, return intervention or None)
- Have no dependencies on each other (no guardrail calls another guardrail)
- Be independently testable (unit test with synthetic iteration context)
- Be registered declaratively (a list in config or factory, not if/elif chains)

### Pattern 3: Context Is Layered and Composable

The system prompt is assembled from independent layers, each owned by one subsystem. No
layer knows about the others. The context builder composes them in a defined order.

```
System Prompt = Identity
              + Reasoning Protocol
              + Tool Selection Guide
              + Procedural Memory (strategies)
              + Declarative Memory (facts)
              + Bootstrap Files
              + Feedback
              + Active Skills
              + Skills Summary
              + Verification Instructions (if enabled)
              + Security Advisory
```

**Rationale:** Layered composition means each subsystem manages its own context
contribution independently. Adding a new layer means adding a function, not modifying
the builder.

**Enforcement:** Each context layer is a function: `(workspace, config, query) -> str | None`.
The builder calls each in order and joins non-None results.

### Pattern 4: Memory Has Three Tiers

| Tier | Scope | Content | Storage |
|------|-------|---------|---------|
| **Declarative** | Cross-session | Facts, entities, relationships | SQLite (existing) |
| **Procedural** | Cross-session | Tool strategies, what-worked/what-failed | SQLite (new table) |
| **Working** | Per-turn | Current goals, attempted approaches, accumulated evidence | In-memory dataclass |

**Rationale:** The system previously saved facts but not strategies. This caused the agent
to repeat the same failing approach across sessions. Procedural memory breaks the
repetition cycle. Working memory prevents within-turn amnesia (the agent losing track
of what it already tried).

### Pattern 5: Feedback Loops Close the Learning Gap

```
Guardrail fires -> recovery succeeds -> strategy extractor
  saves pattern to procedural memory -> next session loads
  strategy into context -> guardrail never fires again
```

This is the system's learning mechanism. Without it, guardrails are just band-aids. With
it, every failure makes the system permanently smarter.

---

<a id="the-cognitive-loop"></a>
## 3. The Cognitive Loop (TurnRunner)

The core engine. The name "runner" reflects its role: it **runs** the loop mechanically,
it does not **orchestrate** intelligence.

### Structure

```python
class TurnRunner:
    """Mechanical tool-use loop with guardrail checkpoints.

    This class has NO domain knowledge. It calls the LLM, executes tools,
    checks guardrails, and manages iteration limits. All intelligence
    lives in the prompt (what the LLM sees) and the guardrails (what
    fires on failure patterns).
    """
```

### The Loop (Pseudocode)

```
async def run(state: TurnState) -> TurnResult:

    while state.iteration < max_iterations:
        state.iteration += 1

        # -- Guardrail: resource limits --
        if wall_time_exceeded:
            break with timeout message
        if context_over_budget:
            compress(messages)

        # -- LLM call --
        filter disabled tools from definitions
        response = call_llm(messages, tools)

        if llm_error:
            handle_error_with_retry()
            continue

        # -- Tool path --
        if response.has_tool_calls:
            results = execute_batch(response.tool_calls)
            add_results_to_messages()
            track_failures()
            update_working_memory(results)

            # -- Guardrail checkpoint --
            intervention = guardrail_chain.check(state)
            if intervention:
                inject(intervention, into=messages)

            continue

        # -- Response path --
        final_content = response.content
        add_to_messages()
        break

    # -- Post-loop --
    if no_answer and iterations_exhausted:
        final_content = fallback_message()

    # -- Optional verification --
    if verification_enabled:
        final_content = self_check(final_content, messages)

    return TurnResult(content, tools_used, messages, token_counts)
```

### Working Memory (Per-Turn State)

```python
@dataclass(slots=True)
class TurnState:
    """Mutable state across loop iterations."""

    # Core
    messages: list[dict]
    user_text: str
    iteration: int = 0

    # Tool tracking
    tools_used: list[str]
    disabled_tools: set[str]
    tracker: ToolCallTracker

    # Working memory (enables guardrails to reason about history)
    tool_results_log: list[ToolAttempt]
    current_strategy: str | None = None

    # Cached
    tools_def_cache: list[dict]
    tools_def_snapshot: frozenset[str]

    # Metrics
    tokens_prompt: int = 0
    tokens_completion: int = 0
    llm_calls: int = 0
```

The `ToolAttempt` captures what guardrails need to detect patterns:

```python
@dataclass(slots=True, frozen=True)
class ToolAttempt:
    tool_name: str
    arguments: dict
    success: bool
    output_empty: bool      # result was success but returned no data
    output_snippet: str     # first 200 chars for pattern detection
    iteration: int
```

This is the **working memory** — it lets guardrails answer questions like:
- "Has the agent tried the same tool twice with similar arguments?"
- "Did the last 2 results come back empty?"
- "Has the agent been calling only skill-specific commands without trying base tools?"

### Self-Check (Configurable Verification)

Two modes, selected by config:

**Mode: prompt-only (default)**
No extra code. The system prompt includes:
```markdown
## Before Sending Your Response
- Does every claim trace to a tool result in this conversation?
- If reporting "not found" — did you try at least 2 approaches?
- Are you stating anything you didn't verify with a tool?
```

**Mode: structured (config: `verification.mode = "structured"`)**
After the loop produces `final_content`, one additional LLM call with the same message
context:

```python
async def _structured_self_check(self, content, messages, user_text):
    check_prompt = {
        "role": "system",
        "content": (
            "Review your response for accuracy. Check:\n"
            "1. Every factual claim has a supporting tool result\n"
            "2. 'Not found' claims tried multiple approaches\n"
            "3. No assumptions stated as facts\n\n"
            "If issues found, output a corrected response. "
            "If no issues, output the response unchanged."
        )
    }
    messages_with_check = messages + [check_prompt]
    response = await call_llm(messages_with_check, tools=None)
    return response.content or content
```

Key properties: **same context** (no information loss), **no separate critique+revision
dance** (one pass), **no confidence scoring** (the model just fixes or passes through).

### File Targets

| File | LOC Target | Responsibility |
|------|-----------|----------------|
| `turn_runner.py` | ~200 | The loop + self-check |
| `turn_types.py` | ~80 | TurnState, TurnResult, ToolAttempt |
| `turn_guardrails.py` | ~150 | GuardrailChain + individual guardrails |

**Total: ~430 LOC**

---

<a id="the-guardrail-layer"></a>
## 4. The Guardrail Layer

The extension point where reasoning enforcement lives — the part that catches
weak models and turns failures into learning opportunities.

### Core Abstraction

```python
@dataclass(slots=True, frozen=True)
class Intervention:
    """A system message to inject into the conversation."""
    source: str          # guardrail name (for observability)
    message: str         # the system message content
    severity: str        # "hint" | "directive" | "override"
    strategy_tag: str | None = None  # for procedural memory extraction

class Guardrail(Protocol):
    """Single responsibility: detect one failure pattern, suggest one intervention."""

    @property
    def name(self) -> str: ...

    def check(self, state: TurnState, latest_results: list[ToolAttempt]) -> Intervention | None:
        """Return an intervention if the pattern is detected, None otherwise.

        MUST be a pure function: no side effects, no state mutation,
        no LLM calls, no I/O. Receives read-only context, returns data.
        """
        ...
```

The guardrail is a **pure function** — it looks at the iteration state and either returns
an intervention or nothing. This makes every guardrail independently testable with
synthetic state.

### GuardrailChain

```python
class GuardrailChain:
    """Runs guardrails in priority order, returns first intervention or None.

    Design rules:
    - Guardrails are evaluated in registration order (highest priority first)
    - First intervention wins (no stacking — one correction at a time)
    - The chain never modifies state; the loop handles injection
    """

    def __init__(self, guardrails: list[Guardrail]) -> None:
        self._guardrails = guardrails

    def check(self, state: TurnState, latest_results: list[ToolAttempt]) -> Intervention | None:
        for guardrail in self._guardrails:
            intervention = guardrail.check(state, latest_results)
            if intervention is not None:
                return intervention
        return None
```

**Why first-intervention-wins:** Stacking multiple corrections confuses the model. If the
agent got an empty result AND it is repeating a strategy, the most specific guardrail
(empty result) should fire, not both. Priority ordering handles this.

### The Guardrails

Each guardrail is a small, focused module. The initial set addresses failures observed
in the DS10540 case:

#### Guardrail 1: Empty Result Recovery

Fires when a tool returns success but no meaningful data.

```python
class EmptyResultRecovery:
    """Fires when a tool returns success but no meaningful data."""

    name = "empty_result_recovery"

    def check(self, state, latest_results):
        empty_results = [r for r in latest_results if r.success and r.output_empty]
        if not empty_results:
            return None

        tool_name = empty_results[0].tool_name
        prior_empties = [
            r for r in state.tool_results_log[:-len(latest_results)]
            if r.tool_name == tool_name and r.output_empty
        ]

        if prior_empties:
            # Same tool returned empty twice — escalate
            return Intervention(
                source=self.name,
                message=(
                    f"STOP: `{tool_name}` returned no results twice. "
                    "Your search approach is likely wrong — the term may match "
                    "a folder name, file name, or metadata rather than content. "
                    "Try a structural approach: use `list_dir` to explore the "
                    "directory, or use a different command from the skill that "
                    "browses by name instead of searching content. "
                    "Do NOT call the same tool with the same approach again."
                ),
                severity="directive",
                strategy_tag="empty_result_strategy_switch",
            )

        # First empty — gentle hint
        return Intervention(
            source=self.name,
            message=(
                f"`{tool_name}` returned no results. Before reporting 'not found', "
                "consider: could your search term be a folder name, file name, or "
                "tag rather than file content? Try an alternative approach."
            ),
            severity="hint",
            strategy_tag="empty_result_first_hint",
        )
```

#### Guardrail 2: Repeated Strategy Detection

Catches the "same tool, same args, same failure" loop.

```python
class RepeatedStrategyDetection:
    """Fires when the agent calls the same tool with similar arguments repeatedly."""

    name = "repeated_strategy"

    def check(self, state, latest_results):
        for result in latest_results:
            similar_prior = [
                r for r in state.tool_results_log[:-len(latest_results)]
                if r.tool_name == result.tool_name
                and self._args_similar(r.arguments, result.arguments)
            ]
            if len(similar_prior) >= 2:
                return Intervention(
                    source=self.name,
                    message=(
                        f"You have called `{result.tool_name}` {len(similar_prior)+1} "
                        "times with similar arguments. This approach is not working. "
                        "You MUST try a fundamentally different strategy: different tool, "
                        "different command, or fall back to base tools (list_dir, read_file)."
                    ),
                    severity="override",
                    strategy_tag="strategy_loop_break",
                )
        return None
```

#### Guardrail 3: Skill-Only Tunnel Vision

Catches the pattern where the agent stays inside a skill's commands and never falls back
to base tools.

```python
class SkillTunnelVision:
    """Fires when the agent uses only skill commands (exec) and ignores base tools."""

    name = "skill_tunnel_vision"

    def check(self, state, latest_results):
        if state.iteration < 3:
            return None  # too early to judge

        recent = state.tool_results_log[-6:]
        all_exec = all(r.tool_name == "exec" for r in recent)
        any_success_with_data = any(r.success and not r.output_empty for r in recent)

        if all_exec and not any_success_with_data:
            return Intervention(
                source=self.name,
                message=(
                    "You have been using only shell commands from the skill, "
                    "but none have returned useful data. Your base tools "
                    "(list_dir, read_file) can access the same filesystem directly. "
                    "Try using list_dir to explore the directory structure, then "
                    "read_file to read specific files you find."
                ),
                severity="directive",
                strategy_tag="fallback_to_base_tools",
            )
        return None
```

#### Guardrail 4: No-Progress Budget

Fires when too many iterations pass without useful data.

```python
class NoProgressBudget:
    """Fires when too many iterations pass without useful data."""

    name = "no_progress_budget"

    def check(self, state, latest_results):
        if state.iteration < 4:
            return None

        useful = sum(
            1 for r in state.tool_results_log
            if r.success and not r.output_empty
        )

        if useful == 0 and state.iteration >= 4:
            return Intervention(
                source=self.name,
                message=(
                    f"After {state.iteration} iterations, no tool call has "
                    "returned useful data. Stop calling tools. Explain to the "
                    "user what you tried, why it didn't work, and suggest what "
                    "they could try (e.g., providing a specific file name or path)."
                ),
                severity="override",
                strategy_tag=None,
            )
        return None
```

#### Guardrail 5: Failure Escalation

Wraps the existing `ToolCallTracker` logic — tool disabling after repeated failures.

```python
class FailureEscalation:
    """Fires when a specific tool has failed enough times to be disabled."""

    name = "failure_escalation"

    def check(self, state, latest_results):
        failed = [r for r in latest_results if not r.success]
        if not failed:
            return None

        messages = []
        for result in failed:
            count, fc = state.tracker.record_failure(
                result.tool_name, result.arguments, result
            )
            if count >= ToolCallTracker.REMOVE_THRESHOLD or fc.is_permanent:
                state.disabled_tools.add(result.tool_name)
                messages.append(
                    f"`{result.tool_name}` disabled ({fc.value}). "
                    "Use a different tool."
                )
            elif count >= ToolCallTracker.WARN_THRESHOLD:
                messages.append(
                    f"`{result.tool_name}` has failed {count} times. "
                    "Try different arguments or a different tool."
                )

        if messages:
            return Intervention(
                source=self.name,
                message="\n".join(messages),
                severity="directive",
                strategy_tag=None,
            )
        return None
```

**Note:** This guardrail is the one exception to the "pure function" rule — it calls
`state.tracker.record_failure()` which mutates the tracker. This is acceptable because
failure tracking is a bookkeeping concern, not a reasoning concern.

### Registration and Ordering

Guardrails are registered in the composition root (`agent_factory.py`):

```python
def _build_guardrails(config: AgentConfig) -> GuardrailChain:
    guardrails = [
        FailureEscalation(),          # Priority 1: disable broken tools
        NoProgressBudget(),           # Priority 2: stop after too many failures
        RepeatedStrategyDetection(),  # Priority 3: break strategy loops
        EmptyResultRecovery(),        # Priority 4: suggest alternatives
        SkillTunnelVision(),          # Priority 5: fall back to base tools
    ]
    return GuardrailChain(guardrails)
```

Higher-severity guardrails come first. `FailureEscalation` fires before
`EmptyResultRecovery` because a failing tool should be disabled before alternative
strategies are suggested.

### Adding New Guardrails (The Extension Pattern)

When a new failure pattern is discovered:

1. Create a new class implementing `Guardrail` protocol
2. Write unit tests with synthetic `TurnState` and `ToolAttempt` lists
3. Add to the registration list in `_build_guardrails()` at the appropriate priority
4. No changes to `TurnRunner`, `GuardrailChain`, or any other guardrail

**Guardrails are additive.** You never modify existing code to handle new patterns.

---

<a id="the-prompt-layer"></a>
## 5. The Prompt Layer (Context Architecture)

This is where the primary cognitive improvement lives. The loop is mechanical, guardrails
are reactive — the prompt is what makes the agent **think well in the first place**.

### System Prompt Structure

The system prompt has a strict composition order where each section has one owner and
one purpose:

```
┌─────────────────────────────────────────────────────────┐
│ 1. IDENTITY          Who you are, workspace, runtime     │
│    Owner: identity.md (static template)                  │
├─────────────────────────────────────────────────────────┤
│ 2. REASONING PROTOCOL  How to think before acting        │
│    Owner: reasoning.md (static template)                 │
├─────────────────────────────────────────────────────────┤
│ 3. TOOL GUIDE         How to choose tools                │
│    Owner: tool_guide.md (static template + dynamic list) │
├─────────────────────────────────────────────────────────┤
│ 4. STRATEGIES         Procedural memory                  │
│    Owner: Memory subsystem (dynamic per-query)           │
├─────────────────────────────────────────────────────────┤
│ 5. MEMORY             Declarative facts                  │
│    Owner: Memory subsystem (dynamic per-query)           │
├─────────────────────────────────────────────────────────┤
│ 6. BOOTSTRAP          User workspace files               │
│    Owner: Workspace (AGENTS.md, SOUL.md, etc.)           │
├─────────────────────────────────────────────────────────┤
│ 7. FEEDBACK           Past corrections                   │
│    Owner: Feedback store (dynamic)                       │
├─────────────────────────────────────────────────────────┤
│ 8. ACTIVE SKILLS      Always-on skill content            │
│    Owner: Skills loader (always=true skills)             │
├─────────────────────────────────────────────────────────┤
│ 9. SKILLS SUMMARY     Available skills for on-demand load│
│    Owner: Skills loader (dynamic list)                   │
├─────────────────────────────────────────────────────────┤
│ 10. SELF-CHECK        Verification instructions          │
│     Owner: verification.md (static, conditional)         │
├─────────────────────────────────────────────────────────┤
│ 11. SECURITY          Prompt injection boundary          │
│     Owner: security.md (static, always present)          │
└─────────────────────────────────────────────────────────┘
```

### The Composition Pattern

Each section is produced by a **context contributor** — a function that takes
workspace/config/query and returns its section or None:

```python
class ContextContributor(Protocol):
    """Produces one section of the system prompt."""

    @property
    def name(self) -> str: ...

    @property
    def order(self) -> int: ...

    async def contribute(
        self,
        *,
        workspace: Path,
        config: AgentConfig,
        query: str,
    ) -> str | None:
        """Return section content, or None to skip."""
        ...
```

The context builder composes them:

```python
class ContextBuilder:
    def __init__(self, contributors: list[ContextContributor]) -> None:
        self._contributors = sorted(contributors, key=lambda c: c.order)

    async def build_system_prompt(self, *, workspace, config, query) -> str:
        sections = []
        for contributor in self._contributors:
            section = await contributor.contribute(
                workspace=workspace, config=config, query=query
            )
            if section:
                sections.append(section)
        return "\n\n---\n\n".join(sections)
```

**Registration in factory:**

```python
def _build_context(config, memory, skills, workspace):
    return ContextBuilder([
        IdentityContributor(order=10),
        ReasoningProtocolContributor(order=20),
        ToolGuideContributor(order=30),
        ProceduralMemoryContributor(memory, order=40),
        DeclarativeMemoryContributor(memory, order=50),
        BootstrapContributor(workspace, order=60),
        FeedbackContributor(memory, order=70),
        ActiveSkillsContributor(skills, order=80),
        SkillsSummaryContributor(skills, order=90),
        SelfCheckContributor(config, order=100),
        SecurityContributor(order=110),
    ])
```

### Prompt Templates

#### reasoning.md (Core cognitive improvement)

```markdown
# Reasoning Protocol

## Before Taking Action

When you receive a task, work through these steps before calling any tool:

1. **What does the user need?**
   Find something? Read content? Create something? Modify? Summarize?

2. **What am I looking for?**
   Identify the target type:
   - A project code or identifier -> likely a FOLDER or FILE NAME
   - A topic or keyword -> likely FILE CONTENT
   - A tag, property, or date -> likely METADATA
   - A specific document -> likely a FILE PATH

3. **Which tool or command matches the target type?**
   Match by purpose, not by name similarity:
   - Find by name -> list_dir, or skill commands that list/browse
   - Search content -> grep/search commands
   - Read known file -> read_file
   - Explore structure -> list_dir first, then narrow down

4. **What is my fallback?**
   Before executing, know what you will try if this returns nothing.
   Always have a Plan B that uses a DIFFERENT approach, not the same
   tool with tweaked arguments.

5. **Source check:** Am I about to cite memory or tool results? If memory,
   have I verified it with a tool?

## When a Tool Returns Empty Results

STOP. Do not report "not found" to the user.

"No results" means your APPROACH may be wrong — not that the data
doesn't exist. The user told you it exists.

Ask yourself:
- Could the search term be a folder name instead of file content?
- Could it be a file name instead of a tag?
- Should I list the directory structure instead of searching?

Try your fallback approach before responding.

## When a Tool Returns an Error

Read the error message. Classify it:
- Wrong arguments -> fix the syntax and retry
- Command not found -> use a different command
- Permission denied -> try a different approach entirely
- Timeout -> try a simpler operation

Do not retry the same failing command unchanged.

## Fallback Principle

Your base tools (list_dir, read_file) always work. If specialized
tools or skill commands fail, fall back to the filesystem.
The filesystem is ground truth.
```

#### tool_guide.md (Purpose-driven tool selection)

```markdown
# Tool Selection Guide

Match your INTENT to the right tool. Do not select by name similarity.

| Your intent | Tool | Anti-pattern |
|---|---|---|
| Find files/folders by name or code | `list_dir` | Do NOT use search — it only searches content |
| Search text inside files | `exec` with grep/search | Do NOT use this for name-based lookups |
| Read a known file | `read_file` | Do NOT guess paths — list the directory first |
| Explore unknown structure | `list_dir` first, then `read_file` | Do NOT jump to search without knowing the structure |
| Run a skill command | `exec` | Consult the skill's instructions for which command fits your intent |
| Modify a file | `write_file` or `edit_file` | Always `read_file` first to confirm current content |

## When a Skill Is Loaded

Skills provide specialized commands. But they are ADDITIONS to your
base tools, not REPLACEMENTS. If a skill command fails or returns
nothing, your base tools still work.

Read the skill's decision guide (if present) to choose the right
command for your intent. Do not default to "search" for every
lookup task.
```

#### self_check.md (Verification instructions)

```markdown
## Before Sending Your Response

Self-check:
1. Does every factual claim trace to a tool result in this conversation?
2. If reporting "not found" — did you try at least 2 different approaches?
3. Are you stating anything as fact that you didn't verify with a tool?
4. For claims from memory sections (marked "from previous sessions") — did you
   verify them with a tool this session? If not, either verify now or attribute
   them: "Based on previous sessions..."

If any check fails, take the missing action before responding.
```

### Tool Descriptions (Registry Level)

Tool descriptions in the registry include purpose and anti-pattern guidance:

```python
ExecTool(description=(
    "Execute a shell command. Use for skill commands, system operations, "
    "or as a fallback when no specific tool fits. When running skill "
    "commands, check the skill's decision guide for which command to use."
))
ListDirTool(description=(
    "List files and folders in a directory. Use to explore structure, "
    "find items by name, or verify paths exist. Prefer this over "
    "search when looking for something by project code or folder name."
))
ReadFileTool(description=(
    "Read the full contents of a file at a known path. Use when you "
    "already know the path. If you don't know the path, use list_dir "
    "first to find it."
))
```

These descriptions create **negative selection** ("do NOT use search for name lookups")
which is critical. The model does not just know what a tool does — it knows what it
**should not** be used for.

### Skill Architecture: Decision Trees

Skills consumed by the agent should follow a structured pattern:

```markdown
# Skill Template

## Decision Guide (REQUIRED — first section)

| You want to... | Use this command | Example |
|---|---|---|
| Find by name   | `command_a`      | Finding project X |
| Search content  | `command_b`      | Finding keyword Y |
| Read a file     | `command_c`      | Reading document Z |

## When to Fall Back

If `command_b` (search) returns no results, your term might be a
folder/file name. Try `command_a` (find by name) instead.

## Command Reference (secondary — full syntax details)

[... existing reference material ...]
```

Decision logic comes first, reference material comes second. The agent reads top-down —
the first thing it sees should be HOW TO CHOOSE, not every possible command.

### Context Budget Management

When compression is needed, sections are preserved by priority:

| Priority | Section | Reason |
|----------|---------|--------|
| Never compressed | Identity, Security | Structural requirements |
| Last to compress | Reasoning Protocol, Tool Guide | Core intelligence |
| Compress early | Bootstrap files, Feedback | Supplementary context |
| Dynamic budget | Memory (declarative + procedural) | Already has its own retrieval-k budget |
| Dynamic budget | Skills | Loaded on demand, not always present |

Under token pressure, the agent loses workspace customization and feedback history
first — but never loses its reasoning protocol or tool selection guidance.

---

<a id="the-memory-interface"></a>
## 6. The Memory Interface (Three-Tier Model)

This section covers how the cognitive core **interfaces** with memory — not the memory
subsystem internals (SQLite, FTS5, vector search are stable and unchanged).

### The Three Tiers

```
┌─────────────────────────────────────────────────────────┐
│                  MEMORY INTERFACE                         │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ TIER 1: DECLARATIVE (existing)                     │  │
│  │                                                    │  │
│  │ What: Facts, entities, relationships               │  │
│  │ Examples: "Vault is at C:\Users\...\PM"           │  │
│  │           "DS10540 is a project code"              │  │
│  │                                                    │  │
│  │ Write path: MemoryExtractor (existing)             │  │
│  │ Read path: retrieve(query) (existing)              │  │
│  │ Storage: events table in SQLite (existing)         │  │
│  │ Injected as: "# Memory" section in system prompt   │  │
│  │                                                    │  │
│  │ NO CHANGES to this tier.                           │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ TIER 2: PROCEDURAL (NEW)                           │  │
│  │                                                    │  │
│  │ What: Tool strategies, what-worked/what-failed     │  │
│  │ Examples:                                          │  │
│  │   "obsidian search only matches content, not       │  │
│  │    folder names. For project codes, use            │  │
│  │    obsidian files folder=<code>"                   │  │
│  │   "When list_dir shows a target folder, use        │  │
│  │    read_file on files inside rather than searching" │  │
│  │                                                    │  │
│  │ Write path: StrategyExtractor (new)                │  │
│  │ Read path: retrieve_strategies(domain, task) (new) │  │
│  │ Storage: strategies table in same SQLite DB        │  │
│  │ Injected as: "# Strategies" section in system      │  │
│  │   prompt, BEFORE declarative memory                │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ TIER 3: WORKING (NEW)                              │  │
│  │                                                    │  │
│  │ What: Current turn state for guardrail reasoning   │  │
│  │ Examples:                                          │  │
│  │   tool_results_log: [{exec, obsidian search,       │  │
│  │     success=true, output_empty=true, iter=1}]      │  │
│  │   current_strategy: "searching content"            │  │
│  │                                                    │  │
│  │ Write path: TurnRunner updates after each tool     │  │
│  │ Read path: Guardrails inspect directly             │  │
│  │ Storage: In-memory TurnState (per-turn only)       │  │
│  │ NOT injected into prompt — used only by guardrails │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Tier 2: Procedural Memory — Design

#### Data Model

```python
@dataclass(slots=True)
class Strategy:
    """A learned tool-use pattern."""
    id: str                    # deterministic hash of domain + task_type + key content
    domain: str                # "obsidian", "github", "filesystem", "web"
    task_type: str             # "find_by_name", "search_content", "read_file", "explore"
    strategy: str              # the actual instruction
    context: str               # why this works (the explanation)
    source: str                # "guardrail_recovery" | "user_correction" | "manual"
    confidence: float          # 0.0-1.0, increases with repeated confirmation
    created_at: datetime
    last_used: datetime
    use_count: int             # times retrieved and presumably applied
    success_count: int         # times the subsequent task succeeded after retrieval
```

#### Storage (New Table in Existing SQLite)

```sql
CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    task_type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    context TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'guardrail_recovery',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    last_used TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_strategies_domain ON strategies(domain);
CREATE INDEX IF NOT EXISTS idx_strategies_task_type ON strategies(task_type);
```

This lives in the existing `MemoryDatabase` — one new table, no schema changes to
existing tables.

#### Write Path: Strategy Extraction

Strategies are extracted from two sources:

**Source 1: Guardrail recoveries (automatic)**

When a guardrail fires (has a `strategy_tag`) and the subsequent iteration succeeds,
the strategy extractor saves the pattern:

```python
class StrategyExtractor:
    """Extracts tool-use strategies from successful guardrail recoveries."""

    async def extract_from_turn(
        self,
        state: TurnState,
        guardrail_log: list[GuardrailActivation],
    ) -> list[Strategy]:
        strategies = []
        for activation in guardrail_log:
            if activation.strategy_tag is None:
                continue
            subsequent = [
                r for r in state.tool_results_log
                if r.iteration > activation.iteration
                and r.success and not r.output_empty
            ]
            if not subsequent:
                continue  # intervention didn't help — don't save

            strategy = await self._build_strategy(
                activation, subsequent, state.user_text
            )
            strategies.append(strategy)
        return strategies
```

The `_build_strategy` method uses a lightweight LLM call to summarize the recovery into
a reusable instruction.

**Source 2: User corrections (via feedback tool)**

When a user gives negative feedback with a comment like "you should have listed the
folder, not searched," the existing feedback capture path is extended to also extract
strategy-like patterns.

#### Read Path: Strategy Retrieval

Strategies are retrieved and injected as a context section before declarative memory:

```python
class ProceduralMemoryContributor(ContextContributor):
    """Injects relevant strategies into the system prompt."""

    name = "strategies"
    order = 40  # before declarative memory (50)

    async def contribute(self, *, workspace, config, query):
        strategies = await self._memory.retrieve_strategies(
            query=query,
            limit=5,
            min_confidence=0.3,
        )
        if not strategies:
            return None

        lines = ["# Relevant Strategies\n"]
        lines.append(
            "These strategies were learned from past sessions. "
            "Apply them when relevant.\n"
        )
        for s in strategies:
            lines.append(
                f"**{s.domain} / {s.task_type}** "
                f"(confidence: {s.confidence:.0%}, used {s.use_count}x)\n"
                f"{s.strategy}\n"
            )
        return "\n".join(lines)
```

#### Confidence Updates

Strategy confidence evolves based on usage:

```python
# After a turn completes successfully with strategies in context:
for strategy in strategies_used_this_turn:
    strategy.use_count += 1
    strategy.last_used = now()
    if turn_result.tools_used and turn_had_no_guardrail_activations:
        strategy.success_count += 1
        strategy.confidence = min(1.0, strategy.confidence + 0.1)
    elif turn_had_guardrail_activations:
        strategy.confidence = max(0.0, strategy.confidence - 0.05)
```

Strategies below 0.1 confidence are pruned during memory consolidation.

### The Learning Feedback Loop (Complete)

```
SESSION 1:
  Declarative memory: "Vault is at Project Management" (from prior session)
  Procedural memory: (empty — no strategies yet)

  Agent: obsidian search -> empty
  Guardrail fires: EmptyResultRecovery (strategy_tag="empty_result_strategy_switch")
  Agent: list_dir -> finds DS10540/ -> read_file -> content -> success

  Post-turn: StrategyExtractor sees guardrail recovery -> saves:
    domain=obsidian, task_type=find_by_name
    strategy="obsidian search only matches file content. For project
    codes like DS10540, use list_dir or obsidian files folder=<code>"
    confidence=0.5

SESSION 2:
  Declarative memory: "Vault is at Project Management"
  Procedural memory: [obsidian/find_by_name strategy, confidence=0.5]

  System prompt now includes:
    # Relevant Strategies
    **obsidian / find_by_name** (confidence: 50%, used 0x)
    obsidian search only matches file content. For project codes
    like DS10540, use list_dir or obsidian files folder=<code>

  Agent: reads strategy -> calls obsidian files folder=DS10540 -> success
  No guardrail fires.

  Post-turn: strategy confidence bumped to 0.6, use_count=1, success_count=1

SESSION 5:
  Strategy confidence now 0.9, used 4x, succeeded 4x.
  Agent handles obsidian folder lookups correctly every time.
  System learned permanently from one failure.
```

---

<a id="entry-layer-and-composition"></a>
## 7. Entry Layer and Composition

### Simplified MessageProcessor

```
Message In
    |
    v
+---------------------------------------------+
|            MessageProcessor                  |
|                                              |
|  1. Session: get or create                   |
|  2. Slash commands: /new, /help, etc.        |
|  3. Memory pre-turn: conflict checks         |
|  4. Context: build messages array             |
|  5. Run: TurnRunner.run(state)               |
|  6. Post-turn: save session, extract memory  |
|  7. Post-turn: extract strategies (NEW)      |
|  8. Assemble: OutboundMessage                |
|                                              |
+---------------------------------------------+
    |
    v
Message Out
```

### Composition Root (agent_factory.py)

```python
async def build_agent(config, provider, bus, ...) -> AgentLoop:

    # -- Unchanged subsystems --
    memory = build_memory_store(config, workspace)
    sessions = SessionManager(workspace)
    tool_registry = ToolRegistry()
    register_default_tools(tool_registry, workspace, config)
    tool_executor = ToolExecutor(tool_registry)
    capabilities = CapabilityRegistry(tool_registry)
    llm_caller = StreamingLLMCaller(provider)

    # -- Guardrails --
    guardrails = GuardrailChain([
        FailureEscalation(),
        NoProgressBudget(),
        RepeatedStrategyDetection(),
        EmptyResultRecovery(),
        SkillTunnelVision(),
    ])

    # -- Context contributors --
    skills_loader = SkillsLoader(workspace)
    context = ContextBuilder([
        IdentityContributor(order=10),
        ReasoningProtocolContributor(order=20),
        ToolGuideContributor(order=30),
        ProceduralMemoryContributor(memory, order=40),
        DeclarativeMemoryContributor(memory, order=50),
        BootstrapContributor(workspace, order=60),
        FeedbackContributor(memory, order=70),
        ActiveSkillsContributor(skills_loader, order=80),
        SkillsSummaryContributor(skills_loader, order=90),
        SelfCheckContributor(config, order=100),
        SecurityContributor(order=110),
    ])

    # -- Strategy extractor --
    strategy_extractor = StrategyExtractor(provider, memory)

    # -- TurnRunner --
    turn_runner = TurnRunner(
        llm_caller=llm_caller,
        tool_executor=tool_executor,
        guardrails=guardrails,
        context=context,
        config=config,
        provider=provider,
    )

    # -- Processor (no router, no role manager) --
    processor = MessageProcessor(
        turn_runner=turn_runner,
        context=context,
        sessions=sessions,
        memory_services=MemoryServices(
            store=memory, strategy_extractor=strategy_extractor
        ),
        bus=bus,
        config=config,
        workspace=workspace,
    )

    return AgentLoop(
        bus=bus,
        provider=provider,
        processor=processor,
        capabilities=capabilities,
        config=config,
    )
```

### Complete Request Flow

```
1. InboundMessage arrives on bus
        |
2. AgentLoop.run() consumes it
   +-- TraceContext setup (correlation IDs, Langfuse)
   +-- MCP connection (lazy, first-time only)
        |
3. MessageProcessor._process_message()
   +-- Session lookup
   +-- Slash command handling (/new, /help)
   +-- Memory pre-turn checks (conflicts, corrections)
   +-- Build messages array (system prompt + history + current)
        |
4. TurnRunner.run(state)
   +-- Loop: LLM call -> tool execution -> guardrail check
   +-- Working memory updated each iteration
   +-- Guardrail interventions injected when patterns detected
   +-- Loop ends when: text response | max iterations | wall time
   +-- Optional: structured self-check
   +-- Returns: TurnResult
        |
5. MessageProcessor post-turn
   +-- Save session (messages + timestamps)
   +-- Micro-extraction (declarative memory — existing)
   +-- Strategy extraction (procedural memory — NEW)
   +-- Assemble OutboundMessage
        |
6. AgentLoop sends to bus
   +-- Langfuse flush
        |
7. Channel delivers response
```

### Dependency Graph

```
AgentLoop
  +-- MessageProcessor
        +-- TurnRunner
        |     +-- StreamingLLMCaller -> LLMProvider
        |     +-- ToolExecutor -> ToolRegistry -> Tool instances
        |     +-- GuardrailChain -> [Guardrail, Guardrail, ...]
        |     +-- ContextBuilder -> [ContextContributor, ...]
        +-- SessionManager
        +-- MemoryServices
        |     +-- MemoryStore (existing)
        |     +-- StrategyExtractor (new)
        +-- Bus (for outbound messages)
```

Every arrow points **downward** — no circular dependencies, no upward references.

### Constructor Parameter Discipline

| Component | Params | Status |
|-----------|--------|--------|
| TurnRunner | 6 (llm_caller, tool_executor, guardrails, context, config, provider) | Under limit (7) |
| MessageProcessor | 7 (turn_runner, context, sessions, memory_services, bus, config, workspace) | At limit |

Memory + StrategyExtractor grouped as `MemoryServices` dataclass:

```python
@dataclass(slots=True, frozen=True)
class MemoryServices:
    store: MemoryStore
    strategy_extractor: StrategyExtractor
```

---

<a id="structural-patterns"></a>
## 8. Structural Patterns for Long-Term Stability

These are the blueprint rules that keep the codebase stable across hundreds of
LLM-driven sessions.

### Pattern 6: The Stable Core / Volatile Edge

```
STABLE (rarely changes)          VOLATILE (changes often)
---------------------           -------------------------
TurnRunner loop logic           Prompt templates (.md files)
GuardrailChain mechanics        Individual guardrail classes
ContextBuilder composer         Context contributors
ToolExecutor batch logic        Tool descriptions
StrategyExtractor pipeline      Strategy extraction prompt
MessageProcessor pipeline       Skill content (SKILL.md files)
```

**The rule:** When a behavioral change is needed (agent makes wrong decisions, picks
wrong tools, fails at a task type), the fix must be in the volatile edge — a prompt,
a guardrail, a tool description, a skill. If the fix requires changing the stable core,
the design is wrong.

**Why this matters for LLM development:** Every session starts with no memory of the
previous session's code changes. If a behavioral fix requires understanding and modifying
the loop, each new session must re-read and re-understand the loop. If the fix is a
prompt change or a new guardrail class, the session can make the change without
understanding the loop internals.

**Enforcement test:** For any proposed code change, ask: "Could this be a
prompt/guardrail/description change instead?" If yes, it must be.

### Pattern 7: One File, One Reason to Change

Every file must have exactly one reason to change. If you can describe two independent
scenarios that would require editing the same file, it has two responsibilities and
should be split.

| File | One reason to change |
|------|---------------------|
| `turn_runner.py` | The mechanics of the tool-use loop change |
| `turn_guardrails.py` | A new guardrail is added or existing detection logic changes |
| `context/context.py` | The composition mechanics change |
| `context/contributors/reasoning.py` | The reasoning protocol content changes |
| `context/contributors/procedural_memory.py` | How strategies are formatted for the prompt changes |
| `memory/strategy.py` | The strategy data model or storage schema changes |
| `memory/strategy_extractor.py` | How strategies are extracted from turns changes |
| `message_processor.py` | The pipeline steps or their ordering changes |

### Pattern 8: Protocols at Boundaries, Concrete Inside

Every component boundary uses a Protocol (structural typing). Inside a component, use
concrete types freely.

```python
# BOUNDARY: TurnRunner accepts any guardrail chain
class GuardrailChainProtocol(Protocol):
    def check(self, state: TurnState, latest: list[ToolAttempt]) -> Intervention | None: ...

# BOUNDARY: ContextBuilder accepts any contributor
class ContextContributor(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def order(self) -> int: ...
    async def contribute(self, **kwargs) -> str | None: ...

# INSIDE: Guardrail implementations use concrete types freely
class EmptyResultRecovery:
    def check(self, state: TurnState, latest: list[ToolAttempt]) -> Intervention | None:
        # concrete logic, no abstractions needed
```

**Why:** Protocols break import cycles and enable testing with fakes. But excessive
abstraction inside components adds indirection without value.

**Enforcement:** `scripts/check_imports.py` validates that no component imports concrete
classes from another component for instantiation. Only the factory does construction.

### Pattern 9: Three Extension Points

ALL behavioral changes go through one of these:

```
+-----------------------------------------------------+
|              EXTENSION POINTS                        |
|                                                      |
|  1. GUARDRAILS (reactive behavior)                   |
|     Add: new class implementing Guardrail protocol   |
|     Register: in _build_guardrails() in factory      |
|     Test: unit test with synthetic TurnState          |
|                                                      |
|  2. CONTEXT CONTRIBUTORS (proactive context)         |
|     Add: new class implementing ContextContributor   |
|     Register: in _build_context() in factory         |
|     Test: unit test returns expected string           |
|                                                      |
|  3. PROMPT TEMPLATES (reasoning instructions)        |
|     Add: new .md file in templates/prompts/          |
|     Reference: from a ContextContributor             |
|     Test: integration test verifying prompt assembly  |
|                                                      |
|  Everything else is STABLE CORE — do not extend.     |
+-----------------------------------------------------+
```

**The rule:** If a session wants to change agent behavior, it must use one of these
three extension points. If none of them fit, the session must propose a new extension
point (which is a design change requiring review), not modify the stable core.

### Pattern 10: Growth Limits With Automatic Triggers

| Metric | Limit | What happens when exceeded |
|--------|-------|--------------------------|
| File LOC | 300 (advisory), 500 (hard) | At 300: review if file has two responsibilities. At 500: split before adding code. |
| Package files | 15 | Extract a subpackage or new top-level package. |
| `__init__.py` exports | 12 | Package API too broad — extract. |
| Constructor params | 7 | Group related params into a dataclass. |
| Guardrail count | **10** | If you need more than 10 guardrails, the prompt architecture is failing. Fix the prompts. |
| Context contributors | 15 | If you need more than 15 sections, consolidate or make dynamic. |
| Prompt template LOC | 100 per template | Split by concern. |

**The guardrail count limit is critical.** Guardrails are the designated extension
point — which means they are where complexity will accumulate. A limit of 10 prevents
the guardrail layer from becoming the new ReflectPhase.

### Pattern 11: Observable by Default

Every component emits structured data for Langfuse without explicit instrumentation:

```
TurnRunner:
  - Span: "turn" (root, per-turn)
  - Metadata: iterations, tools_used, tokens, guardrails_fired

GuardrailChain:
  - Event: "guardrail_activated" with source, severity, strategy_tag
  - Event: "guardrail_skipped" (all returned None)

ContextBuilder:
  - Metadata: sections_included, total_tokens, compression_applied

StrategyExtractor:
  - Event: "strategy_extracted" with domain, task_type, source
  - Event: "strategy_confidence_updated" with delta
```

**Enforcement:** The `Guardrail` protocol returns an `Intervention` with a `source`
field. The `ContextContributor` protocol has a `name` property. These are required by
the protocol — you cannot implement the protocol without being observable.

### Pattern 12: No Implicit Coupling

Components communicate through explicit interfaces — never through shared mutable state,
global variables, module-level singletons, or side-channel mutation.

**Allowed:**
```python
# Explicit parameter passing
result = turn_runner.run(state)
strategies = extractor.extract_from_turn(state, guardrail_log)

# Explicit dependency injection
processor = MessageProcessor(turn_runner=runner, memory=memory)

# Immutable data objects crossing boundaries
@dataclass(frozen=True, slots=True)
class TurnResult:
    content: str
    tools_used: list[str]
```

**Forbidden:**
```python
# Shared mutable state
self._dispatcher.active_messages = state.messages

# Post-construction wiring
loop._role_manager = TurnRoleManager(loop)

# Reaching into another component's internals
self._dispatcher.delegation_count = 0
```

### Pattern 13: Prompt Changes Are Code Changes

Prompt templates (`.md` files) must be treated with the same discipline as code:

1. **Reviewed:** Every prompt change must pass `make prompt-check`
2. **Tested:** Integration tests verify prompt assembly
3. **Versioned:** Prompt templates are checked into git and appear in diffs
4. **Sized:** No prompt template exceeds 100 lines
5. **Owned:** Each template is referenced by exactly one context contributor

### Pattern 14: Design for Deletion

Every component should be removable without cascading changes:

- Remove a guardrail: delete the class, remove from registration list. No other changes.
- Remove a context contributor: delete the class, remove from registration list. No other changes.
- Remove a prompt template: delete the file, update the contributor. No other changes.
- Remove procedural memory: delete `strategy.py`, `strategy_extractor.py`,
  `ProceduralMemoryContributor`. No changes to TurnRunner, GuardrailChain, or other
  contributors.

**Enforcement test:** For any new component, ask: "Can I delete this in one session
without modifying the stable core?" If not, the boundaries are wrong.

### Pattern 15: Test by Contract, Not by Implementation

Tests verify WHAT the system does, not HOW it does it internally.

**Contract tests (the system's behavioral guarantees):**

```python
# "Empty search results trigger a strategy change intervention"
def test_empty_result_triggers_recovery():
    state = make_state(tool_results_log=[
        ToolAttempt("exec", {"command": "obsidian search query=X"},
                    success=True, output_empty=True, iteration=1)
    ])
    result = EmptyResultRecovery().check(state, state.tool_results_log)
    assert result is not None
    assert "alternative approach" in result.message

# "The loop terminates within max_iterations"
async def test_loop_terminates():
    runner = make_runner(max_iterations=5)
    state = make_state(...)
    result = await runner.run(state)
    assert state.iteration <= 5

# "Strategies are injected before declarative memory"
async def test_strategy_section_ordering():
    prompt = await context.build_system_prompt(query="find DS10540")
    strategy_pos = prompt.index("# Relevant Strategies")
    memory_pos = prompt.index("# Memory")
    assert strategy_pos < memory_pos
```

**What NOT to test:**

```python
# DON'T: test that the loop calls methods in a specific order
# DON'T: test that a specific system message is at index N in messages
# DON'T: test internal state of TurnRunner between iterations
# DON'T: test that a guardrail is checked before another (that's config)
```

---

<a id="extension-points"></a>
## 9. Extension Points

### Adding a New Guardrail

1. Create a new class implementing `Guardrail` protocol
2. Write unit tests with synthetic `TurnState` and `ToolAttempt` lists
3. Add to the registration list in `_build_guardrails()` at the appropriate priority
4. No changes to `TurnRunner`, `GuardrailChain`, or any other guardrail

### Adding a New Context Section

1. Create a new class implementing `ContextContributor` protocol
2. Choose an `order` value that places it correctly in the prompt
3. Register in `_build_context()` in the factory
4. No changes to `ContextBuilder` or other contributors

### Adding a New Prompt Template

1. Create a `.md` file in `templates/prompts/`
2. Create or update a `ContextContributor` to load and return it
3. No changes to the builder or other templates

### Modifying Agent Behavior

**Decision tree:**
1. Is the issue a bad tool choice? -> Update tool descriptions or tool_guide.md
2. Is the issue a missing reasoning step? -> Update reasoning.md
3. Is the issue a repeated failure pattern? -> Add a guardrail
4. Is the issue a known strategy the agent forgets? -> Add to procedural memory
5. Is the issue a skill-specific decision? -> Update the skill's decision tree
6. None of the above? -> Propose a new extension point (design review required)

---

<a id="testing-strategy"></a>
## 10. Testing Strategy

### Contract Tests

```
tests/contract/test_loop_contracts.py:
  test_loop_terminates_within_max_iterations
  test_loop_terminates_within_wall_time
  test_empty_result_triggers_intervention
  test_repeated_strategy_triggers_intervention
  test_tool_failure_disables_tool
  test_guardrail_intervention_is_system_message
  test_self_check_uses_same_context
  test_working_memory_tracks_all_attempts

tests/contract/test_context_contracts.py:
  test_reasoning_protocol_always_present
  test_strategies_before_memory
  test_contributor_order_respected
  test_security_advisory_always_last
  test_missing_contributor_skipped

tests/contract/test_strategy_contracts.py:
  test_guardrail_recovery_produces_strategy
  test_failed_recovery_produces_no_strategy
  test_strategy_confidence_increases_on_success
  test_low_confidence_strategies_pruned
```

### Integration Tests

```
tests/integration/test_cognitive_loop.py:
  test_obsidian_folder_lookup — DS10540 case end-to-end
  test_successful_path_no_guardrails — clean path
  test_strategy_loaded_prevents_failure — pre-seeded strategy
```

### Guardrail Unit Tests

```
tests/test_guardrails.py:
  TestEmptyResultRecovery: 5 cases (no fire, first empty, second empty, error, tag)
  TestRepeatedStrategyDetection: 4 cases (first, different args, third similar, whitespace)
  TestSkillTunnelVision: 4 cases (early, all exec no data, exec with data, mixed)
  TestNoProgressBudget: 3 cases (early, no data after 4, some data)
  TestGuardrailChain: 3 cases (first wins, all pass, priority order)
```

### Observability as Testing

Post-deployment Langfuse checks:
- Guardrail activation rate (expected: decreasing over time)
- Strategy extraction rate (expected: positive early, decreasing)
- Average iterations per turn (expected: decreasing)
- Cost per turn (expected: decreasing)

---

<a id="observability"></a>
## 11. Observability

Every guardrail activation is a traceable event:

```python
# In TurnRunner, after guardrail check:
intervention = self._guardrails.check(state, latest_results)
if intervention:
    update_current_span(metadata={
        "guardrail_fired": intervention.source,
        "guardrail_severity": intervention.severity,
        "guardrail_strategy_tag": intervention.strategy_tag,
    })
    state.messages.append({"role": "system", "content": intervention.message})
```

This feeds into Langfuse so you can query: "Which guardrails fire most often? Which lead
to successful recovery? Which never fire (and can be removed)?"

---

<a id="appendix-a"></a>
## Appendix A: Approach Selection (3 Approaches Evaluated)

### Approach 1: Minimal Loop + Rich Prompt ("Claude Code Pattern")

Simple tool loop (~200 LOC). All intelligence in prompts. No guardrails.

**Pros:** Simplest code. Industry-proven. Most maintainable.
**Cons:** Weak models ignore prompt instructions. No structural enforcement.
**Verdict:** Rejected — model-agnostic requirement means we cannot rely on prompt-only.

### Approach 2: Explicit State Machine ("LangGraph Pattern")

Explicit states: UNDERSTAND -> STRATEGIZE -> ACT -> EVALUATE. Code-enforced transitions.

**Pros:** Guarantees reasoning steps. Predictable. Easy to test per state.
**Cons:** Over-engineers happy path. Rigid — adding states requires refactoring.
**Verdict:** Rejected — becomes the new "PAOR problem" as features accumulate on states.

### Approach 3: Adaptive Loop with Guardrail Escalation ("Layered Pattern")

Simple core loop + modular guardrail checks after each iteration. Smart models flow
through without overhead. Weak models get progressively stronger interventions.

**Pros:** Simple happy path. Guardrails are modular plugins. Easy to add/remove.
**Cons:** Guardrails are reactive (fire after failure, not before).
**Verdict:** Chosen — best fit for model-agnostic + layered enforcement decisions.

---

<a id="appendix-b"></a>
## Appendix B: How the Three Layers Work Together

The guardrails are the **safety net**, not the intelligence. The actual cognitive
improvement comes from three layers:

### Layer 1: Prompt Architecture (Proactive — Before the model acts)

The system prompt is restructured from "here's who you are and your tools" into a
**reasoning framework**. The Reasoning Protocol teaches the model to decompose tasks
before acting. The Tool Guide creates selection heuristics. These cost zero extra LLM
calls — they are prompt engineering that forces the model to reason.

For the DS10540 case: the model reads "What am I looking for? A project code -> likely
a folder name" -> selects `list_dir` instead of `obsidian search`.

### Layer 2: Context Quality (Proactive — What the model sees)

Better tool descriptions with purpose and anti-patterns. Skill decision trees instead
of reference manuals. Procedural memory strategies from past sessions. The model makes
better decisions because it has better information to reason from.

### Layer 3: Guardrails (Reactive — When Layers 1 and 2 are not enough)

Fire only when the model did not follow prompt instructions or when the instructions
were not sufficient. Detect failure patterns and inject correction prompts. Smart models
never trigger guardrails. Weak models get caught by them.

### The Feedback Loop

Guardrails also feed back into Layer 2: when a guardrail fires and leads to successful
recovery, the strategy extractor saves that pattern to procedural memory. Next session,
Layer 2 handles it proactively — the guardrail never fires again.

```
Smart model (follows prompt):
  Prompt reasoning -> correct tool -> success -> no guardrail fires

Weak model (ignores prompt):
  Prompt ignored -> wrong tool -> empty -> GUARDRAIL fires ->
  correct tool -> success -> strategy saved

Next session (any model):
  Strategy in context -> correct tool -> success -> guardrail never fires
```

The system **gets smarter over time** because guardrail recoveries become procedural
memories which become proactive context.
