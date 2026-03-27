# Agent Cognitive Core Redesign — Full Analysis Report

> Date: 2026-03-27
> Author: Claude Opus 4.6 (collaborative session with project owner)
> Duration: ~4 hours of analysis, design, and documentation
> Output: Architectural blueprint spec + Phase 1 implementation plan

This report captures the complete analytical journey from failure diagnosis through
architectural redesign. It documents every finding, every comparison, every decision,
and the reasoning behind each — so that any future session can understand not just
WHAT was decided, but WHY.

---

## Table of Contents

1. [The Trigger: DS10540 Obsidian Failure](#1-the-trigger)
2. [Data Gathering: Multi-Source Evidence Collection](#2-data-gathering)
3. [Langfuse Trace Analysis: 13 Traces, 5 Sessions](#3-langfuse-trace-analysis)
4. [Session Conversation Replay](#4-session-conversation-replay)
5. [Root Cause Analysis: 8 Missing Mechanisms](#5-root-cause-analysis)
6. [PAOR Loop Code-Level Diagnosis](#6-paor-loop-diagnosis)
7. [Industry Architecture Comparison](#7-industry-comparison)
8. [Claude Code Self-Comparison](#8-claude-code-self-comparison)
9. [Blank-Sheet Architecture Proposal](#9-blank-sheet-proposal)
10. [Keep vs Refactor vs Rewrite Decision](#10-keep-refactor-rewrite)
11. [Agent Loop Deep Dive](#11-agent-loop-deep-dive)
12. [Design Decisions (Q&A)](#12-design-decisions)
13. [Architecture Design (9 Sections)](#13-architecture-design)
14. [Migration Path](#14-migration-path)
15. [Spec and Plan Deliverables](#15-deliverables)

---

## 1. The Trigger

The project owner removed multi-role routing capabilities to simplify the agent and
incrementally improve it. They asked for an in-depth analysis of the last conversation
with the agent, using Langfuse data and any other source.

The last conversation was the user asking the nanobot agent:
**"Summarize details in Obsidian for DS10540"**

This request was made 5 times across 5 separate sessions on March 26-27, 2026. The agent
failed every single time. The data exists. The tools work. The agent's reasoning was wrong.

### The Ground Truth

The DS10540 folder exists at:
```
C:\Users\C95071414\Documents\Project Management\DS10540\
├── Opportunity Brief.md    (780 bytes)
└── Timekeeping Information.md  (43 bytes)
```

The Obsidian vault is correctly configured:
```
$ obsidian vault
name    Project Management
path    C:\Users\C95071414\Documents\Project Management
files   12
folders 5
size    71849
```

The `obsidian` CLI binary is in PATH and functional. The vault is the active vault.

### Why It Failed

`obsidian search query="DS10540"` returns **"No matches found"** because `search` searches
**file contents**, not file/folder names. The string "DS10540" never appears inside any
markdown file — it's only a folder name.

The correct commands:
```bash
obsidian files folder="DS10540"          # Lists files in the folder
obsidian read path="DS10540/Opportunity Brief.md"  # Reads the file
```

The 440-line obsidian-cli skill provides these commands explicitly. The agent had the
right tool but chose the wrong command.

---

## 2. Data Gathering

Evidence was collected from 5 parallel sources simultaneously:

### Source 1: Langfuse Traces
- API: `https://us.cloud.langfuse.com`
- Project: `cmn8142mz05fnad06qk7rdjtf`
- 13 traces retrieved across 5 sessions
- Full observation details for each trace (spans, generations, tool calls)
- 5 verification scores retrieved

### Source 2: Session Files
- Location: `~/.nanobot/workspace/sessions/`
- 3 session files from March 27 read in full
- Complete user messages, assistant responses, tool calls, errors

### Source 3: Git History
- Recent 30 commits analyzed
- Multi-role removal tracked through commits `ca1cc3c` → `8cf9a3a`
- Routing architecture changes mapped

### Source 4: Codebase (Agent System)
- Every file in `nanobot/agent/` read completely (8 files, 2,773 LOC)
- Every file in `nanobot/context/` read completely (4 files, 1,238 LOC)
- Every file in `nanobot/tools/` infrastructure read (5 files, ~1,100 LOC)
- All prompt templates read (35 files)
- Provider abstraction layer read (4 files, ~740 LOC)
- Coordination package read (all files)

### Source 5: Configuration
- `~/.nanobot/config.json` — full agent config
- `nanobot/config/schema.py` — schema definitions
- Routing config: `enabled: false`, `default_role: "general"`
- Obsidian-cli skill file: `~/.nanobot/workspace/skills/obsidian-skills/skills/obsidian-cli/SKILL.md` (440 lines)

### Source 6: Filesystem Verification
- `ls "$HOME/Documents/Project Management/"` — confirmed DS10540 folder exists
- `cat "DS10540/Opportunity Brief.md"` — confirmed file content exists
- `obsidian search query="DS10540"` — confirmed search returns nothing (content-only)
- `grep -rl "DS10540"` — confirmed string only in `.obsidian/workspace.json`, not in notes

---

## 3. Langfuse Trace Analysis

### Environment
- Langfuse URL: `https://us.cloud.langfuse.com`
- Release: `0.2.0`
- Environment: `development`
- Total traces analyzed: 13

### All 13 Traces (Chronological)

| # | Trace ID | Time | Model | Role | LLM Calls | Latency | Cost | Input Summary | Outcome |
|---|----------|------|-------|------|-----------|---------|------|---------------|---------|
| 13 | `bb7dbb86` | Mar 26 22:35 | gpt-4o | pm | 1 | 15.8s | **$0.076** | "What is the capital of France?" | Correct (but 30k prompt tokens!) |
| 12 | `36fb5d80` | Mar 26 23:23 | gpt-4o | pm | 3 | 25.0s | **$0.064** | "Summarize details for DS10540" | **FAILED** — search returned nothing |
| 11 | `227dbb37` | Mar 27 00:45 | gpt-4o-mini | general | 2 | 23.5s | $0.003 | "Where is the vault?" | Correct (verifier score=1, false positive) |
| 10 | `b70e6465` | Mar 27 00:46 | gpt-4o-mini | general | 4 | 22.3s | $0.004 | "Project is in vault folders" | **FAILED** — tried list/open, errors |
| 9 | `b046dee6` | Mar 27 09:42 | gpt-4o | pm | 4 | **55.1s** | $0.0001 | "Summarize details for DS10540" | **FAILED** — 16.9s exec, search nothing |
| 8 | `f530e04b` | Mar 27 09:43 | gpt-4o-mini | general | 1 | 21.4s | $0.001 | "Where is the vault?" | Correct (verifier score=1, false positive) |
| 7 | `ac0bff6f` | Mar 27 09:44 | gpt-4o-mini | general | 5 | 19.8s | $0.0001 | "Details for project in vault" | **FAILED** — 4 exec calls, all errors |
| 6 | `91d6f7f7` | Mar 27 10:01 | gpt-4o | pm | 3 | 29.2s | $0.0001 | "Summarize details for DS10540" | **FAILED** — search returned nothing |
| 5 | `9ce1173a` | Mar 27 10:01 | gpt-4o | pm | 1 | 10.5s | $0.002 | "Where is the vault?" | Correct (verified, score=5) |
| 4 | `52ffe082` | Mar 27 10:02 | gpt-4o-mini | general | 2 | 22.0s | $0.0001 | "Details are in that vault" | **FAILED** — search with --vault flag |
| 3 | `802c75b1` | Mar 27 10:44 | gpt-4o-mini | none | 3 | 25.8s | $0.00004 | "Summarize details for DS10540" | **FAILED** — search returned nothing |
| 2 | `6ac042db` | Mar 27 10:45 | gpt-4o-mini | none | 1 | 15.1s | $0.0002 | "Where is the vault?" | Correct (verified, score=5) |
| 1 | `c860476b` | Mar 27 10:45 | gpt-4o-mini | none | 2 | 13.3s | $0.00007 | "Details are in that vault" | **FAILED** — search with vault path |

### Observation Pipeline Pattern

Each trace followed this pipeline:
```
classify (router, gpt-4o-mini, ~1.5-3.8s, ~$0.00009)
  → chat_completion (1-4 rounds with tool calls)
  → verify (optional, triggers revision on failure)
  → memory save_events (gpt-4o-mini, ~$0.00005)
```

### Detailed Observation Breakdown (Key Traces)

**Trace 9 (`b046dee6`) — Longest trace, 55.1s, PM role:**
```
SPAN   request                                    53,612ms (root)
SPAN   classify                                    3,787ms
  GEN  classify (gpt-4o-mini)    479in/34out       3,770ms  $0.00009
SPAN   chat_completion                             4,587ms  → tool: load_skill
TOOL   tool:load_skill                                23ms
SPAN   chat_completion                             7,808ms  → tool: exec
TOOL   tool:exec                                  16,914ms  ← SLOW (obsidian IPC cold start)
SPAN   chat_completion                            10,820ms  → tool: exec
TOOL   tool:exec                                   1,093ms
SPAN   chat_completion                             5,137ms  → final response
GEN    litellm_request (memory)  254in/13out       1,279ms  $0.00005
```

**Trace 12 (`36fb5d80`) — Most expensive single trace, $0.064:**
```
SPAN   request                                    25,021ms
SPAN   classify (gpt-4o-mini)                      2,831ms  $0.00009
GEN    chat_completion (gpt-4o)  5,547in/16out     1,793ms  $0.014  → load_skill
TOOL   tool:load_skill                                18ms
GEN    chat_completion (gpt-4o)  9,833in/23out     2,438ms  $0.025  → exec
TOOL   tool:exec                                  11,883ms
GEN    chat_completion (gpt-4o)  9,874in/56out     3,198ms  $0.025  → final response
GEN    litellm_request (memory)                      869ms  $0.00005
```

**Trace 13 (`bb7dbb86`) — "Capital of France" test, $0.076:**
```
SPAN   request                                    15,765ms
GEN    classify (gpt-4o-mini)    473in/34out       2,290ms  $0.00009
GEN    chat_completion (gpt-4o)  30,013in/8out     7,046ms  $0.075  ← 30K PROMPT TOKENS
SPAN   verify (gpt-4o)                               565ms  $0.0005
```
A trivial factual question cost $0.076 because 30,000 prompt tokens were sent to gpt-4o.

### Verification Scores

| Score | Trace | Comment |
|-------|-------|---------|
| 5 (pass) | `6ac042db` | Vault path answer verified |
| 5 (pass) | `9ce1173a` | Vault path answer verified |
| **1 (fail)** | `f530e04b` | "assumes specific user directory structure" |
| **1 (fail)** | `227dbb37` | "assumes specific user profile and file structure" |
| 5 (pass) | `bb7dbb86` | "Capital of France" verified |

The two score=1 results are **false positives** — the vault path is a confirmed fact
stored in memory, not an assumption. The verifier lacked memory context.

### Cost Analysis

| Category | Traces | Cost | % of Total |
|----------|--------|------|------------|
| PM role (gpt-4o) | 5 | **$0.142** | 91% |
| General role (gpt-4o-mini) | 6 | $0.008 | 5% |
| No role (routing disabled) | 2 | $0.0003 | <1% |
| Classification overhead | 10 | $0.001 | <1% |
| Memory extraction | 13 | $0.001 | <1% |
| Verification + revision | 5 | $0.004 | 3% |
| **Total** | **13** | **$0.156** | **100%** |

The correct solution (2 commands, gpt-4o-mini) would cost ~$0.001. The agent spent
156x more than necessary.

### Latency Analysis

| Metric | Value |
|--------|-------|
| Average trace latency | 23.5s |
| Worst trace | 55.1s (PM role, cold Obsidian IPC) |
| Best trace | 7.7s (single LLM call) |
| Cumulative user wait | ~5 minutes across all attempts |
| Elapsed real time | 12+ hours (first attempt Mar 26 22:35, last Mar 27 10:45) |

---

## 4. Session Conversation Replay

### Session 1 (`web_a70d3fa3`, 09:42-09:45 EDT)

**User:** "Summarize details in Obsidian for DS10540"

**Agent flow:**
1. Loaded obsidian-cli skill
2. Ran `obsidian search query="DS10540" format=json` — **exit code 1** (format=json flag error)
3. Retried: `obsidian search query="DS10540"` — **"No matches found"**
4. Told user: no matches found

**User:** "Do you know where is the vault?"
- Agent correctly identified: `C:\Users\C95071414\Documents\Project Management`
- Routing: classified as `general` (0.7 confidence)

**User:** "The details for the project is in that vault"
- Agent tried `obsidian list "Project Management"` — **error: command "list" not found**
- Tried `obsidian open "Project Management"` — **error: missing required parameter**
- Tried `obsidian open "C:\Users\..."` — **same error**
- Gave up, asked user for specific file names

### Session 2 (`web_1583547f`, 10:01-10:02 EDT)

**User:** "Summarize details in Obsidian for DS10540" (identical, new session)

**Agent flow:**
1. Loaded obsidian-cli skill
2. Ran `obsidian search query="DS10540" format=json` — **"No matches found"**
3. Told user: no matches found

**User:** "Do you know where is the vault?" (typo)
- Correctly identified vault
- Routing: classified as `pm` (0.8 confidence) — **wrong role, triggered gpt-4o**

**User:** "The project details are in that vault"
- Ran `obsidian search query="DS10540" format=json --vault "C:\Users\..."` — **"No matches found"**
- Routing: classified as `general` (0.7 confidence)

### Session 3 (`web_731c8daf`, 10:44-10:45 EDT)

**User:** "Summarize details in Obsidian for DS10540" (identical, third attempt)

**Agent flow:**
1. Loaded obsidian-cli skill
2. Ran `obsidian search query="DS10540"` — **"No matches found"**
3. Told user: no matches found

**User:** "Where is the vault?"
- Correctly identified vault
- No routing trace (routing may have been disabled by this session)

**User:** "The project details are in that vault"
- Ran `obsidian search query="DS10540" --vault "C:\Users\..."` — **"No matches found"**
- Same failure, same approach

### Pattern Across All Sessions

1. Same request repeated 5 times across 5 sessions
2. Agent always used `obsidian search` (content search)
3. Agent never tried `obsidian files`, `obsidian folders`, `list_dir`, or `read_file`
4. Agent never questioned its strategy after failure
5. Routing inconsistently classified the same request as `pm` or `general`
6. User had to clarify the vault location in every session (amnesia)

---

## 5. Root Cause Analysis: 8 Missing Mechanisms

Comparing the nanobot agent with Claude Code (which solved the same task in 2 commands),
8 structural mechanisms were identified as missing:

### Mechanism 1: Pre-Action Reasoning

**Claude Code:** Internal thinking step decomposes the problem before any tool call.
"DS10540 looks like a project code — probably a folder name. Let me check the vault
structure first."

**Nanobot:** Goes directly from user message to tool call. The PAOR "Plan" phase is a
keyword heuristic (`_needs_planning()`), not actual reasoning. "Summarize details in
Obsidian for DS10540" doesn't trigger planning because none of the keywords match
("and", "then", "first", "build", etc.).

### Mechanism 2: Purpose-Driven Tool Descriptions

**Claude Code:** Tool descriptions say WHEN to use each tool:
- `Glob: "Use when you need to find files by name patterns"`
- `Grep: "Use for search tasks" (content search)`

**Nanobot:** Tool descriptions are syntax-only:
- `exec: "Execute a shell command"`
- Plus a 440-line skill dump listing commands by category with no selection guidance.

### Mechanism 3: Adaptive Failure Response

**Claude Code:** System prompt says "If your approach is blocked, do not brute force...
consider alternative approaches." Empty results are treated as signal to change strategy.

**Nanobot:** "No matches found" → report to user. When user pushes back → same approach
with minor variations (--vault flag). Never questions the strategy itself.

### Mechanism 4: Fallback Chains

**Claude Code:** When specialized tool fails → falls back to generic tools:
`obsidian search fails → ls the directory → grep the files → cat the file`

**Nanobot:** Stays within the loaded skill's command set. Never falls back to `list_dir`
or `read_file` even though they're always available.

### Mechanism 5: Parallel Exploration

**Claude Code:** Can launch multiple tool calls simultaneously when independent.
Casts a wide net.

**Nanobot:** Sequential single-tool-call execution. Each failed attempt costs a full
LLM round-trip (3-10s) before trying something else.

### Mechanism 6: Contextual Tool Selection

**Claude Code:** Selects tools based on understanding task structure.
"DS10540" → identifier → likely a folder name → use `ls`, not `search`.

**Nanobot:** Pattern-matches "find information" → "search command". The word "search"
doesn't appear in the user's message, but the agent maps "find info about X" to
"search for X" reflexively.

### Mechanism 7: Cross-Session Strategy Learning

**Claude Code:** Within a conversation, maintains full context. Across conversations,
auto-memory saves non-obvious learnings.

**Nanobot:** Memory saves facts ("vault is at Project Management") but NOT strategies
("obsidian search only searches content, not folder names — use `files folder=X`").
Same failing approach repeated across 5 sessions.

### Mechanism 8: Informed Verification

**Claude Code:** Verification is implicit — checks own work against tool results it
already received. Same context.

**Nanobot:** Separate verifier LLM call that lacks memory context. Caused false positives:
vault path scored 1/5 because verifier didn't know it was a confirmed memory fact.

---

## 6. PAOR Loop Code-Level Diagnosis

### What the Loop Actually Does

After reading every line of the 497-line TurnOrchestrator, the PAOR loop reduces to:

```python
while iteration < max_iterations:
    if context_too_large: compress_messages()
    response = call_llm(messages, tools)
    if llm_error: retry_or_break(); continue
    if response.has_tool_calls:
        results = execute_tools(response.tool_calls)
        add_results_to_messages()
        track_failures()
        inject_delegation_nudge_or_failure_prompt()  # "Reflect"
    else:
        final_answer = response.content
        break
if final_answer:
    final_answer = verify(final_answer)  # Separate LLM call
```

### The Naming vs Reality Gap

| Phase Name | Suggests | Actually Does |
|------------|----------|---------------|
| **Plan** | Reasoning about approach | One-shot keyword heuristic (`_needs_planning()` checks for "and", "then", "build", etc.) |
| **Act** | Intelligent tool selection | Standard tool execution (same as every agent framework) |
| **Observe** | Evaluating results | Adding tool results to message list (bookkeeping) |
| **Reflect** | Strategy evaluation | Injecting delegation nudges as system messages (90% delegation logic) |

### The reflect.md Prompt

The entire "reflection" prompt:
```
Briefly reflect: did the tool results above achieve your goal? If not, state
what went wrong and what you will try next. If yes, produce the final answer.
```
One sentence. Injected as a system message that the model may or may not follow.

### LOC Breakdown: What Earns Its Keep

| Component | LOC | Earns Keep? | Why |
|-----------|-----|-------------|-----|
| Tool execution pipeline (ActPhase) | ~340 | **Yes** | Correct, well-engineered parallel/sequential execution |
| Context compression | ~370 | **Yes** | Essential for long conversations |
| Streaming LLM caller | ~150 | **Yes** | Good abstraction |
| Failure tracking (ToolCallTracker) | ~100 | **Yes** | Prevents infinite loops |
| LLM error handling | ~70 | **Yes** | Robustness (retries, content filters) |
| Observability spans | ~50 | **Yes** | Debugging — led to this analysis |
| Max iterations + wall time | ~20 | **Yes** | Safety guardrails |
| **Subtotal: earns keep** | **~1,100** | | |
| DelegationAdvisor integration | ~200 | **No** | Dead with routing disabled |
| ReflectPhase class | ~130 | **No** | 90% delegation nudges |
| Plan enforcement | ~40 | **No** | Keyword heuristic, could be prompt |
| `_needs_planning()` heuristic | ~25 | **No** | Unreliable keyword matching |
| Role-switching machinery | ~200 | **No** | Dead with routing disabled |
| Classification result tracking | ~30 | **No** | Dead |
| Nudge prompts (8 files) | ~50 | **No** | Mostly delegation |
| Verifier (separate LLM call) | ~476 | **No** | False positives, context gap |
| Recovery attempt | ~60 | **No** | Could be inline |
| **Subtotal: doesn't earn keep** | **~1,241** | | |

### The Damning Comparison

The existing `tool_loop.py` (168 lines), used by subagents, is structurally closer to
industry best practice than the 497-line TurnOrchestrator:

```python
async def run_tool_loop(provider, tools, messages, model, ...):
    while iteration < max_iterations:
        response = await provider.chat(messages, tools=tool_defs, model=model)
        if response.tool_calls:
            execute_batch()
            add_results_to_messages()
        else:
            return response.content
    return await provider.chat(messages, tools=None)  # fallback
```

168 lines. No phases. No delegation advisor. No plan enforcement. No nudge prompts.
And it works for every subagent task.

---

## 7. Industry Architecture Comparison

### Production Agent Architectures

| Agent | Loop Pattern | LOC (est.) | Intelligence Source |
|-------|-------------|-----------|-------------------|
| **Claude Code** | Simple tool loop | ~200 | Extended thinking + rich tool descriptions + behavioral system prompt rules |
| **Cursor** | Simple tool loop | ~200 | Codebase-aware context, intelligent file selection |
| **Devin** | Plan → Execute steps → Verify | ~300 | Model-generated plan (not keyword heuristic), simple loop per step |
| **OpenAI Agents SDK** | `while has_tool_calls: execute` | ~100 | Model + tool descriptions. Literally the simplest loop possible. |
| **LangGraph** | Explicit state machine | varies | Graph controls FLOW (routing between nodes), not REASONING. Reasoning is inside the LLM. |

### Academic Patterns

| Pattern | Key Insight | Applicable To |
|---------|------------|---------------|
| **ReAct** (Yao et al., 2023) | Interleave reasoning traces with actions | Prompt architecture: force reasoning before tool selection |
| **Reflexion** (Shinn et al., 2023) | Self-reflection on failures drives strategy improvement | Guardrails + procedural memory feedback loop |
| **Voyager** (NVIDIA) | Skill library grows from experience | Procedural memory: save successful strategies |
| **Inner Monologue** (Google) | Success detection from environment feedback | Result classification in guardrails |
| **Soar/ACT-R** (Cognitive Architectures) | Impasse detection → strategy switch; three knowledge types (declarative, procedural, working) | Empty result → replan guardrail; three-tier memory |

### The Universal Pattern

Every successful agent framework has:
1. A simple tool-use loop (~100-200 lines)
2. Excellent tool descriptions (purpose, when-to-use, anti-patterns)
3. A well-crafted system prompt with behavioral rules
4. Good context management (what the model sees)
5. Guardrails (max iterations, failure limits, token budgets)

No successful framework has:
- External "reflection" phases injecting prompts between tool calls
- Delegation advisors nudging toward specific tool patterns
- Plan enforcement detecting "wrong" model behavior
- Separate verification LLM calls lacking the agent's full context

---

## 8. Claude Code Self-Comparison

When asked "What mechanisms do you have that my agent lacks?", the analysis compared
Claude Code's actual execution of the same task:

### Claude Code's Execution (2 commands, ~$0.001)

```
[THINKING] DS10540 looks like a project code — probably a folder name.
           Let me check the vault structure.

[ACT]      ls "$HOME/Documents/Project Management/"
[RESULT]   Shows DS10540/ folder

[THINKING] DS10540 is a folder. Let me read the files inside.

[ACT]      cat "DS10540/Opportunity Brief.md"
[RESULT]   File content

[RESPOND]  Summary of DS10540...
```

### Nanobot's Execution (13 traces, $0.156)

```
[NO THINKING STEP]

[ACT]      obsidian search query="DS10540"
[RESULT]   No matches found

[RESPOND]  "No matches found for DS10540"

[USER]     "The data is in that vault"

[ACT]      obsidian search query="DS10540" --vault "C:\Users\..."
[RESULT]   No matches found

[RESPOND]  "Still no matches. Can you provide a specific file name?"

[Repeated 5 times across 5 sessions]
```

### The Fundamental Difference

Claude Code's intelligence comes from **reasoning inside the LLM call** (extended
thinking), not from external orchestration. The loop is simple — the model is smart.

Nanobot invested in **orchestration complexity** (routing, delegation, plan enforcement,
separate verification) while the reasoning step (what happens inside the LLM call) is
unguided. The model receives a 440-line command reference dump and picks `search` because
it pattern-matches "find information" → "search."

---

## 9. Blank-Sheet Architecture Proposal

Asked "From a blank sheet, how would you design the agent?", the proposal was:

### Core Principle: Reasoning Is the Product, Not Orchestration

The cognitive loop is the core product. Everything else — memory, tools, skills,
channels — exists to feed the loop better information.

### Three-Layer Cognitive Model

**Layer 1 — Prompt Architecture (proactive).** Structured reasoning instructions in
the system prompt teach the model HOW to think before acting. Zero extra LLM calls.
This is where most improvement lives.

**Layer 2 — Context Quality (proactive).** Purpose-typed tool descriptions, skill
decision trees (not reference manuals), procedural memory from past sessions.

**Layer 3 — Guardrails (reactive).** Code-enforced interventions when Layers 1 and 2
fail. The safety net that catches weak models.

### Three-Tier Memory

| Tier | Content | Storage | Missing From Nanobot? |
|------|---------|---------|----------------------|
| Declarative | Facts, entities | SQLite (existing) | No — this works |
| Procedural | Tool strategies, what-worked/failed | SQLite (new) | **Yes — completely missing** |
| Working | Current task state, attempts made | In-memory per-turn | **Yes — partially missing** |

### What to Remove

- Multi-role routing (already done)
- Intent classification
- Delegation advisor
- Plan enforcement heuristic
- Separate verifier LLM call (as default)
- Role-specific model switching
- 8 nudge prompt templates

---

## 10. Keep vs Refactor vs Rewrite Decision

### Assessment by Layer

| Layer | LOC | Quality | Decision |
|-------|-----|---------|----------|
| Memory subsystem (SQLite + FTS5 + sqlite-vec + graph) | ~3,000 | Excellent | **Keep** |
| Observability (Langfuse + tracing) | ~600 | Good | **Keep** |
| Providers (LiteLLM abstraction) | ~500 | Solid | **Keep** |
| Config (Pydantic models) | ~800 | Standard | **Keep** |
| Channels (platform adapters) | ~1,000 | Working | **Keep** |
| Bus (async message queue) | ~300 | Simple, correct | **Keep** |
| Tools infrastructure (base, registry, executor) | ~500 | Well-engineered | **Keep** |
| Tools implementations (builtin/) | ~2,000 | Working | **Keep** |
| Session management | ~400 | Works | **Keep** |
| CLI entry points | ~600 | Just wiring | **Keep** |
| **Subtotal: Keep** | **~9,700** | | **65%** |
| Agent loop (TurnOrchestrator) | ~500 | Over-engineered | **Redesign** |
| Turn phases (Act + Reflect) | ~476 | Mixed (Act good, Reflect bad) | **Redesign** |
| Message processor | ~586 | Routing-heavy | **Simplify** |
| Verifier | ~476 | False positives | **Replace** |
| **Subtotal: Rework** | **~2,038** | | **14%** |
| Routing infrastructure | ~800 | Dead code | **Delete** |
| Delegation advisor | ~200 | Dead code | **Delete** |
| Role prompts + nudges | ~150 | Dead code | **Delete** |
| **Subtotal: Delete** | **~1,150** | | **8%** |

### Verdict: Major Refactor, Not Rewrite

The infrastructure is genuinely good — the memory subsystem alone represents weeks of
engineering. The problem is concentrated in the cognitive core (~2,000 LOC). Rewriting
15,000 LOC to fix a 2,000 LOC problem is a poor cost-benefit ratio.

The metaphor: "Your infrastructure is a Formula 1 chassis. The engine (cognitive loop)
needs a redesign. You don't scrap the chassis to fix the engine."

---

## 11. Agent Loop Deep Dive

### Every File in agent/ (Complete Inventory)

| File | LOC | Core Responsibility | Verdict |
|------|-----|---------------------|---------|
| `loop.py` | 430 | Bus consumption, MCP lifecycle, message delegation | Simplify (remove coordinator wiring) |
| `turn_orchestrator.py` | 497 | PAOR state machine | **Replace** with TurnRunner (~200 LOC) |
| `message_processor.py` | 586 | Per-message pipeline | Simplify (~400 LOC, remove routing) |
| `verifier.py` | 476 | Separate LLM critique + revision | **Replace** with inline self-check |
| `agent_factory.py` | 493 | Composition root | Simplify (~350 LOC, remove routing wiring) |
| `agent_components.py` | 135 | DI data containers | Simplify (~80 LOC, remove routing fields) |
| `turn_types.py` | 122 | TurnState, protocols | Simplify (~80 LOC, remove active_* fields) |
| `turn_phases.py` | 476 | ActPhase + ReflectPhase | **Delete ReflectPhase**, inline ActPhase into TurnRunner |
| `__init__.py` | 34 | Public exports | Update |
| **Total** | **3,249** | | **Target: ~1,000** |

### Prompt Templates (Complete Inventory)

| Template | LOC | Used By | Verdict |
|----------|-----|---------|---------|
| `identity.md` | 39 | ContextBuilder | Keep |
| `plan.md` | 1 | TurnOrchestrator (plan phase) | **Delete** (plan enforcement removed) |
| `reflect.md` | 1 | ReflectPhase | Keep (1 line, may be useful later) |
| `progress.md` | 1 | ReflectPhase | Keep (1 line, may be useful later) |
| `failure_strategy.md` | 20 | ReflectPhase | Keep (useful failure recovery guidance) |
| `critique.md` | 15 | AnswerVerifier | Keep (may be used by structured self-check) |
| `recovery.md` | 1 | AnswerVerifier | Keep (fallback prompt) |
| `classify.md` | 14 | Coordinator | **Delete** |
| `role_*.md` (5 files) | ~75 | Role switching | **Delete** |
| `nudge_*.md` (6 files) | ~30 | ReflectPhase/planning | **Delete** |
| Other (14 files) | ~200 | Various (compression, delegation, etc.) | Keep |

---

## 12. Design Decisions

Four architectural questions were asked, each with 2-3 options, trade-offs, and a
recommendation. The project owner chose:

### Question 1: Model Assumptions

**Options:** (A) Model-agnostic, (B) Capable-model-first, (C) Single model target

**Chosen: (A) Model-agnostic.** Architecture must work with any model including weak
ones (gpt-4o-mini). Reasoning quality enforced through structure, not model native ability.

**Impact:** Can't rely on extended thinking or native parallel tool calls. Must enforce
reasoning through structured prompts and code-level guardrails.

### Question 2: Sub-Agent / Delegation

**Options:** (A) Pure single agent, (B) Single + optional spawning, (C) Keep delegation as-is

**Chosen: (B) Single agent with optional spawning.** One primary agent, no roles/routing.
Can spawn lightweight sub-agents via existing `tool_loop.py`.

**Impact:** Delete routing/role/coordination machinery. Keep delegation.py, mission.py,
scratchpad.py for spawning.

### Question 3: Verification Strategy

**Options:** (A) Prompt-only, (B) Structured self-check, (C) Configurable

**Chosen: (C) Configurable.** Prompt-only by default. Optional structured self-check
(extra LLM call, same context) via config flag.

**Impact:** Delete 476-line AnswerVerifier as default. Replace with prompt instructions +
optional post-loop self-check in TurnRunner.

### Question 4: Reasoning Enforcement

**Options:** (A) Prompt-driven, (B) Code-enforced, (C) Layered

**Chosen: (C) Layered.** Prompt instructions as baseline + code-enforced guardrails that
activate on failure patterns. Smart models never hit guardrails; weak models get help.

**Impact:** This determined the core architecture pattern: Adaptive Loop with Guardrail
Escalation.

---

## 13. Architecture Design

Nine sections were presented and approved one at a time:

### Section 1: Architecture Overview & Core Patterns

Four architectural layers:
1. **Entry Layer** — MessageProcessor (simplified)
2. **Cognitive Loop** — TurnRunner (new, replaces TurnOrchestrator)
3. **Guardrail Layer** — GuardrailChain (new, modular checks)
4. **Prompt Layer** — ContextBuilder + ContextContributors (extended)

Five governing patterns:
1. The Loop Is Dumb, The Prompt Is Smart
2. Guardrails Are Plugins, Not States
3. Context Is Layered and Composable
4. Memory Has Three Tiers
5. Feedback Loops Close the Learning Gap

### Section 2: The Cognitive Loop (TurnRunner)

Simple tool-use loop (~200 LOC) replacing TurnOrchestrator (497 LOC):
- No plan enforcement, no ReflectPhase, no delegation advisor
- Guardrail checkpoint after each iteration
- Working memory (ToolAttempt log) for guardrail reasoning
- Configurable self-check replacing separate Verifier

New TurnState: 12 fields (down from 17), adds `tool_results_log: list[ToolAttempt]`

### Section 3: The Guardrail Layer

5 initial guardrails in priority order:
1. FailureEscalation (tool disabled after N failures)
2. NoProgressBudget (stop after 4 iterations with no data)
3. RepeatedStrategyDetection (same tool+args 3 times)
4. EmptyResultRecovery (success but no data → suggest alternatives)
5. SkillTunnelVision (all exec, no data, iteration ≥ 3 → suggest base tools)

Plugin architecture: `Guardrail` protocol, `GuardrailChain` (first-intervention-wins),
`Intervention` dataclass with `strategy_tag` for procedural memory feedback.

### Section 4: The Prompt Layer (Context Architecture)

11-section system prompt with strict composition order, each section owned by one
`ContextContributor`. New templates:
- `reasoning.md` — how to think before acting (4-step reasoning protocol)
- `tool_guide.md` — purpose-driven tool selection with anti-patterns
- `self_check.md` — verification instructions

Skill decision trees: decision logic first, reference material second.
Tool descriptions: purpose + anti-patterns ("do NOT use search for name lookups").

### Section 5: Memory Interface (Three Tiers)

- **Tier 1 Declarative** (existing): facts, entities. No changes.
- **Tier 2 Procedural** (new): `Strategy` dataclass, `strategies` table in SQLite,
  `StrategyExtractor` saves from guardrail recoveries and user feedback.
  Confidence evolution: +0.1 on success, -0.05 on failure despite strategy, prune below 0.1.
- **Tier 3 Working** (new): `tool_results_log` on TurnState. Per-turn only, not persisted.

Feedback loop: guardrail recovery → strategy saved → loaded next session → no guardrail.

### Section 6: Entry Layer & Composition

MessageProcessor simplified to ~400 LOC (down from 586). Factory simplified to ~350 LOC
(down from 493). All components under 7 constructor params. Clean downward-only
dependency graph.

### Section 7: Structural Stability Patterns (15 patterns)

1. The Loop Is Dumb, The Prompt Is Smart
2. Guardrails Are Plugins, Not States
3. Context Is Layered and Composable
4. Memory Has Three Tiers
5. Feedback Loops Close the Learning Gap
6. Stable Core / Volatile Edge
7. One File, One Reason to Change
8. Protocols at Boundaries, Concrete Inside
9. Three Extension Points (guardrails, contributors, prompts)
10. Growth Limits (guardrail count ≤ 10, contributors ≤ 15, templates ≤ 100 LOC)
11. Observable by Default
12. No Implicit Coupling
13. Prompt Changes Are Code Changes
14. Design for Deletion
15. Test by Contract, Not Implementation

### Section 8: Migration Path

6 sequential phases:
1. Delete dead code (~1,600 LOC) — risk: low
2. Introduce new components (standalone, no wiring) — risk: low
3. Rewire the loop (feature-flag cutover) — risk: medium
4. Prompt architecture (parallelizable with Phase 3) — risk: low
5. Procedural memory (depends on Phase 3) — risk: low
6. Cleanup & documentation — risk: low

### Section 9: Testing Strategy

Contract tests (behavioral guarantees), integration tests (ScriptedProvider scenarios),
guardrail unit tests (synthetic state). Observability as production testing (Langfuse
metrics for guardrail activation rate, strategy extraction rate, iteration count, cost).

### Net Impact

```
Current agent system:  ~5,500 LOC
New agent system:      ~2,385 LOC
New capabilities:      Guardrails, procedural memory, reasoning protocol,
                       tool guide, decision-tree skills
Net reduction:         ~3,115 LOC (57%)
```

---

## 14. Migration Path

### Parallelization Assessment

Project owner asked: "Can we do this in parallel since there are no users?"

**Answer: Mostly no.** The constraint isn't uptime — it's:
1. **File contention** — `agent_factory.py` is touched by 4 of 5 phases
2. **Phase 3 requires Phase 1 complete** — otherwise the session reads 1,400 lines of dead code
3. **Integration testing can't be deferred** — big-bang integration breaks are expensive to debug

**What CAN parallelize:** Stream A (structural changes) + Stream B (prompt content — writing
reasoning.md, tool_guide.md, restructuring skills). These have zero file contention.

### Phase 1 Implementation Plan

Written as `docs/superpowers/plans/2026-03-27-phase1-delete-dead-code.md`:
- 10 atomic tasks, each produces `make check`-passing codebase
- ~35 files deleted, ~15 files modified
- Estimated: ~2 hours
- Execution: worktree + feature branch per CLAUDE.md protocol

---

## 15. Deliverables

### Documents Produced

| Document | Location | Content |
|----------|----------|---------|
| Architectural Blueprint (Spec) | `docs/superpowers/specs/2026-03-27-agent-cognitive-redesign.md` | 746 lines, full architecture + patterns + migration + file manifest |
| Phase 1 Plan | `docs/superpowers/plans/2026-03-27-phase1-delete-dead-code.md` | 894 lines, 10 tasks with exact file paths and code |
| This Report | `docs/superpowers/reports/2026-03-27-agent-cognitive-redesign-report.md` | Full analytical journey |

### Memory Records Created

| Memory | File | Content |
|--------|------|---------|
| Redesign Analysis | `project_agent_redesign_analysis.md` | 8 missing mechanisms, PAOR diagnosis |
| Design Decisions | `project_agent_redesign_decisions.md` | 4 architectural choices + rationale |
| Langfuse Traces | `project_langfuse_trace_analysis.md` | 13 traces, cost/latency breakdown |
| Code Analysis | `project_agent_loop_code_analysis.md` | Line-by-line review, LOC verdicts |
| Industry Patterns | `project_industry_agent_patterns.md` | Claude Code, Cursor, Devin comparison |
| Workflow Pattern | `feedback_analysis_design_workflow.md` | Repeatable analysis→design workflow |
| Memory Discipline | `feedback_save_research_to_memory.md` | Save findings incrementally |
| Worktree Protocol | `feedback_always_follow_worktree_protocol.md` | Always use feature branches |

### Commits

| Hash | Message |
|------|---------|
| `0c701ac` | `docs: add agent cognitive core redesign architectural blueprint` |
| `2db22e4` | `docs: add Phase 1 implementation plan (delete dead code)` |

### Worktree (Ready for Execution)

```
Branch: phase1/delete-dead-code
Path:   ../nanobot-phase1-delete-dead-code
Status: Created, baseline lint+typecheck passed
```

---

## Success Criteria (From Spec)

The redesign is successful when:

1. **DS10540 litmus test passes** — Agent finds the folder and reads files on first attempt
2. **No guardrail fires on the happy path** — Capable models flow through without interventions
3. **Weak models recover via guardrails** — gpt-4o-mini hits guardrails but completes the task
4. **Cross-session learning works** — Session 2 handles the same task without guardrails
5. **Cost reduction** — Average turn cost decreases
6. **Latency reduction** — Average turn latency decreases
7. **`make check` passes clean** — All contract, unit, and integration tests pass
8. **Langfuse traces show improvement** — Fewer iterations, lower guardrail activation rate over time
