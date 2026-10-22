# How to Configure MCP Tools in nanobot

This guide adds an MCP server to nanobot so the agent can use external tools through the Model Context Protocol.

## What you will build

- a working nanobot agent
- one MCP integration configured through Apps or `~/.nanobot/config.json`
- a restricted set of MCP tools exposed to the model

## When to use this

Use MCP when the capability you need already exists as an MCP server, or when you want external tools to be managed outside nanobot core.

## Before you start

Complete [Quick Start](../quick-start.md) if nanobot is not installed or cannot reply yet. If you already have a working WebUI or CLI session, continue here using that instance; no reinstall or second gateway is needed.

Choose a connection type first: use **stdio** for a tool that nanobot starts as a local process (you must install its runtime, such as `npx` or `uvx`); use **HTTP** or **SSE** for a tool available at a remote URL. If the remote server requires sign-in, configure OAuth in Apps and connect it in the browser.

## Minimal working example

For local interactive setup:

1. Run `nanobot webui` and open **Apps**.
2. Choose a known MCP server preset, or add a custom stdio, HTTP, or SSE server. For a custom OAuth server, choose **OAuth** under **Authentication**, save it, and click **Connect**. Presets such as Xmind, Notion, and Linear go straight to **Connect**. Approve access in the browser window. HTTPS and localhost WebUIs return automatically. From a remote plain-HTTP WebUI, copy the complete localhost callback URL from the browser address bar and paste it into nanobot.
3. Limit the enabled tools when the server exposes more than the task needs.
4. Save and restart when prompted.
5. Mention the connected MCP server with `@` in the next message and ask for a small test action.

<details>
<summary>Manual configuration</summary>

For manual or deployment-managed config, add this to `~/.nanobot/config.json`:

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

Restart nanobot and ask a question that requires the MCP tool.

</details>

## Production notes

- Prefer `enabledTools` over exposing every tool by default.
- Use `toolTimeout` for slow MCP operations.
- Use HTTP MCP only for endpoints you trust.
- For deployment-managed OAuth servers, set `auth` to `oauth` and complete the browser connection from **Apps → MCP**.
- Keep MCP server commands stable and versioned in deployment docs or scripts.

## Security notes

- Stdio MCP starts a local process; review the command before enabling it.
- HTTP/SSE connections are checked to prevent nanobot from reaching private or internal network addresses. This check also applies during OAuth sign-in and redirects.
- OAuth credentials live in the nanobot data directory, not in `config.json`.
- Allow private HTTP MCP hosts only with narrow `tools.ssrfWhitelist` CIDRs.
- Do not place secrets in command arguments when environment variables or headers can be used.

## Troubleshooting

- Run the MCP command outside nanobot first.
- Start `nanobot gateway --verbose` and inspect tool registration logs.
- If an HTTP MCP URL is blocked, check whether it points to loopback or a private address that needs explicit allowlisting.

## Related nanobot docs

- [MCP service presets](../mcp-presets.md)
- [MCP tools for AI agents](./mcp-tools-for-ai-agents.md)
- [Configuration: MCP](../configuration.md#mcp-model-context-protocol)
- [Security](../configuration.md#security)
