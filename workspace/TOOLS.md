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
- Commands have a 60-second timeout
- Output is truncated at 10,000 characters
- Use with caution for destructive operations

## Web Access

### web_search
Search the web using DuckDuckGo.
```
web_search(query: str) -> str
```

Returns top 5 search results with titles, URLs, and snippets.

### web_fetch
Fetch and extract main content from a URL.
```
web_fetch(url: str) -> str
```

**Notes:**
- Content is extracted using trafilatura
- Output is truncated at 8,000 characters

## Communication

### message
Send a message to the user (used internally).
```
message(content: str, channel: str = None, chat_id: str = None) -> str
```

## Usage Tracking & Self-Awareness

### usage
Query token usage, costs, and budget information for self-awareness and cost monitoring.
```
usage(query: str, model_filter: str = None, channel_filter: str = None) -> str
```

**Available queries:**
- `"current_budget"`: Get current monthly budget status and alerts
- `"usage_today"`: Show today's usage statistics
- `"usage_week"`: Show this week's usage statistics  
- `"usage_month"`: Show this month's usage statistics
- `"forecast"`: Get usage forecast for remaining month
- `"alerts"`: Show current budget alerts
- `"model_breakdown"`: Usage breakdown by model
- `"channel_breakdown"`: Usage breakdown by channel

**Optional filters:**
- `model_filter`: Filter results by specific model (e.g., "claude-3-5-sonnet")
- `channel_filter`: Filter results by specific channel ("cli", "telegram", "whatsapp")

**Examples:**
```python
# Check current budget status
usage("current_budget")

# Get today's usage for a specific model
usage("usage_today", model_filter="claude-3-5-sonnet")

# Get channel breakdown
usage("channel_breakdown")
```

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

---

## Adding Custom Tools

To add custom tools:
1. Create a class that extends `Tool` in `nanobot/agent/tools/`
2. Implement `name`, `description`, `parameters`, and `execute`
3. Register it in `AgentLoop._register_default_tools()`
