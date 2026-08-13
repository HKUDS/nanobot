# How to Add MCP Tools to an AI Agent with nanobot

nanobot can connect MCP servers and expose their tools to the agent alongside
built-in file, shell, web, cron, image generation, and subagent tools.

## What you will build

- a working nanobot agent
- one MCP server configured in `config.json`
- a restricted set of tools available to the model

## When to use this

Use MCP when a tool already exists as an MCP server, when another application
publishes an MCP adapter, or when you want a clean boundary between nanobot and
external tool logic.

## Install

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
nanobot agent -m "Hello!"
```

Install the MCP server's own runtime separately. For example, many local MCP
servers use `npx` or `uvx`.

## Minimal working example

Add a stdio MCP server to `~/.nanobot/config.json`:

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "enabledTools": ["read_file"]
      }
    }
  }
}
```

Restart nanobot, then ask a question that needs the MCP tool.

## Production notes

- Use `enabledTools` to expose only the tools the agent actually needs.
- Set `toolTimeout` for slow MCP servers.
- Prefer stdio MCP for local tools and HTTP MCP for trusted remote services.
- Keep MCP server install/update steps outside nanobot config when possible.

## Security notes

- HTTP/SSE MCP URLs use the same SSRF guard as web fetch.
- Local/private HTTP endpoints require an explicit `tools.ssrfWhitelist` entry.
- Stdio MCP servers run local processes; review their command and arguments.
- Do not pass secrets in command-line args when environment variables or headers
  are available.

## Troubleshooting

- Start `nanobot gateway --verbose` and check MCP startup logs.
- Confirm the MCP command works by itself before debugging nanobot.
- If an HTTP MCP server is blocked, review the SSRF whitelist and use a narrow
  host CIDR.

## Related nanobot docs

- [Configure MCP tools](./configure-mcp-tools.md)
- [Configuration: MCP](../configuration.md#mcp-model-context-protocol)
- [Security](../configuration.md#security)
