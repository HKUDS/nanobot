# Agent Cognitive Core Redesign — Complete Analysis & Design

> Date: 2026-03-27
> Author: Claude Opus 4.6 (collaborative session with project owner)
> This is the definitive document. It captures the complete analytical journey
> and every design detail exactly as presented during the session.

---

## Part 1: The User's Request

The project owner had just removed multi-role routing capabilities from the nanobot agent
to simplify the scenario and incrementally improve the agent. They asked:

> "Do an in-depth and exhaustive analysis and critique of the last conversation with
> the agent using the data from Langfuse and any other source of information. I have
> now removed the multi-role capabilities to simplify the scenario and incrementally
> improve the agent."

This triggered a multi-source evidence collection, followed by a series of increasingly
deep analytical questions from the user that evolved the work from a diagnostic into a
full architectural redesign.

---

## Part 2: Multi-Source Evidence Collection

Evidence was gathered from 5+ sources simultaneously using parallel agent dispatches:

### Source 1: Langfuse Configuration & Integration

The nanobot project has a fully implemented Langfuse v4 integration (OTEL-based):

- **URL:** `https://us.cloud.langfuse.com`
- **Project:** `cmn8142mz05fnad06qk7rdjtf`
- **Public Key:** `pk-lf-b88d840f-2cf9-4138-a522-03e05f7d7661`
- **Environment:** `development`, Release `0.2.0`

**Integration architecture:**
- `nanobot/observability/langfuse.py` (478 lines) — main integration
- `nanobot/observability/tracing.py` (145 lines) — correlation IDs + PII sanitizer
- Auto-instrumentation via litellm OTEL callbacks
- Manual instrumentation: `trace_request()`, `tool_span()`, `span()`, `score_current_trace()`

**Span coverage at time of analysis:**

| Span Site | File | Input | Output | Status |
|-----------|------|:-----:|:------:|--------|
| `trace_request` (root) | agent/loop.py:266 | Yes | Yes | Complete |
| `tool_span` (main path) | tools/registry.py:149 | Yes | Missing | Gap |
| `span("classify")` | coordination/coordinator.py:215 | Yes | Yes | Complete |
| `span("verify")` | agent/verifier.py:93 | Missing | Missing | Gap |
| `span("delegate")` | coordination/delegation.py:345 | Yes | Missing | Gap |

### Source 2: Git History

Recent 30 commits analyzed. Key architectural changes (March 24-25):

| Commit | Date | Change | Impact |
|--------|------|--------|--------|
| `ca1cc3c` | Earlier | feat: multi-agent coordinator with LLM-based intent routing | Introduced role classification |
| `5d01b01` | Earlier | refactor(loop): extract tool registration + role switching | Separated concerns |
| `24171a8` | Mar 25 | feat: move routing into MessageProcessor._process_message() | Moved routing to processor |
| `8cf9a3a` | Mar 25 | refactor: remove routing from AgentLoop | Removed loop-level routing |

**Key finding:** Routing was architecturally moved (loop → processor) rather than removed.
The config still had `routing.enabled: false` but all the code remained.

### Source 3: Agent Configuration

From `~/.nanobot/config.json`:
```json
"routing": {
  "enabled": false,
  "classifier_model": "openai/gpt-4o-mini",
  "roles": [{"name": "pm", ...}],
  "default_role": "general"
}
```

**Built-in DEFAULT_ROLES** (in coordinator.py, lines 45-82):
- `code`: Code generation, debugging (no denied tools)
- `research`: Web search, analysis (denied: write_file, edit_file)
- `writing`: Documentation, emails (denied: exec)
- `system`: Shell commands, infrastructure (no denied tools)
- `pm`: Project planning, coordination (denied: exec)
- `general`: General-purpose fallback (no denied tools)

### Source 4: Session Conversation Files

Three session files from March 27 read in full:
- `web_a70d3fa3` (09:42-09:45 EDT)
- `web_1583547f` (10:01-10:02 EDT)
- `web_731c8daf` (10:44-10:45 EDT)

Plus earlier sessions from March 26.

### Source 5: Codebase (Complete Read)

Every file in the agent orchestration layer read completely:

| File | LOC | Responsibility |
|------|-----|----------------|
| `agent/loop.py` | 430 | Bus consumption, MCP lifecycle |
| `agent/turn_orchestrator.py` | 497 | PAOR state machine |
| `agent/message_processor.py` | 586 | Per-message pipeline |
| `agent/verifier.py` | 476 | Answer critique + revision |
| `agent/agent_factory.py` | 493 | Composition root |
| `agent/agent_components.py` | 135 | DI data containers |
| `agent/turn_types.py` | 122 | TurnState, protocols |
| `agent/turn_phases.py` | 476 | ActPhase + ReflectPhase |
| `agent/__init__.py` | 34 | Public API |
| **Total** | **3,249** | |

Also read completely:
- `context/context.py` (355 lines) — system prompt assembly
- `context/compression.py` (373 lines) — token budget management
- `context/skills.py` (439 lines) — skill loading and transformation
- `context/feedback_context.py` (71 lines) — feedback injection
- `tools/base.py` (204 lines) — Tool ABC and ToolResult
- `tools/registry.py` (282 lines) — tool registry and execution
- `tools/executor.py` (145 lines) — parallel/sequential batch execution
- `tools/tool_loop.py` (168 lines) — reusable subagent loop
- `tools/capability.py` (350 lines) — unified capability registry
- `providers/base.py` (169 lines) — LLMProvider abstract base
- `providers/litellm_provider.py` (478 lines) — multi-provider LLM implementation
- All 35 prompt templates
- All coordination module files
- `identity.md` (39 lines) — core system prompt
- `classify.md` (14 lines) — classification prompt
- All role prompts and nudge prompts

### Source 6: Obsidian-CLI Skill

The obsidian-cli skill at `~/.nanobot/workspace/skills/obsidian-skills/skills/obsidian-cli/SKILL.md`
was read completely — 440 lines of command reference covering vault automation, daily notes,
search, tasks, tags, properties, links, bookmarks, bases, templates, themes, plugins, sync,
publish, workspaces, and developer tools.

### Source 7: Filesystem Verification

Direct verification of the Obsidian vault:

```bash
$ ls "$HOME/Documents/Project Management/"
.obsidian/
D21410 - PLM Transformation/
DS10540/                          ← EXISTS
Project Management practices/

$ ls "$HOME/Documents/Project Management/DS10540/"
Opportunity Brief.md    (780 bytes)
Timekeeping Information.md  (43 bytes)

$ cat "DS10540/Opportunity Brief.md"
The current secured digital signature solution is in DOCUMENTUM, not
functionally integrated in ENOVIA, which creates lost time and some
confusion when not properly trained on the process...

$ obsidian search query="DS10540"
No matches found.                 ← SEARCH ONLY MATCHES FILE CONTENT

$ obsidian vault
name    Project Management
path    C:\Users\C95071414\Documents\Project Management
files   12
folders 5
size    71849

$ grep -rl "DS10540" "$HOME/Documents/Project Management/"
.obsidian/workspace.json          ← Only in Obsidian config, not in any note
```

**Definitive finding:** `obsidian search` searches FILE CONTENTS only. "DS10540" exists
only as a FOLDER NAME. The search will never find it. The correct command is
`obsidian files folder="DS10540"` or `obsidian folders`.

---

## Part 3: Langfuse Trace Analysis — 13 Traces, 5 Sessions

### All 13 Traces

| # | Trace ID | Time | Model | Role | LLM Calls | Latency | Cost | Input | Outcome |
|---|----------|------|-------|------|-----------|---------|------|-------|---------|
| 13 | `bb7dbb86` | Mar 26 22:35 | gpt-4o | pm | 1 | 15.8s | **$0.076** | "What is the capital of France?" | Correct (30k prompt tokens!) |
| 12 | `36fb5d80` | Mar 26 23:23 | gpt-4o | pm | 3 | 25.0s | **$0.064** | "Summarize details for DS10540" | **FAILED** |
| 11 | `227dbb37` | Mar 27 00:45 | gpt-4o-mini | general | 2 | 23.5s | $0.003 | "Where is the vault?" | Correct (verifier score=1, FALSE POSITIVE) |
| 10 | `b70e6465` | Mar 27 00:46 | gpt-4o-mini | general | 4 | 22.3s | $0.004 | "Project is in vault folders" | **FAILED** — tried list/open, errors |
| 9 | `b046dee6` | Mar 27 09:42 | gpt-4o | pm | 4 | **55.1s** | $0.0001 | "Summarize details for DS10540" | **FAILED** — 16.9s exec |
| 8 | `f530e04b` | Mar 27 09:43 | gpt-4o-mini | general | 1 | 21.4s | $0.001 | "Where is the vault?" | Correct (verifier score=1, FALSE POSITIVE) |
| 7 | `ac0bff6f` | Mar 27 09:44 | gpt-4o-mini | general | 5 | 19.8s | $0.0001 | "Details for project in vault" | **FAILED** — 4 exec calls, all errors |
| 6 | `91d6f7f7` | Mar 27 10:01 | gpt-4o | pm | 3 | 29.2s | $0.0001 | "Summarize details for DS10540" | **FAILED** |
| 5 | `9ce1173a` | Mar 27 10:01 | gpt-4o | pm | 1 | 10.5s | $0.002 | "Where is the vault?" | Correct (verified, score=5) |
| 4 | `52ffe082` | Mar 27 10:02 | gpt-4o-mini | general | 2 | 22.0s | $0.0001 | "Details are in that vault" | **FAILED** — search with --vault |
| 3 | `802c75b1` | Mar 27 10:44 | gpt-4o-mini | none | 3 | 25.8s | $0.00004 | "Summarize details for DS10540" | **FAILED** |
| 2 | `6ac042db` | Mar 27 10:45 | gpt-4o-mini | none | 1 | 15.1s | $0.0002 | "Where is the vault?" | Correct (verified, score=5) |
| 1 | `c860476b` | Mar 27 10:45 | gpt-4o-mini | none | 2 | 13.3s | $0.00007 | "Details are in that vault" | **FAILED** |

### Detailed Observation Breakdowns

**Trace 9 (`b046dee6`) — Longest trace, 55.1s, PM role, first session attempt:**

```
SPAN   request                                           53,612ms (root)
SPAN   classify                                           3,787ms
  GEN  classify (gpt-4o-mini-2024-07-18) 479in/34out     3,770ms  $0.00009
SPAN   chat_completion                                    4,587ms  → tool: load_skill
TOOL   tool:load_skill                                       23ms
SPAN   chat_completion                                    7,808ms  → tool: exec
TOOL   tool:exec                                         16,914ms  ← 16.9s (Obsidian IPC cold start)
SPAN   chat_completion                                   10,820ms  → tool: exec
TOOL   tool:exec                                          1,093ms
SPAN   chat_completion                                    5,137ms  → final response
GEN    litellm_request (memory) 254in/13out               1,279ms  $0.00005
```

The agent loaded the skill, ran `obsidian search query="DS10540"` (16.9s for IPC cold
start), got "No matches found", tried again with different syntax, got nothing, reported
failure. Never tried `obsidian files`, `obsidian folders`, or `list_dir`.

**Trace 12 (`36fb5d80`) — Most expensive single trace, $0.064:**

```
SPAN   request                                           25,021ms
SPAN   classify (gpt-4o-mini)                             2,831ms  $0.00009
GEN    chat_completion (gpt-4o)  5,547in/16out            1,793ms  $0.014  → load_skill
TOOL   tool:load_skill                                       18ms
GEN    chat_completion (gpt-4o)  9,833in/23out            2,438ms  $0.025  → exec
TOOL   tool:exec                                         11,883ms
GEN    chat_completion (gpt-4o)  9,874in/56out            3,198ms  $0.025  → final response
GEN    litellm_request (memory)                             869ms  $0.00005
```

Three LLM calls to gpt-4o at ~$0.02 each. The PM role triggered gpt-4o model switch,
making the same failing search 50x more expensive than with gpt-4o-mini.

**Trace 13 (`bb7dbb86`) — "Capital of France" test, $0.076:**

```
SPAN   request                                           15,765ms
GEN    classify (gpt-4o-mini)    473in/34out              2,290ms  $0.00009
GEN    chat_completion (gpt-4o)  30,013in/8out            7,046ms  $0.075  ← 30K TOKENS
SPAN   verify (gpt-4o-2024-08-06)                           565ms  $0.0005
```

**30,000 prompt tokens** sent to gpt-4o for "What is the capital of France?" The system
prompt (identity + role + bootstrap + memory + skills + security) filled 30K tokens.
The answer was 8 tokens. Cost: $0.076.

**Trace 8 (`f530e04b`) — Verifier false positive:**

```
SPAN   request                                           18,746ms
SPAN   classify                                           1,830ms  $0.00009
SPAN   chat_completion                                    6,038ms  → response (no tools)
SPAN   verify                                             7,249ms
  GEN  litellm_request (initial verify)  216in/41out      1,392ms  $0.00006
  SPAN revision                                           5,848ms
    GEN litellm_request (revision)       3,543in/49out    5,847ms  $0.0006
GEN    litellm_request (memory)                           2,443ms  $0.00007
```

The verifier gave score=1 with comment "assumes specific user directory structure that
may not apply to all users." But the vault path IS a confirmed fact stored in memory.
The verifier triggered a 5.8s revision pass costing $0.0006 to rewrite a correct answer.

### Cost Analysis

| Category | Traces | Cost | % of Total |
|----------|--------|------|------------|
| PM role (gpt-4o) | 5 | **$0.142** | **91%** |
| General role (gpt-4o-mini) | 6 | $0.008 | 5% |
| No role (routing disabled) | 2 | $0.0003 | <1% |
| Classification overhead | 10 | $0.001 | <1% |
| Memory extraction | 13 | $0.001 | <1% |
| Verification + revision | 5 | $0.004 | 3% |
| **Total** | **13** | **$0.156** | **100%** |

The correct solution (2 commands, gpt-4o-mini) would cost ~$0.001.
**The agent spent 156x more than necessary.**

### Verification Scores

| Score | Trace | Comment |
|-------|-------|---------|
| 5 (pass) | `6ac042db` | Vault path verified |
| 5 (pass) | `9ce1173a` | Vault path verified |
| **1 (fail)** | `f530e04b` | "assumes specific user directory structure" ← FALSE POSITIVE |
| **1 (fail)** | `227dbb37` | "assumes specific user profile and file structure" ← FALSE POSITIVE |
| 5 (pass) | `bb7dbb86` | "Capital of France" verified |

### Latency Analysis

| Metric | Value |
|--------|-------|
| Average trace latency | 23.5s |
| Worst trace | 55.1s (PM role, cold Obsidian IPC) |
| Best trace | 7.7s (single LLM call) |
| Cumulative user wait | ~5 minutes across all attempts |
| Elapsed real time | 12+ hours (first attempt Mar 26 22:35, last Mar 27 10:45) |

---

## Part 4: Session Conversation Replay

### Session 1 (`web_a70d3fa3`, 09:42-09:45 EDT)

**User:** "Summarize details in Obsidian for DS10540"

**Agent flow:**
1. Loaded obsidian-cli skill
2. Ran `obsidian search query="DS10540" format=json` — **exit code 1** (format=json
   flag not supported in this build)
3. Retried: `obsidian search query="DS10540"` — **"No matches found"**
4. Told user: "I wasn't able to find any notes matching 'DS10540'"

**User:** "Do you know where is the vault?"
- Agent correctly identified: `C:\Users\C95071414\Documents\Project Management`
- Routing: classified as `general` (0.7 confidence)

**User:** "The details for the project is in that vault"
- Agent tried `obsidian list "Project Management"` — **error: command "list" not found**
- Tried `obsidian open "Project Management"` — **error: missing required parameter**
- Tried `obsidian open "C:\Users\..."` — **same error**
- Gave up, asked user for specific file names

**4 tool calls, all wrong. Never tried `obsidian files folder="DS10540"`,
`obsidian folders`, or `list_dir`.**

### Session 2 (`web_1583547f`, 10:01-10:02 EDT)

**User:** "Summarize details in Obsidian for DS10540" (identical, new session)

**Agent flow:**
1. Loaded obsidian-cli skill
2. Ran `obsidian search query="DS10540" format=json` — **"No matches found"**
3. Told user: no matches found

**User:** "Do you know where is the vault?" (typo: "t evault")
- Correctly identified vault
- Routing: classified as `pm` (0.8 confidence) — **wrong role, triggered gpt-4o**

**User:** "The project details are in that vault"
- Ran `obsidian search query="DS10540" format=json --vault "C:\Users\..."` —
  **"No matches found"**
- Routing: classified as `general` (0.7 confidence)

**Same approach, same failure. Added --vault flag but still used search (content search)
instead of files/folders (structural lookup).**

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

**Same approach, fifth session. The agent learned NOTHING across sessions.**

### Cross-Session Pattern

| Session | Approach | Result | Alternative Tried? |
|---------|----------|--------|--------------------|
| Mar 26 evening | `obsidian search` | No matches | No |
| Mar 26 evening follow-up | `obsidian search` + list/open | Errors | No (wrong commands) |
| Session 1 | `obsidian search` | No matches | No |
| Session 1 follow-up | `obsidian search` with format/vault | No matches | No |
| Session 2 | `obsidian search` | No matches | No |
| Session 2 follow-up | `obsidian search` with --vault | No matches | No |
| Session 3 | `obsidian search` | No matches | No |
| Session 3 follow-up | `obsidian search` with --vault | No matches | No |

**8 attempts. Same tool. Same failure. Zero adaptation.**

---

## Part 5: Root Cause Analysis — The First Major Finding

After presenting the trace analysis and session replay, the user asked:

> "This is failing over and over again. I believe there is a structural or conceptual
> issue in our existing design. You are also an agent and you are capable of selecting
> the right tools and get the right data. What mechanisms do you have that are missing
> in my agent to do the same?"

This question shifted the analysis from "what went wrong" to "what's structurally missing."

### How Claude Code (Me) Solved the Same Task

When given the same problem, I did:

```
Step 1: ls "$HOME/Documents/Project Management/"
→ Result: Shows DS10540/ folder

Step 2: cat "DS10540/Opportunity Brief.md"
→ Result: File content

Done. 2 commands. Correct answer.
```

### The 8 Missing Mechanisms

By comparing my behavior with the nanobot agent's, 8 structural mechanisms were identified:

#### Mechanism 1: Pre-Action Reasoning (Chain of Thought)

**What I have:** Before every tool call, I have an internal thinking step:
```
User wants to "summarize details in Obsidian for DS10540"
→ This means: find files related to DS10540, read them, summarize
→ Step 1: Where are they? DS10540 could be a folder name, file name, or content term
→ Step 2: Try the most structural approach first — check if it's a folder
→ Step 3: Read files inside, then summarize
```

**What the agent lacks:** Goes directly from user message → tool call. The PAOR "Plan"
phase plans which tool to call, not what the problem structure is.

**Solution:** Add a mandatory decomposition step in the system prompt:
```
Before calling any tool, answer:
1. What exactly does the user need?
2. What is the search target? (content keyword? file name? folder name?)
3. Which tool matches the target type?
4. What will I do if the first attempt returns nothing?
```

#### Mechanism 2: Tool Descriptions That Guide Selection

**What I have:** My tools have descriptions that include WHEN to use and WHEN NOT:
```
Glob: "Use this tool when you need to find files by name patterns"
Grep: "Use for search tasks" (content search)
Read: "Reads a file from the local filesystem"
```

**What the agent has:** A single `exec` tool that does everything ("Execute a shell
command"), plus a 440-line skill dump listing commands by category. No selection heuristic.

**Solution:** Purpose-typed descriptions with anti-patterns:
```
list_dir: "List files and folders. Prefer over search when looking
          for something by project code or folder name."
```

#### Mechanism 3: Adaptive Failure Response

**What I have:** My system prompt says "If your approach is blocked, do not attempt to
brute force... consider alternative approaches." Empty results are treated as signal.

```
obsidian search returned nothing
→ But user says the data exists
→ Therefore my search approach is wrong, not the data
→ "DS10540" might not be in file content — it might be a folder name
→ Try: list folders, check for DS10540 as a structural element
```

**What the agent does:** Reports "No matches found" to the user. When pushed, retries
the same approach with minor variations (`--vault` flag).

**Solution:** Empty-result reflection prompt:
```
When a tool returns no results:
STOP. "No results" means your APPROACH may be wrong, not that the data
doesn't exist. Consider alternative target types. Try at least one
alternative before reporting failure.
```

#### Mechanism 4: Multi-Tool Repertoire With Fallback Chains

**What I have:** When primary tool fails, I fall back to lower-level tools:
```
Obsidian search fails → ls the vault directory → grep the files → cat the file
```

**What the agent has:** Operates exclusively within the loaded skill's command set. Never
drops down to `list_dir` or `read_file`.

**Solution:** System prompt guidance:
```
Skills provide specialized tools. But your base tools (list_dir, read_file)
always work. If a skill's commands fail, fall back to the filesystem.
The filesystem is always ground truth.
```

#### Mechanism 5: Parallel Exploration

**What I have:** I can launch multiple tool calls simultaneously:
```
# In a single turn:
- ls the vault directory
- obsidian search query="DS10540"
- obsidian folders
```

**What the agent has:** Sequential single-tool-call execution. Each failed attempt costs
3-10s before trying something else.

**Solution:** Enable parallel tool calls in the LLM API configuration + guidance to
explore multiple approaches simultaneously.

#### Mechanism 6: Contextual Tool Selection (Not Pattern Matching)

**What I have:** I parse "Summarize details for DS10540" as:
- "Summarize" → I'll need to read content and synthesize
- "DS10540" → an identifier (project code)
- "in Obsidian" → data is in an Obsidian vault
This gives me: find files by identifier → read → synthesize.

**What the agent does:** Pattern-matches "find info about DS10540" → `obsidian search
query="DS10540"`. The agent maps "find information" to "search command" reflexively.

**Solution:** Task decomposition in the system prompt + entity type recognition:
"Project codes and identifiers are often folder or file names, not content."

#### Mechanism 7: Cross-Session Strategy Learning

**What I have:** Auto-memory saves non-obvious learnings across conversations.

**What the agent lacks:** Memory saves facts ("vault is at PM") but not strategies
("obsidian search only searches content — use `files folder=X` for folder lookups").
This is why the same failure repeated across 5 sessions.

**Solution:** Procedural memory tier that stores tool-use strategies, not just facts.

#### Mechanism 8: Informed Verification

**What I have:** Verification is implicit — I check my own work against tool results
in the same context.

**What the agent has:** Separate verifier that sees the response but NOT the memory
context. Caused false positives: vault path scored 1/5.

**Solution:** Either inline self-check (same context) or pass memory to the verifier.

---

## Part 6: The Second Major Question — Architecture Comparison

The user then asked:

> "Based on this analysis, let's assume we start with a blank sheet for a new agent
> design. How would you design the agent architecture to accomplish all of this
> effectively? Think in best practices, other projects, industry best solutions,
> long term and improved maintainability... be exhaustive and critical. Then after
> the analysis and proposal, looking at the current structure of the project. Is it
> worth to keep it, refactor, or simply redesign it from scratch?"

### Design Principles From First Principles

#### Principle 1: Reasoning Is the Product, Not Orchestration

The ReAct pattern (Yao et al., 2023) demonstrated that interleaving reasoning traces
with actions dramatically improves agent performance. Most agent frameworks get this
backwards — they invest in routing, delegation, multi-agent coordination while the
actual reasoning step is just "call the LLM and see what tool it picks."

#### Principle 2: Strategies, Not Just Facts

Cognitive science distinguishes three types of knowledge:
- **Declarative**: Facts ("the vault is at C:\Users\...")
- **Procedural**: Strategies ("to find projects by code, list folders first")
- **Episodic**: Experiences ("last time search failed for folder names")

Nanobot has excellent declarative memory. Zero procedural memory.

#### Principle 3: Progressive Refinement, Not Single-Shot

The best agents form hypotheses, take small exploratory actions, update understanding,
repeat. Not: "pick a tool → call it → report result."

#### Principle 4: Tools Are Typed by Purpose, Not Just by API

When I select tools, I choose based on purpose categories:
- "Find by name" → Glob
- "Find by content" → Grep
- "Read known file" → Read

The nanobot agent has `exec` (do anything) — which is purpose-less.

#### Principle 5: Simplicity Beats Sophistication

| Agent | Architecture | Key Strength |
|-------|-------------|-------------|
| Claude Code | Single agent, extended thinking, rich tools | Reasoning quality |
| Cursor | Single agent, codebase-aware context | Context quality |
| Devin | Simple planner + executor loop | Plan-then-execute |
| OpenAI Codex | Single agent, sandboxed execution | Tool reliability |
| LangGraph | Explicit state machine | Predictable flow |

**None use multi-role routing. None use intent classification to switch models.**

### The Blank-Sheet Architecture

**Core Loop:** Think → Plan → Act → Observe → Reflect (but with real reasoning, not
keyword heuristics)

**Tool Intelligence:** Purpose-typed descriptions with negative selection

**Memory:** Three tiers (declarative + procedural + working)

**Skills:** Decision trees, not reference manuals

**Verification:** Inline with full context, not separate call

### Keep vs Refactor vs Rewrite

```
Current total codebase: ~15,000 LOC

Keep as-is:          ~9,700 LOC  (65%)  — infrastructure layers
Rework:              ~1,850 LOC  (12%)  — cognitive core
Remove:              ~1,390 LOC  ( 9%)  — dead routing code
New:                   ~800 LOC  ( 5%)  — guardrails, procedural memory, prompts
Unchanged other:     ~1,260 LOC  ( 9%)
```

**Verdict: Major refactor, not rewrite.** The infrastructure is genuinely good. The
problem is concentrated in the cognitive core.

> "Your infrastructure is a Formula 1 chassis. The engine (cognitive loop) needs a
> redesign. You don't scrap the chassis to fix the engine."

---

## Part 7: The Third Major Question — Agent Loop Deep Dive

The user then asked:

> "Let's say we just focus on the agent system, the PAOR, the loop... I'm seeing it
> getting more and more complex over time. Let's say I ask you the same question, and
> I ask you to compare it with your inner logic. What are the industry best solutions,
> long term and for improved maintenance. Be exhaustive and critical. After the analysis
> and looking at the existing project. Is it worth moving to a different structure or
> architecture? Refactor, redesign, or start from scratch?"

### What the PAOR Loop Actually Does

After reading every line of the 497-line TurnOrchestrator:

```python
# Pseudocode of the ACTUAL logic (stripped of naming)
while iteration < max_iterations:
    if context_too_large:
        compress_messages()

    response = call_llm(messages, tools)

    if llm_error:
        retry_or_break()
        continue

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

| Phase | Suggests | Actually Does |
|-------|----------|---------------|
| **Plan** | Reasoning about approach | One-shot keyword heuristic checking for "and", "then", "build" |
| **Act** | Intelligent tool selection | Standard tool execution (same as every framework) |
| **Observe** | Evaluating results | Adding tool results to messages (bookkeeping) |
| **Reflect** | Strategy evaluation | Injecting delegation nudges (90% delegation logic) |

The `reflect.md` prompt in its entirety:
```
Briefly reflect: did the tool results above achieve your goal? If not,
state what went wrong and what you will try next. If yes, produce the
final answer for the user.
```

One sentence. That's the entire "reflection."

### How My Loop (Claude Code) Works

```
[THINKING - before any tool call]
The user wants details about DS10540 from Obsidian.
DS10540 looks like a project code — probably a folder name.
I should check the vault structure first, not search content.
Let me ls the vault directory to see if DS10540 is a folder.

[ACT]
Tool: ls "$HOME/Documents/Project Management/"
→ Result: shows DS10540/ folder

[THINKING - after result]
DS10540 is a folder with files inside.
Let me read the files.

[ACT]
Tool: cat "DS10540/Opportunity Brief.md"
→ Result: file content

[THINKING - after result]
I have the content. Let me summarize.

[RESPOND]
Summary of DS10540...
```

**The critical difference: my reasoning happens INSIDE the LLM call, not as an external
state machine.** There is no "ReflectPhase" object. The model reasons natively because:

1. My tool descriptions tell me WHEN to use each tool
2. My system prompt tells me to consider alternatives
3. I have extended thinking that lets me reason before acting
4. I can call multiple tools in parallel

### What Earns Its Keep vs What Doesn't

**Earns its keep (~1,160 LOC):**
- Tool execution pipeline: ~400 LOC
- Context compression: ~370 LOC
- Streaming LLM caller: ~150 LOC
- Failure tracking + budget: ~100 LOC
- LLM error handling: ~70 LOC
- Observability spans: ~50 LOC
- Max iterations + wall time: ~20 LOC

**Does NOT earn its keep (~1,241 LOC):**
- DelegationAdvisor integration: ~200 LOC
- ReflectPhase class: ~130 LOC
- Plan enforcement: ~40 LOC
- `_needs_planning()` heuristic: ~25 LOC
- Role-switching machinery: ~200 LOC
- Classification result tracking: ~30 LOC
- Nudge prompts (8 files): ~50 LOC
- Verifier (separate LLM call): ~476 LOC
- Recovery attempt: ~60 LOC

### The Damning Comparison

`tool_loop.py` (168 lines), used by subagents, is closer to industry best practice:

```python
async def run_tool_loop(provider, tools, messages, model, ...):
    while iteration < max_iterations:
        response = await provider.chat(messages, tools=tool_defs)
        if response.tool_calls:
            execute_batch()
            add_results_to_messages()
        else:
            return response.content
    return await provider.chat(messages, tools=None)  # fallback
```

168 lines. No phases. No delegation advisor. No plan enforcement. Works for every
subagent task.

### The Fundamental Design Error

> The nanobot agent system invested in **orchestration complexity** (what happens between
> LLM calls) instead of **reasoning quality** (what happens inside LLM calls).

The industry has converged: **simple loop, smart prompt, capable model.** The orchestration
framework handles mechanics. The intelligence comes from the model's reasoning, guided by
well-crafted prompts.

---

## Part 8: Design Decisions

Four questions were asked, each with options, trade-offs, and a recommendation:

### Question 1: Model Assumptions

> (A) Model-agnostic — must work with any model including weak ones
> (B) Capable-model-first — design for gpt-4o/Claude, degrade for weaker
> (C) Single model target

**Chosen: (A) Model-agnostic.** Can't rely on extended thinking or native parallel calls.
Must enforce reasoning through structure.

### Question 2: Sub-Agent / Delegation

> (A) Pure single agent — remove all delegation
> (B) Single agent with optional spawning — keep lightweight sub-agents
> (C) Keep delegation as-is

**Chosen: (B) Single agent with optional spawning.** The existing `tool_loop.py` pattern
stays for task parallelism. Routing/roles/advisor go away.

### Question 3: Verification Strategy

> (A) Prompt-only self-check — zero extra calls
> (B) Structured self-check — one extra call, same context
> (C) Configurable — prompt-only default, structured optional

**Chosen: (C) Configurable.** Weak models may not follow prompt-only self-checks.
Having a structural option gives a safety net without mandating cost.

### Question 4: Reasoning Enforcement

> (A) Prompt-driven — system prompt instructions, simple loop
> (B) Code-enforced — explicit states, mandatory reasoning steps
> (C) Layered — prompt baseline + code-enforced guardrails on failure

**Chosen: (C) Layered.** Smart models flow through without overhead. Weak models get
progressively stronger interventions. The guardrails are reactive, not proactive.

### How the Three Layers Work Together

The guardrails are the **safety net**, not the intelligence:

**Layer 1 — Prompt Architecture (proactive):** Structured reasoning protocol teaches the
model to decompose tasks before acting. Zero extra LLM calls. Where most improvement lives.

**Layer 2 — Context Quality (proactive):** Purpose-typed tool descriptions, skill decision
trees, procedural memory from past sessions. Better info in = better decisions out.

**Layer 3 — Guardrails (reactive):** Fire only when Layers 1-2 fail. Detect patterns
(empty results, repeated strategies, skill tunnel vision) and inject corrections.

**The feedback loop:**
```
SESSION 1:
  Layer 1 (prompt): "What am I looking for? A project code..."
  Model: ignores protocol → obsidian search → empty
  Layer 3 (guardrail): empty-result intervention fires
  Model: tries list_dir → finds DS10540/ → reads files → success
  Post-session: strategy saved to procedural memory

SESSION 2:
  Layer 2 (context): "Strategy: project codes are folder names, use list_dir"
  Layer 1 (prompt): "What am I looking for? A project code..."
  Model: reads strategy → list_dir → success
  Layer 3 (guardrail): never fires
```

The system gets smarter over time.

### Approach Selection

Three approaches were evaluated:

**Approach 1: Minimal Loop + Rich Prompt ("Claude Code Pattern")**
Simple loop, all intelligence in prompts. Rejected — model-agnostic means can't rely
on prompt-only.

**Approach 2: Explicit State Machine ("LangGraph Pattern")**
UNDERSTAND → STRATEGIZE → ACT → EVALUATE with code-enforced transitions. Rejected —
becomes the new PAOR problem as features accumulate on each state.

**Approach 3: Adaptive Loop with Guardrail Escalation ("Layered Pattern")** ← CHOSEN
Simple core loop + modular guardrail checks. Happy path is simple. Guardrails fire
only on detected failure patterns. Best of both: simple code, structural safety net.

---

## Part 9: The Complete Design (9 Sections)

Each section was presented individually and approved before proceeding.

### Section 1: Architecture Overview & Core Patterns

Four layers: Entry (MessageProcessor), Cognitive Loop (TurnRunner), Guardrails
(GuardrailChain), Prompt (ContextBuilder + Contributors).

Five governing patterns:
1. The Loop Is Dumb, The Prompt Is Smart
2. Guardrails Are Plugins, Not States
3. Context Is Layered and Composable
4. Memory Has Three Tiers
5. Feedback Loops Close the Learning Gap

### Section 2: The Cognitive Loop (TurnRunner)

Simple tool-use loop (~200 LOC) replacing TurnOrchestrator (497 LOC):

```
async def run(state: TurnState) -> TurnResult:
    while state.iteration < max_iterations:
        state.iteration += 1
        if wall_time_exceeded: break
        if context_over_budget: compress(messages)
        response = call_llm(messages, tools)
        if llm_error: handle_error(); continue
        if response.has_tool_calls:
            results = execute_batch(response.tool_calls)
            add_results_to_messages()
            track_failures()
            update_working_memory(results)
            intervention = guardrail_chain.check(state)
            if intervention: inject(intervention)
            continue
        final_content = response.content
        break
    if verification_enabled:
        final_content = self_check(final_content, messages)
    return TurnResult(content, tools_used, messages, tokens)
```

New TurnState with working memory:
```python
@dataclass(slots=True)
class TurnState:
    messages: list[dict]
    user_text: str
    iteration: int = 0
    tools_used: list[str]
    disabled_tools: set[str]
    tracker: ToolCallTracker
    tool_results_log: list[ToolAttempt]  # NEW
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
    output_empty: bool
    output_snippet: str
    iteration: int
```

Configurable self-check: prompt-only default, structured mode via
`verification.mode = "structured"` (one extra LLM call, same context).

### Section 3: The Guardrail Layer

```python
@dataclass(slots=True, frozen=True)
class Intervention:
    source: str
    message: str
    severity: str        # "hint" | "directive" | "override"
    strategy_tag: str | None = None

class Guardrail(Protocol):
    @property
    def name(self) -> str: ...
    def check(self, state: TurnState, latest: list[ToolAttempt]) -> Intervention | None: ...

class GuardrailChain:
    def __init__(self, guardrails: list[Guardrail]) -> None: ...
    def check(self, state, latest) -> Intervention | None:
        # First intervention wins
```

Five guardrails (full implementations in detailed design doc):
1. **FailureEscalation** — disables tools after N failures
2. **NoProgressBudget** — stops after 4+ iterations with no data
3. **RepeatedStrategyDetection** — breaks same-tool-same-args loops
4. **EmptyResultRecovery** — suggests alternatives when search returns nothing
5. **SkillTunnelVision** — suggests base tools when exec-only fails

Extension pattern: new class + tests + register in factory. No changes to loop or chain.

### Section 4: The Prompt Layer

11-section system prompt:
1. Identity (identity.md)
2. Reasoning Protocol (reasoning.md — NEW)
3. Tool Guide (tool_guide.md — NEW)
4. Strategies (ProceduralMemoryContributor — NEW)
5. Memory (DeclarativeMemoryContributor)
6. Bootstrap (workspace files)
7. Feedback (past corrections)
8. Active Skills (always=true)
9. Skills Summary (on-demand load)
10. Self-Check (conditional)
11. Security (prompt injection boundary)

ContextContributor protocol:
```python
class ContextContributor(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def order(self) -> int: ...
    async def contribute(self, *, workspace, config, query) -> str | None: ...
```

New reasoning.md (full text):
```markdown
## Before Taking Action
1. What does the user need? (find/read/create/modify/summarize)
2. What am I looking for? (folder name? file content? metadata?)
3. Which tool matches the target type?
4. What is my fallback?

## When a Tool Returns Empty Results
STOP. Your approach may be wrong. Try fallback before reporting failure.

## Fallback Principle
Base tools (list_dir, read_file) always work. Filesystem is ground truth.
```

New tool_guide.md (full text):
```markdown
| Intent | Tool | Anti-pattern |
|---|---|---|
| Find by name | list_dir | Do NOT use search |
| Search content | exec with grep | Do NOT use for names |
| Read known file | read_file | Do NOT guess paths |
| Explore structure | list_dir first | Do NOT search blind |
| Skill command | exec | Check decision guide |
```

Updated tool descriptions with purpose + anti-patterns.
Skill decision trees: decision guide first, reference second.
Compression priority: never compress reasoning/security, compress bootstrap/feedback early.

### Section 5: Memory Interface (Three Tiers)

Tier 1 Declarative (existing, unchanged): facts, entities, SQLite.

Tier 2 Procedural (new):
```python
@dataclass(slots=True)
class Strategy:
    id: str
    domain: str          # "obsidian", "github", "filesystem"
    task_type: str       # "find_by_name", "search_content"
    strategy: str        # the reusable instruction
    context: str         # why this works
    source: str          # "guardrail_recovery" | "user_correction"
    confidence: float    # 0.0-1.0
    created_at: datetime
    last_used: datetime
    use_count: int
    success_count: int
```

SQL:
```sql
CREATE TABLE strategies (
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
```

Write: StrategyExtractor (from guardrail recoveries + user feedback).
Read: retrieve by domain + task_type, inject before declarative memory.
Confidence: +0.1 on success, -0.05 on failure, prune below 0.1.

Tier 3 Working (per-turn, not persisted): `tool_results_log` on TurnState.

### Section 6: Entry Layer & Composition

MessageProcessor simplified to ~400 LOC (pipeline: session → slash → memory → context →
run → save → extract strategies → assemble). Factory simplified to ~350 LOC. All
components under 7 params. MemoryServices groups memory + strategy extractor.

Complete request flow and downward-only dependency graph documented.

### Section 7: 15 Structural Patterns

1. Loop Is Dumb, Prompt Is Smart
2. Guardrails Are Plugins, Not States
3. Context Is Layered and Composable
4. Memory Has Three Tiers
5. Feedback Loops Close the Learning Gap
6. Stable Core / Volatile Edge
7. One File, One Reason to Change
8. Protocols at Boundaries, Concrete Inside
9. Three Extension Points (guardrails, contributors, prompts)
10. Growth Limits (guardrail count ≤ 10, contributors ≤ 15)
11. Observable by Default
12. No Implicit Coupling
13. Prompt Changes Are Code Changes
14. Design for Deletion
15. Test by Contract, Not Implementation

### Section 8: Migration Path

6 phases: Delete → Introduce → Rewire → Prompts → Memory → Cleanup.
Feature-flag cutover in Phase 3. Phase 4 parallelizable with Phase 3.
Net: ~5,500 → ~2,385 LOC (57% reduction).

### Section 9: Testing Strategy

Contract tests (behavioral guarantees), integration tests (ScriptedProvider DS10540
scenario), guardrail unit tests (synthetic state), Langfuse observability checks.

---

## Part 10: Success Criteria

1. DS10540 litmus test passes on first attempt
2. No guardrail fires on the happy path (capable models)
3. Weak models recover via guardrails
4. Cross-session learning works (Session 2 succeeds without guardrails)
5. Cost reduction (no verifier call, no classification)
6. Latency reduction (fewer iterations)
7. `make check` passes clean
8. Langfuse traces show improvement over time

---

## Part 11: Deliverables

| Document | Path | Lines |
|----------|------|-------|
| Architectural Blueprint (Spec) | `specs/2026-03-27-agent-cognitive-redesign.md` | 746 |
| Phase 1 Implementation Plan | `plans/2026-03-27-phase1-delete-dead-code.md` | 894 |
| Analysis Report | `reports/2026-03-27-agent-cognitive-redesign-report.md` | 916 |
| Detailed Design | `reports/2026-03-27-agent-cognitive-redesign-detailed-design.md` | 1,976 |
| This Document | `reports/2026-03-27-complete-analysis-and-design.md` | — |

8 memory records created. 3 feedback patterns saved. Worktree ready for Phase 1 execution.
