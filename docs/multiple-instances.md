# Multiple Instances

Use a separate home directory for each instance. Place `--home` before the subcommand; without it, nanobot uses `~/.nanobot`.

Use this for separate clients, users, or personal/work agents that need independent configuration and long-term memory. A new topic or a different project folder inside one instance does not provide that separation.

Separate homes and workspaces separate stored application data; they do not create an operating-system security boundary. Processes running as the same OS user may still access each other's files through unrestricted tools. For mutually untrusted users, use separate OS accounts or containers with separate mounts and credentials, and configure [tool restrictions](./configuration.md#security) for each instance.

## Quick Start

```bash
nanobot --home ~/.nanobot-work onboard
nanobot --home ~/.nanobot-work webui --port 8766 --gateway-port 18791
```

Configure this instance's models in **Settings → Models** and chat apps through **Channels** in the sidebar. Onboarding saves its default workspace as `~/.nanobot-work/workspace`. Use the collapsed examples in the [configuration reference](./configuration.md) for deployment-managed JSON.

Use the same home for other commands:

```bash
nanobot --home ~/.nanobot-work status
nanobot --home ~/.nanobot-work agent
nanobot --home ~/.nanobot-work gateway --port 18791
```

Concurrent instances need distinct gateway health ports and WebUI/channel ports. `webui --port` sets the WebUI/WebSocket port; `--gateway-port` sets the health port. For `gateway`, `--port` sets the health port. You can also save these ports in each config. Chat channels should use separate bot credentials.

## Path Resolution

| Data | Location |
|------|----------|
| Config | `<home>/config.json`, or explicit `--config` |
| Workspace | `<home>/workspace` by default; saved `agents.defaults.workspace` takes precedence; `--workspace` overrides both |
| Sessions | `<config-directory>/sessions/<workspace-id>/` |
| Media, logs, runtime state | Under the config directory |
| Memory, skills, cron jobs | Under the workspace |
| CLI input history | `<home>/history/cli_history` |

An explicit `--config` also selects the runtime data directory. Keep each config in its own directory and use separate workspaces to isolate memory, skills, and sessions. A new home gets its own config and default workspace; existing paths saved in a config remain unchanged when you select a different `--home`. Check which paths this instance will use with `nanobot --home ~/.nanobot-work status`. Selecting a home does not move or rewrite paths saved in an existing config.

For custom config/workspace locations:

```bash
nanobot onboard --config ~/bots/work/config.json --workspace ~/work-agent
nanobot webui --config ~/bots/work/config.json --port 8766 --gateway-port 18791
```

You can also copy an existing config into the new directory and change `agents.defaults.workspace`. Model presets can be reused; select a different `agents.defaults.modelPreset` when needed.

Interactive `agent` and `webui` commands with the same config and explicit workspace selectors share a gateway. Different selectors produce separate runtime state and processes; one-shot and `--classic` agent runs execute directly. Background gateways receive `--home` through their command-line arguments.

## Health Check

Each gateway serves `GET /health` on `gateway.host:gateway.port`, bound to `127.0.0.1` by default. It returns `200` when the WebSocket channel is disabled or running, and `503` when enabled but not running. The JSON fields are `status`, `process`, `ready`, and `websocket`; other paths return `404`.

This checks process liveness and WebSocket readiness, not other chat channels, MCP servers, or model connectivity. See [CLI Reference](./cli-reference.md#gateway) for gateway management commands.
