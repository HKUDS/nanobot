# CLI Reference

Use this page when you know what you want to run and need the command shape. For a guided first run, start with [`quick-start.md`](./quick-start.md).

## Choose a Command

| Goal | Command | Notes |
|---|---|---|
| Check the install | `nanobot --version` | If this fails, try `python -m nanobot --version` |
| Create or refresh config | `nanobot onboard` | Creates `~/.nanobot/config.json` and `~/.nanobot/workspace/` |
| Refresh config non-interactively | `nanobot onboard --refresh` | Preserves existing values and adds missing default fields without prompting |
| Use guided setup | `nanobot onboard --wizard` | Opens the complete Agent TUI configuration editor |
| Open the browser workbench | `nanobot webui` | Prepares local WebUI settings, starts the gateway, and opens the browser |
| Check readiness without calling a model | `nanobot status` | Summarizes config/workspace and validates the active provider/model configuration |
| Send one test message | `nanobot agent -m "Hello!"` | First proof that install, config, provider, model, and workspace all work |
| Chat in the terminal | `nanobot agent` | Interactive local chat; exit with `exit`, `/exit`, `:q`, or `Ctrl+D` |
| Run the gateway directly | `nanobot gateway` | Service/ops command for WebUI, chat apps, cron, and heartbeat |
| Deliver a local trigger | `nanobot trigger <id> "message"` | Created first with `/trigger <name>` in the target chat/session |
| Serve an OpenAI-compatible API | `nanobot serve` | Starts `/v1/chat/completions`, `/v1/models`, and `/health` |
| Check chat channel setup | `nanobot channels status` | Useful before starting `nanobot gateway` |
| Manage optional features | `nanobot plugins list` | Shows channels and optional capabilities you can turn on |
| Log in to QR/OAuth-style channels | `nanobot channels login <channel>` | Used by channels such as WhatsApp and WeChat |
| Log in to OAuth model providers | `nanobot provider login <provider>` | Used by OpenAI Codex, xAI subscription, and GitHub Copilot providers |

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
| `nanobot onboard --refresh` | Refresh an existing config without prompting, preserving existing values |
| `nanobot onboard --wizard` | Open the Agent TUI directly in the complete configuration editor |
| `nanobot onboard --config <path> --workspace <path>` | Initialize or refresh a specific instance |

Default paths:

| Path | Default |
|---|---|
| Config | `~/.nanobot/config.json` |
| Workspace | `~/.nanobot/workspace/` |

## Status

| Command | Description |
|---|---|
| `nanobot status` | Summarize the default config/workspace and check Agent provider/model readiness |
| `nanobot status --config <path>` | Check a specific config file |
| `nanobot status --workspace <path>` | Show status with a workspace override |

Status does not send a model request. On success, run the printed
`nanobot agent -m "Hello!"` command to verify network access and credentials. On failure,
follow the printed WebUI **Settings → Models** or `nanobot onboard --wizard` route.

## Agent CLI

| Command | Description |
|---|---|
| `nanobot agent -m "Hello!"` | Send one message and exit |
| `nanobot agent` | Start interactive terminal chat |
| `nanobot agent --session <id>` | Use a WebSocket session key; add `--classic` for another channel |
| `nanobot agent --workspace <path>` | Override workspace |
| `nanobot agent --config <path>` | Use a specific config file |
| `nanobot agent --classic` | Use the classic Python prompt instead of the native terminal UI |
| `nanobot agent --theme auto\|dark\|light` | Auto-detect the terminal appearance or force a TUI palette |
| `nanobot agent --open config` | Start the terminal Agent directly in Configuration |
| `nanobot agent --no-markdown` | Use the classic prompt and print plain text instead of Markdown |
| `nanobot agent --logs` | Use the classic prompt and show runtime logs while chatting |

Inside the native terminal Agent, enter `/config` at any time to edit configuration. The first page
keeps the essential workspace and model choices visible; section links and `/` search expose the
complete advanced configuration. Press `Ctrl+S` to persist staged changes.

Inside the native TUI, `/sessions` switches saved conversations, `/new-chat` starts another saved
conversation, and `/context` explains the compacted summary and raw session suffix available to
the next agent turn. `/branch` forks a saved conversation from a completed reply, and `/diff`
opens the latest turn's file changes as a full-screen unified diff.
`PageUp` loads older transcript pages when you reach the top. By default, each launch starts a
new session using the launch directory as its workspace. `--session` selects a specific existing
session, and `--workspace` overrides the launch directory. When the TUI exits, it prints a
ready-to-run `nanobot agent --session ...` command for the current session.

## Session Storage and Rollback

Session JSONL files live under `<config-dir>/sessions/<workspace-id>/`, outside the
agent-readable workspace. On the first upgraded start, nanobot safely migrates existing
`<workspace>/sessions/*.jsonl` files after verifying an atomic copy. Stop every old nanobot
process that uses the workspace before upgrading; old and new binaries must not write the
same session concurrently.

To prepare a downgrade, stop nanobot and copy the current sessions back to the path understood
by older releases:

```bash
nanobot sessions restore-workspace --config ./bot-a/config.json --workspace ./bot-a/workspace
```

The command never deletes the external store and refuses to overwrite a different existing
workspace file. Back up both the config directory and workspace before changing versions.

Interactive mode uses nanobot's native TypeScript terminal UI. It talks to the same local gateway as the WebUI, so streaming, tool progress, and WebSocket sessions share one protocol instead of maintaining a second agent loop. If no gateway is running, either client starts it on demand. The TUI paints immediately while the local gateway starts, then obtains fresh bootstrap credentials and connects in the background. Exiting one TUI or WebUI launcher releases only that client; the last interactive launcher stops the on-demand gateway. A small gateway watchdog also reclaims an on-demand process if its last client crashes. `/detach` promotes the shared gateway to persistent background mode before closing the TUI, so active agent work continues without a connected client. An explicit `nanobot gateway --background` starts or promotes the gateway the same way before opening a client. `nanobot gateway restart` restarts a detached gateway without changing that lifetime; restart an attached foreground gateway in its owning terminal. `nanobot gateway stop` ends either mode.

The default `--theme auto` mode paints first with the terminal's default background, probes the real foreground and background colors asynchronously, and follows supported live appearance changes. Use `--theme light` or `--theme dark` when a terminal or multiplexer does not report its colors reliably. The model preset and workspace access labels above the composer can be clicked to open their selectors; arrow keys, `Enter`, and `Esc` provide the same controls without a mouse. Access changes still pass through the gateway's local-trust and active-turn policy checks.

`Enter` sends the current message. While a turn is active, `Enter` steers it immediately, `Tab` queues a visible follow-up for the next turn, and `Option+Up` on macOS (`Alt+Up` on Windows/Linux) returns the latest queued message to the composer. Press `Shift+Enter` to add a newline; `Ctrl+J` is the universal fallback when a terminal cannot distinguish modified Enter keys. `Alt+Enter` and `Ctrl+Enter` are also accepted when distinguishable. Use `Up`/`Down` at the composer edge to recall prompts from the current saved session. Large pastes appear as a compact placeholder in the composer but are sent unchanged. Type `/` to discover nanobot commands and terminal navigation in one palette, or type `@` to complete installed apps, configured MCP servers, and saved sessions. Use the arrow keys to choose an item and `Tab` to complete it. `/sessions` opens a searchable conversation picker, `/new-chat` preserves the current conversation and starts another one, and `/branch` forks from a completed reply. `/diff` opens a read-only unified diff for the newest turn; use `Left`/`Right` to switch edits and `Esc` to close it. The core `/new` command retains its cross-channel behavior and resets the current chat. `Ctrl+C` copies a selection, stops a running turn, clears a non-empty composer, or exits when idle. Use `PageUp`/`PageDown` to scroll, `Ctrl+Home`/`Ctrl+End` to jump to the transcript edges, and `Ctrl+O` to expand or collapse long tool traces. When you leave the bottom, the TUI shows a scrollbar and a `Ctrl+End` hint until you return. The footer reports provider token/cache usage when available. Selections copy through OSC 52 when the terminal supports it. The transcript reflows when the terminal is resized, and exiting restores the previous screen.

Packaged releases fetch a version-matched, checksummed terminal archive for macOS (Apple Silicon and Intel), Linux (x64 and ARM64), or Windows x64 on first use. The cache keeps the executable together with its licenses, third-party notices, source offer, relinking instructions, and corresponding TUI source. Windows ARM64 currently falls back to the classic prompt because the Bun runtime disables the FFI required by OpenTUI on that platform. Set `NANOBOT_TUI_NO_DOWNLOAD=1` or pass `--classic` to keep the Python-only path. A local source install requires Bun and runs its own `tui/` source while the original checkout remains available; it never silently falls back to a release binary.

Non-interactive input/output, `--logs`, and `--no-markdown` automatically retain the classic prompt so existing scripts and diagnostic workflows do not acquire terminal control sequences or silently ignore their options.

Interactive mode exits with `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`. Use `/detach` instead to close the TUI without stopping the shared gateway or its active agent work. The restored terminal prints a copyable stop command with the same `--config` and explicit `--workspace` selectors.

## WebUI

| Command | Description |
|---|---|
| `nanobot webui` | Create config/workspace if needed, enable the local WebUI channel after confirmation, start the gateway, and open `http://127.0.0.1:8765` |
| `nanobot webui --background` | Deprecated; prints the equivalent explicit `nanobot gateway --background` command and exits |
| `nanobot webui --dev` | Start the gateway and Vite together at `http://127.0.0.1:5173`, with live frontend updates |
| `nanobot webui --no-open` | Prepare and start the WebUI without opening a browser |
| `nanobot webui --port <port>` | Set the WebUI/WebSocket port |
| `nanobot webui --gateway-port <port>` | Override the gateway health port |
| `nanobot webui --yes` | Apply safe localhost WebUI defaults without confirmation; configure provider credentials in **Settings → Models** |

First-run WebUI setup binds to `127.0.0.1` by default. Use manual configuration and a WebUI password before exposing the WebSocket channel beyond localhost.

`--dev` is a foreground source-checkout workflow. Persistent gateway lifecycle is deliberately
owned only by `nanobot gateway --background`; `nanobot webui --background` prints migration
guidance instead of silently changing process ownership.
It installs frontend dependencies when `webui/node_modules` is missing, proxies to the configured
WebSocket channel port, and stops Vite when the launcher exits. The shared on-demand gateway stops
only when no other interactive client still holds it.

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
| `nanobot gateway status` | Show PID, foreground/background launch mode, explicit/on-demand lifetime, live client count, state, and logs |
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

See [Automations](./automations.md) for the broader automation model, WebUI
management, and delivery behavior.

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

Public binds (`0.0.0.0` or `::`) require `api.apiKey`; send it as a Bearer token on API routes.

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

The `plugins` command name is retained for compatibility, but these entries are
nanobot runtime support packages, not the user-invokable tools shown in WebUI
Apps. They cannot be attached to a chat turn with `@`.

| Feature name | What it enables |
|---|---|
| `api` | Dependencies required by the OpenAI-compatible `nanobot serve` process |
| `azure` | Azure identity support for Azure-hosted models |
| `bedrock` | AWS Bedrock model provider support |
| `langfuse` | Langfuse tracing support for OpenAI-compatible providers |
| `olostep` | Olostep web search provider support |
| A channel name such as `telegram` or `slack` | The connector package and saved channel enablement |

| Command | Description |
|---|---|
| `nanobot plugins list` | Show available channels and optional capabilities |
| `nanobot plugins enable <name>` | Install missing support and enable the feature or channel |
| `nanobot plugins enable <name> --logs` | Show package install logs while enabling |
| `nanobot plugins disable <channel>` | Turn off a channel without deleting its saved settings |
| `nanobot plugins list --config <path>` | Read a specific config file |
| `nanobot plugins enable <name> --config <path>` | Update a specific config file |
| `nanobot plugins disable <channel> --config <path>` | Turn off a channel in a specific config file |

Document and PDF reading are included in the standard installation. The old
`nanobot plugins enable documents` and `nanobot plugins enable pdf` commands
remain accepted as no-op compatibility aliases.

## Provider OAuth

| Command | Description |
|---|---|
| `nanobot provider login openai-codex --set-main` | Authenticate Codex and select its current default model |
| `nanobot provider login xai-grok --set-main` | Authenticate an eligible X Premium / Grok subscription and select Grok 4.5; hosted X Search is enabled for models that advertise support |
| `nanobot provider login github-copilot --set-main` | Authenticate GitHub Copilot and select its current default model |
| `nanobot provider logout openai-codex` | Remove OpenAI Codex OAuth state |
| `nanobot provider logout xai-grok --config <path>` | Remove the selected nanobot instance's xAI OAuth state |
| `nanobot provider logout github-copilot` | Remove GitHub Copilot OAuth state |

See [`providers.md`](./providers.md#oauth-providers) for when OAuth providers need explicit provider/model selection.

## Useful First Checks

```bash
nanobot --version
nanobot status
nanobot agent -m "Hello!"
```

If these fail, use [`troubleshooting.md`](./troubleshooting.md) before debugging WebUI, chat apps, Docker, systemd, or SDK integrations.
