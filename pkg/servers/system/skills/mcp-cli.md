---
name: mcp-cli
description: Interface for MCP (Model Context Protocol) servers via CLI. Use when you need to interact with external tools, APIs, or data sources through MCP servers.
---

# MCP-CLI

Access MCP servers through the command line. MCP enables interaction with external systems like GitHub, filesystems, databases, and APIs.

**Critical rules — never skip these:**
Your config file is located in your session directory at `.nanobot/mcp_servers.json`.
Always set `MCP_CONFIG_PATH=.nanobot/mcp_servers.json` when running mcp-cli.

Before invoking any tool, you MUST make both of these calls in order:
  1. Call `mcp-cli info <server>` to see all available tools on the server
  2. Call `mcp-cli info <server> <tool>` to get the full schema for the specific tool you plan to call.
DO NOT SKIP EITHER STEP. Do not call a tool until you have completed both info calls in the current session.

## Commands

| Command | Output |
|---------|--------|
| `mcp-cli` | List all servers and tools |
| `mcp-cli info <server>` | Show server tools and parameters |
| `mcp-cli info <server> <tool>` | Get tool JSON schema |
| `mcp-cli grep "<pattern>"` | Search tools by name |
| `mcp-cli call <server> <tool>` | Call tool (reads JSON from stdin if no args) |
| `mcp-cli call <server> <tool> '<json>'` | Call tool with arguments |

**Both formats work:** `<server> <tool>` or `<server>/<tool>`

## Workflow

1. **Discover**: `mcp-cli` → see available servers
2. **Explore**: `mcp-cli info <server>` → see tools with parameters
3. **Inspect**: `mcp-cli info <server> <tool>` → get full JSON schema
4. **Execute**: `mcp-cli call <server> <tool> '<json>'` → run with arguments

## Examples

```bash
# List all servers
mcp-cli

# With descriptions  
mcp-cli -d

# See server tools
mcp-cli info filesystem

# Get tool schema (both formats work)
mcp-cli info filesystem read_file
mcp-cli info filesystem/read_file

# Call tool
mcp-cli call filesystem read_file '{"path": "./README.md"}'

# Pipe from stdin (no '-' needed!)
cat args.json | mcp-cli call filesystem read_file

# Search for tools
mcp-cli grep "*file*"

# Output is raw text (pipe-friendly)
mcp-cli call filesystem read_file '{"path": "./file"}' | head -10
```

## Advanced Chaining

```bash
# Chain: search files → read first match
mcp-cli call filesystem search_files '{"path": ".", "pattern": "*.md"}' \
  | head -1 \
  | xargs -I {} mcp-cli call filesystem read_file '{"path": "{}"}'

# Loop: process multiple files
mcp-cli call filesystem list_directory '{"path": "./src"}' \
  | while read f; do mcp-cli call filesystem read_file "{\"path\": \"$f\"}"; done

# Conditional: check before reading
mcp-cli call filesystem list_directory '{"path": "."}' \
  | grep -q "README" \
  && mcp-cli call filesystem read_file '{"path": "./README.md"}'

# Multi-server aggregation
{
  mcp-cli call github search_repositories '{"query": "mcp", "per_page": 3}'
  mcp-cli call filesystem list_directory '{"path": "."}'
}

# Save to file
mcp-cli call github get_file_contents '{"owner": "x", "repo": "y", "path": "z"}' > output.txt
```

**Note:** `call` outputs raw text content directly (no jq needed for text extraction)

## Options

| Flag | Purpose |
|------|---------|
| `-d` | Include descriptions |
| `-c <path>` | Specify config file |

## Common Errors

| Wrong Command | Error | Fix |
|---------------|-------|-----|
| `mcp-cli server tool` | AMBIGUOUS_COMMAND | Use `call server tool` or `info server tool` |
| `mcp-cli run server tool` | UNKNOWN_SUBCOMMAND | Use `call` instead of `run` |
| `mcp-cli list` | UNKNOWN_SUBCOMMAND | Use `info` instead of `list` |
| `mcp-cli call server` | MISSING_ARGUMENT | Add tool name |
| `mcp-cli call server tool {bad}` | INVALID_JSON | Use valid JSON with quotes |

## Exit Codes

- `0`: Success
- `1`: Client error (bad args, missing config)
- `2`: Server error (tool failed)
- `3`: Network error

## Authentication

`MCP_API_KEY` is automatically available in the environment for all bash commands.
The key is refreshed on every command execution, so you do not need to manage it manually.

If you receive authentication errors (401, 403, or any auth-related failures) from an MCP server,
simply retry the command — a fresh key will be loaded automatically.

## Configuring New Servers

The mcp-cli configuration file can be found in your session directory, in `.nanobot/mcp_servers.json`.
When you need to connect to a new MCP server, add it to this file.
Only connect to MCP servers that you found in Obot.
Use the exact connection URL that was provided by the MCP server connect tool.
You MUST ALWAYS include the MCP_API_KEY credential as shown in the example below.

ALWAYS read the current configuration before attempting to modify it.
If no configuration exists, create a new one.

Example configuration:

```json
{
  "mcpServers": {
    "remote-server": {
      "url": "https://mcp.example.com",
      "headers": {
        "Authorization": "Bearer ${MCP_API_KEY}"
      }
    }
  }
}
```
