# IPython Tools Skill

Use agent tools directly from IPython.

## Description

This skill exposes all agent tools for use within IPython, allowing you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch URLs
- And more...

## Usage

```python
from nanobot.agent.tools.ipython_tools import Tools, get_tools

# Create tools instance
tools = Tools(workspace="/path/to/workspace")

# Or use convenience function
tools = get_tools()

# List available tools
tools.list()
# ['read_file', 'write_file', 'edit_file', 'list_dir', 'exec', 'web_search', 'web_fetch']

# Get help for a specific tool
print(tools.help("read_file"))

# Execute tools (all are async)
result = await tools.read_file(path="/etc/hostname")
result = await tools.write_file(path="/tmp/test.txt", content="Hello!")
result = await tools.list_dir(path="/home/user")
result = await tools.exec(command="ls -la", timeout=30)
result = await tools.web_search(query="python asyncio", count=5)
result = await tools.web_fetch(url="https://example.com", extractMode="markdown")

# Alternative: execute by name
result = await tools.execute("read_file", path="/etc/hostname")
```

## Available Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read the contents of a file |
| `write_file` | Write content to a file |
| `edit_file` | Edit a file by replacing text |
| `list_dir` | List contents of a directory |
| `exec` | Execute a shell command |
| `web_search` | Search the web |
| `web_fetch` | Fetch and extract content from a URL |

## Getting Help

```python
# List all tools
tools.list()

# Get schema for all tools
tools.schemas()

# Get help for a specific tool
tools.help("exec")
```

## Parameters

### Tools Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workspace` | `str \| Path` | Current directory | Working directory for file/shell operations |
| `timeout` | `int` | 60 | Default timeout for shell commands |
| `restrict_to_workspace` | `bool` | False | Restrict operations to workspace only |

### Tool-Specific Parameters

#### read_file
- `path` (str, required): File path to read

#### write_file
- `path` (str, required): File path to write
- `content` (str, required): Content to write

#### edit_file
- `path` (str, required): File path to edit
- `old_text` (str, required): Text to find and replace
- `new_text` (str, required): Replacement text

#### list_dir
- `path` (str, required): Directory path to list

#### exec
- `command` (str, required): Shell command to execute
- `working_dir` (str, optional): Working directory
- `timeout` (int, optional): Timeout in seconds

#### web_search
- `query` (str, required): Search query
- `count` (int, optional): Number of results (1-10)

#### web_fetch
- `url` (str, required): URL to fetch
- `extractMode` (str, optional): "markdown" or "text"
- `maxChars` (int, optional): Maximum characters to extract

## Examples

### File Operations

```python
# Read a file
content = await tools.read_file(path="/home/user/.bashrc")
print(content)

# Write a file
await tools.write_file(
    path="/tmp/notes.txt",
    content="Meeting notes:\n- Discuss project\n- Review timeline"
)

# Edit a file (replace text)
await tools.edit_file(
    path="/home/user/config.json",
    old_text='"debug": false',
    new_text='"debug": true'
)

# List directory
files = await tools.list_dir(path="/home/user/projects")
print(files)
```

### Shell Commands

```python
# Run a command
result = await tools.exec(command="git status", working_dir="/home/user/repo")
print(result)

# With timeout
result = await tools.exec(command="sleep 5 && echo done", timeout=10)
```

### Web Operations

```python
# Search the web
results = await tools.web_search(query="best practices for REST API design", count=5)
print(results)

# Fetch a webpage
content = await tools.web_fetch(
    url="https://docs.python.org/3/library/asyncio.html",
    extractMode="markdown"
)
print(content[:1000])  # First 1000 chars
```

## Notes

- All tool methods are **async** - use `await` when calling them
- Tools maintain the same restrictions as agent tools (workspace restrictions, etc.)
- The `exec` tool runs in a sandboxed environment with configurable restrictions
- Web tools may have rate limits depending on the underlying services
