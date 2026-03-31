# 2026-03-31 Source Conflation Research — Comprehensive Report

> Problem: The agent blends facts from declarative memory, wrongly-retrieved tool results,
> and model training data into a plausible but incorrect composite answer.
> Scope: Root cause in nanobot, industry state of the art, Claude-specific mechanisms, recommendations.

---

## 1. The Problem Observed

The nanobot agent was asked: "Summarize details in Obsidian for project DS10540."

The final answer contained:

| Claim | Actual Source | Correct? |
|-------|-------------|----------|
| "Planned Duration: 186 days" | Declarative memory (from earlier session) | Yes, but unverified |
| "Integrating digital signatures into ENOVIA" | Declarative memory | Yes, but unverified |
| "Agent Cognitive Core Redesign" | Tool result (wrong document from wrong vault) | No — this is about nanobot, not DS10540 |
| "15 structural design patterns" | Tool result (wrong document) | No |
| "Opportunity Brief.md, Timekeeping.md" | Declarative memory (file names from past session) | Yes, but never read this session |

The agent **never read the actual DS10540 project files**. It read architecture documents
that mention DS10540 as a case study, then blended those with memorized facts from prior
sessions. The result was a plausible but internally inconsistent summary that the user
could not distinguish from a correct one.

---

## 2. Root Cause in Nanobot

### 2.1 The Context Is an Undifferentiated Blob

The LLM receives a system prompt containing:

```
[identity section]
[reasoning protocol]
[tool guide]
[strategies]         ← no source labels
[memory facts]       ← labeled only with retrieval method (src=vector), not origin
[bootstrap files]    ← labeled with filename headers
[skills]
[security]
```

Memory facts look like:
```
- [2026-03-25] (fact) DS10540 planned duration is 186 days [sem=0.45, rec=0.62, src=vector]
```

The `src=vector` indicates the **retrieval mechanism** (vector search), NOT the original
source (which session, which tool, which document). The agent cannot determine whether
this fact was:
- Extracted from a tool result in a prior session
- Manually annotated
- Inferred by the agent during consolidation

### 2.2 Memory Instruction Conflict

The `memory_header.md` template says:

```
**Answer from these facts first.** Use the exact names, regions, and terms below.
```

But `identity.md` (updated in PR #100) says:

```
Memory provides background context — it does NOT replace accessing external systems.
When memory and external data conflict, trust the external data source.
```

These are **competing instructions**. The memory header says "answer from facts first"
while identity says "memory is just background context." The model must choose, and
smaller models default to whichever instruction is closer to the relevant content in
the prompt.

### 2.3 Tool Results Lose Provenance in History

When tool results are added to the message list, they carry source metadata:
```json
{"role": "tool", "tool_call_id": "...", "name": "exec", "content": "<tool_result>...</tool_result>"}
```

But when these messages become part of conversation history in subsequent turns, they are
indistinguishable from any other message. The `<tool_result>` tags provide some structural
boundary, but the LLM treats them as inline context once they scroll up in the conversation.

### 2.4 No Conflict Detection

There is no mechanism to detect when memory facts and tool results disagree. In the
DS10540 case:
- Memory: "DS10540 is about digital signatures in ENOVIA"
- Tool result: "DS10540 appears in Agent Cognitive Core Redesign report"

These describe different things entirely, but no guardrail detects "wrong source" —
only "empty result" and "repeated strategy."

### 2.5 Self-Check Is Insufficient

The `self_check.md` prompt says:
```
4. For memory-sourced claims — are you attributing them?
```

This is post-hoc advice that assumes the model can retroactively distinguish which facts
came from memory vs. tools. With an undifferentiated context blob, this is unreliable.

---

## 3. Why LLMs Conflate Sources (Mechanistic Explanation)

Research from ReDeEP (ICLR 2025) using mechanistic interpretability explains the
underlying mechanism:

- **Copying Heads** (attention heads) preserve external context (tool results, documents)
  in the model's residual stream
- **Knowledge FFNs** (feed-forward networks in later layers) inject parametric knowledge
  (training data) into the residual stream
- **Conflation occurs when Knowledge FFNs overpower Copying Heads** — the model's
  internal knowledge overwrites or supplements the external context

Key finding: "Hallucinated responses exhibit higher parametric knowledge scores than
truthful ones, particularly in later layers."

**Practical implication**: There is no way to "turn off" parametric knowledge during
generation. Every mitigation is an approximation that reduces the probability of
conflation but cannot eliminate it.

---

## 4. Industry State of the Art

### 4.1 Structural Enforcement (Most Reliable)

| Solution | Vendor | How It Works |
|----------|--------|-------------|
| **Citations API** | Anthropic | Documents provided with `citations.enabled=true`; response contains `cite` blocks with exact character spans pointing to source documents. 15% higher recall vs prompt-based citation. |
| **Grounding Supports** | Google Gemini | Response includes `groundingSupports` metadata linking specific response substrings (by char index) to source URLs/documents. |
| **FIDES IFC** | Microsoft Research | Formal taint-label tracking through agent tool calls. Quarantined LLM for untrusted data. 3.5x improvement on AgentDojo benchmarks. |
| **CORPGEN Sub-Agent Isolation** | Microsoft Research | Complex operations run in isolated sub-agent contexts. Returns only structured results, preventing cross-task memory contamination. |

### 4.2 Prompt Architecture (Moderate Reliability)

| Technique | Description | Effectiveness |
|-----------|-------------|---------------|
| XML tag isolation | Wrap sources in distinct tags (`<tool_result>`, `<memory>`, `<user_context>`) | Good — helps model distinguish structurally |
| Source labeling | Prefix each data block with origin: `[FROM TOOL: exec]` | Moderate — helps attribution |
| Negative selection | "Do NOT use this tool for X" in tool descriptions | Good — creates exclusion zones |
| Extract-then-synthesize | "First extract direct quotes, then synthesize" | Good — forces grounding before generation |
| Competing instruction elimination | Remove conflicting instructions (e.g., "prefer memory" vs "use tools") | Critical — #1 cause of wrong-source answers |

### 4.3 Verification (Post-Hoc)

| Approach | Source | How It Works |
|----------|--------|-------------|
| **Chain of Verification (CoVe)** | ACL 2024 | Generate answer → formulate verification questions → answer them in isolated context → revise |
| **Classification-based grounding** | ASAPP | ML classifier checks if proposed response is grounded in retrieved sources; reprompts if not |
| **ContextCite** | MIT | Context ablations: remove parts of context and observe response changes to trace provenance |
| **Self-check prompts** | Common practice | "Does every claim trace to a tool result?" — works for strong models, ignored by weak ones |

### 4.4 Memory Management (Preventive)

| Approach | Source | How It Works |
|----------|--------|-------------|
| **Mem0 conflict detection** | Mem0 (2025) | LLM compares new facts to similar existing memories: ADD, UPDATE, DELETE, or NOOP |
| **Tiered memory** | CORPGEN | Working memory (active task only), structured long-term, semantic memory — isolated contexts |
| **Source provenance** | Not widely implemented | Store original source (tool name, session ID) with each memory event for attribution |
| **Temporal decay** | Mem0, various | Older memories lose influence unless consistently useful |

---

## 5. Claude-Specific Mechanisms

### 5.1 Citations API

The most impactful mechanism for nanobot. Key properties:
- Wrap tool results as `document` content blocks with `citations.enabled = true`
- Response contains `cite` blocks with exact character spans
- Uncited claims become structurally identifiable — framework can flag or reject them
- Works across all Claude model sizes
- **Limitation**: Works on documents in messages, not directly on tool call results

### 5.2 Extended Thinking

Claude's extended thinking (chain-of-thought) helps with source tracking:
- Thinking trace can show "Tool A returned X, Tool B returned Y, these conflict"
- Higher `budget_tokens` gives more reasoning space for source attribution
- Does not structurally prevent conflation — just makes reasoning more auditable

### 5.3 Model Size and Grounding Reliability

| Model | Grounding Behavior |
|-------|-------------------|
| Claude Opus | Best at following complex grounding instructions |
| Claude Sonnet | Good with explicit instructions; may blend with subtle prompts |
| Claude Haiku | Most likely to take shortcuts; needs structural forcing |

For Haiku, `tool_choice` forcing and structural mechanisms (citations) are more
important than prompt instructions.

---

## 6. How Claude Code Solves This

Claude Code (the tool powering this conversation) has several mechanisms:

1. **Dedicated tools**: `Read`, `Grep`, `Glob` instead of generic `exec` — each tool's
   purpose is unambiguous, creating clear provenance
2. **Memory labeled as stale**: "Memory records can become stale over time... verify
   that the memory is still correct by reading the current state"
3. **Structural skill enforcement**: "YOU DO NOT HAVE A CHOICE. YOU MUST USE IT"
4. **Anti-pattern guidance**: "do NOT use search for name lookups" in tool descriptions
5. **Separation of memory types**: user memories, feedback memories, project memories,
   reference memories — each with explicit type labels

---

## 7. Recommendations for Nanobot

Ordered by impact and feasibility:

### 7.1 Immediate: Fix Competing Instructions (Prompt-Only)

**Cost: Zero. Impact: High.**

Remove "Answer from these facts first" from `memory_header.md`. Replace with:

```markdown
# Memory (Background Context)

These are facts from previous conversations. They may be outdated.
Use them as hints for WHERE to look, not as authoritative answers.
Always verify memory facts with fresh tool results before citing them.

{memory}
```

This eliminates the competing instruction that tells the agent to prefer memory over tools.

### 7.2 Short-Term: Add Source Labels to Memory and Tool Results

**Cost: ~20 lines. Impact: Medium.**

Label each section with its source type:

```
[MEMORY — from previous sessions, may be stale]
- [2026-03-25] DS10540 planned duration is 186 days

[TOOL RESULTS — fresh data from this conversation]
<tool_result>...</tool_result>
```

Update `context_assembler.py` to add `[MEMORY]` prefix. The `<tool_result>` tags already
exist but should be reinforced with a label.

### 7.3 Short-Term: Add Source-Tracking to Reasoning Protocol

**Cost: Prompt change only. Impact: Medium.**

Add a 5th question to the `[REASONING]` block:

```
5. Source check: Am I citing memory or tool results? If memory, have I verified it?
```

### 7.4 Medium-Term: Integrate Anthropic Citations API

**Cost: Moderate (~100 lines). Impact: Very High.**

Wrap tool results as `document` content blocks with `citations.enabled = true`.
The response will structurally cite which tool result each claim comes from.
Uncited claims can be flagged or rejected by the framework.

This is the single most impactful structural change. It transforms grounding from a
behavioral request (prompt) into a structural constraint (API response format).

**Limitation**: Requires restructuring how tool results are presented to the model.
The current `role: "tool"` messages would need to be converted to `document` blocks
in the user message for the citations to attach.

### 7.5 Medium-Term: Add a "Wrong Source" Guardrail

**Cost: ~50 lines. Impact: Medium.**

A new guardrail that checks: "Did the agent answer from memory without calling any
data-retrieval tool?" If the final answer contains claims that only appear in the
memory section (not in any tool result), inject an intervention:

```
"Your answer appears to include facts from memory that were not verified
with a tool this session. Call the appropriate tool to verify before responding."
```

### 7.6 Long-Term: Source Provenance on Memory Events

**Cost: Schema change + ~100 lines. Impact: High (prevents future conflation).**

Add `source_tool`, `source_session_id` fields to the `events` table in
`MemoryDatabase`. When the micro-extractor saves facts from a conversation, record
which tool produced the data. When memory is injected into the prompt, include the
source:

```
- [2026-03-25] (fact, from: obsidian-cli session 687d) DS10540 planned duration is 186 days
```

---

## 8. The Layered Defense Model

No single layer is sufficient. The industry is converging on:

```
Layer 1: STRUCTURAL ENFORCEMENT (most reliable)
  → Anthropic Citations API
  → Dedicated tools (not generic exec)
  → Sub-agent isolation for different data sources

Layer 2: PROMPT ARCHITECTURE (moderate reliability)
  → Source labels on memory vs tool results
  → Eliminate competing instructions
  → Source-tracking in reasoning protocol
  → "Extract quotes first, synthesize second"

Layer 3: VERIFICATION (post-hoc)
  → Self-check with source verification
  → "Wrong source" guardrail
  → Chain of Verification for critical claims

Layer 4: MEMORY MANAGEMENT (preventive)
  → Source provenance on stored facts
  → Conflict detection on ingestion (Mem0 pattern)
  → Temporal decay for stale facts
```

**Nanobot currently has**: Partial Layer 2 (some source labels, self-check) and
partial Layer 3 (guardrails, but none for wrong-source). The highest-impact
improvements are fixing the competing instruction (Layer 2), integrating the
Citations API (Layer 1), and adding source provenance to memory (Layer 4).

---

## References

- ReDeEP: Detecting Hallucination in RAG via Mechanistic Interpretability (ICLR 2025)
- Anthropic Citations API Documentation
- Google Gemini Grounding with Search
- Microsoft FIDES: Securing AI Agents with Information-Flow Control (2025)
- CORPGEN: Microsoft Research (2026)
- Chain of Verification Reduces Hallucination in LLMs (ACL 2024)
- ContextCite: MIT (2024)
- ASAPP: Preventing Hallucinations in Generative AI Agent
- Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (2025)
- OWASP LLM Prompt Injection Prevention Cheat Sheet
- A Survey on Hallucination in LLMs (ACM TOIS 2025)
