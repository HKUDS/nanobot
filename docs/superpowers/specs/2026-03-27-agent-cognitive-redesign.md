# Agent Cognitive Core Redesign — Architectural Blueprint

> Spec status: **Approved**
> Date: 2026-03-27
> Scope: Agent cognitive core + interfaces to memory, tools, skills, verification
> Supersedes: ADR-002 (Agent Loop Ownership), PAOR loop design, AnswerVerifier design,
> multi-role routing architecture

## Motivation

Exhaustive analysis of 13 Langfuse traces across 5 sessions revealed a fundamental
architectural problem: the agent has sophisticated orchestration (routing, classification,
delegation, verification, plan enforcement) but cannot find a folder in Obsidian.

The user asked "Summarize details in Obsidian for DS10540" five times. The DS10540 folder
exists. The agent used `obsidian search` (content search) every time instead of
`obsidian files folder=DS10540` (structural lookup). It never tried an alternative approach,
never fell back to base tools (`list_dir`), and repeated the same failing strategy across
all sessions. Total cost: $0.156 for a task that needs two commands ($0.001).

Root cause: the architecture invested in **orchestration complexity** (what happens between
LLM calls) instead of **reasoning quality** (what happens inside LLM calls). The current
PAOR loop (Plan-Act-Observe-Reflect) is 497 lines of code where a 168-line tool loop
(`tool_loop.py`, used by subagents) would produce better results with better prompts.

Industry analysis confirms this: Claude Code, Cursor, Devin, and the OpenAI Agents SDK
all use simple tool-use loops (~100-200 lines). Intelligence comes from prompt quality,
tool descriptions, and model reasoning — not orchestration code.

## Design Decisions

These decisions were made during collaborative design review on 2026-03-27:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Model assumptions | **Model-agnostic** | Architecture must work with any model including weak ones (gpt-4o-mini). Reasoning quality enforced through structure, not model native ability. |
| Agent multiplicity | **Single agent with optional spawning** | One primary agent, no roles/routing. Can spawn lightweight sub-agents for task parallelism via existing `tool_loop.py`. |
| Verification | **Configurable** | Prompt-only self-check by default. Optional structured self-check (extra LLM call, same context) via config flag. |
| Reasoning enforcement | **Layered** | Prompt instructions as baseline + code-enforced guardrails on failure patterns. Smart models never hit guardrails; weak models get structural help. |

---

## Architecture Overview

### Four Layers

```
ENTRY LAYER          MessageProcessor (simplified)
                     Receives messages, manages sessions, delivers responses
        |
COGNITIVE LOOP       TurnRunner (new, replaces TurnOrchestrator)
                     Simple tool-use loop with guardrail checkpoints
        |
GUARDRAIL LAYER      GuardrailChain (new)
                     Modular, independent checks that fire on failure patterns
        |
PROMPT LAYER         ContextBuilder (extended) + ContextContributors (new)
                     System prompt architecture + tool descriptions + skills
```

Consumed by all layers: Memory (3-tier), Tools (registry), Providers (LLM), Observability (Langfuse).

### Three-Layer Cognitive Model

The agent's intelligence comes from three layers working together:

**Layer 1 — Prompt Architecture (proactive).** Structured reasoning protocol in the system
prompt teaches the model HOW to approach tasks before acting. This is where most improvement
lives. Costs zero extra LLM calls.

**Layer 2 — Context Quality (proactive).** Purpose-typed tool descriptions, skill decision
trees, procedural memory from past sessions. Better information in = better decisions out.

**Layer 3 — Guardrails (reactive).** Code-enforced interventions when Layers 1 and 2 fail.
Detect failure patterns (empty results, repeated strategies, skill tunnel vision) and inject
correction prompts. Guardrail recoveries feed back into procedural memory — the system
learns permanently from each failure.

---

## Governing Patterns

These patterns keep the codebase stable as it evolves. Every future change must satisfy them.

### Pattern 1: The Loop Is Dumb, The Prompt Is Smart

The cognitive loop is a mechanical executor — it calls the LLM, runs tools, and checks
guardrails. It has no domain knowledge, no task understanding, no strategy. All intelligence
lives in what the LLM sees: the system prompt, tool descriptions, skill content, and
memory context.

When the agent makes a bad decision, the fix is a prompt/guardrail/description change,
not a loop change.

**Enforcement:** The loop must never contain:
- Task-type detection (no `_needs_planning()` keyword heuristics)
- Domain-specific logic (no "if obsidian then..." branching)
- Model-specific behavior (no "if gpt-4o then..." branching)
- Strategy selection (no "choose between search and browse")

### Pattern 2: Guardrails Are Plugins, Not States

Each guardrail is an independent module that receives iteration context and returns either
`None` (no intervention) or an `Intervention` (a system message to inject). Guardrails are
composed into a chain. Adding or removing a guardrail never changes the loop.

**Enforcement:** Guardrails must:
- Be pure functions (receive context, return intervention or None)
- Have no dependencies on each other
- Be independently testable with synthetic state
- Be registered declaratively (a list in factory, not if/elif chains)

### Pattern 3: Context Is Layered and Composable

The system prompt is assembled from independent contributors. Each contributor owns one
section and knows nothing about the others. The context builder composes them in order.

**Enforcement:** Each context layer is a function:
`(workspace, config, query) -> str | None`. Adding a new layer means adding a contributor
class and registering it — the builder never changes.

### Pattern 4: Memory Has Three Tiers

| Tier | Scope | Content | Storage |
|------|-------|---------|---------|
| Declarative | Cross-session | Facts, entities, relationships | SQLite (existing) |
| Procedural | Cross-session | Tool strategies, what-worked/what-failed | SQLite (new table) |
| Working | Per-turn | Current goals, attempted approaches, evidence | In-memory TurnState |

### Pattern 5: Feedback Loops Close the Learning Gap

Guardrail fires -> recovery succeeds -> strategy extractor saves pattern to procedural
memory -> next session loads strategy into context -> guardrail never fires again.

Without this loop, guardrails are band-aids. With it, every failure makes the system
permanently smarter.

---

## Structural Stability Patterns

These are the rules that keep the codebase stable across hundreds of LLM-driven sessions.

### Pattern 6: Stable Core / Volatile Edge

```
STABLE (rarely changes)          VOLATILE (changes often)
---------------------------      ---------------------------
TurnRunner loop logic            Prompt templates (.md files)
GuardrailChain mechanics         Individual guardrail classes
ContextBuilder composer          Context contributors
ToolExecutor batch logic         Tool descriptions
StrategyExtractor pipeline       Strategy extraction prompt
MessageProcessor pipeline        Skill content (SKILL.md files)
```

**Rule:** When a behavioral change is needed, the fix must be in the volatile edge.
If the fix requires changing the stable core, the design is wrong.

### Pattern 7: One File, One Reason to Change

Every file has exactly one reason to change. Two independent scenarios requiring edits to
the same file means it has two responsibilities and must be split.

### Pattern 8: Protocols at Boundaries, Concrete Inside

Component boundaries use Protocol (structural typing). Inside components, use concrete
types freely. This breaks import cycles and enables testing without excessive abstraction.

### Pattern 9: Three Extension Points

ALL behavioral changes go through one of these:

1. **Guardrails** (reactive behavior) — new class implementing Guardrail protocol
2. **Context Contributors** (proactive context) — new class implementing ContextContributor
3. **Prompt Templates** (reasoning instructions) — new .md file in templates/prompts/

Everything else is stable core. If none of these fit, propose a new extension point
(design change), don't modify the core directly.

### Pattern 10: Growth Limits

| Metric | Limit | Action |
|--------|-------|--------|
| File LOC | 300 advisory, 500 hard | Split before adding code |
| Package files | 15 | Extract subpackage first |
| `__init__.py` exports | 12 | Package API too broad — extract |
| Constructor params | 7 | Group into dataclass |
| Guardrail count | 10 | Fix prompts, don't add more guardrails |
| Context contributors | 15 | Consolidate or make dynamic |
| Prompt template LOC | 100 per template | Split by concern |

### Pattern 11: Observable by Default

Every component emits structured data for Langfuse. The Guardrail protocol returns
Intervention with a `source` field. The ContextContributor protocol has a `name` property.
Observability is part of the interface, not an afterthought.

### Pattern 12: No Implicit Coupling

Components communicate through explicit interfaces — never shared mutable state, global
variables, module-level singletons, or side-channel mutation. All dependencies visible
at the call site.

### Pattern 13: Prompt Changes Are Code Changes

Prompt templates are reviewed, tested, versioned, sized (max 100 lines), and owned by
exactly one contributor. An untested prompt change can break behavior as badly as a code bug.

### Pattern 14: Design for Deletion

Every component must be removable without cascading changes. Remove a guardrail: delete
class, remove from list. Remove a contributor: delete class, remove from list. Remove
procedural memory: delete 3 files, no changes to TurnRunner or GuardrailChain.

### Pattern 15: Test by Contract, Not Implementation

Tests verify WHAT the system does, not HOW it does it internally. Contract tests survive
refactoring because they test external behavior. Implementation tests break on every change.

---

## Component Designs

### 1. Cognitive Loop (TurnRunner)

Replaces `TurnOrchestrator` (497 LOC) with a simple tool-use loop (~200 LOC).

```
async def run(state: TurnState) -> TurnResult:

    while state.iteration < max_iterations:
        state.iteration += 1

        # Resource guardrails
        if wall_time_exceeded: break
        if context_over_budget: compress(messages)

        # LLM call
        response = call_llm(messages, tools)
        if llm_error: handle_error(); continue

        # Tool path
        if response.has_tool_calls:
            results = execute_batch(response.tool_calls)
            add_results_to_messages()
            track_failures()
            update_working_memory(results)

            # Guardrail checkpoint
            intervention = guardrail_chain.check(state)
            if intervention: inject(intervention)
            continue

        # Response path
        final_content = response.content
        break

    # Optional structured self-check
    if verification_enabled:
        final_content = self_check(final_content, messages)

    return TurnResult(content, tools_used, messages, tokens)
```

**What's removed from the current orchestrator:**
- Plan enforcement (`_needs_planning()` keyword heuristic)
- ReflectPhase class (delegation nudges)
- DelegationAdvisor integration
- Role-switching resolution (`active_*` fields)
- Classification result tracking
- ActPhase as separate class (inlined — 15 lines of tool execution)

**Working memory (TurnState):**

```python
@dataclass(slots=True)
class TurnState:
    messages: list[dict]
    user_text: str
    iteration: int = 0
    tools_used: list[str]
    disabled_tools: set[str]
    tracker: ToolCallTracker
    tool_results_log: list[ToolAttempt]    # NEW: what was tried + outcome
    tools_def_cache: list[dict]
    tools_def_snapshot: frozenset[str]
    tokens_prompt: int = 0
    tokens_completion: int = 0
    llm_calls: int = 0

@dataclass(slots=True, frozen=True)
class ToolAttempt:
    tool_name: str
    arguments: dict
    success: bool
    output_empty: bool       # success but no data
    output_snippet: str      # first 200 chars
    iteration: int
```

**Configurable self-check:**
- Default (prompt-only): verification rules in system prompt, zero extra calls
- Structured (config: `verification.mode = "structured"`): one extra LLM call with same
  context, model reviews and corrects its own response

**Target: ~200 LOC** in `turn_runner.py`

### 2. Guardrail Layer

```python
@dataclass(slots=True, frozen=True)
class Intervention:
    source: str           # guardrail name (observability)
    message: str          # system message to inject
    severity: str         # "hint" | "directive" | "override"
    strategy_tag: str | None = None  # for procedural memory extraction

class Guardrail(Protocol):
    @property
    def name(self) -> str: ...
    def check(self, state: TurnState, latest: list[ToolAttempt]) -> Intervention | None: ...

class GuardrailChain:
    """Runs guardrails in priority order. First intervention wins."""
    def __init__(self, guardrails: list[Guardrail]) -> None: ...
    def check(self, state, latest) -> Intervention | None: ...
```

**Initial guardrails (priority order):**

| # | Guardrail | Fires when | Severity |
|---|-----------|-----------|----------|
| 1 | FailureEscalation | Tool fails N times | directive |
| 2 | NoProgressBudget | 4+ iterations with no useful data | override |
| 3 | RepeatedStrategyDetection | Same tool+args 3 times | override |
| 4 | EmptyResultRecovery | Tool succeeds but returns no data | hint/directive |
| 5 | SkillTunnelVision | All exec calls, no data, iteration >= 3 | directive |

**First-intervention-wins:** Only one correction per iteration. Stacking confuses the model.

**Extension pattern:** New failure pattern? Create a class, write tests, add to registration
list. No changes to TurnRunner or GuardrailChain.

**Target: ~150 LOC** in `turn_guardrails.py`

### 3. Prompt Layer (Context Architecture)

**System prompt structure (11 sections, strict order):**

| # | Section | Owner | Purpose |
|---|---------|-------|---------|
| 1 | Identity | identity.md template | Who you are, workspace, runtime |
| 2 | Reasoning Protocol | reasoning.md template (NEW) | How to think before acting |
| 3 | Tool Guide | tool_guide.md template (NEW) | How to choose tools by intent |
| 4 | Strategies | ProceduralMemoryContributor (NEW) | Learned tool strategies |
| 5 | Memory | DeclarativeMemoryContributor | Facts and entities |
| 6 | Bootstrap | BootstrapContributor | AGENTS.md, SOUL.md, etc. |
| 7 | Feedback | FeedbackContributor | Past user corrections |
| 8 | Active Skills | ActiveSkillsContributor | always=true skill content |
| 9 | Skills Summary | SkillsSummaryContributor | Available skills for on-demand load |
| 10 | Self-Check | SelfCheckContributor (conditional) | Verification instructions |
| 11 | Security | SecurityContributor | Prompt injection boundary |

**Composition pattern:**

```python
class ContextContributor(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def order(self) -> int: ...
    async def contribute(self, *, workspace, config, query) -> str | None: ...

class ContextBuilder:
    def __init__(self, contributors: list[ContextContributor]) -> None: ...
    async def build_system_prompt(self, **kwargs) -> str:
        # calls each contributor in order, joins non-None results
```

**reasoning.md (new — core cognitive improvement):**

```markdown
## Before Taking Action

Work through these steps before calling any tool:
1. What does the user need? (find / read / create / modify / summarize)
2. What am I looking for? Identify target type:
   - Project code or identifier -> likely a FOLDER or FILE NAME
   - Topic or keyword -> likely FILE CONTENT
   - Tag, property, date -> likely METADATA
3. Which tool matches the target type? Match by purpose, not name similarity.
4. What is my fallback? Know your Plan B before executing Plan A.

## When a Tool Returns Empty Results

STOP. "No results" means your APPROACH may be wrong, not that the data
doesn't exist. Try your fallback approach before responding.

## Fallback Principle

Your base tools (list_dir, read_file) always work. If specialized tools
fail, fall back to the filesystem. The filesystem is ground truth.
```

**tool_guide.md (new — purpose-driven selection):**

```markdown
| Your intent | Tool | Anti-pattern |
|---|---|---|
| Find files/folders by name | list_dir | Do NOT use search for name lookups |
| Search text inside files | exec with grep/search | Do NOT use for name-based lookups |
| Read a known file | read_file | Do NOT guess paths — list first |
| Explore unknown structure | list_dir first | Do NOT search without knowing structure |
| Run a skill command | exec | Check skill's decision guide first |
```

**Tool descriptions (updated at registration):**

```python
ExecTool(description=(
    "Execute a shell command. Use for skill commands, system operations, "
    "or as a fallback when no specific tool fits."
))
ListDirTool(description=(
    "List files and folders in a directory. Use to explore structure, "
    "find items by name, or verify paths. Prefer over search when "
    "looking for something by project code or folder name."
))
ReadFileTool(description=(
    "Read the full contents of a file at a known path. If you don't "
    "know the path, use list_dir first to find it."
))
```

**Skill content pattern (decision trees, not reference manuals):**

```markdown
## Decision Guide (first section in every skill)
| You want to... | Use this command | Example |
|---|---|---|
| Find by name | command_a | Finding project X |
| Search content | command_b | Finding keyword Y |

## When to Fall Back
If search returns nothing, the term might be a folder name.
Try the find-by-name command instead.

## Command Reference (secondary)
[full syntax details...]
```

**Compression priority (under token pressure):**
- Never compressed: Identity, Security
- Last to compress: Reasoning Protocol, Tool Guide
- Compress early: Bootstrap, Feedback
- Dynamic budget: Memory, Skills

**Target: ~200 LOC** in `context/context.py` + ~280 LOC across contributor modules

### 4. Memory Interface (Three Tiers)

**Tier 1 — Declarative (existing, no changes):**
Facts, entities, relationships. Write via MemoryExtractor. Read via retrieve(query).
Storage in SQLite events table. Injected as "# Memory" section.

**Tier 2 — Procedural (new):**

```python
@dataclass(slots=True)
class Strategy:
    id: str               # hash of domain + task_type + key content
    domain: str           # "obsidian", "github", "filesystem", "web"
    task_type: str        # "find_by_name", "search_content", "explore"
    strategy: str         # the reusable instruction
    context: str          # why this works
    source: str           # "guardrail_recovery" | "user_correction"
    confidence: float     # 0.0-1.0
    created_at: datetime
    last_used: datetime
    use_count: int
    success_count: int
```

Storage: `strategies` table in existing SQLite DB.

Write path (two sources):
1. **Guardrail recoveries (automatic):** When a guardrail fires (with strategy_tag)
   and subsequent iteration succeeds, StrategyExtractor saves the pattern via lightweight
   LLM call.
2. **User corrections (via feedback tool):** Negative feedback with strategy-like
   comments triggers extraction.

Read path: retrieve by domain + task_type, inject as "# Relevant Strategies" section
before declarative memory.

Confidence evolution:
- Success without guardrail activation: +0.1
- Guardrail activation despite strategy in context: -0.05
- Below 0.1: pruned during consolidation

**Tier 3 — Working (per-turn, not persisted):**
`tool_results_log` on TurnState. Updated by TurnRunner after each tool execution.
Inspected by guardrails. Discarded when turn ends.

**The feedback loop:**

```
Session 1: Agent fails -> guardrail fires -> recovery succeeds
           -> strategy extracted (confidence 0.5)
Session 2: Strategy in context -> agent succeeds without guardrail
           -> confidence bumped to 0.6
Session 5: Confidence 0.9 -> agent handles this task type permanently
```

**Target: ~100 LOC** `memory/strategy.py` + **~120 LOC** `memory/strategy_extractor.py`

### 5. Entry Layer & Composition

**MessageProcessor (simplified to ~400 LOC, down from 586):**

Pipeline steps:
1. Session: get or create
2. Slash commands: /new, /help
3. Memory pre-turn: conflict checks
4. Context: build messages array
5. Run: TurnRunner.run(state)
6. Post-turn: save session, extract declarative memory
7. Post-turn: extract strategies (NEW)
8. Assemble: OutboundMessage

Removed: routing pipeline, role manager wiring, active settings, classification tracking,
recovery attempt (moved to TurnRunner self-check).

**Composition root (agent_factory.py, ~350 LOC, down from 493):**

Constructs: memory, sessions, tools, guardrails, context contributors, context builder,
strategy extractor, turn runner, processor, loop.

Does not construct: coordinator, router, role manager, delegation advisor, answer verifier.

**Constructor discipline:** All components under 7 params. Memory + StrategyExtractor
grouped as `MemoryServices` dataclass.

**Dependency graph (downward only):**

```
AgentLoop
  -> MessageProcessor
       -> TurnRunner
       |    -> StreamingLLMCaller -> LLMProvider
       |    -> ToolExecutor -> ToolRegistry -> Tools
       |    -> GuardrailChain -> [Guardrail, ...]
       |    -> ContextBuilder -> [ContextContributor, ...]
       -> SessionManager
       -> MemoryServices
       |    -> MemoryStore (existing)
       |    -> StrategyExtractor
       -> Bus
```

---

## Testing Strategy

### Contract Tests (behavioral guarantees)

```
test_loop_terminates_within_max_iterations
test_loop_terminates_within_wall_time
test_empty_result_triggers_intervention
test_repeated_strategy_triggers_intervention
test_tool_failure_disables_tool
test_guardrail_intervention_is_system_message
test_self_check_uses_same_context
test_working_memory_tracks_all_attempts
test_reasoning_protocol_always_present
test_strategies_before_memory_in_prompt
test_contributor_order_respected
test_security_advisory_always_last
test_guardrail_recovery_produces_strategy
test_failed_recovery_produces_no_strategy
test_strategy_confidence_increases_on_success
test_low_confidence_strategies_pruned
```

### Integration Tests (ScriptedProvider scenarios)

```
test_obsidian_folder_lookup — DS10540 case: search fails, guardrail fires,
  recovery via list_dir succeeds, strategy extracted
test_successful_path_no_guardrails — clean path, no interventions
test_strategy_loaded_prevents_failure — pre-seeded strategy avoids failure
```

### Guardrail Unit Tests

Each guardrail tested with synthetic TurnState and ToolAttempt lists. No LLM, no I/O.

### What NOT to Test

- Message array structure at specific indices (fragile)
- Internal call order of TurnRunner methods (implementation detail)
- Exact prompt template text (content changes are expected)

---

## Migration Path

### What Stays in coordination/

The coordination package loses routing but retains spawning infrastructure:

| File | Action | Reason |
|------|--------|--------|
| coordinator.py | **DELETE** | Routing removed |
| router.py | **DELETE** | Routing removed |
| role_switching.py | **DELETE** | Routing removed |
| registry.py | **DELETE** | Routing removed |
| delegation.py | **KEEP** | Sub-agent spawning (tool_loop.py based) |
| delegation_advisor.py | **DELETE** | Nudge logic removed; spawning is a tool call, not an advisor decision |
| delegation_contract.py | **KEEP** | Contract for delegation tool |
| mission.py | **KEEP** | Long-running background tasks |
| scratchpad.py | **KEEP** | Inter-agent communication |
| task_types.py | **KEEP** | Task classification for delegation |

### Phase 1: Delete Dead Code (risk: low)

Delete routing infrastructure and delegation advisor (~1,600 LOC):
- coordination/coordinator.py, router.py, role_switching.py, registry.py,
  delegation_advisor.py
- templates/prompts/classify.md, role_*.md (5 files), nudge_*.md (6 files)
- Remove routing and advisor wiring from factory, processor, orchestrator, turn_types
- Remove plan enforcement heuristic (_needs_planning, _PLANNING_SIGNALS)

### Phase 2: Introduce New Components (risk: low)

Create standalone modules with tests (no wiring yet):
- turn_guardrails.py (Guardrail protocol, GuardrailChain, 5 guardrails)
- ToolAttempt dataclass in turn_types.py
- Prompt templates: reasoning.md, tool_guide.md, self_check.md
- memory/strategy.py (Strategy model, StrategyStore, DB migration)

### Phase 3: Rewire the Loop (risk: medium)

- Create TurnRunner alongside TurnOrchestrator (same Orchestrator protocol)
- Feature-flag switch in factory (agent.use_turn_runner config)
- Test new loop with ScriptedProvider integration tests
- Cut over: make TurnRunner default, delete TurnOrchestrator + turn_phases.py + verifier.py

### Phase 4: Prompt Architecture (parallelizable with Phase 3)

- Create ContextContributor protocol and contributor classes
- Rebuild ContextBuilder to use contributor composition
- Update tool descriptions with purpose and anti-patterns
- Restructure obsidian-cli skill as decision tree

### Phase 5: Procedural Memory (depends on Phase 3)

- Create StrategyExtractor
- Wire into MessageProcessor post-turn pipeline
- Activate ProceduralMemoryContributor (replace stub)
- Add confidence evolution logic

### Phase 6: Cleanup & Documentation (last)

- Remove stale imports and unused code
- Update CLAUDE.md, docs/architecture.md
- Create ADR-011: Agent Cognitive Redesign
- Final validation: `make check` + DS10540 litmus test + Langfuse review

---

## File Manifest

### New Files (~925 LOC)

| File | LOC | Purpose |
|------|-----|---------|
| agent/turn_runner.py | ~200 | Cognitive loop |
| agent/turn_guardrails.py | ~150 | Guardrail layer |
| context/contributors/__init__.py | ~5 | Package |
| context/contributors/identity.py | ~30 | Identity section |
| context/contributors/reasoning.py | ~15 | Reasoning protocol |
| context/contributors/tool_guide.py | ~15 | Tool selection guide |
| context/contributors/declarative_memory.py | ~40 | Memory retrieval |
| context/contributors/procedural_memory.py | ~50 | Strategy retrieval |
| context/contributors/bootstrap.py | ~40 | Workspace files |
| context/contributors/feedback.py | ~20 | Feedback summary |
| context/contributors/skills.py | ~40 | Skill injection |
| context/contributors/self_check.py | ~15 | Verification |
| context/contributors/security.py | ~10 | Security advisory |
| memory/strategy.py | ~100 | Strategy model + store |
| memory/strategy_extractor.py | ~120 | Strategy extraction |
| templates/prompts/reasoning.md | ~40 | Reasoning protocol |
| templates/prompts/tool_guide.md | ~25 | Tool selection guide |
| templates/prompts/self_check.md | ~10 | Self-check instructions |

### Deleted Files (~2,413 LOC)

| File | LOC | Reason |
|------|-----|--------|
| agent/turn_orchestrator.py | 497 | Replaced by turn_runner.py |
| agent/turn_phases.py | 476 | ActPhase inlined, ReflectPhase deleted |
| agent/verifier.py | 476 | Replaced by inline self-check |
| coordination/coordinator.py | 350 | Routing removed |
| coordination/router.py | 200 | Routing removed |
| coordination/role_switching.py | 150 | Routing removed |
| coordination/registry.py | 100 | Routing removed |
| templates/prompts/classify.md | 14 | Routing removed |
| templates/prompts/role_*.md | ~100 | 5 role prompts removed |
| templates/prompts/nudge_*.md | ~50 | 6 nudge prompts removed |

### Modified Files (net -661 LOC)

| File | Before | After |
|------|--------|-------|
| agent/agent_factory.py | 493 | ~350 |
| agent/message_processor.py | 586 | ~400 |
| agent/loop.py | 430 | ~350 |
| agent/agent_components.py | 135 | ~80 |
| agent/turn_types.py | 122 | ~80 |
| context/context.py | 355 | ~200 |

### Net Impact

```
Current agent system:  ~5,500 LOC
New agent system:      ~2,385 LOC
Net reduction:         ~3,115 LOC (57%)
```

---

## Success Criteria

The redesign is successful when:

1. **DS10540 litmus test passes** — Agent finds the folder and reads files on first attempt
2. **No guardrail fires on the happy path** — Capable models flow through without interventions
3. **Weak models recover via guardrails** — gpt-4o-mini hits guardrails but completes the task
4. **Cross-session learning works** — Session 2 handles the same task without guardrails
5. **Cost reduction** — Average turn cost decreases (no separate verifier call, no routing classification)
6. **Latency reduction** — Average turn latency decreases (fewer iterations, simpler loop)
7. **`make check` passes clean** — All contract, unit, and integration tests pass
8. **Langfuse traces show improvement** — Fewer iterations, lower guardrail activation rate over time
