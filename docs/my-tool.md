# My Tool

This page is for operators configuring the agent's runtime self-inspection tool. It describes what the agent can read or change at runtime, and what it saves. Scratchpad values survive across turns until the agent runtime restarts; they are shared by sessions using that runtime, not private per-session storage or durable preferences.

## Why You Need It

Normal tools let the agent operate on the outside world (read/write files, search code). But the agent knows nothing about itself — it doesn't know which model it's running on, which workspace it can access, or which runtime limits apply.

My tool fills this gap. With it, the agent can:

- **Inspect the current request**: What model am I using? Which project can I access? What is my per-turn iteration limit?
- **Tune runtime settings**: Adjust the iteration limit or select a configured model preset for the session's next turn when writes are enabled.
- **Keep temporary notes**: Store non-sensitive scratchpad values across turns, without relying on them surviving a restart.

## Configuration

Enabled by default (read-only mode). The agent can check its state but not set it.

```yaml
tools:
  my:
    enable: true       # default: true
    allow_set: false   # default: false (read-only)
```

To allow the agent to set its configuration (e.g. switch models, adjust parameters), set `tools.my.allow_set: true`.

Legacy `tools.myEnabled` / `tools.mySet` keys are auto-migrated on load, and rewritten in-place the next time `nanobot onboard` refreshes the config.

Most modifications are held in memory only. `model_preset` is the exception: it is stored in the current session so the selection survives a restart.

---

## check — Check "my" current state

Without a key, returns an overview of inspectable runtime settings. Example values:

```text
my(action="check")
# → max_iterations: 40
#   context_window_tokens: 200000
#   model: 'anthropic/claude-sonnet-4-6'
#   model_preset: 'deep'
#   workspace: PosixPath('/tmp/agent-workspace')
#   workspace_sandbox: {...}
#   provider_retry_mode: 'standard'
#   max_tool_result_chars: 16000
#   ...
```

With a key parameter, drill into a specific config:

```text
my(action="check", key="workspace_sandbox.workspace_root")
# → Current project path

my(action="check", key="model")
# → What model I'm currently running on

my(action="check", key="web_config.enable")
# → Whether web search is enabled
```

### What you can do with it

| Scenario | How |
|----------|-----|
| "What model are you using?" | `check("model")` |
| "Which model preset is active?" | `check("model_preset")` |
| "What is the per-turn iteration limit?" | `check("max_iterations")` |
| "What is the context-window capacity?" | `check("context_window_tokens")` — capacity, not current usage or remaining space |
| "Which project is active?" | `check("workspace_sandbox.workspace_root")` |
| "Is file access restricted to the project?" | `check("workspace_sandbox.restrict_to_workspace")` |
| "Show inspectable runtime settings" | `check()` |

`workspace` is a legacy display of the agent workspace, not the current project or an access grant. Use `workspace_sandbox` for the active project and file restriction. `exec_config` separately reports shell sandbox settings; shell binds do not grant file tools access.

---

## set — Runtime tuning

Changes do not require a restart. `model_preset` is saved for the current session and applies to its next turn. Other writable settings are updated in memory; changing the iteration limit does not extend an already-running agent loop. Direct `model` and `context_window_tokens` writes are rejected during an active session because those setters change the shared instance default. Configure a named preset for model or context-window changes instead.

```text
my(action="set", key="max_iterations", value=80)
# → Bump iteration limit from 40 to 80

my(action="set", key="model_preset", value="fast")
# → Use a configured model preset for this session's next turn
```

You can also store temporary, non-sensitive state in your scratchpad. Values remain available across turns until the runtime restarts, and are shared by its sessions:

```text
my(action="set", key="task_focus", value="documentation")
my(action="set", key="response_style", value="concise")
my(action="set", key="task_complexity", value="high")
# → These notes survive across turns, but not a runtime restart
```

### Protected parameters

These parameters have type and range validation — invalid values are rejected:

| Parameter | Type | Range | Purpose |
|-----------|------|-------|---------|
| `max_iterations` | int | 1–100 | Max model/tool iterations per agent run |
| `context_window_tokens` | int | 4,096–1,000,000 | Instance default; during a session, select through a preset |
| `model` | str | non-empty | Instance default; during a session, select through a preset |
| `model_preset` | str | configured preset name | Current session's preset for its next turn |

`provider_retry_mode` and `max_tool_result_chars` must match their existing value types. Setting `workspace` changes only the legacy display string, not the active project, shell directory, or file permissions. Unknown top-level keys store JSON-safe scratchpad values rather than creating runtime settings. Nested configuration fields cannot be changed through `my`.

---

## Practical Scenarios

### "This task is complex, I need more room"

```text
Agent: This codebase is large, let me switch this session to the configured deep preset.
→ my(action="set", key="model_preset", value="deep")
```

### "Simple question, don't waste compute"

```text
Agent: This is a straightforward question, let me switch to the fast preset.
→ my(action="set", key="model_preset", value="fast")
```

### "Remember user preferences across turns"

```text
Turn 1: my(action="set", key="user_prefers_concise", value=True)
Turn 2: my(action="check", key="user_prefers_concise")
# → True (still remembers the user likes concise replies)
```

### "Self-diagnosis"

```text
User: "Why aren't you searching the web?"
Agent: Let me check my web config.
→ my(action="check", key="web_config.enable")
# → False
Agent: Web search is disabled — please set tools.web.enable: true in your config.
```

### "Context capacity"

```text
Agent: Let me check the context-window capacity.
→ my(action="check", key="context_window_tokens")
# → context_window_tokens: 200000
```

This is the configured capacity, not current occupancy, remaining space, or cumulative token usage. `my` does not expose `_last_usage`. For context and per-round usage, see the [WebUI activity and context indicators](./webui.md#activity-and-context-usage).

### "Subagent monitoring"

Use the separate `subagent` tool, not `my`. To list the current session's live tasks or inspect a known task ID:

```text
subagent(action="check")
subagent(action="check", task_id="<task-id>")
```

Only tasks owned by the current session are accessible. A known task ID can retrieve retained results after completion; finished tasks leave the live list. Checks without a current session identity fail. Background results arrive automatically, so avoid repeated polling.

---

## Safety Mechanisms

Core design principle: **The tool does not rewrite `config.json`.** Instance-wide changes live in memory only, while `model_preset` persists only as the current session's selector.

### Off-limits (BLOCKED)

Cannot be checked or modified — fully hidden:

| Category | Attributes | Reason |
|----------|-----------|--------|
| Core infrastructure | `bus`, `provider`, `_running` | Changes would crash the system |
| Tool registry | `tools` | Must not remove its own tools |
| Subsystems | `runner`, `sessions`, `consolidator`, `subagents`, etc. | Use dedicated tools instead of inspecting internal managers |
| Sensitive data | `_mcp_servers`, `_pending_queues`, etc. | Contains credentials and message routing |
| Security boundaries | `restrict_to_workspace`, `channels_config` | Bypassing would violate isolation |
| Python internals | `__class__`, `__dict__`, etc. | Prevents sandbox escape |

### Read-only (check only)

Can be checked but not set:

| Category | Attributes | Reason |
|----------|-----------|--------|
| Workspace access | `workspace_sandbox` | Shows the active project and file restriction; cannot change access |
| Execution config | `exec_config` | Can check sandbox/enable status, cannot change it |
| Web config | `web_config` | Can check enable status, cannot change it |

### Sensitive field protection

Sub-fields matching sensitive names (`api_key`, `password`, `secret`, `token`, etc.) are blocked from both check and set, regardless of parent path. This prevents credential leaks via dot-path traversal (e.g. `web_config.search.api_key`).
