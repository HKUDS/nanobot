# Review Scope

## Target

`nanobot/agent/loop.py` — the core agent loop implementing the Plan-Act-Observe-Reflect
cycle. 2173 lines. Recently modified to add `FailureClass` enum, failure classification
in `ToolCallTracker`, and `_build_failure_prompt()` dynamic failure strategy.

## Files

- `nanobot/agent/loop.py` (primary)
- `nanobot/agent/tools/base.py` (ToolResult — referenced by ToolCallTracker)
- `nanobot/agent/capability.py` (CapabilityRegistry — composed in AgentLoop)
- `nanobot/errors.py` (error taxonomy — used throughout loop)
- `tests/test_tool_call_tracker.py` (tests for ToolCallTracker)
- `tests/golden/test_golden_scenarios.py` (golden integration tests)

## Flags

- Security Focus: no
- Performance Critical: no
- Strict Mode: no
- Framework: nanobot async agent framework (Python 3.10+, asyncio, litellm)

## Review Phases

1. Code Quality & Architecture
2. Security & Performance
3. Testing & Documentation
4. Best Practices & Standards
5. Consolidated Report
