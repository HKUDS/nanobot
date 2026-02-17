# Nanobot — Tools & Operational Reference

This document describes the tools the agent can call and the conventions for using them.
Keep tool usage safe, minimal, and goal‑directed.

## Workspace Conventions
- Work inside: `{workspace_path}`
- Memory:
  - `{workspace_path}/memory/MEMORY.md` (long‑term)
  - `{workspace_path}/memory/HISTORY.md` (append‑only)
- Custom skills:
  - `{workspace_path}/skills/<skill-name>/SKILL.md`

If a task mentions a custom skill, load it with `read_file` first.

---

## File Tools

### read_file
Read a text file.
```
read_file(path: str) -> str
```
Use when you need context before editing or answering.

### write_file
Write a full file (creates parent directories if needed).
```
write_file(path: str, content: str) -> str
```
Use for complete rewrites or new files.

### edit_file
Replace specific text in a file (literal string replace).
```
edit_file(path: str, old_text: str, new_text: str) -> str
```
Use for small, targeted edits. Prefer multiple small edits over one risky large edit.

### list_dir
List directory contents.
```
list_dir(path: str) -> str
```

---

## Shell Tool

### exec
Run a shell command and return stdout/stderr output.
```
exec(command: str, working_dir: str | None = None) -> str
```

Safety & practicality:
- Assume a command may fail; handle errors and explain fixes.
- Avoid destructive operations (e.g., recursive deletes, disk formatting, reboot/shutdown).
- Output may be truncated; if needed, narrow the command (grep, head, tail).

---

## Web Tools

### web_search
Search the web.
```
web_search(query: str, count: int = 5) -> str
```

### web_fetch
Fetch and extract main content from a URL.
```
web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str
```

Notes:
- Use web_search first, then web_fetch for promising sources.
- Prefer primary sources (official docs, repos, specs) for technical questions.

---

## Messaging Tool

### message
Send a message to a specific channel (e.g., WhatsApp/Telegram) if and only if the task requires it.
For normal conversation replies, do **not** call this tool—reply with plain text.

---

## Background Work

### spawn
Create a sub‑task handled by a sub‑agent.
```
spawn(task: str, label: str | None = None) -> str
```
Use only for genuinely long, independent work. Prefer doing the work directly when possible.

---

## Scheduled Reminders (Cron)

When the user requests a reminder/notification at a time or on a schedule, create it via `exec`:

### One‑time reminder
```
nanobot cron add --name "<name>" --message "<text>" --at "YYYY-MM-DDTHH:MM:SS" --deliver --to "<USER_ID>" --channel "<CHANNEL>"
```

### Recurring reminders
```
# Cron expression
nanobot cron add --name "<name>" --message "<text>" --cron "0 9 * * *"

# Every N seconds
nanobot cron add --name "<name>" --message "<text>" --every 7200
```

### Manage reminders
```
nanobot cron list
nanobot cron remove <job_id>
```

Important:
- Do **not** “store reminders” in MEMORY.md. That does not create notifications.
- USER_ID and CHANNEL come from the current session identifier (example format: `telegram:8281248569`).

---

## Heartbeat Tasks

`HEARTBEAT.md` in the workspace is checked periodically (e.g., every 30 minutes).
Use file tools to manage the checklist.

Example format:
```
- [ ] Check calendar for upcoming events
- [ ] Scan inbox for urgent emails
```
