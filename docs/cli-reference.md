# CLI Reference

Use this page when you know what you want to run and need the command shape.
For a guided first run, start with [`quick-start.md`](./quick-start.md).

## Global

```bash
nanobot --help
nanobot --version
python -m nanobot --help
python -m nanobot --version
```

`python -m nanobot ...` is useful when the package is installed but the
`nanobot` script is not on `PATH`.

## Setup

| Command | Description |
|---|---|
| `nanobot onboard` | Initialize or refresh the default config and workspace |
| `nanobot onboard --wizard` | Use the interactive setup wizard |
| `nanobot onboard --config <path> --workspace <path>` | Initialize or refresh a specific instance |

Default paths:

| Path | Default |
|---|---|
| Config | `~/.nanobot/config.json` |
| Workspace | `~/.nanobot/workspace/` |

## Agent CLI

| Command | Description |
|---|---|
| `nanobot agent -m "Hello!"` | Send one message and exit |
| `nanobot agent` | Start interactive terminal chat |
| `nanobot agent --session <id>` | Use a specific session key |
| `nanobot agent --workspace <path>` | Override workspace |
| `nanobot agent --config <path>` | Use a specific config file |
| `nanobot agent --no-markdown` | Print plain text instead of Rich-rendered Markdown |
| `nanobot agent --logs` | Show runtime logs while chatting |

Interactive mode exits with `exit`, `quit`, `/exit`, `/quit`, `:q`, or
`Ctrl+D`.

## Gateway

`nanobot gateway` starts enabled chat channels, WebUI/WebSocket when configured,
cron-backed system jobs, Dream, heartbeat, and the health endpoint.

| Command | Description |
|---|---|
| `nanobot gateway` | Start the gateway with config defaults |
| `nanobot gateway --verbose` | Show verbose runtime output |
| `nanobot gateway --port <port>` | Override `gateway.port` for the health endpoint |
| `nanobot gateway --workspace <path>` | Override workspace |
| `nanobot gateway --config <path>` | Use a specific config file |

Default health endpoint:

```text
http://127.0.0.1:18790/health
```

The bundled WebUI is served by the WebSocket channel, usually on port `8765`,
not by the gateway health endpoint.

## OpenAI-Compatible API

| Command | Description |
|---|---|
| `nanobot serve` | Start `/v1/chat/completions`, `/v1/models`, and `/health` |
| `nanobot serve --host <host>` | Override API bind host |
| `nanobot serve --port <port>` | Override API port |
| `nanobot serve --timeout <seconds>` | Override per-request timeout |
| `nanobot serve --verbose` | Show runtime logs |
| `nanobot serve --workspace <path>` | Override workspace |
| `nanobot serve --config <path>` | Use a specific config file |

Default API endpoint:

```text
http://127.0.0.1:8900
```

See [`openai-api.md`](./openai-api.md) for request examples.

## Status

```bash
nanobot status
```

Shows the default config path, workspace path, active model, and provider
summary. This command does not currently accept `--config`; use explicit
`--config` and `--workspace` on `agent`, `gateway`, or `serve` when debugging a
specific instance.

## Channels

| Command | Description |
|---|---|
| `nanobot channels status` | Show configured channel status |
| `nanobot channels status --config <path>` | Show channel status for a specific config |
| `nanobot channels login <channel>` | Run interactive login for supported channels |
| `nanobot channels login <channel> --force` | Re-authenticate even if credentials already exist |
| `nanobot channels login <channel> --config <path>` | Use a specific config file |

Examples:

```bash
nanobot channels login whatsapp
nanobot channels login weixin
nanobot channels status
```

See [`chat-apps.md`](./chat-apps.md) for channel-specific setup.

## Provider OAuth

| Command | Description |
|---|---|
| `nanobot provider login openai-codex` | Authenticate OpenAI Codex provider |
| `nanobot provider login github-copilot` | Authenticate GitHub Copilot provider |
| `nanobot provider logout openai-codex` | Remove OpenAI Codex OAuth state |
| `nanobot provider logout github-copilot` | Remove GitHub Copilot OAuth state |

See [`providers.md`](./providers.md#oauth-providers) for when OAuth providers
need explicit provider/model selection.

## Useful First Checks

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

If these fail, use [`troubleshooting.md`](./troubleshooting.md) before
debugging WebUI, chat apps, Docker, systemd, or SDK integrations.
