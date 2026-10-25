# How to Configure Langfuse Observability for nanobot

nanobot can trace supported OpenAI-compatible provider calls through Langfuse's OpenAI SDK wrapper, and Codex OAuth provider calls through Langfuse's native Python SDK.

## What you will build

- Langfuse installed in the same Python environment as nanobot
- Langfuse environment variables set before startup
- one traced nanobot model call

## When to use this

Use Langfuse when you need observability for model requests, latency, errors, cost, or prompt behavior during development or production operation.

## Install

Complete [Quick Start](../quick-start.md) if nanobot is not installed or cannot reply yet. Continue with the same working instance.

Install Langfuse:

```bash
nanobot plugins enable langfuse
```

nanobot uses Langfuse Python SDK 4.7 or later in the 4.x series. Tracing supports Langfuse Cloud and self-hosted Langfuse 3.63.0 or later. The SDK enables real-time ingestion on Langfuse v4 automatically; see [Langfuse compatibility](https://langfuse.com/docs/compatibility).

## Minimal working example

Set credentials before starting nanobot:

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

PowerShell:

```powershell
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_BASE_URL = "https://cloud.langfuse.com"
nanobot agent -m "Hello!"
```

## Production notes

- Langfuse is configured with environment variables, not `config.json`.
- Start services from an environment that exports the same variables.
- Add tracing after the provider works; it should not be the first setup step.
- Native providers other than Codex OAuth that do not use the OpenAI-compatible client path may not produce Langfuse traces.

## Security notes

- Treat Langfuse projects as observability stores for sensitive prompts and outputs.
- Use separate projects for personal, staging, and production traffic.
- Keep Langfuse keys out of committed service files.

## Troubleshooting

- If no traces appear, confirm the service process sees the environment variables.
- Confirm the provider path is OpenAI-compatible or the Codex OAuth provider.
- Run one local `nanobot agent -m "Hello!"` call before debugging service logs.

## Related nanobot docs

- [Configuration: Langfuse Observability](../configuration.md#langfuse-observability)
- [Provider Cookbook: Langfuse Tracing](../provider-cookbook.md#recipe-langfuse-tracing)
- [Deployment](../deployment.md)
