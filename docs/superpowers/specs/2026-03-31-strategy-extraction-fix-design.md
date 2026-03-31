# Fix Strategy Extraction Pipeline — Design Spec

> Date: 2026-03-31
> Issue: Strategies Saved But Useless (Issue 2 in claude-haiku-integration-issues report)
> Approach: B — Enrich data + structured prompt + strategy_tags on all guardrails

## Problem

The procedural memory learning loop is broken. Guardrail recoveries are detected
correctly, but the extracted strategies are unusable because:

1. **Data gap**: Guardrail activations don't include `failed_tool` or `failed_args`.
   The extractor receives `"unknown"` and `""`, producing garbage like
   `"What doesn't work: Calling unknown() function..."`.

2. **Vague prompt**: The LLM extraction prompt says "Summarize it in 1-2 sentences"
   instead of demanding structured, actionable output.

3. **Missing strategy_tags**: Only `EmptyResultRecovery` has `strategy_tag` set.
   The other 3 active guardrails (`RepeatedStrategyDetection`, `SkillTunnelVision`,
   `NoProgressBudget`) have `strategy_tag=None`, so their recoveries are never
   extracted.

## Changes

### 1. Enrich guardrail activation dict (`turn_runner.py`)

At the guardrail checkpoint (~line 497), find the failed/empty attempt from
`latest_attempts` and add it to the activation dict:

```python
_failed = next(
    (a for a in reversed(latest_attempts) if not a.success or a.output_empty),
    None,
)
state.guardrail_activations.append({
    "source": intervention.source,
    "severity": intervention.severity,
    "iteration": state.iteration,
    "message": intervention.message,
    "strategy_tag": intervention.strategy_tag,
    "failed_tool": _failed.tool_name if _failed else "unknown",
    "failed_args": _failed.arguments if _failed else {},
})
```

### 2. Add strategy_tags to all guardrails (`turn_guardrails.py`)

| Guardrail | Current tag | New tag |
|-----------|-------------|---------|
| EmptyResultRecovery (hint) | `"empty_result_first_hint"` | Keep (no change) |
| EmptyResultRecovery (directive) | `"empty_recovery:{tool}"` | Keep (no change) |
| RepeatedStrategyDetection | `None` | `"repeated_strategy"` |
| SkillTunnelVision | `None` | `"skill_tunnel_vision"` |
| NoProgressBudget | `None` | `"no_progress_budget"` |

The tag format uses the guardrail name as a stable identifier. No dynamic
interpolation needed — the failed tool info now comes from the activation dict.

### 3. Improve extraction prompt (`strategy_extractor.py`)

Replace `_llm_summarize()` prompt:

```python
prompt = (
    "Extract a tool-use rule from this recovery. Be specific and actionable.\n\n"
    f"User asked: {user_text[:200]}\n"
    f"Tool that failed: {failed_tool}({failed_args[:150]})\n"
    f"Tool that worked: {success_tool}({success_args[:150]})\n\n"
    "Write the rule in this exact format:\n"
    "WHEN: <what the user is trying to do>\n"
    "DON'T: <tool and why it fails for this case>\n"
    "DO: <tool and specific arguments that work>\n"
)
```

Increase `max_tokens` from 150 to 200.

Also update the fallback (no LLM) to include tool names:

```python
f"WHEN: {user_text[:80]}\nDON'T: {failed_tool} (returned no results)\nDO: {success_tool}"
```

### 4. Purge stale strategies (`strategy.py`)

Add `purge_invalid()` method to `StrategyAccess`:

```python
def purge_invalid(self) -> int:
    """Delete strategies with 'unknown()' — produced by broken extraction."""
    with self._conn:
        cursor = self._conn.execute(
            "DELETE FROM strategies WHERE strategy LIKE '%unknown()%'"
        )
        return cursor.rowcount
```

Call it once during `MemoryStore` initialization to clean up existing garbage.

## Files Changed

| File | Change |
|------|--------|
| `nanobot/agent/turn_runner.py` | Add `failed_tool`/`failed_args` to activation dict |
| `nanobot/agent/turn_guardrails.py` | Add `strategy_tag` to 3 guardrails |
| `nanobot/memory/strategy_extractor.py` | Improve extraction prompt + fallback |
| `nanobot/memory/strategy.py` | Add `purge_invalid()` method |
| `nanobot/memory/store.py` | Call `purge_invalid()` on init |
| `tests/test_turn_runner.py` | Test activation dict includes failed tool data |
| `tests/test_turn_guardrails.py` | Test new strategy_tags present |
| `tests/test_litellm_provider.py` | No changes |

## Expected Result

After this fix, the DS10540 scenario would produce:

```
WHEN: Looking for a project by code/identifier in Obsidian
DON'T: exec(obsidian search query="DS10540") — search only matches file content, not folder names
DO: exec(obsidian folders) to list vault structure, then exec(obsidian files folder="DS10540")
```

This strategy would be injected into the system prompt on the next session, and the
agent would skip `obsidian search` and go straight to `obsidian folders`.

## Verification

```bash
make lint && make typecheck
python -m pytest tests/test_turn_runner.py tests/test_turn_guardrails.py -x -q
make check
```

Manual: restart gateway, run DS10540 query, check strategy extraction log output
and verify the strategy text is actionable.
