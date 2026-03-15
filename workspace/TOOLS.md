# Available Tools

This document describes the tools available to nanobot.

## File Operations

### read_file
Read the contents of a file.
```
read_file(path: str) -> str
```

### write_file
Write content to a file (creates parent directories if needed).
```
write_file(path: str, content: str) -> str
```

### edit_file
Edit a file by replacing specific text.
```
edit_file(path: str, old_text: str, new_text: str) -> str
```

### list_dir
List contents of a directory.
```
list_dir(path: str) -> str
```

## Shell Execution

### exec
Execute a shell command and return output.
```
exec(command: str, working_dir: str = None) -> str
```

**Safety Notes:**
- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- Optional `restrictToWorkspace` config to limit paths

## Web Access

### web_fetch
Fetch and extract main content from a URL, or call a JSON API.
```
web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str
```

**Notes:**
- Content is extracted using readability for HTML pages
- Supports markdown or plain text extraction
- Output is truncated at 50,000 characters by default

### Web Search (via SearXNG)

Use `web_fetch` against the local SearXNG instance for web searches:
```
web_fetch("http://127.0.0.1:8080/search?q=YOUR+QUERY&format=json")
```

The response is JSON. Results are in the `results` array, each with `title`, `url`, and `content` fields.
Example: `web_fetch("http://127.0.0.1:8080/search?q=python+asyncio&format=json")`

## Communication

### message
Send a message to the user (used internally).
```
message(content: str, channel: str = None, chat_id: str = None) -> str
```

## Background Tasks

### spawn
Spawn a subagent to handle a task in the background.
```
spawn(task: str, label: str = None) -> str
```

Use for complex or time-consuming tasks that can run independently. The subagent will complete the task and report back when done.

## Scheduled Reminders (Cron)

Use the `exec` tool to create scheduled reminders with `nanobot cron add`:

### Set a recurring reminder
```bash
# Every day at 9am
nanobot cron add --name "morning" --message "Good morning! ☀️" --cron "0 9 * * *"

# Every 2 hours
nanobot cron add --name "water" --message "Drink water! 💧" --every 7200
```

### Set a one-time reminder
```bash
# At a specific time (ISO format)
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"
```

### Manage reminders
```bash
nanobot cron list              # List all jobs
nanobot cron remove <job_id>   # Remove a job
```

## Heartbeat Task Management

The `HEARTBEAT.md` file in the workspace is checked every 30 minutes.
Use file operations to manage periodic tasks:

### Add a heartbeat task
```python
# Append a new task
edit_file(
    path="HEARTBEAT.md",
    old_text="## Example Tasks",
    new_text="- [ ] New periodic task here\n\n## Example Tasks"
)
```

### Remove a heartbeat task
```python
# Remove a specific task
edit_file(
    path="HEARTBEAT.md",
    old_text="- [ ] Task to remove\n",
    new_text=""
)
```

### Rewrite all tasks
```python
# Replace the entire file
write_file(
    path="HEARTBEAT.md",
    content="# Heartbeat Tasks\n\n- [ ] Task 1\n- [ ] Task 2\n"
)
```

## Browser Automation (Playwright MCP)

For JavaScript-heavy pages, login flows, screenshots, and sites that block plain HTTP requests, use the Playwright MCP tools instead of `web_fetch`.

**IMPORTANT: Before using any `mcp_playwright_*` tool, read the skill guide first:**
```
read_file("~/.nanobot/workspace/skills/playwright/SKILL.md")
```

The skill explains when to use Playwright vs `web_fetch`, how the persistent Playwright MCP service is exposed on the internal Docker network, and how to forward screenshots back to the user with `message(media=[...])`.

Available tools:
- `mcp_playwright_browser_navigate` — go to a URL
- `mcp_playwright_browser_snapshot` — get page accessibility tree and refs
- `mcp_playwright_browser_click` — click an element
- `mcp_playwright_browser_fill_form` — fill form fields
- `mcp_playwright_browser_take_screenshot` — capture a screenshot
- `mcp_playwright_browser_evaluate` — run JavaScript on the page

## PostgreSQL Database Query (Postgres MCP)

Use `mcp_postgres_query` to run read-only SQL queries against the connected PostgreSQL database.

**IMPORTANT: Before querying, read the skill guide for workflow and patterns:**
```
read_file("~/.nanobot/workspace/skills/postgres/SKILL.md")
```

The skill covers: schema discovery, table inspection, common query patterns, and best practices.

Available tool:
- `mcp_postgres_query(sql: str)` — execute a read-only SQL query and return results

**Quick reference:**
```sql
-- Discover tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

-- Describe a table
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'your_table' ORDER BY ordinal_position;

-- Query data (always LIMIT when exploring)
SELECT * FROM your_table LIMIT 20;
```

Constraints: read-only only — INSERT, UPDATE, DELETE, and DDL are not permitted.

---

## Adding Custom Tools

To add custom tools:
1. Create a class that extends `Tool` in `nanobot/agent/tools/`
2. Implement `name`, `description`, `parameters`, and `execute`
3. Register it in `AgentLoop._register_default_tools()`
