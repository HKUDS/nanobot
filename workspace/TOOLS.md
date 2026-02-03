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

## Scheduled Reminders (Cron)

**CRITICAL: NEVER use system `crontab`!** Use `nanobot cron add` instead.

System crontab does NOT work:
- Docker containers don't run cron daemon
- Jobs won't persist across container restarts
- Bash scripts writing to files won't notify anyone

### Correct way - use `nanobot cron add`:

```bash
# Daily at 9am (cron expression)
nanobot cron add --name "morning" --message "Good morning!" --cron "0 9 * * *" --deliver --to "USER_ID" --channel "telegram"

# Every 2 hours (interval in seconds)
nanobot cron add --name "water" --message "Drink water!" --every 7200 --deliver --to "USER_ID" --channel "telegram"

# One-time at specific time (ISO format)
nanobot cron add --name "meeting" --message "Meeting starts!" --at "2025-01-31T15:00:00" --deliver --to "USER_ID" --channel "telegram"
```

### Manage reminders
```bash
nanobot cron list              # List all jobs
nanobot cron remove <job_id>   # Remove a job
nanobot cron enable <job_id> --disable  # Disable without removing
nanobot cron run <job_id>      # Run immediately (test)
```

### Cron expression examples
- `0 9 * * *` - daily at 9:00
- `30 15 * * *` - daily at 15:30
- `0 */2 * * *` - every 2 hours
- `0 9 * * 1-5` - weekdays at 9:00
- `0 0 1 * *` - first day of month

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
