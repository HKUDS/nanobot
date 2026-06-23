# CLI Reference

Use this page when you know what you want to run and need the command shape. For a guided first run, start with [`quick-start.md`](./quick-start.md).

## Choose a Command

| Goal | Command | Notes |
|---|---|---|
| Check the install | `blackcat --version` | If this fails, try `python -m blackcat --version` |
| Create or refresh config | `blackcat onboard` | Creates `~/.blackcat/config.json` and `~/.blackcat/workspace/` |
| Use guided setup | `blackcat onboard --wizard` | Best when you prefer prompts over hand-editing JSON |
| Check config without calling a model | `blackcat status` | Reads the default config and summarizes the active model/provider |
| Send one test message | `blackcat agent -m "Hello!"` | First proof that install, config, provider, model, and workspace all work |
| Chat in the terminal | `blackcat agent` | Interactive local chat; exit with `exit`, `/exit`, `:q`, or `Ctrl+D` |
| Use WebUI or chat apps | `blackcat gateway` | Keep this terminal running while those surfaces are in use |
| Serve an OpenAI-compatible API | `blackcat serve` | Starts `/v1/chat/completions`, `/v1/models`, and `/health` |
| Check chat channel setup | `blackcat channels status` | Useful before starting `blackcat gateway` |
| Log in to QR/OAuth-style channels | `blackcat channels login <channel>` | Used by channels such as WhatsApp and WeChat |
| Log in to OAuth model providers | `blackcat provider login <provider>` | Used by OAuth providers such as OpenAI Codex and GitHub Copilot |

## Global

```bash
blackcat --help
blackcat --version
python -m blackcat --help
python -m blackcat --version
```

`python -m blackcat ...` is useful when the package is installed but the `blackcat` script is not on `PATH`.

## Common Patterns

Most day-to-day commands use the default config and workspace. Advanced or multi-instance runs usually pass both paths explicitly:

```bash
blackcat agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
blackcat gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
blackcat serve --config ./bot-a/config.json --workspace ./bot-a/workspace
```

Use `--verbose` on long-running processes when you need startup or runtime logs:

```bash
blackcat gateway --verbose
blackcat serve --verbose
```

Long-running commands keep working until you stop them. Press `Ctrl+C` in that terminal to stop `blackcat gateway` or `blackcat serve`.

## Setup

| Command | Description |
|---|---|
| `blackcat onboard` | Initialize or refresh the default config and workspace |
| `blackcat onboard --wizard` | Use the interactive setup wizard |
| `blackcat onboard --config <path> --workspace <path>` | Initialize or refresh a specific instance |

Default paths:

| Path | Default |
|---|---|
| Config | `~/.blackcat/config.json` |
| Workspace | `~/.blackcat/workspace/` |

## Agent CLI

| Command | Description |
|---|---|
| `blackcat agent -m "Hello!"` | Send one message and exit |
| `blackcat agent` | Start interactive terminal chat |
| `blackcat agent --session <id>` | Use a specific session key |
| `blackcat agent --workspace <path>` | Override workspace |
| `blackcat agent --config <path>` | Use a specific config file |
| `blackcat agent --no-markdown` | Print plain text instead of Rich-rendered Markdown |
| `blackcat agent --logs` | Show runtime logs while chatting |

Interactive mode exits with `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

## Gateway

`blackcat gateway` starts enabled chat channels, WebUI/WebSocket when configured, cron-backed system jobs, Dream, heartbeat, and the health endpoint.

| Command | Description |
|---|---|
| `blackcat gateway` | Start the gateway with config defaults |
| `blackcat gateway --verbose` | Show verbose runtime output |
| `blackcat gateway --port <port>` | Override `gateway.port` for the health endpoint |
| `blackcat gateway --workspace <path>` | Override workspace |
| `blackcat gateway --config <path>` | Use a specific config file |

Default health endpoint:

```text
http://127.0.0.1:18790/health
```

The bundled WebUI is served by the WebSocket channel, usually on port `8765`, not by the gateway health endpoint.

## OpenAI-Compatible API

| Command | Description |
|---|---|
| `blackcat serve` | Start `/v1/chat/completions`, `/v1/models`, and `/health` |
| `blackcat serve --host <host>` | Override API bind host |
| `blackcat serve --port <port>` | Override API port |
| `blackcat serve --timeout <seconds>` | Override per-request timeout |
| `blackcat serve --verbose` | Show runtime logs |
| `blackcat serve --workspace <path>` | Override workspace |
| `blackcat serve --config <path>` | Use a specific config file |

Default API endpoint:

```text
http://127.0.0.1:8900
```

See [`openai-api.md`](./openai-api.md) for request examples.

## Status

```bash
blackcat status
```

Shows the default config path, workspace path, active model, and provider summary. This command does not currently accept `--config`; use explicit `--config` and `--workspace` on `agent`, `gateway`, or `serve` when debugging a specific instance.

## Channels

| Command | Description |
|---|---|
| `blackcat channels status` | Show configured channel status |
| `blackcat channels status --config <path>` | Show channel status for a specific config |
| `blackcat channels login <channel>` | Run interactive login for supported channels |
| `blackcat channels login <channel> --force` | Re-authenticate even if credentials already exist |
| `blackcat channels login <channel> --config <path>` | Use a specific config file |

Examples:

```bash
blackcat channels login whatsapp
blackcat channels login weixin
blackcat channels status
```

See [`chat-apps.md`](./chat-apps.md) for channel-specific setup.

## Provider OAuth

| Command | Description |
|---|---|
| `blackcat provider login openai-codex` | Authenticate OpenAI Codex provider |
| `blackcat provider login github-copilot` | Authenticate GitHub Copilot provider |
| `blackcat provider logout openai-codex` | Remove OpenAI Codex OAuth state |
| `blackcat provider logout github-copilot` | Remove GitHub Copilot OAuth state |

See [`providers.md`](./providers.md#oauth-providers) for when OAuth providers need explicit provider/model selection.

## Useful First Checks

```bash
blackcat --version
blackcat status
blackcat agent -m "Hello!"
```

If these fail, use [`troubleshooting.md`](./troubleshooting.md) before debugging WebUI, chat apps, Docker, systemd, or SDK integrations.
