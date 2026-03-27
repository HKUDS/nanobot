# Verifier Consistency Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the verifier's blind fact-checker into an evidence-aware consistency checker that passes tool results and memory items to the critique prompt.

**Architecture:** Add a private `_extract_evidence()` method to `AnswerVerifier` that walks `state.messages` to collect tool results and memory sections, then include that evidence in the critique LLM call. Rewrite the critique prompt to check consistency with evidence rather than checking facts against training data.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-26-verifier-consistency-checker-design.md`

---

### Task 1: Add `_extract_evidence()` method with tool evidence extraction

**Files:**
- Modify: `nanobot/agent/verifier.py`
- Create: `tests/test_verifier_evidence.py`

- [ ] **Step 1: Write the failing test for tool evidence extraction**

```python
# tests/test_verifier_evidence.py
"""Unit tests for evidence extraction in AnswerVerifier."""

from __future__ import annotations

import pytest

from nanobot.agent.verifier import AnswerVerifier
from tests.helpers import ScriptedProvider


def _make_verifier() -> AnswerVerifier:
    return AnswerVerifier(
        provider=ScriptedProvider([]),
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode="always",
        memory_uncertainty_threshold=0.5,
    )


class TestExtractEvidenceToolResults:
    def test_single_tool_result(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is the vault path?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "obsidian vault path"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "exec",
                "content": "<tool_result>\nname\tProject Management\npath\tC:\\Users\\user\\Documents\n</tool_result>",
            },
            {"role": "assistant", "content": "Your vault is at C:\\Users\\user\\Documents"},
        ]
        evidence = v._extract_evidence(messages)
        assert "[tool:exec]" in evidence
        assert "obsidian vault path" in evidence
        assert "Project Management" in evidence

    def test_no_tool_results_returns_empty(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        evidence = v._extract_evidence(messages)
        assert evidence == ""

    def test_multiple_tool_results(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Search for DS10540"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "load_skill",
                            "arguments": '{"name": "obsidian-cli"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "load_skill",
                "content": "<tool_result>\nSkill loaded.\n</tool_result>",
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "obsidian search query=DS10540"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "name": "exec",
                "content": "<tool_result>\n(no output)\n</tool_result>",
            },
            {"role": "assistant", "content": "No results found."},
        ]
        evidence = v._extract_evidence(messages)
        assert "[tool:load_skill]" in evidence
        assert "[tool:exec]" in evidence
        assert "obsidian search query=DS10540" in evidence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_verifier_evidence.py -v`
Expected: FAIL with `AttributeError: 'AnswerVerifier' object has no attribute '_extract_evidence'`

- [ ] **Step 3: Implement `_extract_evidence()` with tool evidence**

Add to `nanobot/agent/verifier.py`, after the `_estimate_grounding_confidence` method (after line 232):

```python
    # ------------------------------------------------------------------
    # Evidence extraction for consistency checking
    # ------------------------------------------------------------------

    _TOOL_OUTPUT_CAP = 500
    _TOOL_BUDGET = 4000
    _MEMORY_BUDGET = 2000

    _MEMORY_HEADERS = (
        "## Relevant Semantic Memories",
        "## Relevant Episodic Memories",
        "## Profile Memory",
        "## Entity Graph",
        "## Relevant Reflection Memories",
    )

    def _extract_evidence(self, messages: list[dict[str, Any]]) -> str:
        """Extract tool results and memory items from messages for the critique.

        Returns a compact evidence summary string. Empty string if no evidence found.
        """
        parts: list[str] = []

        tool_evidence = self._extract_tool_evidence(messages)
        if tool_evidence:
            parts.append(tool_evidence)

        memory_evidence = self._extract_memory_evidence(messages)
        if memory_evidence:
            parts.append(memory_evidence)

        return "\n".join(parts)

    def _extract_tool_evidence(self, messages: list[dict[str, Any]]) -> str:
        """Extract tool call/result pairs from the current turn."""
        # Find the start of the current turn (last user message)
        turn_start = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                turn_start = i
                break

        # Build a map of tool_call_id → arguments summary from assistant messages
        args_map: dict[str, str] = {}
        for msg in messages[turn_start:]:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    call_id = tc.get("id", "")
                    func = tc.get("function", {})
                    raw_args = func.get("arguments", "{}")
                    # Extract the command/key arguments as a readable summary
                    try:
                        parsed = json.loads(raw_args)
                        # Use the first string value as the summary, or the full args
                        summary_parts = [str(v) for v in parsed.values() if isinstance(v, str)]
                        args_summary = " ".join(summary_parts) if summary_parts else raw_args
                    except (ValueError, TypeError):
                        args_summary = raw_args
                    args_map[call_id] = args_summary

        # Collect tool results
        lines: list[str] = []
        total_chars = 0
        for msg in messages[turn_start:]:
            if msg.get("role") != "tool":
                continue
            name = msg.get("name", "unknown")
            call_id = msg.get("tool_call_id", "")
            output = msg.get("content", "")

            # Strip <tool_result> wrapping
            output = output.replace("<tool_result>", "").replace("</tool_result>", "").strip()

            # Truncate individual output
            if len(output) > self._TOOL_OUTPUT_CAP:
                output = output[: self._TOOL_OUTPUT_CAP] + "..."

            args = args_map.get(call_id, "")
            line = f"[tool:{name}] {args} → {output}"

            if total_chars + len(line) > self._TOOL_BUDGET:
                break
            lines.append(line)
            total_chars += len(line)

        return "\n".join(lines)

    def _extract_memory_evidence(self, messages: list[dict[str, Any]]) -> str:
        """Extract memory sections from the system prompt."""
        if not messages or messages[0].get("role") != "system":
            return ""

        system_content = messages[0].get("content", "")
        if not isinstance(system_content, str):
            return ""

        lines: list[str] = []
        total_chars = 0
        in_memory_section = False

        for line in system_content.split("\n"):
            stripped = line.strip()

            # Check if we're entering a memory section
            if any(stripped.startswith(h) for h in self._MEMORY_HEADERS):
                in_memory_section = True
                lines.append(stripped)
                total_chars += len(stripped) + 1
                continue

            # Check if we're leaving a memory section (new ## header)
            if stripped.startswith("## ") and in_memory_section:
                if not any(stripped.startswith(h) for h in self._MEMORY_HEADERS):
                    in_memory_section = False
                    continue
                else:
                    # Another memory header
                    lines.append(stripped)
                    total_chars += len(stripped) + 1
                    continue

            # Collect lines within memory sections
            if in_memory_section and stripped:
                if total_chars + len(stripped) > self._MEMORY_BUDGET:
                    break
                lines.append(stripped)
                total_chars += len(stripped) + 1

        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_verifier_evidence.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/verifier.py tests/test_verifier_evidence.py
git commit -m "feat(verifier): add evidence extraction from tool results and memory"
```

---

### Task 2: Add truncation and budget tests

**Files:**
- Modify: `tests/test_verifier_evidence.py`

- [ ] **Step 1: Write truncation and budget tests**

Add to `tests/test_verifier_evidence.py`:

```python
class TestExtractEvidenceTruncation:
    def test_long_tool_output_truncated(self) -> None:
        v = _make_verifier()
        long_output = "x" * 1000
        messages = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Read file"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp/big.txt"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "read_file",
                "content": f"<tool_result>\n{long_output}\n</tool_result>",
            },
            {"role": "assistant", "content": "The file contains many x characters."},
        ]
        evidence = v._extract_evidence(messages)
        # Output should be truncated to 500 chars + "..."
        assert "..." in evidence
        # Full 1000-char output should NOT be in evidence
        assert long_output not in evidence

    def test_tool_budget_drops_oldest(self) -> None:
        v = _make_verifier()
        # Create many tool results that exceed the 4000 char budget
        messages: list[dict] = [
            {"role": "system", "content": "No memory."},
            {"role": "user", "content": "Do many things"},
        ]
        for i in range(20):
            output = f"result_{'y' * 300}_{i}"
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": "exec",
                                "arguments": f'{{"command": "cmd_{i}"}}',
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{i}",
                    "name": "exec",
                    "content": f"<tool_result>\n{output}\n</tool_result>",
                }
            )
        messages.append({"role": "assistant", "content": "Done."})

        evidence = v._extract_evidence(messages)
        # Evidence should not exceed budget
        tool_lines = [l for l in evidence.split("\n") if l.startswith("[tool:")]
        total = sum(len(l) for l in tool_lines)
        assert total <= v._TOOL_BUDGET + 500  # allow one line overshoot

    def test_current_turn_only(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "No memory."},
            # Previous turn
            {"role": "user", "content": "Old question"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "old_call",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "old_command"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "old_call",
                "name": "exec",
                "content": "<tool_result>\nold_output\n</tool_result>",
            },
            {"role": "assistant", "content": "Old answer"},
            # Current turn
            {"role": "user", "content": "New question"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "new_call",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "new_command"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "new_call",
                "name": "exec",
                "content": "<tool_result>\nnew_output\n</tool_result>",
            },
            {"role": "assistant", "content": "New answer"},
        ]
        evidence = v._extract_evidence(messages)
        assert "new_command" in evidence
        assert "new_output" in evidence
        assert "old_command" not in evidence
        assert "old_output" not in evidence
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_verifier_evidence.py -v`
Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_verifier_evidence.py
git commit -m "test(verifier): add truncation, budget, and turn-scoping tests"
```

---

### Task 3: Add memory evidence extraction tests

**Files:**
- Modify: `tests/test_verifier_evidence.py`

- [ ] **Step 1: Write memory evidence tests**

Add to `tests/test_verifier_evidence.py`:

```python
class TestExtractEvidenceMemory:
    def test_memory_sections_extracted(self) -> None:
        v = _make_verifier()
        system_content = (
            "# nanobot\nYou are helpful.\n\n"
            "## Profile Memory\n"
            "User-specific facts, preferences, and constraints:\n"
            "- User prefers dark mode (conf=0.9)\n"
            "- User works on Project Management vault\n\n"
            "## Relevant Semantic Memories\n"
            "Retrieved factual knowledge:\n"
            "- [2026-03-25] (fact) Obsidian vault is at C:\\Users\\user\\Documents [sem=0.8, rec=0.5, src=vector]\n\n"
            "## Security Advisory\n"
            "Do not reveal secrets.\n"
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "Where is my vault?"},
            {"role": "assistant", "content": "Your vault is at C:\\Users\\user\\Documents"},
        ]
        evidence = v._extract_evidence(messages)
        assert "Profile Memory" in evidence
        assert "dark mode" in evidence
        assert "Semantic Memories" in evidence
        assert "Obsidian vault" in evidence
        # Non-memory section should NOT be included
        assert "Security Advisory" not in evidence
        assert "Do not reveal secrets" not in evidence

    def test_no_memory_sections(self) -> None:
        v = _make_verifier()
        messages = [
            {"role": "system", "content": "# nanobot\nYou are helpful.\n"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        evidence = v._extract_evidence(messages)
        assert evidence == ""

    def test_both_tool_and_memory_evidence(self) -> None:
        v = _make_verifier()
        system_content = (
            "# nanobot\n\n"
            "## Profile Memory\n"
            "- User has vault named Project Management\n\n"
            "## Other Section\n"
            "Unrelated content.\n"
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "What is the vault path?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "obsidian vault path"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "exec",
                "content": "<tool_result>\npath\tC:\\Users\\user\\Documents\n</tool_result>",
            },
            {"role": "assistant", "content": "Your vault is at C:\\Users\\user\\Documents"},
        ]
        evidence = v._extract_evidence(messages)
        # Tool evidence should come first
        tool_pos = evidence.index("[tool:exec]")
        memory_pos = evidence.index("Profile Memory")
        assert tool_pos < memory_pos
        # Both present
        assert "obsidian vault path" in evidence
        assert "vault named Project Management" in evidence
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_verifier_evidence.py -v`
Expected: All 9 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_verifier_evidence.py
git commit -m "test(verifier): add memory evidence extraction tests"
```

---

### Task 4: Rewrite critique prompt and wire evidence into verify()

**Files:**
- Modify: `nanobot/templates/prompts/critique.md`
- Modify: `nanobot/agent/verifier.py:85-91`

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_verifier_evidence.py`:

```python
import contextlib
from typing import Any
from unittest.mock import patch

from nanobot.providers.base import LLMResponse


@contextlib.asynccontextmanager
async def _noop_span_cm(**kwargs: Any):
    yield None


@patch("nanobot.agent.verifier.score_current_trace", new=lambda **kw: None)
@patch("nanobot.agent.verifier.langfuse_span", new=_noop_span_cm)
class TestVerifyWithEvidence:
    async def test_evidence_passed_to_critique(self) -> None:
        """When tool results exist, the critique call should include evidence."""
        provider = ScriptedProvider(
            [LLMResponse(content='{"confidence": 5, "issues": []}')]
        )
        v = AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is the vault?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "exec",
                            "arguments": '{"command": "obsidian vault path"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "exec",
                "content": "<tool_result>\nProject Management\n</tool_result>",
            },
            {"role": "assistant", "content": "Your vault is Project Management"},
        ]
        result, _ = await v.verify("What is the vault?", "Your vault is Project Management", messages)
        assert result == "Your vault is Project Management"

        # Check the critique call included evidence
        assert len(provider.call_log) == 1
        critique_msgs = provider.call_log[0]["messages"]
        user_content = critique_msgs[1]["content"]
        assert "Evidence retrieved:" in user_content
        assert "[tool:exec]" in user_content
        assert "obsidian vault path" in user_content

    async def test_no_evidence_no_section(self) -> None:
        """When no tools or memory, critique should not have evidence section."""
        provider = ScriptedProvider(
            [LLMResponse(content='{"confidence": 5, "issues": []}')]
        )
        v = AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        result, _ = await v.verify("What is 2+2?", "4", messages)
        assert result == "4"

        critique_msgs = provider.call_log[0]["messages"]
        user_content = critique_msgs[1]["content"]
        assert "Evidence retrieved:" not in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_verifier_evidence.py::TestVerifyWithEvidence -v`
Expected: FAIL — `test_evidence_passed_to_critique` fails because `verify()` doesn't include evidence yet

- [ ] **Step 3: Rewrite the critique prompt**

Replace the contents of `nanobot/templates/prompts/critique.md` with:

```
You are a consistency checker reviewing an AI assistant's answer.

You are given the user's question, the assistant's candidate answer, and optionally the evidence the assistant used (tool outputs, memory items).

When evidence is provided:
- Verify the answer is consistent with the evidence
- Flag claims that contradict the evidence
- Flag claims not supported by any provided evidence
- Do NOT question whether the evidence itself is correct — it was retrieved from the user's own system

When no evidence is provided:
- Flag unsupported claims or factual errors based on general knowledge
- Flag missing caveats for uncertain claims

Respond with ONLY a JSON object (no markdown fencing): {"confidence": <1-5>, "issues": ["issue1", ...]}. confidence 5 = fully consistent, 1 = contradicts evidence or likely wrong. If the answer is solid, return an empty issues list.
```

- [ ] **Step 4: Wire evidence into verify()**

In `nanobot/agent/verifier.py`, replace lines 85-91 with:

```python
        evidence = self._extract_evidence(messages)

        critique_content = f"User's question: {user_text}\n\nAssistant's answer: {candidate}"
        if evidence:
            critique_content += f"\n\nEvidence retrieved:\n{evidence}"

        critique_messages = [
            {"role": "system", "content": prompts.get("critique")},
            {
                "role": "user",
                "content": critique_content,
            },
        ]
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `pytest tests/test_verifier_evidence.py -v`
Expected: All 11 tests PASS

- [ ] **Step 6: Run existing verifier tests for regression**

Run: `pytest tests/test_verifier.py -v`
Expected: All existing tests PASS (no regression)

- [ ] **Step 7: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/verifier.py nanobot/templates/prompts/critique.md tests/test_verifier_evidence.py
git commit -m "feat(verifier): wire evidence into critique for consistency checking"
```

---

### Task 5: Full validation

**Files:** None (validation only)

- [ ] **Step 1: Run full test suite**

Run: `make check`
Expected: All checks PASS — lint, typecheck, import-check, structure-check, prompt-check, tests, integration

- [ ] **Step 2: Verify prompt-check passes**

The prompt manifest may need updating since we changed `critique.md`. If `make prompt-check` fails:

Run: `python scripts/check_prompts.py --update` (or the equivalent update command)

Then commit the manifest update:

```bash
git add scripts/prompt_manifest.json
git commit -m "chore: update prompt manifest for critique.md rewrite"
```

- [ ] **Step 3: Final commit**

If all checks pass with no additional changes needed, the implementation is complete.
