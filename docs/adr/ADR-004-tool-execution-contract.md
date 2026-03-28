# ADR-004: Tool Execution Contract

## Status

Accepted — ToolExecutor extracted (2026-03-12)

## Date

2026-03-11

## Context

Tools are central to the agent's ability to act. The current tool system has:

- **`Tool` ABC** (`nanobot/tools/base.py`) with `name`, `description`, `parameters`
  (JSON Schema), `readonly` flag, and `async execute(**kwargs) -> str | ToolResult`.
- **`ToolResult`** dataclass with `ok()`/`fail()` factories, `output`, `success`,
  `error`, `truncated`, `metadata`.
- **`ToolRegistry`** (`nanobot/tools/registry.py`) for registration, validation,
  and parallel/sequential execution.

This contract is already well-defined. The gap is that tool *execution orchestration*
(batching, timeouts, result shaping) lives inside `AgentLoop` instead of a dedicated
service.

## Decision

1. **Keep the existing `Tool` ABC and `ToolResult` contract unchanged.** They are stable
   and well-tested.

2. **Introduce capability/implementation separation** for high-level capabilities:

   ```
   capability: web_research
     policy: allowed_domains, cost_limits, freshness_rules
     implementations: openai_web, playwright_browser, serp_api
   ```

   This is an architectural target, not an immediate refactor. Document the pattern in
   `.claude/rules/architecture.md` and apply when adding new tool families.

3. **Extract `ToolExecutor`** from `AgentLoop` (see ADR-002). The executor:
   - Receives `list[ToolCallRequest]` and the `ToolRegistry`.
   - Batches readonly tools for parallel execution via `asyncio.gather`.
   - Runs write tools sequentially.
   - Enforces per-tool timeouts.
   - Shapes results (truncation, error formatting) before returning to the loop.
   - Returns `list[ToolResult]`.

4. **Tool registration is handled by `agent_factory.py` via `build_agent()`** (see
   Composition Root). A future ADR may propose a declarative registration mechanism.

## Consequences

### Positive

- `ToolExecutor` is independently testable with mock registries.
- Execution policies (timeouts, batching) centralized in one place.
- Capability/implementation separation prevents vendor lock-in for new tool families.

### Negative

- Extracting `ToolExecutor` requires updating ~10 tests.
- Capability abstraction adds complexity; defer until second tool family arrives.

### Neutral

- External tool contract (`Tool.execute()` → `ToolResult`) does not change.
- MCP tools continue wrapping as `MCPToolWrapper(Tool)` — no change needed.
