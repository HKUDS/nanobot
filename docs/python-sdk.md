# Python SDK

Use nanobot as a library — no CLI, no gateway, just Python.

## Quick Start

```python
import asyncio

from nanobot import Nanobot


async def main() -> None:
    bot = Nanobot.from_config()
    result = await bot.run("What time is it in Tokyo?")
    print(result.content)


asyncio.run(main())
```

`Nanobot.from_config()` reuses your normal `~/.nanobot/config.json`, so the SDK follows the same provider, model, tools, and workspace defaults as the CLI unless you override them.

## Common Patterns

### Use a specific config or workspace

```python
from nanobot import Nanobot

bot = Nanobot.from_config(
    config_path="~/.nanobot/config.json",
    workspace="/my/project",
)
```

### Isolate conversations with `session_key`

Different session keys keep independent conversation history:

```python
await bot.run("hi", session_key="user-alice")
await bot.run("hi", session_key="task-42")
```

### Attach hooks for observability

Hooks let you inspect tool calls, streaming, and iteration state without modifying nanobot internals:

```python
from nanobot.agent import AgentHook, AgentHookContext


class AuditHook(AgentHook):
    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tc in context.tool_calls:
            print(f"[tool] {tc.name}")


result = await bot.run("Review this change", hooks=[AuditHook()])
```

## API Reference

### `Nanobot.from_config(config_path=None, *, workspace=None)`

Create a `Nanobot` instance from a config file.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `config_path` | `str \| Path \| None` | `None` | Path to `config.json`. Defaults to `~/.nanobot/config.json`. |
| `workspace` | `str \| Path \| None` | `None` | Override the workspace directory from config. |

Raises `FileNotFoundError` if an explicit config path does not exist.

### `await bot.run(message, *, session_key="sdk:default", hooks=None)`

Run the agent once and return a `RunResult`.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | `str` | *(required)* | The user message to process. |
| `session_key` | `str` | `"sdk:default"` | Session identifier for conversation isolation. Different keys get independent history. |
| `hooks` | `list[AgentHook] \| None` | `None` | Lifecycle hooks for this run only. |

### `RunResult`

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str` | The agent's final text response. |
| `tools_used` | `list[str]` | Reserved for richer SDK introspection; may be empty in current versions. |
| `messages` | `list[dict]` | Reserved for richer SDK introspection; may be empty in current versions. |

## Hooks

Hooks let you observe or customize the agent loop. Subclass `AgentHook` and override the methods you need.

### Hook lifecycle

| Method | When |
|--------|------|
| `wants_streaming()` | Return `True` if you want token-by-token `on_stream()` callbacks |
| `before_iteration(context)` | Before each LLM call |
| `on_stream(context, delta)` | On each streamed token when streaming is enabled |
| `on_stream_end(context, *, resuming)` | When streaming finishes |
| `before_execute_tools(context)` | Before tool execution |
| `after_iteration(context)` | After each iteration |
| `finalize_content(context, content)` | Transform final output text |

Useful fields on `AgentHookContext` include:

- `iteration`
- `messages`
- `response`
- `usage`
- `tool_calls`
- `tool_results`
- `tool_events`
- `final_content`
- `stop_reason`
- `error`

### Example: audit tool calls

```python
from nanobot.agent import AgentHook, AgentHookContext


class AuditHook(AgentHook):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tc in context.tool_calls:
            self.calls.append(tc.name)
            print(f"[audit] {tc.name}({tc.arguments})")
```

```python
hook = AuditHook()
result = await bot.run("List files in /tmp", hooks=[hook])
print(result.content)
print(f"Tools observed: {hook.calls}")
```

### Example: receive streaming tokens

```python
from nanobot.agent import AgentHook, AgentHookContext


class StreamingHook(AgentHook):
    def wants_streaming(self) -> bool:
        return True

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        print(delta, end="", flush=True)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        print()
```

### Compose multiple hooks

Pass multiple hooks when you want to combine behaviors:

```python
result = await bot.run("hi", hooks=[AuditHook(), MetricsHook()])
```

Async hook methods are fan-out with error isolation. `finalize_content` is a pipeline: each hook receives the previous hook's output.

### Example: post-process final content

```python
from nanobot.agent import AgentHook


class Censor(AgentHook):
    def finalize_content(self, context, content):
        return content.replace("secret", "***") if content else content
```

## Full Example

```python
import asyncio
import time

from nanobot import Nanobot
from nanobot.agent import AgentHook, AgentHookContext


class TimingHook(AgentHook):
    def __init__(self) -> None:
        super().__init__()
        self._started_at = 0.0

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._started_at = time.perf_counter()

    async def after_iteration(self, context: AgentHookContext) -> None:
        elapsed_ms = (time.perf_counter() - self._started_at) * 1000
        print(f"[timing] iteration {context.iteration} took {elapsed_ms:.1f}ms")


async def main() -> None:
    bot = Nanobot.from_config(workspace="/my/project")
    result = await bot.run(
        "Explain the main function",
        session_key="sdk:demo",
        hooks=[TimingHook()],
    )
    print(result.content)


asyncio.run(main())
```
