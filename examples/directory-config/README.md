# Directory-Based Configuration Example

This directory demonstrates the directory-based configuration format for nanobot.

## Structure

```
directory-config/
├── agents/              # Agent definitions directory
│   ├── main.md          # Main agent (default entrypoint)
│   └── helper.md        # Additional helper agent
├── mcp-servers.yaml     # MCP server definitions
└── README.md            # This file
```

## Agent Files (.md)

Agent `.md` files are placed in the `agents/` subdirectory. Each file defines one agent with YAML front-matter:

### Front-Matter Fields

All `HookAgent` fields are supported in the front-matter:

- `id` - Agent ID (defaults to filename without `.md`)
- `name` - Display name for the agent
- `model` - LLM model to use (e.g., `gpt-4`, `claude-3-7-sonnet-latest`)
- `mcpServers` - List of MCP servers this agent can access
- `tools` - Specific tools to expose to the agent
- `agents` - Sub-agents this agent can delegate to
- `temperature` - Sampling temperature (0.0 to 1.0)
- `topP` - Top-p sampling parameter
- `maxTokens` - Maximum tokens in response
- `starterMessages` - Suggested prompts for users
- `description` - Short description of the agent
- `icon` - Icon URL (light mode)
- `iconDark` - Icon URL (dark mode)
- And all other HookAgent fields...

### Markdown Body = Instructions

The markdown content after the front-matter becomes the agent's instructions.

## MCP Servers File

Define MCP servers in `mcp-servers.yaml` or`mcp-servers.json`:

```yaml
myserver:
  url: https://example.com/mcp
  headers:
    Authorization: Bearer ${MY_TOKEN}
```

**Note:** You can only have ONE of `mcp-servers.yaml` or `mcp-servers.json`, not both.

## Usage

Run this directory-based config with:

```bash
nanobot run ./examples/directory-config/
```

## Entrypoint Behavior

If a `main.md` file exists in the `agents/` directory, it will automatically be set as the default published entrypoint agent. In this example, the Shopping Assistant is the main agent.
