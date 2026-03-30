---
description: "Architectural constraints for nanobot Python code"
paths:
  - "nanobot/**/*.py"
---

# Non-Negotiable Architectural Constraints

These are hard constraints, not guidelines. Violations are bugs — fix them immediately.

## Package Boundaries — Strict Import Direction

Each top-level package owns a single bounded context. Import direction is enforced
by `scripts/check_imports.py` in CI. These boundaries exist to prevent the architecture
from collapsing back into a monolith.

| Package | Owns | Must never import from |
|---------|------|----------------------|
| `agent/` | Orchestration engine (tool-use loop, guardrails, message processing) | `channels/`, `cli/` |
| `coordination/` | Mission management and scratchpad | `channels/`, `cli/` |
| `memory/` | Persistent memory, retrieval, knowledge graph | `channels/`, `tools/` |
| `tools/` | Tool infrastructure + domain implementations | `channels/` |
| `context/` | Prompt assembly, compression, skill discovery | `channels/`, `cli/` |
| `observability/` | Tracing, instrumentation, metrics | `channels/`, `cli/` |
| `channels/` | Chat platform adapters | `agent/`, `tools/`, `memory/`, `coordination/` |
| `providers/` | LLM provider abstraction | `agent/`, `channels/` |
| `config/` | Pydantic config models + loader | `agent/`, `channels/`, `providers/` |
| `bus/` | Async message bus | `agent/`, `channels/`, `providers/` |

**If you need to add an import that crosses a boundary, stop.** The design is wrong —
restructure the code so the dependency flows in the correct direction. Use `Protocol`
types or dependency injection to invert the dependency if needed.

## Package Responsibilities — Single Ownership

Every file belongs to exactly one package. Every concern has exactly one authoritative
location. If logic is expressed in two packages, one of them is wrong — deduplicate.

- **`agent/`** is only orchestration. If you're adding a tool, it goes in `tools/`. If you're
  adding mission logic, it goes in `coordination/`. If you're adding memory logic, it
  goes in `memory/`. Agent orchestrates — it never owns domain logic for other concerns.
- **`tools/builtin/`** is for domain tool implementations. Tool infrastructure (base, registry,
  executor, capability) stays at `tools/` level. Never mix infrastructure with implementations.
- **`memory/`** has internal subdirectories (`write/`, `read/`, `ranking/`, `persistence/`,
  `graph/`) — respect them. Don't add flat files to `memory/` when they belong in a subdirectory.
- **`observability/`** is cross-cutting instrumentation. It is consumed by other packages but
  owns nothing about their domain logic.

## Composition Root — Single Wiring Point

`agent/agent_factory.py` (`build_agent()`) is the **only** place where subsystems are
constructed and wired together.

**Rules:**

1. `build_agent()` in `agent_factory.py` constructs all subsystems and returns an
   `_AgentComponents` dataclass.
2. `AgentLoop.__init__` is a **slim receiver** — it unpacks `_AgentComponents` and stores
   references. It must **never** call constructors, factory functions, or `setup_*` methods.
3. No other module may construct a subsystem that `build_agent()` is responsible for.
   If you find yourself writing `SomeSubsystem()` outside of `agent_factory.py`, you're
   in the wrong place.
4. If a new subsystem needs wiring, add it to `build_agent()` and `_AgentComponents`.
   Do not scatter construction across multiple modules.

**Detection test:** grep for class instantiation patterns (`SomeClass(`) in `loop.py`,
`turn_runner.py`, `message_processor.py`. If any construct a subsystem (not a local
value object), it's a violation.

## Dependency Inversion — No Cross-Package Instantiation

**No package may import concrete classes from another package for the purpose of
instantiation.** This rule exists because `coordination/mission.py` previously
imported concrete tool classes from `tools/builtin/` to construct tool registries —
coupling coordination to specific tool implementations.

**Allowed cross-package dependencies:**

| Pattern | Example | Why it's OK |
|---------|---------|-------------|
| Injected instances | Constructor receives `MemoryStore` | Dependency is provided, not constructed |
| Injected factories | Constructor receives `Callable[..., ToolRegistry]` | Defers construction to the caller |
| Protocol types | `TYPE_CHECKING: from nanobot.memory.store import MemoryStore` | Structural typing, no runtime coupling |
| Data objects | Pydantic models, dataclasses, enums, constants | Value types, not services |
| Base classes | `from nanobot.tools.base import Tool` for subclassing | Extension point, not instantiation |

**Forbidden:**

```python
# In coordination/mission.py — WRONG
from nanobot.tools.builtin.filesystem import ReadFileTool
registry.register(ReadFileTool(workspace=self.workspace))  # cross-package instantiation

# CORRECT — receive tools from the composition root
def __init__(self, ..., mcp_tools: list[Tool]):
    self.mcp_tools = mcp_tools
```

**Enforcement:** `scripts/check_imports.py` flags runtime imports from `tools/builtin/`
in `coordination/`, and runtime imports from `coordination/` in `tools/`. The script
skips imports inside `if TYPE_CHECKING:` blocks.

## No Architectural Debt by Design

Do not introduce code with the intent to "fix it later." There is no later — the next
session starts with a blank context. Every change must be correctly placed, boundary-safe,
and tested before it is considered done.

- Never add a `# TODO: move this to the right package` comment. Move it now.
- Never add a backward-compatibility shim for internal imports. Update all callers.
- Never add a catch-all module (`utils.py`, `helpers.py`) at the package level.

## Message Processing — Single Pipeline

All message entry points (`run()`, `process_direct()`, future entry points) must
converge into `MessageProcessor._process_message()` before the first processing step.
Processing steps — context building, orchestration, self-check — must have a single
code path inside the processor. Entry points must not duplicate or skip
processing steps.

**If you need a new entry point:** Route through `MessageProcessor._process_message()`.
Do not add processing logic to the loop or the new caller.
