# Operating Policies

> Canonical reference for Nanobot's runtime defaults, safety constraints, and operational
> boundaries. Auto-derived from `nanobot/config/schema.py` and tool implementations.

## Agent Defaults

| Parameter | Default | Source |
|-----------|---------|--------|
| Model | `anthropic/claude-opus-4-5` | `AgentDefaults.model` |
| Temperature | `0.1` | `AgentDefaults.temperature` |
| Max tokens | `8192` | `AgentDefaults.max_tokens` |
| Context window | `128,000` tokens | `AgentConfig.context_window_tokens` |
| Max tool iterations | `40` | `AgentDefaults.max_tool_iterations` |
| Message timeout | `300s` | `AgentConfig.message_timeout` |
| Memory window | `100` messages | `AgentDefaults.memory_window` |
| Memory retrieval k | `6` | `AgentDefaults.memory_retrieval_k` |
| Tool result max chars | `2,000` | `AgentDefaults.tool_result_max_chars` |

## Feature Flags

All flags default to **enabled** (`True`). Disable via `config.features.*`:

| Flag | Controls |
|------|----------|
| `planning_enabled` | Plan step before tool execution |
| `verification_enabled` | Self-critique on responses |
| `delegation_enabled` | Multi-agent delegation |
| `memory_enabled` | Memory consolidation + retrieval |
| `skills_enabled` | Skill auto-discovery |
| `streaming_enabled` | Token-by-token streaming |

## Security Boundaries

### Shell Execution (`shell_mode = "denylist"`)

Blocked patterns (case-insensitive, hex-escape normalised):

- **Destructive**: `rm -rf`, `rmdir /s`, `format`, `mkfs`, `dd if=`
- **System**: `shutdown`, `reboot`, `poweroff`
- **Injection**: `base64 | sh`, `curl | sh`, `eval` with variable expansion
- **Fork bombs**: `:(){ :|:& };:`
- **Privilege escalation**: `chmod 777`, `chown -R root`

Allowlist mode (`shell_mode = "allowlist"`) restricts to an explicit set of safe commands
(file ops, dev tools, network utilities).

> **Delegated agents inherit `shell_mode`** from the parent `ExecToolConfig`. An operator
> configuring `shell_mode: "allowlist"` will have that policy applied to all delegated
> sub-agents. The `shell_mode` field is part of `ExecToolConfig` in `config/schema.py`.

### Filesystem

- Paths resolved via `_resolve_path()` with symlink following
- Workspace containment enforced when `restrict_to_workspace = True`
- Path traversal (`../`) blocked by `Path.relative_to()` check

### Network

- WhatsApp bridge binds `127.0.0.1` only
- API keys never hardcoded — stored in `~/.nanobot/config.json` (0600 permissions)

## Multi-Agent Delegation

### Coordinator Classification Flow

Every inbound message is classified by the `Coordinator` before agent processing begins:

1. **Prompt assembly** — `Coordinator._build_classify_prompt()` lists all registered
   roles (name + description) and wraps the user message in `<user_message>` tags.
2. **LLM classification** — A lightweight LLM call (temperature 0, max 128 tokens)
   returns JSON with `role`, `confidence`, `needs_orchestration`, and `relevant_roles`.
3. **Confidence filter** — If the response is valid JSON (`from_json=True`) and
   `confidence < confidence_threshold` (default 0.6), the role falls back to the
   configured `default_role` (typically `general`).  Text-scan fallback responses
   (`from_json=False`) bypass this filter because they are already a last-resort
   heuristic.
4. **Orchestration override** — When the classified role is not `pm` or `general`,
   the role is overridden to `pm` if either `needs_orchestration=True` **or**
   `len(relevant_roles) >= 2`.  The relevant-roles count is the authoritative signal
   for multi-specialist tasks.
5. **Role lookup** — The final role name is resolved via `AgentRegistry.get()`.  If
   the role is missing or disabled (`enabled=False`), the registry default is used.

### Role Configuration

Roles are defined via `AgentRoleConfig` in `config/schema.py`.  Key fields:

| Field | Effect |
|-------|--------|
| `name` | Unique identifier used in classification and delegation |
| `enabled` | When `False`, the role is excluded from classification candidates and `route_direct()` returns `None` |
| `model` | Per-role model override (falls back to agent default) |
| `temperature` | Per-role temperature override |
| `allowed_tools` | Explicit tool allowlist for delegated agents (see below) |
| `denied_tools` | Tool denylist — always respected, overrides allowlist |

### Delegation Limits

Nanobot enforces **two independent delegation limits** (LAN-132):

| Limit | Default | Behaviour | Configurable? |
|-------|---------|-----------|---------------|
| `MAX_DELEGATION_DEPTH` | `3` | Hard structural cap on ancestry chain length. Raises `_CycleError` — cannot be overridden by the LLM. | Source constant in `delegation.py` |
| `max_delegations` | `8` | Per-session budget on total delegations. Raises `_CycleError` when `delegation_count >= max_delegations`. | `DelegationDispatcher.max_delegations` |

**Key distinction**: `MAX_DELEGATION_DEPTH` prevents deep recursive chains (A→B→C→D would fail at depth 3).
`max_delegations` caps total spend across all parallel branches in a session.

### Tool Permissions in Delegated Agents

Delegated sub-agents receive a **restricted tool set** governed by `AgentRoleConfig`:

- `allowed_tools: null` (default) — reads files, lists dirs, uses web tools; shell/write/re-delegation are **denied by default**
- `allowed_tools: ["exec", "write_file", ...]` — explicitly grant privileged tools
- `denied_tools: ["web_search", "web_fetch"]` — block specific tools even if otherwise permitted

`denied_tools` is always respected: it overrides both the default-allow set and any `allowed_tools` grant.

> **Web tools (`web_search`, `web_fetch`)** are available by default but can be blocked via
> `denied_tools`. Roles intended for network-isolated analysis should set `denied_tools: ["web_search", "web_fetch"]`.

**Resolution order** for each tool in a delegated agent:

1. If the tool name appears in `denied_tools` — **denied** (highest priority).
2. If the tool is privileged (`exec`, `write_file`, `edit_file`, `delegate`) and
   `allowed_tools` is `null` (the default) — **denied**.  Privileged tools require
   an explicit grant.
3. If `allowed_tools` is a non-null list and the tool is not in it — **denied**.
4. Otherwise — **allowed**.

This means a role with `allowed_tools: ["exec", "web_search"]` and
`denied_tools: ["web_search"]` will have `exec` available but `web_search` blocked.

### Classification Security

The routing classification prompt wraps user messages in `<user_message>` XML tags.
The classifier is instructed to treat content inside these tags as opaque data and ignore
any instructions that appear within them. This prevents prompt injection from routing a
malicious message to a privileged role (CWE-77).

## Memory System

| Parameter | Default | Description |
|-----------|---------|-------------|
| `memory_rollout_mode` | `enabled` | Active memory consolidation |
| `memory_type_separation_enabled` | `True` | Separate semantic/episodic mem |
| `memory_router_enabled` | `True` | LLM-based memory routing |
| `memory_reflection_enabled` | `True` | Post-consolidation reflection |
| `memory_enable_contradiction_check` | `True` | Detect conflicting memories |
| `memory_uncertainty_threshold` | `0.6` | Confidence floor for retrieval |
| `mem0.verify_write` | `True` | Verify mem0 writes succeeded |

## Logging & Telemetry

| Parameter | Default | Description |
|-----------|---------|-------------|
| `log.level` | `INFO` | Loguru log level |
| `log.json_stdout` | `False` | JSON-serialised stderr output |
| `log.json_file` | `""` | Path to JSON log file sink |

All log events include correlation IDs (`request_id`, `session_id`, `agent_id`) via
`TraceContext`. Observability metrics are captured via Langfuse.

## Verification Modes

| Mode | Behaviour |
|------|-----------|
| `on_uncertainty` (default) | Verify when LLM confidence is low |
| `always` | Verify every response |
| `disabled` | Skip verification |

## Prompt Templates

Managed via `nanobot/templates/prompts/` with SHA-256 integrity checking
(`prompts_manifest.json`). Override by placing files in `<workspace>/prompts/`.

| Template | Purpose |
|----------|---------|
| `plan.md` | Planning step instructions |
| `classify.md` | Intent classification / routing |
| `compress.md` | Context summarisation |
| `critique.md` | Self-critique + verification |
| `failure_strategy.md` | Error recovery strategies |
| `progress.md` | Progress tracking |
| `reflect.md` | Memory reflection |
