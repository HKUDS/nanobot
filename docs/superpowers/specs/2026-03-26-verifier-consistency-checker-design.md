# Verifier Redesign: Fact-Checker → Consistency Checker

**Date**: 2026-03-26
**Status**: Approved
**Scope**: `nanobot/agent/verifier.py`, `nanobot/templates/prompts/critique.md`

## Problem

The `AnswerVerifier` critique step receives only the user's question and the
candidate answer — no evidence from tool execution or memory retrieval. The
critique LLM (acting as a "fact-checker") has no ground truth to check against,
so it judges answers using its own training data. For personal, local, or
tool-derived data, this produces false positives: correct answers get flagged
as "unsupported claims" and rewritten with hedging language.

This affects all nanobot's primary use cases — memory-backed answers, tool
execution results, local file access — not just tool-backed answers.

### Example

User asks: "Do you know where is the vault?"
Agent runs `obsidian vault path` → gets `Project Management` at
`C:\Users\...\Documents\Project Management` (12 files, 5 folders).
Agent answers with the correct vault details.

Verifier critique (gpt-4o-mini) sees only Q+A, flags confidence=1:
"assumes a specific user profile and file structure without confirmation."

Answer is rewritten to: "I cannot confirm if it specifically belongs to you."

## Solution: Evidence-Aware Consistency Checking

Transform the critique from a blind fact-checker into a consistency checker
that verifies the answer against the evidence the agent actually used.

### Approach

1. Extract evidence from `state.messages` (tool results + memory items)
2. Pass evidence alongside Q+A to the critique prompt
3. Rewrite the critique prompt to check consistency with evidence

No changes to the verifier's method signature, the turn orchestrator, or any
other subsystem. The change is entirely within `verifier.py` and `critique.md`.

## Design

### 1. Evidence Extraction

New private method `_extract_evidence(messages: list[dict]) -> str` in
`verifier.py`.

**Tool evidence**: Walk messages from the last `role: "user"` message forward
(current turn only). For each `role: "tool"` message:

```
[tool:<name>] <arguments summary> → <output, truncated to 500 chars>
```

The arguments summary is found by looking backwards for the `role: "assistant"`
message whose `tool_calls` contains a matching `tool_call_id`.

**Memory evidence**: Parse the system prompt (`messages[0]["content"]`) for
known memory section headers:
- `## Relevant Semantic Memories`
- `## Relevant Episodic Memories`
- `## Profile Memory`

Extract bullet-point lines under each header until the next `##` header.
Include as-is (they're already formatted).

**Scope**: Only current-turn tool results are extracted — not history. This
prevents pulling stale evidence from previous turns.

**Budget**:
- Tool evidence: up to 4000 chars
- Memory evidence: up to 2000 chars
- Total cap: 6000 chars
- If tool evidence exceeds 4000, oldest tool results are dropped first
- Individual tool outputs truncated to 500 chars with "..." suffix

**Empty case**: If no evidence is found (no tools used, no memory retrieved),
returns empty string. The verifier behaves exactly as today — no regression.

### 2. Critique Prompt Rewrite

Replace `nanobot/templates/prompts/critique.md`:

```
You are a consistency checker reviewing an AI assistant's answer.

You are given the user's question, the assistant's candidate answer, and
optionally the evidence the assistant used (tool outputs, memory items).

When evidence is provided:
- Verify the answer is consistent with the evidence
- Flag claims that contradict the evidence
- Flag claims not supported by any provided evidence
- Do NOT question whether the evidence itself is correct — it was retrieved
  from the user's own system

When no evidence is provided:
- Flag unsupported claims or factual errors based on general knowledge
- Flag missing caveats for uncertain claims

Respond with ONLY a JSON object (no markdown fencing):
{"confidence": <1-5>, "issues": ["issue1", ...]}
confidence 5 = fully consistent, 1 = contradicts evidence or likely wrong.
If the answer is solid, return an empty issues list.
```

Key changes from current prompt:
- "Fact-checker" → "consistency checker"
- Evidence-aware with explicit instructions per scenario
- Explicit instruction not to question tool/memory data
- Same JSON output format — no parsing changes needed

### 3. Verify Method Changes

Only the `critique_messages` construction changes in `verify()`:

```python
evidence = self._extract_evidence(messages)

critique_content = f"User's question: {user_text}\n\nAssistant's answer: {candidate}"
if evidence:
    critique_content += f"\n\nEvidence retrieved:\n{evidence}"

critique_messages = [
    {"role": "system", "content": prompts.get("critique")},
    {"role": "user", "content": critique_content},
]
```

**Unchanged**:
- Method signature — no new parameters, no Protocol changes
- `should_force_verification()` logic
- Revision path (still uses full `messages` for revision LLM call)
- Error handling, Langfuse scoring
- Confidence threshold (`>= 3 and not issues`)

### 4. Files Changed

| File | Change |
|------|--------|
| `nanobot/agent/verifier.py` | Add `_extract_evidence()`, modify critique_messages construction |
| `nanobot/templates/prompts/critique.md` | Rewrite prompt |

No changes to: `turn_orchestrator.py`, `message_processor.py`, `turn_types.py`,
`context.py`, or any other file.

## Testing

Unit tests (in existing test file or new `tests/test_verifier_evidence.py`):

1. **`test_extract_evidence_with_tool_results`** — Messages with tool call +
   result pairs → formatted tool lines with name, args, truncated output.

2. **`test_extract_evidence_with_memory`** — System prompt containing memory
   sections → memory lines extracted.

3. **`test_extract_evidence_with_both`** — Tool results + memory → both
   appear, tool evidence first.

4. **`test_extract_evidence_empty`** — No tool results, no memory → empty
   string.

5. **`test_extract_evidence_truncation`** — Large tool output (>500 chars) →
   individual results truncated with "...".

6. **`test_extract_evidence_budget`** — Many tool results exceeding 4000 char
   budget → oldest dropped.

7. **`test_extract_evidence_current_turn_only`** — Tool results in history
   AND current turn → only current turn extracted.

8. **`test_verify_passes_evidence_to_critique`** — Mock LLM provider, verify
   critique call receives evidence in user content.

9. **`test_verify_no_evidence_falls_back`** — No evidence → critique has same
   format as before. Regression test.

## Token Cost Impact

- Evidence summary adds ~100-300 tokens to the critique call
- Negligible compared to the main turn's token usage (typically 5000-25000)
- No additional LLM calls — same two calls (critique + optional revision)
