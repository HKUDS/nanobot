# Docker Connectors

Docker connectors let nanobot start sidecar capabilities as Docker Compose projects, then consume their MCP tools like any other tool server.

Use this when you want to add capabilities such as:
- a local knowledge service
- a speech or media pipeline
- a domain-specific automation agent
- a hardware or LAN bridge

## How it Works

1. Add a connector under `connectors` in `~/.nanobot/config.json`
2. Point it to a Docker Compose file
3. Declare one or more `mcpServers` exported by that connector
4. Start `nanobot gateway`

At startup, nanobot:
- brings the connector up with `docker compose up -d`
- merges the connector's MCP servers into the normal `tools.mcpServers`
- exposes those tools to the agent like built-in MCP tools

## Example

```json
{
  "connectors": {
    "weather-stack": {
      "enabled": true,
      "type": "docker",
      "composeFile": "/home/n/mrklar-life/connectors/weather-stack/compose.yml",
      "projectName": "weather-stack",
      "services": ["weather-mcp"],
      "waitForSeconds": 2,
      "stopOnExit": false,
      "mcpServers": {
        "weather": {
          "type": "streamableHttp",
          "url": "http://127.0.0.1:9060/mcp",
          "toolTimeout": 20
        }
      }
    }
  }
}
```

This produces normal nanobot tools with the usual MCP wrapping. For the example above, a tool exported as `forecast` becomes:

```text
mcp_weather_forecast
```

If the server name collides with an existing `tools.mcpServers` entry, nanobot prefixes it with the connector name.

## Supported Fields

Each connector definition currently supports:

```json
{
  "enabled": true,
  "type": "docker",
  "composeFile": "/abs/or/workspace-relative/path/to/compose.yml",
  "projectName": "optional-compose-project",
  "services": ["optional", "service", "subset"],
  "workingDir": "/optional/working/dir",
  "env": {
    "ANY_VAR": "value",
    "WORKSPACE_PATH": "${WORKSPACE}",
    "CONNECTOR": "${CONNECTOR_NAME}"
  },
  "upArgs": [],
  "downArgs": [],
  "waitForSeconds": 0,
  "stopOnExit": false,
  "mcpServers": {
    "server-name": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:9000/mcp"
    }
  }
}
```

Notes:
- `composeFile` may be absolute or relative to the workspace
- `services` is optional; if omitted, nanobot brings up the whole compose project
- `stopOnExit: true` makes nanobot stop that connector when the gateway exits
- `${WORKSPACE}` and `${CONNECTOR_NAME}` are expanded inside connector `env`

## CLI

```bash
nanobot connectors status
nanobot connectors up
nanobot connectors up weather-stack
nanobot connectors down
nanobot connectors down weather-stack
```

## Design Notes

- Connectors are separate from channels on purpose
- They are meant to add capabilities, not user-facing chat transports
- MCP remains the clean integration boundary, so connector tools behave like every other MCP tool
