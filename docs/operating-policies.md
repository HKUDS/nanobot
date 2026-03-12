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

### Filesystem

- Paths resolved via `_resolve_path()` with symlink following
- Workspace containment enforced when `restrict_to_workspace = True`
- Path traversal (`../`) blocked by `Path.relative_to()` check

### Network

- WhatsApp bridge binds `127.0.0.1` only
- API keys never hardcoded — stored in `~/.nanobot/config.json` (0600 permissions)

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
`TraceContext`. Metrics are flushed to `metrics.json` every 60 seconds.

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
