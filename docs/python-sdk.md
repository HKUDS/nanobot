# Nanobot Python SDK: Run an AI Agent from Python

Use nanobot as a Python library. The SDK gives you the same agent runtime used
by the CLI, but from code: model routing, tools, workspace access, conversation
history, memory, streaming events, and runtime helpers.

If you have used the OpenAI SDK before, the most important difference is this:

- OpenAI SDK calls a model.
- nanobot SDK runs an agent around a model.

That means one SDK call can read files, call tools, keep session history, use
memory, stream progress, and return structured runtime information.

```text
your Python code
  -> Nanobot SDK
    -> agent runtime
      -> configured model provider
      -> tools
      -> workspace
      -> session history
      -> memory
```

## Before You Start

Install and configure nanobot first. If you have not done that yet, follow the
[Quick Start](quick-start.md) and complete the setup wizard. For SDK-only Python
environments, install the package with:

```bash
python -m pip install nanobot-ai
```

`Nanobot.from_config()` reuses your normal `~/.nanobot/config.json` and
`~/.nanobot/workspace/`. Provider, model, tools, memory, and session behavior
match the CLI unless you override them. For the difference between config and
workspace, see [Concepts: Config vs Workspace](concepts.md#config-vs-workspace).

Before writing SDK code, run the same first-run checks from the main
[Install and Quick Start](quick-start.md):

```bash
nanobot status
```

`nanobot status` should show the config path, workspace path, active model or
preset, and provider summary. Then send one real message:

```bash
nanobot agent -m "Hello!"
```

A normal assistant reply means install, config, provider/model selection, and
workspace access are all usable. Once that works, the SDK should see the same
runtime.

## 5-Minute Quick Start

### Ask One Question

```python
import asyncio

from nanobot import Nanobot


async def main() -> None:
    async with Nanobot.from_config() as bot:
        result = await bot.run("What time is it in Tokyo?")
    print(result.content)


asyncio.run(main())
```

Use `async with` when possible so tool connections and background cleanup are
closed before the event loop exits. If you manage the instance manually, call
`await bot.aclose()` in a `finally` block.

The SDK is async-first because agent runs may stream tokens, execute tools, and
wait on external services. In a normal Python script, wrap your async function
with `asyncio.run(...)` as shown above. In a notebook or another async app, call
`await bot.run(...)` directly from your existing event loop.

### Inspect What Happened

`bot.run(...)` returns a `RunResult`, not just a string:

```python
result = await bot.run("Review this repository")

print(result.content)     # final answer
print(result.tools_used)  # tools the agent used
print(result.usage)       # token usage when available
print(result.stop_reason) # why the run stopped
```

### Continue A Conversation

Use a `session_key` when you want history to carry across turns. Different
session keys are isolated from each other:

```python
await bot.run("My name is Alice.", session_key="user:alice")
result = await bot.run("What is my name?", session_key="user:alice")

print(result.content)
```

This is the SDK equivalent of giving each user, task, eval case, or workflow
its own conversation thread.

### Stream A Long Answer

For live output, use `bot.stream(...)`:

```python
from nanobot import STREAM_EVENT_TEXT_DELTA

async for event in bot.stream("Write a migration plan"):
    if event.type == STREAM_EVENT_TEXT_DELTA:
        print(event.delta, end="", flush=True)
```

Streaming returns structured events, so you can also observe tool calls,
reasoning chunks, completion, and failures.

## Complete Starter Script

Save this as `sdk_demo.py` after `nanobot agent -m "Hello!"` works:

```python
import asyncio
import sys

from nanobot import (
    STREAM_EVENT_RUN_COMPLETED,
    STREAM_EVENT_RUN_FAILED,
    STREAM_EVENT_TEXT_DELTA,
    STREAM_EVENT_TOOL_STARTED,
    Nanobot,
)


async def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Explain what nanobot is in one paragraph."
    session_key = "sdk:demo"

    async with Nanobot.from_config() as bot:
        print(f"model: {bot.runtime.model}")
        print(f"workspace: {bot.runtime.workspace}")
        print()

        final_result = None
        async for event in bot.stream(prompt, session_key=session_key):
            if event.type == STREAM_EVENT_TEXT_DELTA:
                print(event.delta, end="", flush=True)
            elif event.type == STREAM_EVENT_TOOL_STARTED:
                print(f"\n[tool] {event.name}", flush=True)
            elif event.type == STREAM_EVENT_RUN_COMPLETED:
                final_result = event.result
            elif event.type == STREAM_EVENT_RUN_FAILED:
                raise RuntimeError(event.error or "nanobot run failed")

        print()
        if final_result is not None:
            print(f"\nstop_reason: {final_result.stop_reason}")
            print(f"tools_used: {final_result.tools_used}")
            print(f"usage: {final_result.usage}")


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python sdk_demo.py "List the top-level files in the current workspace."
```

You should see the configured model, workspace path, streamed assistant text,
and final run metadata. The exact answer depends on your config and workspace,
but a file-listing prompt may look like this:

```text
model: openai/gpt-4.1-mini
workspace: /Users/alice/.nanobot/workspace

[tool] list_dir
Here are the top-level files I found...

stop_reason: completed
tools_used: ['list_dir']
usage: {'prompt_tokens': ..., 'completion_tokens': ..., 'total_tokens': ...}
```

This script shows the usual production shape: create one `Nanobot`, choose a
stable `session_key`, stream events, keep the final `RunResult`, and let
`async with` close runtime resources.

## Core Concepts

| Concept | Meaning |
|---------|---------|
| `Nanobot` | The SDK object that owns one configured agent runtime. |
| Run | One call to `bot.run(...)`, `bot.run_streamed(...)`, or `bot.stream(...)`. |
| `session_key` | The conversation history key. Reuse it to continue a thread; change it to isolate a thread. |
| Workspace | The local directory where file tools and shell tools operate. |
| Tools | Capabilities the agent may call, such as file access, shell, web, or custom tools from your config. |
| Memory | Long-term memory files managed by nanobot. |
| Stream event | A typed event such as `text.delta`, `tool.started`, or `run.completed`. |
| Model override | A temporary model or model preset used for one SDK instance or one run. |

For most users, the mental model is:

1. Create a `Nanobot` from config.
2. Pick a `session_key`.
3. Call `run` or `stream`.
4. Read `RunResult` or stream events.
5. Use session/memory/runtime helpers only when you need more control.

## SDK Or OpenAI-Compatible API?

nanobot has two programming surfaces:

| Use | Choose | Why |
|-----|--------|-----|
| Python code running in the same process as nanobot | Python SDK | Direct access to `RunResult`, sessions, memory, runtime helpers, hooks, and stream events. |
| Existing OpenAI-compatible clients, another language, or a separate process | [OpenAI-Compatible API](openai-api.md) | HTTP `/v1/chat/completions` compatibility with familiar client libraries. |

The Python SDK is best when you are writing evals, notebooks, benchmark
runners, product backends, local scripts, or integrations that should control
nanobot directly.

The OpenAI-compatible API is best when you already have an HTTP client, want
process isolation, or need to call nanobot from a non-Python service.

## Common Patterns

### Use a specific config or workspace

Set the workspace when your agent should work inside a specific project:

```python
from nanobot import Nanobot

async with Nanobot.from_config(workspace="/my/project") as bot:
    result = await bot.run("Explain the project structure")
```

Use a custom config when you run multiple nanobot instances or test an isolated
setup:

```python
async with Nanobot.from_config(
    config_path="./bot-a/config.json",
    workspace="./bot-a/workspace",
) as bot:
    result = await bot.run("Hello from bot A")
```

The config controls what nanobot may use. The workspace is where nanobot keeps
state for that instance. See [multiple-instances.md](multiple-instances.md) for
multi-instance CLI and gateway examples.

### Choose a default or per-run model

Set the SDK instance default model when you create the bot:

```python
bot = Nanobot.from_config(model="openai/gpt-4.1")
```

Override the model for one run without changing the instance default:

```python
result = await bot.run("Summarize this file", model="openai/gpt-4.1-mini")
```

Model presets from `config.json` work the same way:

```python
bot = Nanobot.from_config(model_preset="fast")

result = await bot.run("Think deeply about this bug", model_preset="reasoning")
```

`model` and `model_preset` are mutually exclusive.

For first setup, prefer named presets in `config.json`. Mixing an API key from
one provider with a model ID from another is the most common first-run failure.
For the exact difference between `provider`, `model`, `apiKey`, and `apiBase`,
see [Providers: Provider, Model, API Key, and Base URL](providers.md#provider-model-api-key-and-base-url).
If a run fails before the SDK does anything interesting, confirm the same
provider and model work with `nanobot agent -m "Hello!"` first.

### Isolate conversations with `session_key`

Different session keys keep independent conversation history:

```python
await bot.run("hi", session_key="user-alice")
await bot.run("hi", session_key="task-42")
```

Use stable keys in product code:

```python
session_key = f"user:{user_id}"
result = await bot.run(user_message, session_key=session_key)
```

Avoid using the default `"sdk:default"` for multiple users or unrelated
workflows. It is convenient for local experiments, but stable product code
should choose explicit keys such as `user:<id>`, `project:<id>`, or
`eval:<case-id>`.

### Handle failures

For a normal non-streamed run, catch exceptions around `bot.run(...)` and inspect
`RunResult.error` when the runtime returns a structured failure:

```python
try:
    result = await bot.run("Review this repo", session_key="project:demo")
except Exception as exc:
    print(f"SDK call failed before a result was returned: {exc}")
else:
    if result.error:
        print(f"Agent run failed: {result.error}")
    else:
        print(result.content)
```

For streamed runs, either consume the stream to completion or close it:

```python
run = await bot.run_streamed("Write a long answer", session_key="task:123")
try:
    async for event in run.stream_events():
        ...
finally:
    if not run.done:
        await run.aclose()
```

Use `await run.cancel()` when the user presses a stop button or leaves the page
before the stream finishes.

### Stream long-running output

Use `bot.stream()` when you want Cursor/OpenAI-style live events instead of
waiting for the final `RunResult`:

```python
from nanobot import (
    STREAM_EVENT_RUN_COMPLETED,
    STREAM_EVENT_TEXT_DELTA,
    STREAM_EVENT_TOOL_STARTED,
)

async for event in bot.stream("Review this repository"):
    if event.type == STREAM_EVENT_TEXT_DELTA:
        print(event.delta, end="", flush=True)
    elif event.type == STREAM_EVENT_TOOL_STARTED:
        print(f"\nusing {event.name}")
    elif event.type == STREAM_EVENT_RUN_COMPLETED:
        print("\nfinal:", event.result.content)
```

Use `run_streamed()` when you also want a handle you can wait on:

```python
from nanobot import STREAM_EVENT_TEXT_DELTA

run = await bot.run_streamed("Write a detailed migration plan")

async for event in run.stream_events():
    if event.type == STREAM_EVENT_TEXT_DELTA:
        print(event.delta, end="", flush=True)

result = await run.wait()
```

Always either consume the stream, call `await run.wait()` / `await run.text()`,
or close it with `await run.cancel()` / `await run.aclose()`. Exiting
`stream_events()` or `bot.stream()` early cancels the underlying run so a
half-consumed stream cannot leave a background task stuck behind backpressure.

### Import an existing transcript

This is useful for evals, benchmark runners, migrations, and tests.

Use `bot.sessions.ingest()` when you already have a transcript and want it to
become nanobot session history. Ingesting a transcript does not call the model,
execute tools, update memory, or compact automatically.

```python
await bot.sessions.ingest(
    "eval:case-1",
    [
        {
            "role": "user",
            "content": "I graduated with a degree in Business Administration.",
            "timestamp": "2023/05/30 (Tue) 17:27",
            "source_session_id": "answer_280352e9",
        },
        {
            "role": "assistant",
            "content": "Congratulations on your degree.",
            "timestamp": "2023/05/30 (Tue) 17:27",
        },
    ],
    source="longmemeval",
)

await bot.runtime.compact_session("eval:case-1")

result = await bot.run(
    "Current Date: 2023/05/30 (Tue) 23:40\n"
    "Question: What degree did I graduate with?",
    session_key="eval:case-1",
)
print(result.content)
```

### Attach hooks for observability

Hooks are an advanced escape hatch. Use them when you want custom logging,
metrics, tracing, or output post-processing without modifying nanobot internals:

```python
from nanobot.agent import AgentHook, AgentHookContext


class AuditHook(AgentHook):
    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tc in context.tool_calls:
            print(f"[tool] {tc.name}")


result = await bot.run("Review this change", hooks=[AuditHook()])
```

## Where To Go Next

The SDK page is the programming entry point. The fuller conceptual and
configuration docs remain the source of truth for the runtime around it:

| Need | Read |
|------|------|
| First working install and config | [Install and Quick Start](quick-start.md) |
| Mental model for config, workspace, sessions, tools, and memory | [Concepts](concepts.md) |
| Provider/model/API key/base URL matching | [Providers and Models](providers.md) |
| Pasteable provider recipes | [Provider Cookbook](provider-cookbook.md) |
| Complete configuration reference | [Configuration](configuration.md) |
| Long-term memory design | [Memory](memory.md) |
| HTTP API instead of Python SDK | [OpenAI-Compatible API](openai-api.md) |
| Debugging install, config, provider, or runtime failures | [Troubleshooting](troubleshooting.md) |

## API Reference

### `Nanobot.from_config(config_path=None, *, workspace=None, model=None, model_preset=None)`

Create a `Nanobot` instance from a config file.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `config_path` | `str \| Path \| None` | `None` | Path to `config.json`. Defaults to `~/.nanobot/config.json`. |
| `workspace` | `str \| Path \| None` | `None` | Override the workspace directory from config. |
| `model` | `str \| None` | `None` | Override the instance default model. |
| `model_preset` | `str \| None` | `None` | Override the instance default model preset from `config.json`. |

Raises `FileNotFoundError` if an explicit config path does not exist.
Raises `ValueError` if both `model` and `model_preset` are provided.

### `await bot.run(...)`

Run the agent once and return a `RunResult`.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | `str` | *(required)* | The user message to process. |
| `session_key` | `str` | `"sdk:default"` | Session identifier for conversation isolation. Different keys get independent history. |
| `channel` | `str` | `"cli"` | Logical channel label used in runtime context. |
| `chat_id` | `str` | `"direct"` | Logical chat identifier used in runtime context. |
| `sender_id` | `str` | `"user"` | Logical sender identifier used in runtime context. |
| `media` | `list[str] \| None` | `None` | Optional local media paths attached to the message. |
| `ephemeral` | `bool` | `False` | Run without persisting the turn or compacting session history. |
| `hooks` | `list[AgentHook] \| None` | `None` | Lifecycle hooks for this run only. |
| `model` | `str \| None` | `None` | Override the model for this run only. |
| `model_preset` | `str \| None` | `None` | Override the model preset for this run only. |

`model` and `model_preset` are per-run overrides and do not change
`bot.runtime.model` after the run completes. They are mutually exclusive.

### `await bot.run_streamed(...)`

Start a streamed agent turn and return a `RunStream`. It accepts the same
parameters as `bot.run(...)`.

```python
run = await bot.run_streamed("Generate a long answer")

async for event in run.stream_events():
    ...

result = await run.wait()
```

### `bot.stream(...)`

Convenience wrapper around `run_streamed()` for direct event iteration. It
accepts the same parameters as `bot.run(...)`.

```python
async for event in bot.stream("Generate a long answer"):
    ...
```

### `RunStream`

| Method | Description |
|--------|-------------|
| `stream_events()` | Single-consumer async iterator of `StreamEvent` objects. |
| `await wait()` | Wait for the run to finish and return `RunResult`. |
| `await text()` | Wait for the run to finish and return `RunResult.content`. |
| `await cancel()` | Cancel the run and release stream resources. |
| `await aclose()` | Close the stream; equivalent cleanup primitive for `async with` / manual lifecycle code. |

Normal SDK runs with different session keys may overlap. Runs that use per-run
`model` or `model_preset` overrides are exclusive while the override is active,
because the current `AgentLoop` provider/model state is mutable.

### `StreamEvent`

| Field | Type | Description |
|-------|------|-------------|
| `type` | `StreamEventType` | Event type, such as `text.delta` or `run.completed`. |
| `delta` | `str` | Incremental text or reasoning chunk. |
| `content` | `str` | Completed text segment or final content. |
| `result` | `RunResult \| None` | Present on `run.completed`. |
| `name` | `str \| None` | Tool name for tool events. |
| `tool_call_id` | `str \| None` | Provider tool call id when available. |
| `arguments` | `dict \| None` | Tool arguments when available. |
| `iteration` | `int \| None` | Agent loop iteration when available. |
| `resuming` | `bool \| None` | Whether a text segment ended before more tool work. |
| `usage` | `dict[str, int]` | Token usage on completion events. |
| `error` | `str \| None` | Error text on failed events. |
| `metadata` | `dict` | Additional event metadata. |

Use the exported constants instead of hard-coded strings when possible:

| Constant | Value |
|----------|-------|
| `STREAM_EVENT_RUN_STARTED` | `run.started` |
| `STREAM_EVENT_TEXT_DELTA` | `text.delta` |
| `STREAM_EVENT_TEXT_COMPLETED` | `text.completed` |
| `STREAM_EVENT_REASONING_DELTA` | `reasoning.delta` |
| `STREAM_EVENT_REASONING_COMPLETED` | `reasoning.completed` |
| `STREAM_EVENT_TOOL_STARTED` | `tool.started` |
| `STREAM_EVENT_TOOL_COMPLETED` | `tool.completed` |
| `STREAM_EVENT_TOOL_FAILED` | `tool.failed` |
| `STREAM_EVENT_RUN_COMPLETED` | `run.completed` |
| `STREAM_EVENT_RUN_FAILED` | `run.failed` |

`STREAM_EVENT_TYPES` contains all stable v1 event values.

### `await bot.aclose()`

Release resources held by the SDK instance, including tool connections. The async context manager calls this automatically:

```python
async with Nanobot.from_config() as bot:
    result = await bot.run("Summarize this repo")
```

### `RunResult`

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str` | The agent's final text response. |
| `tools_used` | `list[str]` | Tool names used during the run. |
| `messages` | `list[dict]` | Final message list from the run. |
| `usage` | `dict[str, int]` | Token usage reported or estimated by the runtime. |
| `stop_reason` | `str \| None` | Why the run stopped, such as `"completed"` or `"max_iterations"`. |
| `error` | `str \| None` | Error text when the run failed inside the agent runtime. |
| `metadata` | `dict` | Outbound metadata such as latency. |

## Session, Memory, And Runtime Helpers

### `bot.sessions`

| Method | Description |
|--------|-------------|
| `await ingest(session_key, messages, metadata=None, source=None, save=True)` | Import existing transcript messages without running the model. |
| `get(session_key)` | Return a `SessionSnapshot`, or `None` if missing. |
| `list()` | Return compact `SessionInfo` rows. |
| `export(session_key)` | Return a full `SessionSnapshot` suitable for JSON serialization. |
| `clear(session_key)` | Clear and persist one session. |
| `delete(session_key)` | Delete one session from disk and cache. |
| `flush()` | Flush cached sessions to durable storage. |

Ingested messages must include `role` and `content`. Roles may be `user`,
`assistant`, `tool`, or `system`. Other fields, such as `timestamp`,
`source_session_id`, or `source_date`, are persisted as message metadata.

### `bot.memory`

| Method | Description |
|--------|-------------|
| `read()` | Read `memory/MEMORY.md`. |
| `write(text)` | Overwrite `memory/MEMORY.md`. |
| `append_history(text, session_key=None)` | Append one `memory/history.jsonl` entry and return its cursor. |
| `read_history(session_key=None)` | Read memory history entries, optionally filtered by session key. |

### `bot.runtime`

| Method / Property | Description |
|-------------------|-------------|
| `model` | Current runtime model name. |
| `workspace` | Current runtime workspace path. |
| `await compact_session(session_key)` | Run token/replay-window consolidation for a session. |
| `await compact_idle_session(session_key, max_suffix=8)` | Run idle-session compaction and return its summary. |

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
    async with Nanobot.from_config(workspace="/my/project") as bot:
        result = await bot.run(
            "Explain the main function",
            session_key="sdk:demo",
            hooks=[TimingHook()],
        )
    print(result.content)


asyncio.run(main())
```
