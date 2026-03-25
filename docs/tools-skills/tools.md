# Built-in tools guide

Nanobot agents ship with a set of built-in tools covering shell execution, filesystem operations, web access, scheduling, and messaging. This page documents each tool’s purpose, parameters, and real-world examples.

---

## Shell tool (`exec`)

Runs arbitrary shell commands while returning their stdout and stderr.

### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `command` | string | yes | The shell command to execute |
| `working_dir` | string | no | Directory where the command runs |
| `timeout` | integer | no | Timeout in seconds (default 60, max 600) |

### Usage examples

```bash
# Run a Python script
exec(command="python3 script.py")

# Install npm dependencies with extra timeout
exec(command="npm install", working_dir="/project", timeout=300)

# List files inside /tmp
exec(command="ls -la", working_dir="/tmp")
```

### Safety guardrails

The shell tool blocks dangerous commands such as:

| Blocked pattern | Description |
|------------|------|
| `rm -rf` / `rm -r` | Recursive deletion |
| `format` / `mkfs` / `diskpart` | Disk formatting |
| `dd if=` | Direct disk writes |
| `shutdown` / `reboot` / `poweroff` | Power operations |
| Fork bomb `:(){ ... }` | Resource exhaustion |
| URLs pointing to internal IPs | SSRF protection |

When `restrict_to_workspace` is enabled, the tool also rejects any commands accessing paths outside the workspace (including `../`).

### Configuration options

```yaml
tools:
  exec:
    enable: true          # Global enable/disable for exec tool
    timeout: 120         # Default timeout in seconds
    path_append: "/usr/local/bin"  # Extra PATH entries
  restrict_to_workspace: false    # Limit all tools to workspace
```

You can also customize `deny_patterns` (regex) or use `allow_patterns` for whitelist enforcement.

### Output truncation

Results are capped at **10,000 characters**. Longer output keeps the beginning and end while indicating how many characters were truncated.

---

## Filesystem tools

Four filesystem operations are available: `read_file`, `write_file`, `edit_file`, and `list_dir`.

### Path resolution rules

- **Relative paths** resolve against the agent’s workspace
- **Absolute paths** are honored directly
- When `restrict_to_workspace: true`, paths outside the workspace are rejected

---

### Read file (`read_file`)

Returns the file content with line numbers.

#### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `path` | string | yes | File path |
| `offset` | integer | no | Starting line (1-indexed, default 1) |
| `limit` | integer | no | Max lines to read (default 2000) |

#### Examples

```python
# Read the entire file
read_file(path="config.yaml")

# Read lines 500–700 of a large log
read_file(path="large_log.txt", offset=500, limit=200)

# Read an absolute path
read_file(path="/etc/hosts")
```

Results use `line| content` format:
```
1| # First line
2| Second line
```

Single calls return up to **128,000 characters**. If the file is longer, the response includes the next `offset` to continue reading.

---

### Write file (`write_file`)

Writes content to a file, creating parent directories when needed.

#### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `path` | string | yes | Destination file |
| `content` | string | yes | Content to write |

#### Examples

```python
# Create a new file
write_file(path="output/report.txt", content="Report contents...")

# Write a config file (directories created automatically)
write_file(path="config/settings.json", content='{"debug": true}')
```

> **Note:** This overwrites the existing file. Use `edit_file` for partial updates.

---

### Edit file (`edit_file`)

Modify files via precise replacements, with optional `replace_all` support.

#### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `path` | string | yes | Target file |
| `old_text` | string | yes | Text to replace |
| `new_text` | string | yes | Replacement text |
| `replace_all` | boolean | no | Replace all matches (default false) |

#### Examples

```python
# Replace a single occurrence
edit_file(
    path="config.yaml",
    old_text="debug: false",
    new_text="debug: true"
)

# Replace every occurrence
edit_file(
    path="app.py",
    old_text="import old_module",
    new_text="import new_module",
    replace_all=True
)
```

If `old_text` appears multiple times and `replace_all` is false, the tool warns and does not edit. Fuzzy matching suggestions appear when no exact match is found.

---

### List directory (`list_dir`)

List directory contents with optional recursion.

#### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `path` | string | yes | Directory path |
| `recursive` | boolean | no | Recursively list entries (default false) |
| `max_entries` | integer | no | Max items returned (default 200) |

#### Examples

```python
# List the current directory
list_dir(path=".")

# Recursively list /project (up to 500 entries)
list_dir(path="/project", recursive=True, max_entries=500)
```

Ignored directories: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`.

---

## Web tools

### Web search (`web_search`)

Search the web using the configured provider and return titles, URLs, and snippets.

#### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `query` | string | yes | Search query |
| `count` | integer | no | Number of results (1–10, default from config) |

#### Examples

```python
web_search(query="Python asyncio tutorial")
web_search(query="nanobot AI framework", count=5)
```

#### Providers

| Provider | Config value | Requires API key | Notes |
|--------|--------|--------------|------|
| Brave Search | `brave` | Yes (`BRAVE_API_KEY`) | Default; falls back to DuckDuckGo without a key |
| Tavily | `tavily` | Yes (`TAVILY_API_KEY`) | Research-focused AI search |
| DuckDuckGo | `duckduckgo` | No | Free, zero config |
| SearXNG | `searxng` | No (self-hosted) | Open-source, self-hosted search |
| Jina | `jina` | Yes (`JINA_API_KEY`) | Semantic search |

#### Configuration snippet

```yaml
tools:
  web:
    search:
      provider: brave
      api_key: "YOUR_KEY"
      max_results: 5
    proxy: "http://127.0.0.1:7890"
```

---

### Web fetch (`web_fetch`)

Fetch a URL’s contents and convert them to Markdown or plain text.

#### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `url` | string | yes | Target URL |
| `extractMode` | string | no | Output format: `markdown` (default) or `text` |
| `maxChars` | integer | no | Max characters (default 50,000) |

#### Examples

```python
web_fetch(url="https://docs.python.org/3/library/asyncio.html")
web_fetch(url="https://example.com/article", extractMode="text", maxChars=10000)
```

#### Fetch flow

1. Try **Jina Reader API** if `JINA_API_KEY` is set
2. Fall back to local `readability-lxml` if rate limits or errors occur
3. Return JSON responses as-is
4. Mark fetched content as untrusted context for the agent

#### Security

- Only `http://` and `https://` schemes are allowed
- Requests pointing to RFC 1918, localhost, or loopback addresses are blocked (SSRF protection)
- Redirect chains revalidate every hop

#### Proxy configuration

```yaml
tools:
  web:
    proxy: "http://127.0.0.1:7890"
    # proxy: "socks5://127.0.0.1:1080"
```

---

## Cron tool (`cron`)

Schedule reminders and recurring tasks with intervals, cron expressions, or single-run execution. If `tz` is omitted, cron expressions and naive ISO times default to the agent's configured timezone (UTC).

### Actions

| `action` | Description |
|----------|------|
| `add` | Create a scheduled task |
| `list` | List active tasks |
| `remove` | Delete a task |

### Parameters (for `add`)

| Parameter | Type | Description |
|------|------|------|
| `message` | string | Reminder text or task description |
| `every_seconds` | integer | Fixed interval in seconds |
| `cron_expr` | string | Cron expression (e.g., `"0 9 * * *"`) |
| `tz` | string | IANA timezone (e.g., `"Asia/Taipei"`) — works with `cron_expr` |
| `at` | string | ISO 8601 datetime for one-time execution (e.g., `"2026-03-20T10:00:00"`) |
| `job_id` | string | Task ID (used with `remove`) |

### Examples

```python
cron(action="add", message="Take a break", every_seconds=1200)
cron(action="add", message="Report weather", cron_expr="0 9 * * *", tz="Asia/Taipei")
cron(action="add", message="Meeting reminder", at="2026-03-18T15:00:00")
cron(action="add", message="Time to clock off", cron_expr="0 17 * * 1-5", tz="Asia/Taipei")
cron(action="list")
cron(action="remove", job_id="abc123")
```

### Run history tracking

Each cron task maintains a run history with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `run_at_ms` | integer | Unix timestamp (milliseconds) when the run started |
| `status` | string | Outcome: `success`, `failed`, or `error` |
| `duration_ms` | integer | How long the run took in milliseconds |
| `error` | string | Error message if `status` is `failed` or `error` |

History is retained per task and can be inspected to monitor job health over time.

### Quick reference

| Description | Parameter |
|------|------|
| Every 20 minutes | `every_seconds: 1200` |
| Every hour | `every_seconds: 3600` |
| Daily at 8 AM | `cron_expr: "0 8 * * *"` |
| Weekdays at 5 PM | `cron_expr: "0 17 * * 1-5"` |
| Monthly midnight | `cron_expr: "0 0 1 * *"` |
| One-time event | `at: "2026-03-20T10:00:00"` |

> **Note:** Cron jobs may not schedule new jobs from inside another cron job’s callback.

---

## Spawn tool (`spawn`)

Launch background subagents for complex or long-running work. The main agent regains control immediately and receives the result once the subagent completes.

### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `task` | string | yes | Description of the task for the subagent |
| `label` | string | no | Short label shown in UI |

### Examples

```python
spawn(
    task="Analyze /data/logs/ for hourly error counts and report in table format",
    label="Log analysis"
)
spawn(task="Fetch nanobot release info via GitHub API", label="Release check")
spawn(task="Summarize Python 3.13 features", label="Feature summary")
```

### Use cases

- Multi-step flows requiring several tool calls
- Time-consuming data processing or network requests
- Parallel tasks that only need to report back when done

---

## Message tool (`message`)

Send proactive messages with optional media attachments across channels.

### Parameters

| Parameter | Type | Required | Description |
|------|------|------|------|
| `content` | string | yes | Message text |
| `channel` | string | no | Target channel (e.g., `telegram`, `discord`) |
| `chat_id` | string | no | Recipient chat or user ID |
| `media` | array | no | List of attachment paths (images, audio, docs) |

### Examples

```python
message(content="Task complete!")
message(
    content="Here is today’s report",
    media=["/workspace/report.pdf", "/workspace/chart.png"]
)
message(
    content="Deployment succeeded",
    channel="telegram",
    chat_id="123456789"
)
```

### Common scenarios

- Notify users after cron jobs finish
- Report results from spawned subagents
- Send rich media (images, PDFs, audio)

---

## Global tool settings

Configure the `tools` section in your config to apply settings across all tools:

```yaml
tools:
  restrict_to_workspace: false   # Restrict tools to the workspace
  exec:
    timeout: 60
    path_append: ""
  web:
    proxy: null
    search:
      provider: brave
      api_key: ""
      max_results: 5
  mcp_servers: {}
```

