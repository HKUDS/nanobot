# Test Strategy

> Defines the four test layers used in Nanobot and when to add each type.

## Overview

Tests are organized into four layers, each with a distinct purpose and scope:

| Layer | Location | Purpose | When to add |
|---|---|---|---|
| **Unit** | `tests/test_*.py` | Pure functions, parsing, config, serialization | Every PR that changes logic |
| **Contract** | `tests/contract/` | Interface compliance for tools, providers, channels, memory | When adding/changing a public interface |
| **Golden** | `tests/golden/` | Frozen orchestration behavior baselines | When changing agent loop behavior |
| **Workflow** | `tests/test_workflow_e2e.py` | Full-pipeline request flows | When changing the end-to-end path |

## Layer 1: Unit Tests

**What they test:** Individual functions and classes in isolation.

**Examples:**
- Config parsing and validation (`test_config_*.py`)
- Token estimation and truncation logic (`test_context.py`)
- Tool result serialization (`test_tool_base.py`)
- Shell command security patterns (`test_shell_safety.py`)
- Memory event extraction heuristics (`test_extraction_e2e.py`)
- Feature flag propagation (`test_feature_flags.py`)

**Pattern:** Direct function calls with known inputs and expected outputs.

**When to add:** Every PR that modifies logic or adds a new function.

## Layer 2: Contract Tests

**What they test:** That implementations honour their interface contracts.

**Location:** `tests/contract/`

**Current contract test files:**
- `test_contracts.py` — Tool schema validation, ToolResult factory methods, LLMResponse
- `test_provider_contracts.py` — LLMProvider ABC compliance, chat/stream_chat contract
- `test_memory_contracts.py` — MemoryStore instantiation, append/retrieve roundtrip
- `test_channel_contracts.py` — BaseChannel subclass compliance, required methods

**Pattern:** Import the interface and all implementations, verify structural compliance
(methods exist, signatures match, return types correct). Use `@pytest.mark.parametrize`
for multi-implementation coverage.

**When to add:** When creating a new provider, channel, tool, or when changing a base class.

## Layer 3: Golden Regression Tests

**What they test:** The agent loop's orchestration behavior with scripted LLM responses.

**Location:** `tests/golden/test_golden_scenarios.py`

**Current scenarios:**
1. Single-turn Q&A — no orchestration overhead
2. Tool result injection — real file content in context
3. Multi-step history accumulation
4. Nudge for final answer — tools disabled after nudge
5. Max iterations guard — graceful stop
6. Write tool side effects — real filesystem changes
7. Consecutive error fallback
8. Tool failure → recovery
9. Planning prompt injection
10. Parallel readonly tools

**Pattern:** `ScriptedProvider` with full message capture. Assertions verify what the
agent loop *does* with scripted responses: message assembly, tool execution, iteration
count, orchestration mechanisms.

**When to add:** When modifying agent loop behavior (tool execution, planning, reflection,
compression, delegation). If a golden test fails after a refactor, the behavior change
must be intentional.

## Layer 4: Workflow Integration Tests

**What they test:** Full request processing pipelines.

**Location:** `tests/test_workflow_e2e.py`

**Current workflows:**
1. Full pipeline: question → tool call → answer
2. Write → read verification pipeline
3. Context assembly (system prompt, user message, tools)
4. Provider error → user-friendly message
5. Memory store roundtrip
6. Multi-turn session history

**Pattern:** Same `ScriptedProvider` + `_make_loop` pattern as golden tests, but focused
on end-to-end data flow rather than orchestration mechanism verification.

**When to add:** When modifying the request processing path, error handling, or session management.

## Coverage Expectations

| Area | Target | Rationale |
|---|---|---|
| Overall | ≥ 85% | Enforced in CI via `--cov-fail-under=85` |
| `agent/loop.py` | ≥ 80% | Core orchestration — golden tests cover main paths |
| `tools/` | ≥ 90% | High impact, well-isolated |
| `config/schema.py` | ≥ 95% | Pure validation logic |
| `channels/` | ≥ 60% | Many paths require real platform connections |
| `providers/` | ≥ 70% | Some paths require real API keys |

## Running Tests

```bash
make test           # Fast: stop on first failure
make test-verbose   # All tests with output
make test-cov       # With coverage report + 85% threshold
make check          # lint + typecheck + import-check + prompt-check + test
make ci             # Full CI: lint + typecheck + import-check + prompt-check + test-cov
```

## Adding a New Test

1. Determine the appropriate layer (unit/contract/golden/workflow)
2. Place the test in the correct location
3. Follow existing patterns in that layer
4. Ensure it runs with `make test`
5. If adding a new test file, verify it's discovered by pytest

## Markers

Tests can be tagged with pytest markers:

```python
@pytest.mark.golden    # Golden regression test
@pytest.mark.contract  # Contract compliance test
```

Markers are defined in `pyproject.toml` under `[tool.pytest.ini_options]`.
