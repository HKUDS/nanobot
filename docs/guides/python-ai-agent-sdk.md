# Nanobot Python SDK: Run an AI Agent from Python

This guide shows when to use the Nanobot Python SDK instead of calling a model
directly. The SDK runs the same agent runtime used by the CLI: model routing,
tools, workspace access, session history, memory, streaming events, and runtime
helpers.

## What you will build

- a Python script that creates a `Nanobot`
- one agent run from code
- an optional streamed run with tool visibility

## When to use this

Use the Python SDK for notebooks, evals, product backends, local scripts,
workflow runners, and integrations that need direct access to agent sessions,
memory, hooks, runtime state, or structured run results.

Use the OpenAI-compatible API instead when another language or process should
call nanobot over HTTP.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

## Minimal working example

```python
import asyncio

from nanobot import Nanobot


async def main() -> None:
    async with Nanobot.from_config() as bot:
        result = await bot.run("List the top-level files in this workspace.")
    print(result.content)


asyncio.run(main())
```

## Production notes

- Reuse one `Nanobot` instance for related work.
- Pass `session_key` when a user, job, or eval case needs persistent history.
- Use `bot.stream(...)` when the caller needs live text, tool, or failure
  events.
- Use hooks for audit logs or custom observability.

## Security notes

- The SDK uses the same config, workspace, tools, and secrets as the CLI.
- Do not run untrusted prompts with broad file or shell access.
- Keep separate config/workspace paths for separate products or tenants.

## Troubleshooting

- If SDK code fails, first run `nanobot agent -m "Hello!"` in the same
  environment.
- Print `bot.runtime.workspace` and `bot.runtime.model` to confirm the expected
  config loaded.
- Use explicit `config_path` and `workspace` when scripts run from services.

## Related nanobot docs

- [Nanobot Python SDK](../python-sdk.md)
- [OpenAI-Compatible API](../openai-api.md)
- [Configuration](../configuration.md)
- [Concepts](../concepts.md)
