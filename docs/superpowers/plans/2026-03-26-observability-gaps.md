# Observability Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the instrumentation gaps in Langfuse tracing so that every significant agent operation — tool execution, context compression, verification, delegation, memory pre-checks, and skill injection — records both input and output in Langfuse spans.

**Architecture:** The codebase uses `nanobot/observability/langfuse.py` which exposes three async context managers (`trace_request`, `tool_span`, `span`) and two update functions (`update_current_span`, `score_current_trace`). All are no-ops when Langfuse is disabled. The established pattern for capturing output is: `async with span(...) as obs:` then `if obs is not None: obs.update(output=...)`. Currently only 2 of 8 span sites follow this pattern — the rest discard the `obs` object. Tests mock spans using either `@patch` with `_noop_span_cm` helpers or capture-list side-effects.

**Tech Stack:** Python 3.10+, Langfuse v4 (OTEL-based), pytest, pytest-asyncio

---

## Analysis Summary

### Current State

| Span site | File | Input captured | Output captured | obs.update called |
|-----------|------|:-:|:-:|:-:|
| `trace_request` (root) | `agent/loop.py:266` | Yes (200 chars) | Yes (via message_processor) | Yes (update_current_span) |
| `tool_span` (main path) | `tools/registry.py:149` | Yes (params) | **No** | **No** |
| `tool_span` (subagent path) | `tools/tool_loop.py:106` | Yes (args) | Yes (500 chars) | Yes |
| `span("compress")` | `context/compression.py:309` | **No** | **No** | **No** |
| `span("verify")` | `agent/verifier.py:93` | **No** | **No** | **No** |
| `span("classify")` | `coordination/coordinator.py:215` | Yes (sanitized) | Yes (200 chars) | Yes |
| `span("mission")` | `coordination/mission.py:216` | Yes (200 chars) | Yes (update_current_span) | Yes |
| `span("delegate")` | `coordination/delegation.py:345` | Yes (sanitized) | **No** | **No** |

### Gaps to Fix (ordered by impact)

1. **Tool spans record no output** (`registry.py`) — main agent path tool executions are input-only
2. **Compress span has no input or output** (`compression.py`) — entire compression operation is a black box
3. **Verify span has no input or output** (`verifier.py`) — critique/revision cycle invisible
4. **Token counts missing from root span metadata** (`message_processor.py`) — logged to loguru but not Langfuse
5. **ActPhase batch has no span** (`turn_phases.py`) — batch timing, success/fail counts invisible
6. **ReflectPhase has no span** (`turn_phases.py`) — delegation advice decisions invisible
7. **Memory pre-turn checks have no span** (`message_processor.py`) — conflict detection invisible
8. **Skill injection untraced** (`turn_phases.py`) — which skills injected and when is invisible
9. **Verification revision call has no span** (`verifier.py`) — separate from critique but indistinguishable
10. **Delegation span has no output** (`delegation.py`) — sub-agent result invisible

### File Size Constraints

| File | Current LOC | Budget remaining |
|------|------------|-----------------|
| `turn_phases.py` | 467 | 33 LOC — **tight**, must be minimal |
| `message_processor.py` | 582 | **Already over 500** — cannot add code, only modify existing lines |
| `compression.py` | 356 | 144 LOC — comfortable |
| `registry.py` | 248 | 252 LOC — comfortable |
| `verifier.py` | 318 | 182 LOC — comfortable |
| `langfuse.py` | 477 | 23 LOC — **tight**, do not add to this file |
| `turn_orchestrator.py` | 497 | 3 LOC — **do not touch** |

### Design Decisions

1. **No new files.** All changes are obs.update() calls or metadata additions on existing span sites.
2. **No new span context managers** for turn_phases.py — the LOC budget is too tight. Instead, use `update_current_span()` to annotate the existing root span with batch/reflect metadata.
3. **message_processor.py is over 500 LOC** — only modify existing `update_current_span` call to include token counts. Zero net new lines.
4. **Skill injection**: trace via metadata on the existing root span, not a new span (saves LOC in turn_phases.py).
5. **delegation.py output**: add `obs.update()` inside the existing span context — minimal change.

### Test Strategy

Each gap fix follows the same test pattern already established in `tests/test_observability_plumbing.py`:
- Create a capture-list side-effect for the span context manager
- Run the code path that triggers the span
- Assert the captured span has the expected input/output/metadata

New tests go in `tests/test_observability_plumbing.py` (currently 541 LOC, well within budget).

---

## Tasks

### Task 1: Add output to tool_span in registry.py

The main agent path opens a `tool_span` with `input=params` but never calls `obs.update()`. The subagent path in `tool_loop.py` already does this correctly — we replicate that pattern.

**Files:**
- Modify: `nanobot/tools/registry.py:149-213`
- Test: `tests/test_observability_plumbing.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_observability_plumbing.py`:

```python
class TestToolSpanOutputCaptured:
    """Verify that tool_span records output after execution."""

    @pytest.mark.asyncio
    async def test_tool_span_records_output(self) -> None:
        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class EchoTool(Tool):
            name = "echo"
            description = "echo"
            parameters: dict[str, Any] = {"type": "object", "properties": {}}
            readonly = True

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("hello world")

        registry = ToolRegistry()
        registry.register(EchoTool())

        obs_updates: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            mock_obs = MagicMock()
            mock_obs.update = lambda **kw: obs_updates.append(kw)
            yield mock_obs

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            await registry.execute("echo", {})

        assert len(obs_updates) == 1
        assert obs_updates[0]["output"] == "hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability_plumbing.py::TestToolSpanOutputCaptured -v`
Expected: FAIL — `obs_updates` is empty because `obs.update()` is never called

- [ ] **Step 3: Add obs.update() in registry._execute_inner**

In `nanobot/tools/registry.py`, inside `_execute_inner`, after the result is finalized (around line 193, after Prometheus metrics), add the span output update. The `obs` is already yielded by `async with tool_span(...) as obs:` at line 149 but never used. Change the code to call `obs.update()`:

```python
    async def _execute_inner(self, name: str, tool: Tool, params: dict[str, Any]) -> ToolResult:
        """Run validation and execute, wrapping errors."""
        from nanobot.metrics import tool_calls_total, tool_latency_seconds
        from nanobot.observability.langfuse import tool_span
        from nanobot.observability.tracing import bind_trace

        t0 = time.monotonic()

        async with tool_span(name=name, input=params) as obs:
            try:
                errors = tool.validate_params(params)
                if errors:
                    validation_err = ToolValidationError(name, errors)
                    bind_trace().debug(
                        "Tool {} validation_error duration_ms={:.0f}",
                        name,
                        (time.monotonic() - t0) * 1000,
                    )
                    result = ToolResult.fail(
                        str(validation_err) + self._HINT, error_type="validation"
                    )
                    if obs is not None:
                        obs.update(output=result.output[:500], metadata={"success": False})
                    return result

                raw = await tool.execute(**params)

                # Normalise into ToolResult (supports legacy str returns)
                if isinstance(raw, ToolResult):
                    result = raw
                elif isinstance(raw, str):
                    # Backward compat: detect old-style "Error…" strings.
                    if raw.startswith("Error"):
                        result = ToolResult.fail(raw)
                    else:
                        result = ToolResult.ok(raw)
                else:
                    result = ToolResult.ok(str(raw))

                # Append retry hint for failures
                if not result.success:
                    if not result.output.endswith(self._HINT):
                        result.output += self._HINT

                elapsed = time.monotonic() - t0
                duration_ms = elapsed * 1000
                bind_trace().debug(
                    "Tool {} success={} duration_ms={:.0f}",
                    name,
                    result.success,
                    duration_ms,
                )

                # Prometheus metrics
                tool_calls_total.labels(tool_name=name, success=str(result.success)).inc()
                tool_latency_seconds.labels(tool_name=name).observe(elapsed)

                # Record output on the active Langfuse tool span
                if obs is not None:
                    obs.update(
                        output=result.output[:500],
                        metadata={"success": result.success, "duration_ms": round(duration_ms)},
                    )

                # Cache large successful results and generate summary
                if (
                    result.success
                    and self._cache
                    and tool.cacheable
                    and len(result.output) > self._SUMMARY_THRESHOLD
                ):
                    if tool.summarize:
                        _, result = await self._cache.store_with_summary(
                            name,
                            params,
                            result,
                            provider=self._summary_provider,
                            model=self._summary_model,
                        )
                    else:
                        _, result = self._cache.store_only(name, params, result)

                return result

            except ToolExecutionError as e:
                elapsed = time.monotonic() - t0
                bind_trace().debug(
                    "Tool {} error={} duration_ms={:.0f}",
                    name,
                    e.error_type,
                    elapsed * 1000,
                )
                tool_calls_total.labels(tool_name=name, success="False").inc()
                tool_latency_seconds.labels(tool_name=name).observe(elapsed)
                result = ToolResult.fail(str(e) + self._HINT, error_type=e.error_type)
                if obs is not None:
                    obs.update(
                        output=result.output[:500],
                        metadata={"success": False, "error_type": e.error_type},
                    )
                return result
            except Exception as e:  # crash-barrier: user-provided tool execution
                elapsed = time.monotonic() - t0
                bind_trace().exception(
                    "Tool {} error=unknown duration_ms={:.0f}",
                    name,
                    elapsed * 1000,
                )
                tool_calls_total.labels(tool_name=name, success="False").inc()
                tool_latency_seconds.labels(tool_name=name).observe(elapsed)
                result = ToolResult.fail(
                    f"Error executing {name}: {str(e)}" + self._HINT, error_type="unknown"
                )
                if obs is not None:
                    obs.update(
                        output=result.output[:500],
                        metadata={"success": False, "error_type": "unknown"},
                    )
                return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestToolSpanOutputCaptured -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/tools/registry.py tests/test_observability_plumbing.py
git commit -m "feat(observability): record tool span output in main agent path

tool_span in ToolRegistry._execute_inner now calls obs.update() with
the tool result output (truncated to 500 chars), success status, and
duration. Previously only the subagent path (tool_loop.py) recorded
tool output — the main agent path was input-only."
```

---

### Task 2: Enrich compression span with input and output

The `compress` span in `summarize_and_compress()` passes only metadata — no input or output. The LLM-based compression is a significant cost and context mutation that should be fully visible.

**Files:**
- Modify: `nanobot/context/compression.py:308-323`
- Test: `tests/test_observability_plumbing.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_observability_plumbing.py`:

```python
class TestCompressSpanEnriched:
    """Verify that compress span records input (message count) and output (summary)."""

    @pytest.mark.asyncio
    async def test_compress_span_has_input_and_output(self) -> None:
        from nanobot.context.compression import summarize_and_compress

        class FakeProvider:
            async def chat(self, *, messages, tools, model, temperature, max_tokens):
                from types import SimpleNamespace
                return SimpleNamespace(content="Summary of earlier conversation.")

        obs_updates: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            mock_obs = MagicMock()
            mock_obs.update = lambda **kw: obs_updates.append(kw)
            yield mock_obs

        # Build messages that exceed the budget to trigger LLM summarization
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            *[{"role": "user", "content": f"Message {i} " * 50} for i in range(10)],
            *[{"role": "assistant", "content": f"Reply {i} " * 50} for i in range(10)],
            {"role": "user", "content": "Latest question"},
        ]

        with patch("nanobot.context.compression.langfuse_span", side_effect=fake_span):
            await summarize_and_compress(
                messages,
                max_tokens=200,  # Very low budget to force summarization
                provider=FakeProvider(),
                model="test-model",
            )

        assert len(obs_updates) >= 1
        update = obs_updates[0]
        assert "output" in update
        assert "Summary" in update["output"]
        assert "metadata" in update
        assert "compression_ratio" in update["metadata"]
        assert "before_tokens" in update["metadata"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability_plumbing.py::TestCompressSpanEnriched -v`
Expected: FAIL — `obs_updates` is empty

- [ ] **Step 3: Enrich the compress span**

In `nanobot/context/compression.py`, modify the `async with langfuse_span(...)` block (around lines 308-322) to:
1. Pass `input` with message counts
2. Capture the `obs` object via `as obs`
3. Call `obs.update()` with the summary output and compression stats

Replace lines 308-322:

```python
        before_tokens = estimate_messages_tokens(messages)
        try:
            async with langfuse_span(
                name="compress",
                input={"middle_msgs": len(middle), "total_msgs": len(messages)},
                metadata={"model": model, "before_tokens": before_tokens},
            ) as obs:
                resp = await provider.chat(
                    messages=[
                        {"role": "system", "content": prompts.get("compress")},
                        {"role": "user", "content": digest},
                    ],
                    tools=None,
                    model=model,
                    temperature=0.0,
                    max_tokens=summary_max_tokens,
                )
                summary_text = (resp.content or "").strip()
                if obs is not None:
                    summary_tokens = estimate_tokens(summary_text) if summary_text else 0
                    obs.update(
                        output=summary_text[:500] if summary_text else "(empty)",
                        metadata={
                            "model": model,
                            "before_tokens": before_tokens,
                            "summary_tokens": summary_tokens,
                            "middle_msgs_dropped": len(middle),
                            "compression_ratio": (
                                round(summary_tokens / before_tokens, 3)
                                if before_tokens > 0
                                else 0.0
                            ),
                        },
                    )
```

Note: `summary_text` assignment moves inside the `async with` block. The cache/logging code that follows (starting at `if summary_text:`) remains outside and unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestCompressSpanEnriched -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/context/compression.py tests/test_observability_plumbing.py
git commit -m "feat(observability): enrich compress span with input/output data

The compress span now records message counts as input, and the
summary text plus compression ratio/token counts as output. Previously
only metadata with middle_msgs count was captured."
```

---

### Task 3: Enrich verify span with input and output, add revision span

The `verify` span captures only mode and model in metadata — not the question, candidate answer, critique result, or revision. The revision LLM call is completely invisible.

**Files:**
- Modify: `nanobot/agent/verifier.py:85-154`
- Test: `tests/test_observability_plumbing.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_observability_plumbing.py`:

```python
class TestVerifySpanEnriched:
    """Verify that the verify span records input (question + candidate) and output (critique)."""

    @pytest.mark.asyncio
    async def test_verify_span_has_input_and_output(self) -> None:
        from nanobot.agent.verifier import AnswerVerifier

        provider = ScriptedProvider(['{"confidence": 8, "issues": []}'])

        obs_updates: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            mock_obs = MagicMock()
            mock_obs.update = lambda **kw: obs_updates.append(kw)
            yield mock_obs

        verifier = AnswerVerifier(
            provider=provider,
            model="test",
            temperature=0.0,
            max_tokens=1000,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )

        with (
            patch("nanobot.agent.verifier.langfuse_span", side_effect=fake_span),
            patch("nanobot.agent.verifier.score_current_trace"),
        ):
            await verifier.verify("What is 2+2?", "The answer is 4.", [])

        assert len(obs_updates) >= 1
        update = obs_updates[0]
        assert "output" in update
        assert "metadata" in update
        assert update["metadata"]["confidence"] == 8
        assert update["metadata"]["passed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability_plumbing.py::TestVerifySpanEnriched -v`
Expected: FAIL — `obs_updates` is empty

- [ ] **Step 3: Enrich the verify span**

In `nanobot/agent/verifier.py`, modify the `verify()` method to:
1. Pass `input` to the span with question and candidate (truncated)
2. Capture `obs` from the span context
3. Call `obs.update()` with critique result when verification passes
4. Call `obs.update()` with revision info when issues are found
5. Wrap the revision LLM call in a separate `langfuse_span(name="revision")`

Replace the span block (lines 93-147):

```python
        async with langfuse_span(
            name="verify",
            input={
                "question": user_text[:200],
                "candidate": candidate[:300],
            },
            metadata={"mode": self.verification_mode, "model": effective_model},
        ) as obs:
            try:
                critique_response = await self.provider.chat(
                    messages=critique_messages,
                    tools=None,
                    model=effective_model,
                    temperature=0.0,
                    max_tokens=512,
                )
                raw = (critique_response.content or "").strip()
                parsed = json.loads(raw)
                confidence = int(parsed.get("confidence", 5))
                issues = parsed.get("issues", [])

                # Report verification confidence as a Langfuse score.
                score_current_trace(
                    name="verification_confidence",
                    value=confidence,
                    comment="; ".join(issues) if issues else "passed",
                )

                if confidence >= 3 and not issues:
                    logger.debug("Verification passed (confidence={})", confidence)
                    if obs is not None:
                        obs.update(
                            output="passed",
                            metadata={"confidence": confidence, "passed": True},
                        )
                    return candidate, messages

                logger.info(
                    "Verification flagged issues (confidence={}): {}",
                    confidence,
                    issues,
                )
                issue_text = "\n".join(f"- {i}" for i in issues) if issues else "Low confidence"
                messages.append(
                    {
                        "role": "system",
                        "content": prompts.render("revision_request", issue_text=issue_text),
                    }
                )

                async with langfuse_span(
                    name="revision",
                    input={"issues": issues, "confidence": confidence},
                    metadata={"model": effective_model},
                ) as rev_obs:
                    revision = await self.provider.chat(
                        messages=messages,
                        tools=None,
                        model=effective_model,
                        temperature=effective_temperature,
                        max_tokens=self.max_tokens,
                    )
                    revised = strip_think(revision.content) or candidate
                    if rev_obs is not None:
                        rev_obs.update(output=revised[:500])

                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "assistant":
                        messages[i]["content"] = revised
                        break
                logger.info("Answer revised after verification")
                if obs is not None:
                    obs.update(
                        output="revised",
                        metadata={
                            "confidence": confidence,
                            "passed": False,
                            "issues": issues[:5],
                        },
                    )
                return revised, messages

            except (json.JSONDecodeError, KeyError, ValueError):
                logger.debug("Verification response not parseable, skipping")
                if obs is not None:
                    obs.update(output="parse_error", metadata={"passed": True})
                return candidate, messages
            except Exception:  # crash-barrier: LLM verification call
                logger.debug("Verification call failed, returning original answer")
                if obs is not None:
                    obs.update(output="call_error", metadata={"passed": True})
                return candidate, messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestVerifySpanEnriched -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/verifier.py tests/test_observability_plumbing.py
git commit -m "feat(observability): enrich verify span and add revision span

The verify span now records the question + candidate as input and
the critique result (passed/revised/error) as output with confidence
score. The revision LLM call is wrapped in a separate 'revision'
child span so it appears distinctly in Langfuse traces."
```

---

### Task 4: Add token counts to root span metadata

`message_processor.py` calls `update_current_span()` with model/role/channel metadata but omits `prompt_tokens`, `completion_tokens`, and `duration_ms` — even though these are logged to loguru on the next line. This is a metadata-only change on an existing call.

**Files:**
- Modify: `nanobot/agent/message_processor.py:372-382`
- Test: `tests/test_observability_plumbing.py` (modify existing `TestSpanMetadataNoRedundantTokens`)

- [ ] **Step 1: Update the existing test expectation**

The existing test `TestSpanMetadataNoRedundantTokens::test_span_metadata_excludes_token_counts` at line 299 explicitly asserts that token counts are NOT in span metadata. This test must be updated to expect them.

In `tests/test_observability_plumbing.py`, find class `TestSpanMetadataNoRedundantTokens` and update:

```python
class TestSpanMetadataWithTokenCounts:
    """Verify that span metadata includes token counts for Langfuse visibility."""

    @pytest.mark.asyncio
    async def test_span_metadata_includes_token_counts(self) -> None:
        """Token counts should appear in span metadata for Langfuse analysis."""
        # ... (reuse existing test setup from TestSpanMetadataNoRedundantTokens)
        # ... assert "prompt_tokens" IS in captured metadata
        # ... assert "completion_tokens" IS in captured metadata
        # ... assert "duration_ms" IS in captured metadata
```

Note: Read the existing test at lines 296-337 first. Keep the same setup but invert the assertions: token counts should be present, not absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability_plumbing.py::TestSpanMetadataWithTokenCounts -v`
Expected: FAIL — token counts are not in metadata yet

- [ ] **Step 3: Add token counts to update_current_span call**

In `nanobot/agent/message_processor.py`, modify the existing `_update_span()` call at lines 372-382. Add `prompt_tokens`, `completion_tokens`, and `duration_ms` to the metadata dict. This is a modification of existing lines, not new lines:

```python
            _update_span(
                output=final_content[:500] if final_content else None,
                metadata={
                    "channel": msg.channel,
                    "sender": msg.sender_id,
                    "model": effective_model,
                    "role": effective_role,
                    "session_key": key,
                    "llm_calls": self._turn_llm_calls,
                    "prompt_tokens": self._turn_tokens_prompt,
                    "completion_tokens": self._turn_tokens_completion,
                    "duration_ms": round((time.monotonic() - t0_request) * 1000),
                },
            )
```

Note: `llm_calls` changes from `str(self._turn_llm_calls)` to `self._turn_llm_calls` (int) for consistency with token counts.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestSpanMetadataWithTokenCounts -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/message_processor.py tests/test_observability_plumbing.py
git commit -m "feat(observability): add token counts and duration to root span metadata

The root trace span metadata now includes prompt_tokens,
completion_tokens, and duration_ms. Previously these were only
logged to loguru and absent from Langfuse."
```

---

### Task 5: Add delegation span output

The `delegate` span in `delegation.py` captures input and routing metadata but discards the `obs` object. The sub-agent result summary is never recorded.

**Files:**
- Modify: `nanobot/coordination/delegation.py:345-353`
- Test: `tests/test_observability_plumbing.py` (append new test class)

- [ ] **Step 1: Read delegation.py to identify exact lines**

Read `nanobot/coordination/delegation.py` lines 340-400 to find the exact span site and understand what result data is available after the `async with` block.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_observability_plumbing.py`:

```python
class TestDelegationSpanOutput:
    """Verify that the delegation span records the sub-agent result as output."""

    @pytest.mark.asyncio
    async def test_delegate_span_records_output(self) -> None:
        # This test needs to:
        # 1. Set up a DelegationDispatcher with a mock sub-agent
        # 2. Patch langfuse_span with a capture-list side-effect
        # 3. Call dispatch()
        # 4. Assert obs.update(output=...) was called with the sub-agent result
        # Exact setup depends on DelegationDispatcher constructor — read the file first
        pass
```

Note: The exact test code depends on the constructor signature and internal structure of `DelegationDispatcher.dispatch()`. Read the file in step 1 and write the test accordingly. Follow the pattern from `TestToolSpanOutputCaptured` in Task 1.

- [ ] **Step 3: Add obs.update() in delegation.py**

Capture the `obs` from the existing `async with langfuse_span(...)` and call `obs.update()` after the delegated agent returns with:
- `output`: the sub-agent result summary (truncated to 500 chars)
- `metadata`: tools_used count, grounded status

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestDelegationSpanOutput -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/coordination/delegation.py tests/test_observability_plumbing.py
git commit -m "feat(observability): record delegation span output

The delegate span now calls obs.update() with the sub-agent result
summary and metadata after execution completes."
```

---

### Task 6: Add cache-hit metadata to tool registry

When a cached tool result is returned, no `tool_span` is created — the cache hit is invisible in Langfuse. Add a minimal span so cache hits appear in traces.

**Files:**
- Modify: `nanobot/tools/registry.py:121-133`
- Test: `tests/test_observability_plumbing.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_observability_plumbing.py`:

```python
class TestToolSpanCacheHit:
    """Verify that cache hits produce a tool_span with cache metadata."""

    @pytest.mark.asyncio
    async def test_cache_hit_creates_span(self) -> None:
        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class CacheableTool(Tool):
            name = "cached_tool"
            description = "test"
            parameters: dict[str, Any] = {"type": "object", "properties": {}}
            readonly = True
            cacheable = True

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("fresh result")

        registry = ToolRegistry()
        registry.register(CacheableTool())

        # Set up a mock cache that returns a hit
        mock_cache = MagicMock()
        mock_cache.has.return_value = "cache_key_123"
        mock_entry = MagicMock()
        mock_entry.summary = "cached summary"
        mock_cache.get.return_value = mock_entry
        registry.set_cache(mock_cache)

        captured_spans: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            captured_spans.append(kwargs)
            yield None

        with patch("nanobot.tools.registry.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("cached_tool", {"q": "test"})

        assert result.success
        assert len(captured_spans) == 1
        assert captured_spans[0]["metadata"]["cache"] == "hit"
```

Note: `tool_span` is lazy-imported inside `_execute_inner`, but for cache hits we need to import it at the `execute()` level. Add a lazy import at the top of the cache-hit branch.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability_plumbing.py::TestToolSpanCacheHit -v`
Expected: FAIL — no span created for cache hits

- [ ] **Step 3: Add tool_span for cache hits**

In `nanobot/tools/registry.py`, in the `execute()` method, wrap the cache-hit return in a tool_span. Modify the block starting at line 122:

```python
        # Duplicate-call guard: return cached summary if available
        if self._cache and tool.readonly and tool.cacheable:
            hit_key = self._cache.has(name, params)
            if hit_key:
                entry = self._cache.get(hit_key)
                if entry:
                    from nanobot.observability.langfuse import tool_span

                    logger.info("Cache HIT for {}(…) → {}", name, hit_key)
                    async with tool_span(
                        name=name,
                        input=params,
                        metadata={"cache": "hit", "cache_key": hit_key},
                    ) as obs:
                        result = ToolResult.ok(
                            entry.summary,
                            cache_key=hit_key,
                            cached=True,
                            summary=entry.summary,
                        )
                        if obs is not None:
                            obs.update(output=entry.summary[:500])
                    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestToolSpanCacheHit -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/tools/registry.py tests/test_observability_plumbing.py
git commit -m "feat(observability): add tool_span for cache hits

Cache hits now produce a tool_span with cache=hit metadata so they
are visible in Langfuse traces. Previously cache hits returned
immediately with no tracing."
```

---

### Task 7: Add batch and reflect metadata to root span

The ActPhase batch execution and ReflectPhase delegation advice are invisible in Langfuse. `turn_phases.py` is at 467 LOC (33 LOC budget) and cannot accommodate full span wrappers. Instead, use `update_current_span()` to add metadata to the root span — this requires only 2 import lines and ~10 lines of code.

**Files:**
- Modify: `nanobot/agent/turn_phases.py:23-24` (imports) and `~306` (after batch) and `~398` (after reflect)
- Test: `tests/test_observability_plumbing.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_observability_plumbing.py`:

```python
class TestActPhaseSpanMetadata:
    """Verify that ActPhase annotates the active span with batch metadata."""

    @pytest.mark.asyncio
    async def test_batch_metadata_recorded(self) -> None:
        # Set up ActPhase with a mock tool executor that returns one success
        # Patch update_current_span to capture calls
        # Call execute_tools()
        # Assert update_current_span was called with batch metadata
        # (tool_count, any_failed, batch_duration_ms)
        pass
```

Note: Read the ActPhase constructor and execute_tools signature to write the exact test setup. The key assertion is that `update_current_span` is called with metadata containing batch results.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability_plumbing.py::TestActPhaseSpanMetadata -v`
Expected: FAIL

- [ ] **Step 3: Add import and update_current_span call**

In `nanobot/agent/turn_phases.py`:

Add import (line 23):
```python
from nanobot.observability.langfuse import update_current_span
```

At the end of `execute_tools()`, just before the `return ToolBatchResult(...)` statement (around line 323), add:

```python
        update_current_span(metadata={
            "batch_tools": [tc.name for tc in response.tool_calls],
            "batch_any_failed": any_failed,
            "batch_duration_ms": round(tools_elapsed_ms),
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability_plumbing.py::TestActPhaseSpanMetadata -v`
Expected: PASS

- [ ] **Step 5: Run full validation**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/turn_phases.py tests/test_observability_plumbing.py
git commit -m "feat(observability): annotate root span with tool batch metadata

ActPhase.execute_tools() now calls update_current_span() with batch
metadata (tool names, failure status, duration). This makes tool
batch execution visible in Langfuse without adding a new span
(preserving the 500 LOC file budget)."
```

---

### Task 8: Final validation

Run the complete test suite and validation to ensure all changes are correct.

**Files:** None (validation only)

- [ ] **Step 1: Run full check**

Run: `make check`
Expected: All tests pass, no lint errors, no type errors, no import boundary violations

- [ ] **Step 2: Run observability-specific tests**

Run: `pytest tests/test_observability.py tests/test_observability_plumbing.py -v`
Expected: All pass

- [ ] **Step 3: Verify file size limits**

Run:
```bash
wc -l nanobot/tools/registry.py nanobot/context/compression.py nanobot/agent/verifier.py nanobot/agent/message_processor.py nanobot/agent/turn_phases.py
```
Expected: All under 500 LOC (message_processor.py was already over — no net lines added)

- [ ] **Step 4: Verify no import boundary violations**

Run: `make import-check`
Expected: PASS — all imports from `nanobot.observability.langfuse` are allowed by boundary rules (observability is cross-cutting, consumed by all packages)

---

## Summary of Changes

| File | Change | Net LOC added |
|------|--------|:--:|
| `tools/registry.py` | obs.update() on tool_span + cache-hit span | ~25 |
| `context/compression.py` | input/output on compress span | ~15 |
| `agent/verifier.py` | input/output on verify span + revision span | ~25 |
| `agent/message_processor.py` | token counts in metadata | ~3 (modify existing lines) |
| `coordination/delegation.py` | obs.update() on delegate span | ~5 |
| `agent/turn_phases.py` | update_current_span for batch metadata | ~5 |
| `tests/test_observability_plumbing.py` | New test classes | ~120 |

**Total production code:** ~78 LOC added across 6 files
**Total test code:** ~120 LOC added to 1 file
