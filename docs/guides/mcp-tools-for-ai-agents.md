# How to Add MCP Tools to an AI Agent with nanobot

nanobot can connect MCP servers and expose their tools to the agent alongside built-in file, shell, web, cron, image generation, and subagent tools.

## What you will build

- a working nanobot agent
- one MCP server connected through **Apps → MCP**
- a restricted set of tools available to the model

## When to use this

Use MCP when a tool already exists as an MCP server, when another application publishes an MCP adapter, or when you want a clean boundary between nanobot and external tool logic.

## Before you start

Complete [Quick Start](../quick-start.md) if nanobot is not installed or cannot reply yet. If you already have a working WebUI or CLI session, continue here using that instance; no reinstall or second gateway is needed.

Install the MCP server's own runtime separately. For example, many local MCP servers use `npx` or `uvx`.

## Minimal working example

Open **Apps → MCP**, choose a preset or add a custom server, configure its command or endpoint, limit its enabled tools, and save. Follow any connection or restart prompt, then mention the integration with `@` in chat and request a small test action.

<details>
<summary>Manual configuration</summary>

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

</details>

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
- Do not pass secrets in command-line args when environment variables or headers are available.

## Structured MCP results for backend integrations

MCP observations remain text or compact image-artifact references in the model context. Previously, other MCP result fields were discarded. Backend integrations can now inspect a string-compatible `ToolResult.data["mcp"]` in `AgentHook.after_execute_tool` or `AgentHook.on_execute_tool_error`, while `str(result)` keeps the existing model-facing output.

The optional payload retains the originating `server_name` and raw `tool_name`, tool `_meta` as `tool_meta`, `outputSchema`, annotations, and the result's `content`, `structuredContent`, `_meta`, and `isError`. SDK objects are converted with their wire field names, and retained JSON is copied so later changes to the MCP response do not mutate a captured result. Error guidance added by the registry or runner preserves this payload.

```python
from nanobot.agent.hook import AgentHook
from nanobot.agent.tools.base import ToolResult


class StructuredResultHook(AgentHook):
    async def after_execute_tool(self, context, tool_call, tool, params, result):
        if isinstance(result, ToolResult) and result.data is not None:
            mcp_result = result.data.get("mcp")
            if mcp_result is not None:
                # Consume explicitly in your trusted backend integration.
                structured = mcp_result.get("structuredContent")
```

Each MCP payload is limited to 64 KiB of serialized UTF-8 JSON, 16 levels of nesting, and 4096 values. Source identity and `isError` are reserved first; optional fields are considered in the order listed above. A field that is invalid or would exceed the shared budget is omitted whole, with no change to the model-facing result or error status. Consumers must tolerate absent fields, including `content` for large images, and treat retained metadata as untrusted server data. The structured payload is not automatically added to model messages, runtime checkpoints, logs, or ordinary WebUI events; publishing or persisting it is the integration's responsibility. The opt-in App host explicitly consumes this interface. Existing image artifact storage remains unchanged.

Tools with explicit `_meta.ui.visibility` that excludes `"model"`, including app-only tools, are not registered for agent execution. This restriction also applies when `enabledTools` explicitly names the tool. When visibility is omitted, ordinary MCP tool behavior is preserved.

### Explicit backend App bridge

The result interface preserves data without reading UI resources. A trusted host integration can separately opt into a source-bound bridge by calling `MCPToolWrapper.open_app(authorize=...)` on a tool obtained from connection discovery. The authorization callback is held by the backend; it must not be an app-supplied boolean or trust an MCP tool's annotation as proof that an operation is safe.

```python
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.mcp_apps import MCPAppAuthorization, MCPAppResource


async def read_declared_app(
    tool: MCPToolWrapper,
    authorize: MCPAppAuthorization,
) -> MCPAppResource:
    app = tool.open_app(authorize=authorize)
    try:
        return await app.read_resource()
    finally:
        app.close()
```

`read_resource()` reads only the `ui://` URI declared by that tool, through its original MCP connection. It requires exactly one matching resource with MIME type `text/html;profile=mcp-app`, accepts UTF-8 text or base64-encoded UTF-8, and rejects HTML larger than 1 MiB. Resource `_meta`, including UI CSP declarations, is retained as detached JSON within the 64 KiB message budget. The bridge returns the HTML to trusted host code; it does not execute it.

For an active app, `await app.call_tool(raw_name, arguments)` permits only tools from the originating connection that also pass `enabledTools` and include `"app"` in their visibility (or omit visibility). Thus app-only tools can be used by an approved app without entering the model registry. Every call requires an affirmative result from the host's `MCPAppAuthorization` callback, which receives the server name, raw tool name, and a detached argument snapshot. Invalid or oversized arguments fail before dispatch. A denied request never reaches the MCP server. The host must bind the app object and approval flow to its authenticated chat; this Python interface does not establish that browser authentication contract.

Closing the app revokes its access. Connection shutdown or reload revokes all app objects tied to that connection, including calls still awaiting approval. Reopen from a newly discovered wrapper after reconnecting. The bridge applies the configured `toolTimeout` to reads and calls, propagates cancellation, and performs no application-level retries of possibly committed tool actions. A result too large for the 64 KiB JSON budget fails explicitly after the tool finishes; do not retry the action merely to recover its output. This is not an exactly-once execution guarantee.

The backend interfaces do not themselves advertise or render an App. The [opt-in WebUI host](../webui.md#interactive-mcp-apps-opt-in) supplies the browser bridge, explicit approvals, and restricted sandbox. When that host is enabled, gateway MCP connections declare `io.modelcontextprotocol/ui` with `text/html;profile=mcp-app` in their initialization capabilities; disabled installations keep their existing initialization behavior. App sessions are ephemeral, remain tied to the original connection, and are never automatically resumed across a gateway restart.

## Troubleshooting

- Check MCP startup logs on the running gateway; use `--verbose` when restarting it for diagnosis.
- Confirm the MCP command works by itself before debugging nanobot.
- If an HTTP MCP server is blocked, review the SSRF whitelist and use a narrow host CIDR.

## Related nanobot docs

- [Configure MCP tools](./configure-mcp-tools.md)
- [Configuration: MCP](../configuration.md#mcp-model-context-protocol)
- [Security](../configuration.md#security)
