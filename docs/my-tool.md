# My Tool

Let the agent sense and adjust its own runtime state — like asking a coworker "are you busy? can you switch to a bigger monitor?"

## Why You Need It

Normal tools let the agent operate on the outside world (read/write files, search code). But the agent knows nothing about itself — it doesn't know which model it's running on, how many iterations are left, or how many tokens it has consumed.

My tool fills this gap. With it, the agent can:

- **Know who it is**: What model am I using? Where is my workspace? How many iterations remain?
- **Adapt on the fly**: Complex task? Expand the context window. Simple chat? Switch to a faster model.
- **Remember across turns**: Store notes in your scratchpad that persist into the next conversation turn.

## Configuration

Enabled by default (read-only mode). The agent can check its state but not set it.

```yaml
tools:
  my:
    enable: true       # default: true
    allow_set: false   # default: false (read-only)
```

To allow the agent to set its configuration (e.g. switch models, adjust parameters), set `tools.my.allow_set: true`.

Legacy `tools.myEnabled` / `tools.mySet` keys are auto-migrated on load, and
rewritten in-place the next time `nanobot onboard` refreshes the config.

All modifications are held in memory only — restart restores defaults.

---

## check — Check "my" current state

Without parameters, returns a key config overview:

```text
my(action="check")
# → max_iterations: 40
#   context_window_tokens: 65536
#   model: 'anthropic/claude-sonnet-4-20250514'
#   workspace: PosixPath('/tmp/workspace')
#   provider_retry_mode: 'standard'
#   max_tool_result_chars: 16000
#   _current_iteration: 3
#   _last_usage: {'prompt_tokens': 45000, 'completion_tokens': 8000}
#   Note: prompt_tokens is cumulative across all turns, not current context window occupancy.
```

With a key parameter, drill into a specific config:

```text
my(action="check", key="_last_usage.prompt_tokens")
# → How many prompt tokens I've used so far

my(action="check", key="model")
# → What model I'm currently running on

my(action="check", key="web_config.enable")
# → Whether web search is enabled
```

### What you can do with it

| Scenario | How |
|----------|-----|
| "What model are you using?" | `check("model")` |
| "How many more tool calls can you make?" | `check("max_iterations")` minus `check("_current_iteration")` |
| "How many tokens has this conversation used?" | `check("_last_usage")` — cumulative across all turns |
| "Where is your working directory?" | `check("workspace")` |
| "Show me your full config" | `check()` |
| "Are there any subagents running?" | `check("subagents")` — shows phase, iteration, elapsed time, tool events |

---

## set — Runtime tuning

Changes take effect immediately, no restart required.

```text
my(action="set", key="max_iterations", value=80)
# → Bump iteration limit from 40 to 80

my(action="set", key="model", value="fast-model")
# → Switch to a faster model

my(action="set", key="context_window_tokens", value=131072)
# → Expand context window for long documents
```

You can also store custom state in your scratchpad:

```text
my(action="set", key="current_project", value="nanobot")
my(action="set", key="user_style_preference", value="concise")
my(action="set", key="task_complexity", value="high")
# → These values persist into the next conversation turn
```

### Protected parameters

These parameters have type and range validation — invalid values are rejected:

| Parameter | Type | Range | Purpose |
|-----------|------|-------|---------|
| `max_iterations` | int | 1–100 | Max tool calls per conversation turn |
| `context_window_tokens` | int | 4,096–1,000,000 | Context window size |
| `model` | str | non-empty | LLM model to use |

Other parameters (e.g. `workspace`, `provider_retry_mode`, `max_tool_result_chars`) can be set freely, as long as the value is JSON-safe.

---

## Practical Scenarios

### "This task is complex, I need more room"

```text
Agent: This codebase is large, let me expand my context window to handle it.
→ my(action="set", key="context_window_tokens", value=131072)
```

### "Simple question, don't waste compute"

```text
Agent: This is a straightforward question, let me switch to a faster model.
→ my(action="set", key="model", value="fast-model")
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
Agent: Web search is disabled — please set web.enable: true in your config.
```

### "Token budget management"

```text
Agent: Let me check how much budget I have left.
→ my(action="check", key="_last_usage")
# → {"prompt_tokens": 45000, "completion_tokens": 8000}
Agent: I've used ~53k tokens total so far. I'll keep my remaining replies concise.
```

### "Subagent monitoring"

```text
Agent: Let me check on the background tasks.
→ my(action="check", key="subagents")
# → 2 subagent(s):
#   [task-1] 'Code review'
#     phase: running, iteration: 5, elapsed: 12.3s
#     tools: read(✓), grep(✓)
#     usage: {'prompt_tokens': 8000, 'completion_tokens': 1200}
#   [task-2] 'Write tests'
#     phase: pending, iteration: 0, elapsed: 0.2s
#     tools: none
Agent: The code review is progressing well. The test task hasn't started yet.
```

---

## Safety Mechanisms

Core design principle: **All modifications live in memory only. Restart restores defaults.** The agent cannot cause persistent damage.

### Off-limits (BLOCKED)

Cannot be checked or modified — fully hidden:

| Category | Attributes | Reason |
|----------|-----------|--------|
| Core infrastructure | `bus`, `provider`, `_running` | Changes would crash the system |
| Tool registry | `tools` | Must not remove its own tools |
| Subsystems | `runner`, `sessions`, `consolidator`, etc. | Affects other users/sessions |
| Sensitive data | `_mcp_servers`, `_pending_queues`, etc. | Contains credentials and message routing |
| Security boundaries | `restrict_to_workspace`, `channels_config` | Bypassing would violate isolation |
| Python internals | `__class__`, `__dict__`, etc. | Prevents sandbox escape |

### Read-only (check only)

Can be checked but not set:

| Category | Attributes | Reason |
|----------|-----------|--------|
| Subagent manager | `subagents` | Observable, but replacing breaks the system |
| Execution config | `exec_config` | Can check sandbox/enable status, cannot change it |
| Web config | `web_config` | Can check enable status, cannot change it |
| Iteration counter | `_current_iteration` | Updated by runner only |

### Sensitive field protection

Sub-fields matching sensitive names (`api_key`, `password`, `secret`, `token`, etc.) are blocked from both check and set, regardless of parent path. This prevents credential leaks via dot-path traversal (e.g. `web_config.search.api_key`).
