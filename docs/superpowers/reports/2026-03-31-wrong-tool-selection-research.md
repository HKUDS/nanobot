# 2026-03-31 Wrong Tool Selection & Unsolicited Write — Research Report

> Problem: Agent selects `obsidian search` (content search) instead of `obsidian folders`
> (structural navigation) for project code lookups. Also creates files when only asked to
> read/summarize.
> Scope: Root cause in nanobot, industry research, recommendations.

---

## 1. The Problem Observed

**Wrong tool**: User asks "Summarize details in Obsidian for project DS10540." DS10540 is
a folder name. Agent uses `obsidian search` (content search) which returns empty or wrong
documents. The correct tool is `obsidian folders` then `obsidian files folder="DS10540"`.

**Unsolicited write**: User asks to "summarize" but agent runs `obsidian create` to make
a summary file. Safety guard blocks `path=` syntax but `name=` syntax bypasses it.

---

## 2. Why LLMs Pick the Wrong Tool (Research Findings)

### 2.1 Tool Selection Bias Is Measured and Real

**BiasBusters (ICLR 2026)**: Evaluated 7 LLMs. Found substantial bias driven by:
- Semantic alignment between query text and tool metadata (strongest factor)
- Positional bias (tools earlier in the list are over-selected by ~9.5%)
- Pre-training exposure (models favor APIs they saw more during training)
- Small perturbations to tool descriptions significantly shift choices

**ToolTweak (NDSS 2026)**: Proved tool descriptions are the primary control surface.
Selection rates changed from 20% to 81% through description manipulation alone.

### 2.2 Why "Search" Always Wins Over "Navigate"

1. **Training data bias**: "Finding information" = "searching" in training corpora
   (Google, Stack Overflow, docs). Directory navigation is much rarer.
2. **Semantic gravity**: A tool named `search` has enormous pull when the query
   contains "find" or "look for."
3. **Absence of structural reasoning**: LLMs don't naturally reason about entity
   type (folder name? file content?) before selecting a tool.
4. **Generic exec obscures the choice**: When both `search` and `folders` are
   subcommands of `exec`, the model sees one tool, not two competing options.

### 2.3 How Agents Fail (900 Trace Analysis)

From "How Do LLMs Fail In Agentic Scenarios?" (2025):
- **Premature action without grounding**: Agent acts before understanding what
  it's looking for — jumps to "search" without type-classification
- **Over-helpfulness**: Substitutes missing entities rather than exploring
- **Context pollution**: Wrong tool results pollute context, model doubles down

---

## 3. Root Cause in Nanobot

### 3.1 No Obsidian-CLI SKILL.md Exists in the Repository

The obsidian-cli skill is loaded from `~/.nanobot/workspace/skills/obsidian-skills/`,
an external git submodule. It has a SKILL.md but it's a **command reference**, not a
**decision guide**. There is no "when to use search vs folders" decision tree at the
top of the skill.

### 3.2 The Guidance Exists But Is Not Enforced

| Source | What It Says | Why It Fails |
|--------|-------------|-------------|
| `tool_guide.md` | "Find by name → list_dir, not search" | Buried in a table; model doesn't recall during execution |
| `reasoning.md` | "Project code → likely a FOLDER" | Model acknowledges it in [REASONING] then ignores it |
| `list_dir` description | "Prefer over search for folder names" | Good but competes with exec's generic description |
| `exec` description | "Use for skill commands" | Too generic; doesn't say which skill commands |

**The agent emits a correct [REASONING] block** identifying DS10540 as a folder, then
still picks `obsidian search`. The reasoning protocol influences thinking but not action.

### 3.3 The Generic `exec` Tool Is an Architectural Weakness

Research consensus: **specific, well-described tools outperform generic execution shells**
for tool selection accuracy (BiasBusters, StackOne, DiaFORGE). When `obsidian search`
and `obsidian folders` are both just `exec` with different arguments, the model sees
one tool, not two competing options with different purposes.

### 3.4 Unsolicited Write: Missing Intent Classification

No framework currently does upfront intent classification to restrict tool access per
query. The closest approaches:

- **MiniScope** (UC Berkeley, 2025): Computes minimum privilege scope before execution
- **Claude Code auto mode**: Per-tool-call classifier, evaluates post-hoc
- **Progent** (2025): DSL-based privilege policies, 0% attack success

Nanobot has none of these. The `readonly` flag on tools exists but is only used for
execution parallelization, never for access restriction.

---

## 4. Industry Solutions

### 4.1 Tool Description Engineering (Tier 1 — Highest ROI)

From Anthropic, StackOne, and ToolTweak research:

**Negative selection** — telling the model when NOT to use a tool:
```
search: "Searches file CONTENT. Do NOT use for finding files/folders by name."
list_dir: "Lists files/folders by NAME. Use for project codes and identifiers."
```

**StackOne finding**: "Improving tool descriptions had a larger impact on agent accuracy
than improving agent logic itself."

### 4.2 Semantic Pre-Filtering of Tools (Tier 1)

From AWS and BiasBusters:
- Filter tools to a relevant subset before presenting to the LLM
- AWS reports **86.4% error reduction** and **89% token reduction**
- BiasBusters proposes: filter to relevant subset, then sample uniformly

### 4.3 Decision Trees in Skill Descriptions (Tier 2)

From nanobot's cognitive architecture and LlamaIndex Router pattern:
```
## Decision Guide (FIRST section in every skill)
| You want to... | Use this command | NOT this |
|---|---|---|
| Find by name/code | obsidian folders | obsidian search |
| Search content | obsidian search | obsidian folders |
```

### 4.4 Separate Tools Instead of Generic Exec (Tier 2)

From MCP approach and Claude Code:
- Each command becomes its own tool with its own description
- Model sees `obsidian_search`, `obsidian_folders`, `obsidian_files` as distinct tools
- Enables per-tool negative selection and description engineering

### 4.5 Chain-of-Thought Before Tool Selection (Tier 2)

From AutoTool (ICCV 2025 Best Paper):
- Inserting valid rationales between reasoning and tool invocation improves accuracy
- 6.4% improvement in math, 4.5% QA, 7.7% code gen
- Nanobot's [REASONING] block is the right design; it needs enforcement, not just guidance

### 4.6 Write Intent Classification (Tier 2)

| Approach | Source | How It Works |
|----------|--------|-------------|
| Per-turn tool filtering | MiniScope | Classify query as read/write, restrict tool set |
| Per-tool-call classifier | Claude Code auto | Evaluate each tool call against user intent |
| Prompt-level guidance | Most frameworks | "Don't create files unless explicitly asked" |
| Pre-execution hook | LlamaIndex/AgentFS | Intercept and block write calls on read queries |

---

## 5. How Claude Code Solves Both Problems

### Tool Selection
- **Dedicated tools**: `Read`, `Grep`, `Glob` instead of generic `exec`
- **Anti-pattern guidance**: "If you want to read a file, use Read, NOT the Agent tool"
- **Mandatory skill invocation**: "If a skill might apply, YOU MUST invoke it"
- **Red flag table**: "Let me just do this one thing first" → "Check BEFORE doing anything"

### Write Prevention
- **Default supervised mode**: Write operations require explicit "Y" from user
- **Auto mode classifier**: Background model reviews each action pre-execution
- **Plan mode**: Read-only exploration, no writes at all
- **Reversibility framework**: "Carefully consider the reversibility and blast radius"

---

## 6. Recommendations for Nanobot

### Immediate (Prompt-Only, Zero Code)

**6.1 Add write-intent check to reasoning protocol** — `reasoning.md`:
```
5. Do I need to create, modify, or delete anything?
   - "summarize", "find", "search", "read", "list", "explain" → NO writes
   - "create", "write", "edit", "save", "update", "delete" → writes allowed
   - If NO, do NOT call write_file, exec with create/write, or any mutation command
```

**6.2 Strengthen the skill decision tree** — The obsidian-cli SKILL.md needs a
decision guide as its FIRST section:
```
## Decision Guide
| You want to... | Command | NOT this |
|---|---|---|
| Find project folder by code | obsidian folders | obsidian search |
| List files in a project | obsidian files folder="X" | obsidian search |
| Search text inside files | obsidian search query="X" | obsidian folders |
| Read a specific file | obsidian read file="X" | - |
```

### Short-Term (Small Code Changes)

**6.3 Add application-level write patterns to shell denylist** — `shell.py`:
```python
r"\bobsidian\s+(create|delete|move|rename)\b",
```

**6.4 Add negative selection to exec tool description** — `shell.py`:
```
"When running Obsidian commands: use 'folders' for name-based lookups,
'search' only for content keywords. Do NOT use 'create' unless the user
explicitly asked to create a file."
```

### Medium-Term (Architecture Changes)

**6.5 Expose skill commands as separate tools** — Instead of routing everything
through `exec`, register `obsidian_search`, `obsidian_folders`, `obsidian_files`,
`obsidian_read` as individual tools with purpose-specific descriptions. This is the
MCP pattern and the highest-impact structural change.

**6.6 Add per-turn tool filtering by intent** — Classify query as read-only or
read-write in `MessageProcessor` before building `TurnState`. If read-only, add
write tools to `disabled_tools`. The existing tool filtering in `turn_runner.py`
already handles this.

**6.7 Add a "wrong tool type" guardrail** — Fire when: user asks for folder/name
lookup, agent uses content search, result is empty. Intervention: "You used a content
search for a name-based lookup. Use obsidian folders or list_dir instead."

---

## 7. The Layered Defense Model

```
Layer 1: TOOL ARCHITECTURE (most reliable)
  → Separate tools per command (not generic exec)
  → Purpose-specific descriptions with negative selection
  → Semantic pre-filtering (only show relevant tools)

Layer 2: PROMPT ARCHITECTURE (moderate reliability)
  → Decision trees in skill descriptions (FIRST section)
  → Write-intent check in reasoning protocol
  → Negative selection in tool_guide.md (already exists, needs reinforcement)

Layer 3: GUARDRAILS (reactive)
  → "Wrong tool type" guardrail (name lookup → used search → empty)
  → Write-without-intent guardrail
  → Existing empty_result_recovery (already works)

Layer 4: STRUCTURAL ENFORCEMENT (strongest)
  → Per-turn tool filtering by intent classification
  → Shell denylist for application-level write commands
  → Pre-execution hook for write operations on read-only queries
```

---

## References

- BiasBusters: Tool Selection Bias in LLMs (ICLR 2026)
- ToolTweak: Attack on Tool Selection (NDSS 2026)
- AutoTool: Dynamic Tool Selection for Agentic Reasoning (ICCV 2025)
- DiaFORGE: Disambiguation-Centric Finetuning (SAP Research 2025)
- How Do LLMs Fail In Agentic Scenarios? (2025, 900 trace analysis)
- MiniScope: Least Privilege Framework for Tool Calling Agents (UC Berkeley 2025)
- Progent: Programmable Privilege Control for LLM Agents (2025)
- Writing Effective Tools for AI Agents (Anthropic Engineering)
- AI Agent Testing: Failures from Thousands of Tools (StackOne)
- Reduce Agent Errors with Semantic Tool Selection (AWS)
- Claude Code Auto Mode (Anthropic)
- OWASP Top 10 for LLM Applications 2025 (Excessive Agency)
