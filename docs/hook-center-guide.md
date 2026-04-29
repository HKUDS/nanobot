# Hook Center Guide

Extend nanobot with hook plugins: intercept, modify, or cancel operations at named hook points.

## How It Works

nanobot provides a centralized **HookCenter** that manages named hook points. Internal nanobot modules declare hook points; external plugins register handlers that run when those points are triggered.

Hook handlers can:
- **Observe** — receive context, trigger side effects (logging, notifications)
- **Modify** — change the context data that flows to subsequent handlers
- **Intercept** — short-circuit remaining handlers or cancel the originating operation

Plugins are discovered via Python [entry points](https://packaging.python.org/en/latest/specifications/entry-points/) in the `nanobot.hooks` group, loaded automatically at startup.

## Quick Start: Write a Hook Plugin

### 1. Create Your Handler

```python
# my_hook_plugin/handlers.py
from nanobot.hooks import HookContext, HookResult

async def on_before_iteration(ctx: HookContext) -> HookResult | None:
    """Log every agent iteration."""
    iteration = ctx.get("iteration")
    print(f"[hook] agent iteration: {iteration}")
    return None  # None = continue (default)
```

### 2. Register via entry_points

```toml
# my_hook_plugin/pyproject.toml
[project]
name = "my-hook-plugin"
version = "0.1.0"
dependencies = ["nanobot-ai"]

[project.entry-points."nanobot.hooks"]
before_iteration = "my_hook_plugin.handlers:on_before_iteration"
```

### 3. Install and Run

```bash
pip install my-hook-plugin
nanobot agent  # plugins are loaded automatically
```

## Handler Protocol

A handler is any async callable that accepts a `HookContext` and returns `HookResult | None`:

```python
async def my_handler(ctx: HookContext) -> HookResult | None:
    ...
```

**Return values:**
- `None` — continue to the next handler (convenience default)
- `HookResult(action="continue")` — same as None
- `HookResult(action="short_circuit")` — skip remaining handlers, return current state
- `HookResult(action="cancel", reason="...")` — abort the originating operation

**Context:**
- `ctx.get("key")` — read a value
- `ctx.set("key", value)` — write a value (visible to subsequent handlers)

## Registering to Multiple Hook Points

Set a `hook_points` attribute on your handler to register it at multiple points:

```python
async def audit_handler(ctx: HookContext) -> None:
    print(f"[audit] {ctx.data}")

audit_handler.hook_points = ["agent.before_iteration", "agent.before_execute_tools"]
```

Or return a dict mapping point names to handlers:

```python
# In pyproject.toml:
# [project.entry-points."nanobot.hooks"]
# my_plugin = "my_hook_plugin:PLUGIN"

# my_hook_plugin/__init__.py
from my_hook_plugin.handlers import on_save, on_tool

PLUGIN = {
    "agent.before_iteration": on_save,
    "agent.before_execute_tools": on_tool,
}
```

## For nanobot Contributors: Adding Hook Points

### Declare a Hook Point

```python
from nanobot.hooks import get_center, HookContext

center = get_center()
center.register_point("agent.before_iteration", "Fired before each agent iteration")
```

### Emit a Hook Point

```python
ctx = HookContext(data={"session_key": key})
result = await center.emit("agent.before_iteration", ctx)

if result.action == "cancel":
    logger.warning("Iteration cancelled: {}", result.reason)
    return
```

### Naming Convention

Use dot-separated names with the module prefix:

- `agent.before_iteration`
- `agent.after_iteration`
- `agent.before_execute_tools`
- `agent.on_stream_end`

### Built-in Hook Points

| Hook point | When | Can cancel? | Context data |
|------------|------|-------------|-------------|
| `agent.before_iteration` | Before each LLM call | Yes (ends the run) | iteration, channel, chat_id, session_key, tool_calls, usage |
| `agent.after_iteration` | After each LLM response | No (observe only) | iteration, channel, chat_id, session_key, tool_calls, usage |
| `agent.before_execute_tools` | Before tool execution | Yes (ends the run) | iteration, channel, chat_id, session_key, tool_calls, usage |
| `agent.on_stream_end` | After streaming completes | No (observe only) | iteration, channel, chat_id, session_key, tool_calls, usage |

Context data is a **snapshot** — handler modifications flow between handlers but do not propagate back to the agent loop. Use the `cancel` action on `before_iteration` or `before_execute_tools` to stop the agent run.

### Error Isolation

If a handler raises an exception, the HookCenter logs it and continues to the next handler. A faulty plugin cannot crash the main loop.

## Testing Your Plugin

```python
import pytest
from nanobot.hooks import HookCenter, HookContext, HookResult

@pytest.mark.asyncio
async def test_my_handler():
    center = HookCenter()
    center.register_point("agent.before_iteration")

    async def handler(ctx: HookContext) -> None:
        ctx.set("audited", True)

    center.register_handler("agent.before_iteration", handler)

    ctx = HookContext(data={"iteration": 0})
    result = await center.emit("agent.before_iteration", ctx)

    assert result.action == "continue"
    assert ctx.get("audited") is True
```
