# Source Labels & Source-Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `[MEMORY]` and `[TOOL RESULT]` provenance labels throughout the agent's context, and add source-tracking to the reasoning protocol, so the LLM can distinguish stale memory from fresh tool data.

**Architecture:** Pure prompt-layer and context-assembly changes. No new files, no schema changes, no new dependencies. Five files modified: two Python modules (context_assembler.py, context.py) and three prompt templates (memory_header.md, reasoning.md, self_check.md).

**Tech Stack:** Python 3.10+, pytest, ruff, mypy

---

### Task 1: Add Source Labels to Memory Section Headers in context_assembler.py

**Files:**
- Modify: `nanobot/memory/read/context_assembler.py:278-312`
- Test: `tests/test_memory_metadata_policy.py`

- [ ] **Step 1: Update the test assertions to expect new headers**

In `tests/test_memory_metadata_policy.py`, update the three header assertions and the budget test assertions to match the new `[MEMORY — ...]` labeled headers:

```python
# Line 93 — change:
#   assert "## Relevant Semantic Memories" in context
# to:
assert "## Relevant Semantic Memories [MEMORY" in context

# Line 124 — change:
#   assert "## Relevant Episodic Memories" in context
# to:
assert "## Relevant Episodic Memories [MEMORY" in context

# Line 146 — change:
#   assert "## Relevant Reflection Memories" in context
# to:
assert "## Relevant Reflection Memories [MEMORY" in context

# Line 405 — change:
#   assert "## Profile Memory" in context
# to:
assert "## Profile Memory [MEMORY" in context

# Line 407 — change:
#   assert "## Relevant Semantic Memories" in context
# to:
assert "## Relevant Semantic Memories [MEMORY" in context

# Line 409 — change:
#   assert "## Entity Graph" in context
# to:
assert "## Entity Graph [MEMORY" in context
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_memory_metadata_policy.py -v -x`
Expected: FAIL — old headers don't contain `[MEMORY`

- [ ] **Step 3: Update section headers in context_assembler.py**

In `nanobot/memory/read/context_assembler.py`, replace the Phase 4 assembly section (lines ~278-312) with source-labeled headers. Change each header and remove the now-redundant sub-headings:

```python
        # ── Phase 4: assemble in logical presentation order ──

        lines: list[str] = []

        if long_term_text:
            lines.append(
                "## Long-term Memory "
                "[MEMORY — from previous sessions, may be stale]"
            )
            lines.append(long_term_text)

        if fitted_profile_lines:
            lines.append(
                "## Profile Memory "
                "[MEMORY — from previous sessions, may be stale]"
            )
            lines.extend(fitted_profile_lines)

        if semantic_lines:
            lines.append(
                "## Relevant Semantic Memories "
                "[MEMORY — may be stale, verify before citing]"
            )
            lines.extend(semantic_lines)

        if graph_lines:
            lines.append(
                "## Entity Graph "
                "[MEMORY — derived relationships, verify before citing]"
            )
            lines.extend(graph_lines)

        if episodic_lines:
            lines.append(
                "## Relevant Episodic Memories "
                "[MEMORY — past events, verify if still current]"
            )
            lines.extend(episodic_lines)

        if include_reflection and reflection_lines:
            lines.append(
                "## Relevant Reflection Memories "
                "[MEMORY — past reflections]"
            )
            lines.extend(reflection_lines)

        if unresolved_lines:
            lines.append(
                "## Recent Unresolved Tasks/Decisions "
                "[MEMORY — may already be resolved]"
            )
            lines.extend(unresolved_lines)
```

- [ ] **Step 4: Run lint and typecheck**

Run: `cd ../nanobot-feat-source-labels && make lint && make typecheck`
Expected: PASS

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_memory_metadata_policy.py -v`
Expected: PASS — all assertions match new headers

- [ ] **Step 6: Commit**

```bash
cd ../nanobot-feat-source-labels
git add nanobot/memory/read/context_assembler.py tests/test_memory_metadata_policy.py
git commit -m "feat(memory): add [MEMORY] source labels to context assembler section headers"
```

---

### Task 2: Update memory_header.md Template

**Files:**
- Modify: `nanobot/templates/prompts/memory_header.md`

- [ ] **Step 1: Update the template**

Replace the contents of `nanobot/templates/prompts/memory_header.md` with:

```markdown
# Memory [MEMORY — from previous sessions, may be stale]

These are facts from previous conversations. They may be outdated.
Use them as hints for WHERE to look, not as authoritative answers.
Always verify memory facts with fresh tool results before citing them.
Use the exact names, regions, and terms below — do not substitute general knowledge.

{memory}
```

- [ ] **Step 2: Run prompt regression tests**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_prompt_regression.py -v`
Expected: PASS — the regression test checks for "memory" and "knowledge" keywords which are still present

- [ ] **Step 3: Commit**

```bash
cd ../nanobot-feat-source-labels
git add nanobot/templates/prompts/memory_header.md
git commit -m "feat(context): add [MEMORY] source label to memory_header.md template"
```

---

### Task 3: Add [TOOL RESULT] Label to Tool Result Wrapping

**Files:**
- Modify: `nanobot/context/context.py:319-346`
- Test: `tests/test_context_builder.py`

- [ ] **Step 1: Add a test for the new tool result label**

In `tests/test_context_builder.py`, add a new test after the existing `test_add_assistant_and_tool_messages` (around line 73):

```python
def test_tool_result_has_source_label(tmp_path: Path) -> None:
    """Tool results must be labeled with [TOOL RESULT] for source provenance."""
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)
    messages: list[dict] = []

    builder.add_tool_result(
        messages, tool_call_id="1", tool_name="exec", result="hello world"
    )
    content = messages[-1]["content"]
    assert content.startswith("[TOOL RESULT")
    assert "<tool_result>" in content
    assert "hello world" in content


def test_tool_result_already_wrapped_gets_label(tmp_path: Path) -> None:
    """Pre-wrapped tool results still get the [TOOL RESULT] label."""
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)
    messages: list[dict] = []

    builder.add_tool_result(
        messages,
        tool_call_id="1",
        tool_name="read_file",
        result="<tool_result>\nfile content\n</tool_result>",
    )
    content = messages[-1]["content"]
    assert content.startswith("[TOOL RESULT")
    assert "<tool_result>" in content
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_context_builder.py::test_tool_result_has_source_label tests/test_context_builder.py::test_tool_result_already_wrapped_gets_label -v`
Expected: FAIL — current implementation doesn't add `[TOOL RESULT` prefix

- [ ] **Step 3: Update add_tool_result in context.py**

In `nanobot/context/context.py`, update the `add_tool_result` method (lines ~319-346). Replace the wrapping logic:

```python
    def add_tool_result(
        self, messages: list[dict[str, Any]], tool_call_id: str, tool_name: str, result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        The result content is wrapped in ``<tool_result>`` XML tags to create a
        structural boundary between untrusted tool output and agent instructions
        (prompt-injection mitigation, LAN-43).  A ``[TOOL RESULT]`` label is
        prepended for source provenance (source-conflation mitigation).
        Double-wrapping is avoided: if the content is already tagged it is
        passed through with only the label prepended.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        label = "[TOOL RESULT — fresh data from this conversation]"
        if result.startswith("<tool_result>"):
            wrapped = f"{label}\n{result}"
        else:
            wrapped = f"{label}\n<tool_result>\n{result}\n</tool_result>"
        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": wrapped}
        )
        return messages
```

- [ ] **Step 4: Run lint and typecheck**

Run: `cd ../nanobot-feat-source-labels && make lint && make typecheck`
Expected: PASS

- [ ] **Step 5: Run all context builder tests**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_context_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd ../nanobot-feat-source-labels
git add nanobot/context/context.py tests/test_context_builder.py
git commit -m "feat(context): add [TOOL RESULT] source label to tool result wrapping"
```

---

### Task 4: Add Source-Tracking Question to Reasoning Protocol

**Files:**
- Modify: `nanobot/templates/prompts/reasoning.md`

- [ ] **Step 1: Update reasoning.md**

In `nanobot/templates/prompts/reasoning.md`, add question 5 to the `[REASONING]` block. The block currently ends at line 24 with question 4. After question 4, add:

```markdown
5. Source check: Am I about to cite memory or tool results? If memory, have I verified it with a tool?
```

The full `[REASONING]` block format section becomes:

```markdown
Format:

```
[REASONING]
1. What does the user need? <find, read, create, modify, summarize>
2. What am I looking for? <describe the target and its likely type>
   - A project code or identifier → likely a FOLDER or FILE NAME
   - A topic or keyword → likely FILE CONTENT
   - A tag, property, or date → likely METADATA
   - A specific document → likely a FILE PATH
3. Which tool or command matches, and why? <tool choice + reasoning>
   - Find by name → list_dir, or skill commands that list/browse
   - Search content → grep/search commands
   - Read known file → read_file
   - Explore structure → list_dir first, then narrow down
4. What will I try if this returns nothing? <a DIFFERENT approach, not tweaked arguments>
5. Source check: Am I about to cite memory or tool results? If memory, have I verified it with a tool?
[/REASONING]
```

Every question must be answered. Keep each answer to 1-2 lines.
```

- [ ] **Step 2: Run prompt regression tests**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_prompt_regression.py -v`
Expected: PASS — the regression test checks for "tool", "fallback", "target type" keywords which are still present

- [ ] **Step 3: Commit**

```bash
cd ../nanobot-feat-source-labels
git add nanobot/templates/prompts/reasoning.md
git commit -m "feat(context): add source-tracking question to reasoning protocol"
```

---

### Task 5: Strengthen Self-Check Source Attribution

**Files:**
- Modify: `nanobot/templates/prompts/self_check.md`

- [ ] **Step 1: Update self_check.md**

Replace the contents of `nanobot/templates/prompts/self_check.md` with:

```markdown
## Before Sending Your Response

Self-check:
1. Does every factual claim trace to a tool result in this conversation?
2. If reporting "not found" — did you try at least 2 different approaches?
3. Are you stating anything as fact that you didn't verify with a tool?
4. For claims from sections marked [MEMORY] — did you verify them with a tool this session?
   If not, either verify now or attribute them: "Based on previous sessions..."

If any check fails, take the missing action before responding.
```

- [ ] **Step 2: Run prompt regression tests**

Run: `cd ../nanobot-feat-source-labels && python -m pytest tests/test_prompt_regression.py -v`
Expected: PASS — the regression test checks for "claim", "not found", "verified" which are still present

- [ ] **Step 3: Commit**

```bash
cd ../nanobot-feat-source-labels
git add nanobot/templates/prompts/self_check.md
git commit -m "feat(context): strengthen self-check with [MEMORY] label reference"
```

---

### Task 6: Full Validation

- [ ] **Step 1: Run make check**

Run: `cd ../nanobot-feat-source-labels && make check`
Expected: PASS — lint + typecheck + import-check + structure-check + prompt-check + phase-todo-check + doc-check

- [ ] **Step 2: Run full test suite**

Run: `cd ../nanobot-feat-source-labels && make test`
Expected: PASS — all unit tests pass

- [ ] **Step 3: Run doc-check specifically**

Run: `cd ../nanobot-feat-source-labels && make doc-check`
Expected: PASS — no stale references in living docs

- [ ] **Step 4: Final commit (if any fixups needed)**

Only if previous steps required fixes. Otherwise this step is a no-op.
