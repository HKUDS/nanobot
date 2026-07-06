# CLI Reference

Use this page when you know what you want to run and need the command shape. For a guided first run, start with [`quick-start.md`](./quick-start.md).

## Choose a Command

| Goal | Command | Notes |
|---|---|---|
| Check the install | `nanobot --version` | If this fails, try `python -m nanobot --version` |
| Create or refresh config | `nanobot onboard` | Creates `~/.nanobot/config.json` and `~/.nanobot/workspace/` |
| Use guided setup | `nanobot onboard --wizard` | Best when you prefer prompts over hand-editing JSON |
| Open the browser workbench | `nanobot webui` | Prepares local WebUI settings, starts the gateway, and opens the browser |
| Check config without calling a model | `nanobot status` | Summarizes the selected config, workspace, active model, and providers |
| Send one test message | `nanobot agent -m "Hello!"` | First proof that install, config, provider, model, and workspace all work |
| Chat in the terminal | `nanobot agent` | Interactive local chat; exit with `exit`, `/exit`, `:q`, or `Ctrl+D` |
| Run the gateway directly | `nanobot gateway` | Service/ops command for WebUI, chat apps, cron, and heartbeat |
| Deliver a local trigger | `nanobot trigger <id> "message"` | Created first with `/trigger <name>` in the target chat/session |
| Serve an OpenAI-compatible API | `nanobot serve` | Starts `/v1/chat/completions`, `/v1/models`, and `/health` |
| Check chat channel setup | `nanobot channels status` | Useful before starting `nanobot gateway` |
| Manage optional features | `nanobot plugins list` | Shows channels and optional capabilities you can turn on |
| Log in to QR/OAuth-style channels | `nanobot channels login <channel>` | Used by channels such as WhatsApp and WeChat |
| Log in to OAuth model providers | `nanobot provider login <provider>` | Used by OAuth providers such as OpenAI Codex and GitHub Copilot |

## Global

```bash
nanobot --help
nanobot --version
python -m nanobot --help
python -m nanobot --version
```

`python -m nanobot ...` is useful when the package is installed but the `nanobot` script is not on `PATH`.

## Common Patterns

Most day-to-day commands use the default config and workspace. Advanced or multi-instance runs usually pass both paths explicitly:

```bash
nanobot agent --config ./bot-a/config.json --workspace ./bot-a/workspace -m "Hello"
nanobot gateway --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot serve --config ./bot-a/config.json --workspace ./bot-a/workspace
```

Use `--verbose` on long-running processes when you need startup or runtime logs:

```bash
nanobot gateway --verbose
nanobot serve --verbose
```

Long-running commands keep working until you stop them. Press `Ctrl+C` in that terminal
to stop foreground `nanobot gateway` or `nanobot serve`. If you started the gateway
with `--background`, use `nanobot gateway stop`.

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

Interactive mode exits with `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

## WebUI

| Command | Description |
|---|---|
| `nanobot webui` | Create config/workspace if needed, enable the local WebUI channel after confirmation, start the gateway, and open `http://127.0.0.1:8765` |
| `nanobot webui --background` | Start or reuse a background gateway, then open the WebUI |
| `nanobot webui --no-open` | Prepare and start the WebUI without opening a browser |
| `nanobot webui --port <port>` | Set the WebUI/WebSocket port |
| `nanobot webui --gateway-port <port>` | Override the gateway health port |
| `nanobot webui --yes` | Apply safe localhost WebUI defaults without confirmation; provider credentials still require interactive setup |

First-run WebUI setup binds to `127.0.0.1` by default. Use manual configuration and a WebUI password before exposing the WebSocket channel beyond localhost.

## Gateway

`nanobot gateway` starts enabled chat channels, WebUI/WebSocket when configured, cron-backed system jobs, Dream, heartbeat, and the health endpoint. Most local browser users should start with `nanobot webui`; use `gateway` directly for service management, chat app operation, and advanced deployment. By default it runs in the foreground, which keeps existing scripts and terminal workflows unchanged. Use `--background` when you want a local macOS, Linux, or Windows process that you can manage from the CLI.

| Command | Description |
|---|---|
| `nanobot gateway` | Start the gateway in the foreground with config defaults |
| `nanobot gateway --verbose` | Show verbose runtime output |
| `nanobot gateway --port <port>` | Override `gateway.port` for the health endpoint |
| `nanobot gateway --workspace <path>` | Override workspace |
| `nanobot gateway --config <path>` | Use a specific config file |
| `nanobot gateway --background` | Start the gateway as a background process |
| `nanobot gateway status` | Show the recorded background gateway PID, state file, and log file |
| `nanobot gateway logs --no-follow` | Print recent background gateway logs and exit |
| `nanobot gateway logs` | Follow background gateway logs |
| `nanobot gateway restart` | Restart the recorded background gateway with the current config |
| `nanobot gateway stop` | Stop the recorded background gateway |
| `nanobot gateway install-service` | Install a systemd user service or macOS LaunchAgent |
| `nanobot gateway install-service --dry-run` | Preview the generated service file and system commands |
| `nanobot gateway uninstall-service` | Remove the installed system service |

For custom instances, pass the same selector flags to management commands:

```bash
nanobot gateway --background --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot gateway status --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot gateway stop --config ./bot-a/config.json --workspace ./bot-a/workspace
nanobot gateway install-service --config ./bot-a/config.json --workspace ./bot-a/workspace --name bot-a
```

`--background` is a lightweight detached process. `install-service` is for
login/startup integration: Linux uses a systemd user service; macOS uses a
LaunchAgent plist. System services run the foreground gateway under the OS
supervisor rather than nesting another background process.

Default health endpoint:

```text
http://127.0.0.1:18790/health
```

The bundled WebUI is served by the WebSocket channel, usually on port `8765`, not by the gateway health endpoint.

## Local Triggers

`nanobot trigger` delivers one local message to a trigger that was created from
a chat/session with `/trigger <name>`.

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

Keep `nanobot gateway` running so the message can be delivered to the linked
chat/session. The message is recorded as an automation turn in that session,
not as a normal chat message typed by the user.

The command writes to a workspace-local durable queue. If `nanobot gateway` is
not running yet, the message waits in that workspace. If the target session is
already running a turn, the trigger waits for that session to become idle. If the
gateway exits after claiming a delivery but before the linked turn completes,
the next gateway start requeues that delivery. The queue is at-least-once, not
exactly-once, so the same message can be delivered again after an interrupted
process. If the agent receives the delivery and the turn fails, the delivery is
marked failed instead of retried indefinitely. Each delivery also writes an
audit record under `<workspace>/triggers/runs`. Run one gateway consumer per
workspace; this local queue is not a distributed multi-consumer queue.

Use stdin when another local process generates the message:

```bash
generate-report | nanobot trigger trg_8K4P2Q9X
```

Options:

| Command | Description |
|---|---|
| `nanobot trigger <id> "message"` | Deliver one message through a trigger |
| `nanobot trigger <id>` | Read the message from stdin |
| `nanobot trigger --config <path> <id> "message"` | Use the workspace from a specific config |
| `nanobot trigger --workspace <path> <id> "message"` | Use a specific workspace |

Triggers are managed in the WebUI Automations view instead of through separate
`list`, `revoke`, or `delete` CLI subcommands. From there you can pause/resume,
rename, delete, search, and copy the command for each trigger.

For webhooks or other external systems, run your own small service and have it
call this CLI after it decides what message nanobot should receive.

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

Shows the config path, workspace path, active model, and provider summary without calling a model.

| Command | Description |
|---|---|
| `nanobot status` | Inspect the default instance |
| `nanobot status --config <path>` | Inspect a specific config |
| `nanobot status --config <path> --workspace <path>` | Inspect a specific config with a workspace override |

## Channels

| Command | Description |
|---|---|
| `nanobot channels status` | Show configured channel status |
| `nanobot channels status --config <path>` | Show channel status for a specific config |
| `nanobot channels login <channel>` | Run interactive login for supported channels |
| `nanobot channels login <channel> --force` | Re-authenticate even if credentials already exist |
| `nanobot channels login <channel> --config <path>` | Use a specific config file |
| `nanobot plugins list --config <path>` | Show plugin/channel enabled state for a specific config |

Examples:

```bash
nanobot channels login whatsapp
nanobot channels login weixin
nanobot channels status
```

See [`chat-apps.md`](./chat-apps.md) for channel-specific setup.

## Optional Features

Use these commands when you want nanobot to add or remove a built-in capability
without hand-editing JSON. Enabling may install the support package first.
Disabling is for channels such as Telegram, Matrix, or Slack; it keeps your
saved settings and turns the channel off.

| Command | Description |
|---|---|
| `nanobot plugins list` | Show available channels and optional capabilities |
| `nanobot plugins enable <name>` | Install missing support and enable the feature or channel |
| `nanobot plugins enable <name> --logs` | Show package install logs while enabling |
| `nanobot plugins disable <channel>` | Turn off a channel without deleting its saved settings |
| `nanobot plugins list --config <path>` | Read a specific config file |
| `nanobot plugins enable <name> --config <path>` | Update a specific config file |
| `nanobot plugins disable <channel> --config <path>` | Turn off a channel in a specific config file |

## Provider OAuth

| Command | Description |
|---|---|
| `nanobot provider login openai-codex` | Authenticate OpenAI Codex provider |
| `nanobot provider login github-copilot` | Authenticate GitHub Copilot provider |
| `nanobot provider logout openai-codex` | Remove OpenAI Codex OAuth state |
| `nanobot provider logout github-copilot` | Remove GitHub Copilot OAuth state |

See [`providers.md`](./providers.md#oauth-providers) for when OAuth providers need explicit provider/model selection.

## Useful First Checks

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

If these fail, use [`troubleshooting.md`](./troubleshooting.md) before debugging WebUI, chat apps, Docker, systemd, or SDK integrations.
