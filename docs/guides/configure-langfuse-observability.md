# How to Configure Langfuse Observability for nanobot

nanobot can trace supported OpenAI-compatible provider calls and Codex OAuth provider calls. Tracing sends model inputs and outputs to your Langfuse service.

## What you will build

- Langfuse installed in the same Python environment as nanobot
- Langfuse configured through WebUI, `config.json`, or environment variables
- one traced nanobot model call

## When to use this

Use Langfuse when you need observability for model requests, latency, errors, cost, or prompt behavior during development or production operation.

## Configure in WebUI

Open **Settings → System → Tracing → Langfuse**. Install support if needed, enter the key pair, enable tracing, and save. Change the service URL under **Advanced options** for another Cloud region or a self-hosted service. Restart nanobot when ready; saving does not immediately start or stop tracing. Pending changes show the current running state and a restart notice.

**Test connection** uses the unsaved form without sending conversation content. It checks connectivity and credentials, not trace delivery. After restarting, send a model request and check the matching Langfuse project. Connection checks to private self-hosted addresses require an explicit `tools.ssrfWhitelist` entry.

Saved keys remain masked. Leaving them unchanged preserves their existing values or environment references; use the explicit clear action to remove a key. Cancel discards form changes without saving.

## Configure without WebUI

Complete [Quick Start](../quick-start.md) if nanobot is not installed or cannot reply yet. Continue with the same working instance.

Install Langfuse:

```bash
nanobot plugins enable langfuse
```

Use the Langfuse Cloud region or self-hosted URL that belongs to your project. See [Langfuse compatibility](https://langfuse.com/docs/compatibility) for supported self-hosted versions.

## Minimal working example

When `observability.langfuse` is absent from `config.json`, set credentials before starting nanobot:

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

- An explicit `observability.langfuse` block takes precedence as a whole. `enabled: false` disables tracing even when environment credentials exist; omitted keys in an explicit block are not filled from the environment.
- Use `${VAR}` references to keep credentials in environment variables. The first WebUI save preserves existing environment-backed values as references.
- Start services from an environment that exports the referenced variables. Restart each running instance after changing its tracing configuration.
- Add tracing after the provider works; it should not be the first setup step.
- Native providers other than Codex OAuth that do not use the OpenAI-compatible client path may not produce Langfuse traces.

## Security notes

- Treat Langfuse projects as observability stores for sensitive prompts and outputs.
- Use separate projects for personal, staging, and production traffic.
- Keep Langfuse keys out of committed service files.

## Troubleshooting

- If no traces appear, check the dialog's running state, restart if changes are pending, and test the configured URL and credentials. For environment-backed values, confirm the service sees the referenced variables.
- Confirm the provider path is OpenAI-compatible or the Codex OAuth provider.
- Run one local `nanobot agent -m "Hello!"` call before debugging service logs.

## Related nanobot docs

- [Configuration: Langfuse Observability](../configuration.md#langfuse-observability)
- [Provider Cookbook: Langfuse Tracing](../provider-cookbook.md#recipe-langfuse-tracing)
- [Deployment](../deployment.md)
