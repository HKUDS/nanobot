# Hook Plugin Guide

Build a custom nanobot hook plugin in three steps: implement, package, install.

Hooks let you observe, transform, or guard agent lifecycle events — without modifying nanobot internals.

## How It Works

nanobot discovers hook plugins via Python [entry points](https://packaging.python.org/en/latest/specifications/entry-points/), the same mechanism used by channel plugins. When `nanobot gateway` starts, the HookCenter scans:

1. External packages registered under the `nanobot.hooks` entry point group
2. Plugins listed in `config.hooks.enabled_plugins` allowlist (when configured)

## Quick Start

We'll build a minimal rate-limiting hook plugin that blocks excessive tool calls.

### Project Structure

```text
nanobot-hook-ratelimit/
├── nanobot_hook_ratelimit/
│   ├── __init__.py           # re-export RateLimitHandler
│   └── handler.py            # handler implementation
└── pyproject.toml
```

### 1. Implement Your Handler

```python
# nanobot_hook_ratelimit/__init__.py
from nanobot_hook_ratelimit.handler import RateLimitHandler

__all__ = ["RateLimitHandler"]
```

```python
# nanobot_hook_ratelimit/handler.py
from nanobot.hooks import BeforeExecuteTools, Deny, Modified



class RateLimitHandler:
    """Block tool execution when a per-session limit is exceeded."""

    # Register for tool execution events as a guard handler.
    hook_events = [(BeforeExecuteTools, "guard")]

    def __init__(self, max_tools_per_turn: int = 10) -> None:
        self._max_tools_per_turn = max_tools_per_turn
        self._counts: dict[str, int] = {}

    async def __call__(self, event: BeforeExecuteTools):
        session_id = getattr(event, "session_key", "default")
        count = self._counts.get(session_id, 0)

        if count >= self._max_tools_per_turn:
            return Deny(
                f"Rate limit: max {self._max_tools_per_turn} tools per turn "
                f"(current: {count})"
            )

        self._counts[session_id] = count + len(event.tool_calls)
        return None


class BlocklistHandler:
    """Abort the agent loop if a blocked tool is called."""

    hook_events = [(BeforeExecuteTools, "guard")]

    def __init__(self, blocked_tools: list[str] | None = None) -> None:
        self._blocked = set(blocked_tools or [])

    async def __call__(self, event: BeforeExecuteTools):
        for tc in event.tool_calls:
            if tc.name in self._blocked:
                return Deny(
                    f"Blocked tool '{tc.name}' — agent loop aborted",
                    abort=True,
                )
        return None
```

### 2. Register the Entry Point

```toml
# pyproject.toml
[project]
name = "nanobot-hook-ratelimit"
version = "0.1.0"
dependencies = ["nanobot-ai"]

[project.entry-points."nanobot.hooks"]
ratelimit = "nanobot_hook_ratelimit:RateLimitHandler"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["nanobot_hook_ratelimit"]
```

The key (`ratelimit`) becomes the plugin name shown in logs and used in the `enabled_plugins` allowlist. The value points to your handler class.

### 3. Install & Configure

```bash
pip install -e .
```

Edit `~/.nanobot/config.json` to enable the plugin:

```json
{
  "hooks": {
    "enabled_plugins": ["ratelimit"]
  }
}
```

When `enabled_plugins` is set, **only** listed plugins are loaded. Without this key (or when set to `null`), all discovered plugins are loaded.

### 4. Verify

```bash
nanobot gateway
```

Check the logs — you should see:
```
Registered hook plugin 'ratelimit' with 1 events
```

## Handler Contract

A hook handler is any callable matching the `HookHandler` protocol:

```python
async def handler(event: EventType) -> HookResult | Modified | Deny | None: ...
```

| Return value | Semantic | Effect |
|-------------|----------|--------|
| `None` | Observe | No action needed; handler ran as a side-effect |
| `Modified(data)` | Transform | Apply the returned data to the event (dict keys mapped to event fields) |
| `Deny(reason)` | Guard (soft) | Block the operation — runner injects the reason as a tool result and continues the loop |
| `Deny(reason, abort=True)` | Guard (hard) | Block the operation — runner terminates the agent loop immediately, `reason` becomes the final content |

### Declaring subscriptions

Your handler class or module must expose a `hook_events` attribute:

```python
hook_events: list[tuple[type, str]] = [
    (BeforeIteration, "observe"),
    (BeforeExecuteTools, "guard"),
    (AfterIteration, "observe"),
]
```

Each tuple is `(event_type, mode)`. Mode must be one of `"guard"`, `"transform"`, or `"observe"`.

## Event Types

v1 exposes six event types covering the agent iteration lifecycle:

| Event | Fields | Mode |
|-------|--------|------|
| `BeforeIteration` | `iteration`, `messages` | guard, observe |
| `OnStream` | `delta`, `iteration` | observe |
| `OnStreamEnd` | `resuming`, `iteration` | observe |
| `BeforeExecuteTools` | `iteration`, `tool_calls`, `response` | guard, observe |
| `AfterIteration` | `iteration`, `final_content`, `stop_reason`, `usage`, `tool_calls`, `tool_events`, `tool_results`, `error` | observe |
| `FinalizeContent` | *(registration marker only)* | transform pipeline |

All event types are importable from `nanobot.hooks`:

```python
from nanobot.hooks import (
    BeforeIteration,
    AfterIteration,
    BeforeExecuteTools,
    OnStream,
    OnStreamEnd,
    FinalizeContent,
    Deny,
    Modified,
)
```

## Dispatch Order

Within a single event emission, handlers run in this order:

1. **Guards** (internal, then external) — first `Deny` value short-circuits; remaining handlers are skipped.
2. **Transforms** (internal, then external) — chained pipeline; each handler receives data modified by the previous one.
3. **Observes** (internal, then external) — sequential execution with per-handler error isolation.

Internal handlers (built-in framework logic such as streaming and progress) always run before external plugins.

## Security

Hook plugin entry-point loading carries inherent security implications.  When the `nanobot gateway` starts, the `HookCenter` loads all hooks that appear in `hooks.enabled_plugins`.  Any hook plugin has **full access to the agent process** — all conversational data, in-memory state, filesystem access, and network access.

**Important controls:**

- Set `hooks.enabled_plugins` to an explicit allowlist to control which plugins load.
- Audit your plugin dependencies.  Any installed hook package can execute arbitrary Python code at `ep.load()` time.
- For high-security deployments, consider running nanobot in a sandboxed environment (`tools.restrictToWorkspace`, `tools.exec.sandbox: bwrap`).

## Naming Convention

| What | Format | Example |
|------|--------|---------|
| PyPI package | `nanobot-hook-{name}` | `nanobot-hook-ratelimit` |
| Entry point key | `{name}` | `ratelimit` |
| Config allowlist | `hooks.enabled_plugins[{name}]` | `ratelimit` |
| Python package | `nanobot_hook_{name}` | `nanobot_hook_ratelimit` |

## Built-in Hook API (AgentHook, backward-compatible)

Legacy `AgentHook` subclasses remain fully supported through a compatibility adapter.  Existing hook code (such as the Python SDK usage below) continues to work unchanged:

```python
from nanobot.agent import AgentHook, AgentHookContext


class AuditHook(AgentHook):
    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tc in context.tool_calls:
            print(f"[audit] {tc.name}")

# Works as before — adapted internally to HookCenter
result = await bot.run("hello", hooks=[AuditHook()])
```

See the [Python SDK guide](./python-sdk.md) for the full SDK hooks API reference.
