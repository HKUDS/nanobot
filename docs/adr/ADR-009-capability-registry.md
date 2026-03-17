# ADR-009: Capability Registry

## Status

Proposed

## Date

2026-03-17

## Context

The agent framework presents tools, skills, and delegation roles to the LLM through
three independent registries:

- **`ToolRegistry`** (`agent/tools/registry.py`): Simple `dict[str, Tool]` with no
  availability checks. `get_definitions()` returns all registered tools to the LLM
  regardless of configuration state (e.g., missing API keys).
- **`SkillsLoader`** (`agent/skills.py`): Checks binary/env requirements via
  `_check_requirements()`, but still includes unavailable skills in the summary
  (with an `available="false"` XML flag the LLM frequently ignores).
- **`AgentRegistry`** (`agent/registry.py`): Simple `dict[str, AgentRoleConfig]`.
  `route_direct()` returns `None` for unknown roles, silently falling back to
  LLM classification instead of returning a clear error.

This fragmentation causes three concrete failures:

1. **Unconfigured tools offered to LLM**: `WebSearchTool` is registered and its schema
   sent to the LLM even when `BRAVE_API_KEY` is absent. The LLM calls it, gets a
   runtime error, wastes a tool turn, and may then give up or hallucinate alternatives.

2. **Delegation to nonexistent roles**: The LLM can freely invent role names (e.g.,
   `target_role="web"`) in the `delegate` tool. The dispatcher silently falls back to
   LLM classification, which may route to an unrelated role — with no error signal
   to the caller.

3. **No unified view of capabilities**: The system prompt, tool definitions, and
   skill summaries are assembled independently with no shared concept of "what is
   actually available right now."

## Decision

Replace the three registries with a unified **`CapabilityRegistry`** that tracks
availability, health, and metadata for every capability the agent can use.

### 1. Tool availability protocol

Add a method to the `Tool` ABC:

```python
def check_available(self) -> tuple[bool, str | None]:
    """Return (is_available, reason_if_not). Default: always available."""
    return True, None
```

Override in tools with external dependencies:

- `WebSearchTool`: check `self.api_key` is non-empty
- `CheckEmailTool`: check email configuration present
- `DelegateTool`: check `self._dispatch` callable is set
- MCP tools: check connection health

`ToolRegistry.get_definitions()` filters out tools where `check_available()[0]` is
`False`. An `get_unavailable_summary()` method returns a human-readable string
injected into the system prompt: *"web_search is unavailable (missing API key)"*.

### 2. Capability model

```python
@dataclass(slots=True)
class Capability:
    name: str
    kind: Literal["tool", "skill", "delegate_role"]
    description: str
    intents: list[str]                     # free-form tags, e.g. ["search_web"]
    health: Literal["healthy", "degraded", "unavailable"]
    unavailability_reason: str | None
    fallback_priority: int                 # lower = preferred for same intent
    tool: Tool | None = None               # kind="tool"
    skill_name: str | None = None          # kind="skill"
    role_config: AgentRoleConfig | None = None  # kind="delegate_role"
```

### 3. CapabilityRegistry

A single registry that internally **composes** (not replaces) the existing registries:

- `register_tool(tool, intents, fallback_priority)` — wraps Tool, runs `check_available()`
- `register_skill(name, metadata, path)` — wraps skill from SkillsLoader discovery
- `register_role(role_config, intents)` — wraps AgentRoleConfig
- `get_available(kind?, intent?)` — filter by health + optional kind/intent
- `get_tool_definitions()` — only healthy tools, replaces `ToolRegistry.get_definitions()`
- `get_unavailable_summary()` — for system prompt injection
- `get_tool(name)` / `execute_tool(name, params)` — execution path
- `unregister(name)` — for `ToolCallTracker`'s progressive tool removal
- `refresh_health()` — periodic re-check of all capabilities

### 4. Delegation validation

`DelegateTool.parameters` schema dynamically constrains `target_role` to registered
role names (via `enum` in JSON Schema). Unknown roles are rejected immediately with:

```
ToolResult.fail("Unknown role 'web'. Available roles: code, research, writing, system, pm, general",
                error_type="unknown_role")
```

No silent fallback to LLM classification for explicitly-provided role names.

### 5. Implementation phases

| Phase | Scope | Independently valuable? |
|-------|-------|------------------------|
| A | Tool availability protocol on `Tool` ABC + filter `get_definitions()` | **Yes** — prevents LLM from calling unconfigured tools |
| B | `CapabilityRegistry` core (wraps existing registries) | Yes — unified view |
| C | Wire into `AgentLoop` (replace `self.tools` + `self.skills` + `self.agent_registry`) | No — requires B |
| D | Delegation validation (role enum, `UnknownRoleError`) | Yes — can be done on Phase A alone |
| E | Health tracking (`refresh_health()`, heartbeat integration) | No — requires B |

Phase A is the critical first step: it solves the immediate problem with minimal risk.

## Consequences

### Positive

- LLM never sees tools it cannot use — eliminates wasted tool turns on config errors
- Delegation to unknown roles fails fast with actionable error messages
- Single source of truth for "what can the agent do right now"
- System prompt accurately reflects available capabilities
- Foundation for intent-based routing (Layer 2, see backlog)

### Negative

- Every `Tool` subclass gains a new method (though the default is `(True, None)`)
- `AgentLoop.__init__()` registration code must be updated
- Existing tests that construct `ToolRegistry` directly need adaptation
- Slight coupling: `DelegateTool` needs a reference to the registry for dynamic
  schema generation

### Neutral

- Existing `ToolRegistry`, `SkillsLoader`, and `AgentRegistry` continue to exist
  internally — `CapabilityRegistry` composes them, doesn't delete them
- `ToolResult` contract (ADR-004) is unchanged
- Intent tags are free-form strings with no taxonomy — Layer 2 will formalize them
