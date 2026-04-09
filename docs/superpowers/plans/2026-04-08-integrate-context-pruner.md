# Plan: Integrate ContextPruner into AgentRunner

## Problem

`ContextPruner` is created in `AgentLoop` but never called. The pruning logic exists but is not wired into the message flow.

## Root Cause

- `ContextPruner` is instantiated in `loop.py` based on `context_pruning_config`
- `AgentRunner` handles message preparation in `_apply_tool_result_budget()` and `_snip_history()`
- No connection between the two — `prune()` method is never invoked

## Solution

Integrate `ContextPruner` into `AgentRunner` as an optional component:

1. **Add pruner to AgentRunSpec** — make it an optional field
2. **Call prune() in runner** — after `_apply_tool_result_budget()`, before `_snip_history()`
3. **Remove pruner from loop.py** — avoid duplicate ownership

## Changes

### 1. nanobot/agent/runner.py
- Add `pruner: ContextPruner | None = None` to `AgentRunSpec`
- In `run()` method, call `pruner.prune()` after `_apply_tool_result_budget()`

### 2. nanobot/agent/loop.py
- Remove `self.pruner` creation
- Pass `pruner` to `AgentRunSpec` if enabled

## Priority

- Channel-specific > per-channel people > root file (existing logic preserved)
- Pruning happens after tool result budget normalization
- Pruning happens before history snipping

## Testing

- Verify pruner is called when enabled
- Verify pruner is skipped when disabled
- Verify pruner respects `keep_last_assistants` boundary
