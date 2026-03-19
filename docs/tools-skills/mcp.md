# MCP integration guide

MCP (Model Context Protocol) is an open protocol from Anthropic that lets AI agents connect to external tool servers via a standard interface. Nanobot fully supports MCP and dynamically loads any registered tools without touching the core code.

---

## How MCP works

```
Nanobot agent
  → Connects to an MCP server at startup
  → Fetches the tool list
  → Wraps each tool as mcp_<server>_<tool>
  → Calls MCP tools just like built-in tools
```

Each MCP tool is exposed as `mcp_<server_name>_<tool_name>`. For example, a server named `filesystem` exposes `read_file`, so nanobot exposes `mcp_filesystem_read_file`.

---

## Configuration

Define MCP servers under the `tools.mcp_servers` section in your config:

```yaml
tools:
  mcp_servers:
    <server_name>:
      type: stdio        # or sse or streamableHttp (omit to auto-detect)
      command: "..."     # Stdio mode command
      args: []           # Stdio mode arguments
      env: {}            # Additional environment variables
      url: "..."         # HTTP/SSE mode endpoint
      headers: {}        # HTTP/SSE mode headers
      tool_timeout: 30   # Tool call timeout
      enabled_tools:     # Tool whitelist ("*" for all)
        - "*"
```

### Auto-detecting transport

If you omit `type`, nanobot determines it by:

| Condition | Result |
|------|---------|
| `command` present | `stdio` |
| `url` ending with `/sse` | `sse` |
| Other `url` value | `streamableHttp` |

---

## Stdio MCP servers

These run locally as subprocesses speaking via stdin/stdout. Ideal for wrapping CLI tools.

### Filesystem example

```yaml
tools:
  mcp_servers:
    filesystem:
      command: "npx"
      args:
        - "-y"
        - "@modelcontextprotocol/server-filesystem"
        - "/Users/john/documents"
      enabled_tools:
        - "read_file"
        - "write_file"
        - "list_directory"
```

The agent now provides `mcp_filesystem_read_file`, `mcp_filesystem_write_file`, `mcp_filesystem_list_directory`.

### GitHub example

```yaml
tools:
  mcp_servers:
    github:
      command: "npx"
      args:
        - "-y"
        - "@modelcontextprotocol/server-github"
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxxxxxxxxxxxx"
      enabled_tools:
        - "create_issue"
        - "get_pull_request"
        - "list_commits"
```

### SQLite example

```yaml
tools:
  mcp_servers:
    sqlite:
      command: "uvx"
      args:
        - "mcp-server-sqlite"
        - "--db-path"
        - "/data/mydb.sqlite"
```

### Custom Python server

```yaml
tools:
  mcp_servers:
    my-tools:
      command: "python3"
      args:
        - "/path/to/my_mcp_server.py"
      env:
        MY_API_KEY: "secret"
      tool_timeout: 60
```

---

## HTTP/SSE MCP servers

Remote servers communicate via HTTP or SSE (Server-Sent Events).

### SSE transport

URLs ending in `/sse` use SSE automatically:

```yaml
tools:
  mcp_servers:
    remote-tools:
      url: "https://mcp.example.com/sse"
      headers:
        Authorization: "Bearer your-token-here"
        X-Custom-Header: "value"
      tool_timeout: 45
```

### StreamableHTTP transport

Standard HTTP endpoints use StreamableHTTP:

```yaml
tools:
  mcp_servers:
    cloud-service:
      url: "https://api.example.com/mcp"
      headers:
        Authorization: "Bearer your-token-here"
      tool_timeout: 60
      enabled_tools:
        - "search"
        - "summarize"
```

### Force a transport type

```yaml
tools:
  mcp_servers:
    my-server:
      type: sse
      url: "https://..."
```

---

## Tool filtering (`enabled_tools`)

Control which tools nanobot loads from each server:

```yaml
enabled_tools:
  - "*"
```

```yaml
enabled_tools:
  - "read_file"
  - "write_file"
```

```yaml
enabled_tools:
  - "mcp_filesystem_read_file"
  - "mcp_filesystem_write_file"
```

```yaml
enabled_tools: []
```

If a name does not match an available tool, nanobot logs a warning listing the valid names. Both MCP-native (`read_file`) and nanobot-wrapped names (`mcp_filesystem_read_file`) are accepted.

---

## Tool timeout (`tool_timeout`)

Each MCP tool call has its own timeout in seconds. If a call exceeds this limit, it returns an error, and the agent may retry or take another action.

```yaml
tools:
  mcp_servers:
    slow-service:
      url: "https://..."
      tool_timeout: 120
```

Adjust timeouts per server based on tool execution times.

---

## Sample MCP servers

### Official MCP servers (`@modelcontextprotocol/*`)

```yaml
tools:
  mcp_servers:
    filesystem:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]

    github:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxx"

    postgres:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/mydb"]

    brave-search:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-brave-search"]
      env:
        BRAVE_API_KEY: "BSA_xxx"
      enabled_tools:
        - "brave_web_search"
```

### Third-party popular servers

```yaml
tools:
  mcp_servers:
    playwright:
      command: "npx"
      args: ["-y", "@playwright/mcp"]
      tool_timeout: 60

    puppeteer:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-puppeteer"]
      tool_timeout: 60

    memory:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-memory"]
```

### Mixed deployment example

Combine local and remote servers:

```yaml
tools:
  restrict_to_workspace: false
  mcp_servers:
    local-fs:
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
      tool_timeout: 15

    ai-search:
      url: "https://search.example.com/mcp"
      headers:
        Authorization: "Bearer sk-xxx"
      tool_timeout: 30
      enabled_tools:
        - "semantic_search"
        - "summarize_results"

    internal-api:
      type: streamableHttp
      url: "http://internal.corp.com:8080/mcp"
      headers:
        X-Internal-Token: "corp-token"
      tool_timeout: 20
```

---

## Troubleshooting

### Server connection failures

**Symptom:** Logs show `MCP server 'xxx': failed to connect`

| Cause | Fix |
|------|---------|
| `npx` or `uvx` missing | Install Node.js or uv |
| Wrong package name | Verify and run the command manually |
| Missing API key | Populate `env` with the correct secret |
| Unreachable URL | Ensure the remote server is up and accessible |

Test a stdio server manually:

```bash
npx -y @modelcontextprotocol/server-filesystem /tmp
```

### Tool name not found

**Symptom:** `enabledTools entries not found: xxx`

`enabled_tools` entries must match exposed tool names. Check the logs for available names and update the list.

- MCP-native names (e.g., `read_file`)
- Nanobot-wrapped names (`mcp_<server>_read_file`)

### Tool timeouts

**Symptom:** `MCP tool call timed out after Xs`

Increase `tool_timeout`:

```yaml
tool_timeout: 120
```

### SSE disconnections

For long-lived SSE connections, verify:
- The server sends keep-alive events
- Proxies or firewalls do not terminate idle streams
- Switching to `streamableHttp` if SSE is unstable

### MCP logs

Nanobot logs MCP activity when starting:

```
INFO  MCP server 'filesystem': connected, 8 tools registered
DEBUG MCP: registered tool 'mcp_filesystem_read_file' from server 'filesystem'
WARN  MCP server 'github': enabledTools entries not found: get_repo. Available: get_repository, ...
```

---

## Security considerations

- MCP servers act with the agent’s identity, so trust the source
- Stdio servers run with the same system privileges as nanobot
- HTTP/SSE headers may carry API keys—use environment variables instead of plaintext in config
- Nanobot’s SSRF protections apply only to built-in `web_fetch`, not MCP tools
