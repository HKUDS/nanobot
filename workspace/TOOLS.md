# Tools Reference

Nanobot comes equipped with a set of powerful tools.

## Core Tools

### Filesystem
- **read_file**: Read the contents of a file.
- **write_file**: Write content to a file (creates if missing).
- **edit_file**: Edit a specific part of a file.
- **list_dir**: List files in a directory.

### Shell
- **exec**: Execute shell commands in the workspace.

### Web
- **web_search**: Search the web (via Brave API).
- **web_fetch**: Fetch and extract text from a URL.

### Messaging
- **message**: Send a message to a user on a specific channel (Telegram/WhatsApp).
- **spawn**: Spawn a background subagent for complex tasks.

## Tool Response Offloading

To manage context window size, Nanobot automatically "offloads" large tool responses to the file system.

When this happens, you will see a message like:
```
[TOOL RESPONSE OFFLOADED]
Tool: web_fetch
Artifact ID: web_fetch_20240101_123456
...
--- PREVIEW ---
<preview content>
--- END PREVIEW ---

Files Full response saved to: .artifacts/...
Use read_artifact('artifact_id') to load full content.
```

### Artifact Tools
Use these tools to interact with offloaded content:

- **read_artifact(artifact_id)**: Load the full content of an offloaded response.
- **tail_artifact(artifact_id, lines=50)**: Read just the end of a large file (good for logs).
- **search_artifact(artifact_id, query)**: Search for specific text within a large response.
- **list_artifacts()**: See what artifacts are available in the current session.
- **cleanup_artifacts(retention_days=7)**: Manually trigger cleanup of old artifacts.

> [!TIP]
> **Loop Prevention**: Output from `read_artifact`, `search_artifact`, and `tail_artifact` is NEVER offloaded. This ensures you can always read the full content, no matter how large.
