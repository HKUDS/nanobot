"""Honcho memory plugin setup: enable/disable Honcho integration."""

import json
import subprocess
import sys
from pathlib import Path

from rich.console import Console

console = Console()

# ---------------------------------------------------------------------------
# Workspace prompt templates
# ---------------------------------------------------------------------------

# Honcho-aware, conversation-first versions
HONCHO_AGENTS_MD = """\
# Agent Instructions

## Core Guideline

Respond naturally. Most messages are conversational and just need a thoughtful reply.

## When to Use Tools

Only reach for a tool when the user's message requires an action you cannot accomplish with words alone:
- They ask you to create, read, or modify a file
- They ask you to run a command or script
- They need real-time information you don't have (weather, news, live data)
- They want to set a reminder or schedule something
- They ask you to fetch a specific URL

If you're unsure whether a tool is needed, reply with text first. You can always use a tool in a follow-up if the user clarifies.

If a tool call fails, explain what happened conversationally rather than silently retrying the same call.

## When Asked About Memory

You remember things from conversations over time. That's the user-facing answer. Don't mention Honcho, file paths, tools, or any implementation details. If they ask for more specifics: "I pick up on things you tell me and keep them in mind for next time."

## User Context (Honcho)

Honcho automatically learns about users from conversations. The `query_user_context` tool is available for specific lookups about user preferences or history, but don't call it reflexively -- most of the time, conversation context is enough.

## Scheduled Reminders

When a user asks for a reminder at a specific time, use `exec` to run:
```
nanobot cron add --name "reminder" --message "Your message" --at "YYYY-MM-DDTHH:MM:SS" --deliver --to "USER_ID" --channel "CHANNEL"
```
Get USER_ID and CHANNEL from the current session (e.g., `8281248569` and `telegram` from `telegram:8281248569`).

Do NOT just tell the user you'll remind them -- actually create the cron job.

## Heartbeat Tasks

`HEARTBEAT.md` is checked every 30 minutes. For recurring/periodic tasks, edit this file instead of creating one-time reminders.

Task format:
```
- [ ] Check calendar and remind of upcoming events
- [ ] Scan inbox for urgent emails
```
"""

HONCHO_SOUL_MD = """\
# Soul

I am nanobot, a personal AI companion.

## Personality

- Warm and conversational
- Curious and engaged
- Concise but not curt
- I don't reach for actions when words are enough

## Values

- Conversation first, tools second
- Accuracy over speed
- User privacy and safety
- Transparency in actions

## Communication Style

- Respond naturally, like a thoughtful friend
- Match the user's energy and tone
- Be clear and direct
- Explain reasoning when helpful
- Ask clarifying questions when needed
- Do not announce internal actions to the user (memory writes, tool calls, etc.)
"""

HONCHO_TOOLS_MD = """\
# Tool Notes

Tool definitions are provided automatically. This file covers non-obvious behavior only.

## Important

Do NOT use the `message` tool for normal conversation. Just respond with text directly. The `message` tool is only for programmatically sending to a specific channel/chat when needed.

## Shell (`exec`)

- Commands time out after 60 seconds by default
- Output is truncated at 10,000 characters
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)

## Web Search (`web_search`)

- Requires `tools.web.search.apiKey` (Brave Search) in config
- Returns titles, URLs, and snippets

## Subagents (`spawn`)

- Use for complex or time-consuming background tasks
- Subagent has limited context -- provide clear, self-contained instructions

## Cron Reminders

Use `exec` with `nanobot cron add` to create reminders. See AGENTS.md for syntax.

## Heartbeat

`HEARTBEAT.md` is checked every 30 minutes for periodic tasks. Edit it with file tools.
"""

# Stock templates (restored on disable)
STOCK_AGENTS_MD = """\
# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
- Do not announce internal actions to the user (memory writes, tool calls, etc.)
- If the user asks how your memory works, answer simply: you remember things from conversations over time. Do not mention file names or paths.
"""

STOCK_SOUL_MD = """\
# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _get_config_path() -> Path:
    return Path.home() / ".nanobot" / "config.json"


def _get_env_path() -> Path:
    return Path.home() / ".nanobot" / ".env"


def _get_workspace_path() -> Path:
    return Path.home() / ".nanobot" / "workspace"


def _load_raw_config() -> dict:
    """Load config.json as a raw dict (preserving camelCase keys)."""
    path = _get_config_path()
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _save_raw_config(data: dict) -> None:
    """Save a raw dict back to config.json."""
    path = _get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _install_honcho_package() -> bool:
    """Install honcho-ai via uv (fallback to pip)."""
    try:
        import honcho  # noqa: F401
        console.print("  honcho-ai already installed")
        return True
    except ImportError:
        pass

    console.print("  Installing honcho-ai...")
    # Try uv first
    try:
        subprocess.run(
            [sys.executable, "-m", "uv", "pip", "install", "honcho-ai"],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print("  [green]done[/green] (via uv)")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fallback to pip
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "honcho-ai", "--quiet"],
            check=True,
            capture_output=True,
            text=True,
        )
        console.print("  [green]done[/green] (via pip)")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"  [red]Failed to install honcho-ai: {e}[/red]")
        return False


def _write_env_key(api_key: str) -> None:
    """Write HONCHO_API_KEY to ~/.nanobot/.env (append or update)."""
    env_path = _get_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    found = False

    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith("HONCHO_API_KEY="):
                    lines.append(f"HONCHO_API_KEY={api_key}\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(f"HONCHO_API_KEY={api_key}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


def _write_workspace_prompts(honcho: bool) -> None:
    """Write Honcho-aware or stock workspace prompt files, backing up any customized originals."""
    workspace = _get_workspace_path()
    workspace.mkdir(parents=True, exist_ok=True)

    if honcho:
        templates = {
            "AGENTS.md": HONCHO_AGENTS_MD,
            "SOUL.md": HONCHO_SOUL_MD,
            "TOOLS.md": HONCHO_TOOLS_MD,
        }
    else:
        templates = {
            "AGENTS.md": STOCK_AGENTS_MD,
            "SOUL.md": STOCK_SOUL_MD,
        }

    for filename, content in templates.items():
        target = workspace / filename
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing.strip() != content.strip():
                backup = target.with_suffix(f"{target.suffix}.bak")
                target.rename(backup)
                console.print(f"  Backed up {filename} -> {backup.name}")
        target.write_text(content)
        console.print(f"  Updated {filename}")


def _migrate_sessions() -> int:
    """
    Migrate local JSONL sessions into Honcho.

    Returns the number of sessions migrated.
    """
    sessions_dir = Path.home() / ".nanobot" / "sessions"
    if not sessions_dir.exists():
        return 0

    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    if not jsonl_files:
        return 0

    try:
        from nanobot.honcho.session import HonchoSessionManager
    except ImportError:
        console.print("  [red]Cannot import Honcho session manager -- skipping migration[/red]")
        return 0

    import os
    if not os.environ.get("HONCHO_API_KEY"):
        console.print("  [red]HONCHO_API_KEY not set -- skipping migration[/red]")
        console.print("  Run again after sourcing your .env file")
        return 0

    mgr = HonchoSessionManager()
    migrated = 0

    for path in jsonl_files:
        try:
            messages: list[dict] = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        continue
                    messages.append(data)

            if not messages:
                continue

            # Derive session key from filename (telegram_123456 -> telegram:123456)
            key = path.stem.replace("_", ":", 1)

            session = mgr.get_or_create(key)
            for msg in messages:
                session.add_message(msg["role"], msg["content"])
            mgr.save(session)

            # Archive the old file
            archive_dir = sessions_dir / "migrated"
            archive_dir.mkdir(exist_ok=True)
            path.rename(archive_dir / path.name)

            migrated += 1
        except Exception as e:
            console.print(f"  [yellow]Failed to migrate {path.name}: {e}[/yellow]")

    return migrated


# ---------------------------------------------------------------------------
# Public API (called from CLI commands)
# ---------------------------------------------------------------------------

def enable(api_key: str | None = None, migrate: bool = False) -> None:
    """Enable Honcho memory integration."""
    config_path = _get_config_path()
    if not config_path.exists():
        console.print("[red]No config found. Run 'nanobot onboard' first.[/red]")
        return

    console.print("\n[bold]Enabling Honcho memory...[/bold]\n")

    # 1. Install honcho-ai
    if not _install_honcho_package():
        return

    # 2. Update config.json
    console.print("  Updating config.json...")
    data = _load_raw_config()
    honcho_cfg = data.setdefault("honcho", {})
    honcho_cfg["enabled"] = True
    honcho_cfg["prefetch"] = True
    honcho_cfg.setdefault("workspaceId", "nanobot")
    _save_raw_config(data)
    console.print("  [green]done[/green]")

    # 3. Write API key to .env
    if api_key:
        console.print("  Writing HONCHO_API_KEY to ~/.nanobot/.env...")
        _write_env_key(api_key)
        console.print("  [green]done[/green]")

    # 4. Overwrite workspace prompts with conversation-first Honcho versions
    console.print("  Writing Honcho-aware workspace prompts...")
    _write_workspace_prompts(honcho=True)

    # 5. Optional session migration
    if migrate:
        console.print("  Migrating local sessions to Honcho...")
        count = _migrate_sessions()
        if count > 0:
            console.print(f"  [green]Migrated {count} session(s)[/green]")
        else:
            console.print("  No local sessions to migrate")

    # 6. Print result
    console.print("\n[bold green]Honcho memory enabled.[/bold green]\n")

    if api_key:
        env_path = _get_env_path()
        console.print("To activate the API key in your current shell:\n")
        console.print(f"  [cyan]export $(grep HONCHO_API_KEY {env_path})[/cyan]\n")
        console.print("Or add to your shell profile for persistence:\n")
        console.print(f"  [cyan]echo 'export $(grep HONCHO_API_KEY {env_path})' >> ~/.bashrc[/cyan]\n")

    console.print("Verify with: [cyan]nanobot status[/cyan]")


def disable() -> None:
    """Disable Honcho memory integration."""
    config_path = _get_config_path()
    if not config_path.exists():
        console.print("[red]No config found. Nothing to disable.[/red]")
        return

    console.print("\n[bold]Disabling Honcho memory...[/bold]\n")

    # 1. Update config.json
    console.print("  Updating config.json...")
    data = _load_raw_config()
    honcho_cfg = data.setdefault("honcho", {})
    honcho_cfg["enabled"] = False
    _save_raw_config(data)
    console.print("  [green]done[/green]")

    # 2. Restore stock workspace prompts
    console.print("  Restoring stock workspace prompts...")
    _write_workspace_prompts(honcho=False)

    # Note: TOOLS.md is left as-is on disable (the trimmed version is fine
    # for stock usage too -- no point restoring the 166-line version)

    # 3. Print result
    console.print("\n[bold green]Honcho memory disabled.[/bold green]\n")
    console.print("Your HONCHO_API_KEY and remote Honcho data are untouched.")
    console.print("Re-enable any time with: [cyan]nanobot honcho enable[/cyan]")
    console.print("\nThe bot will use local file-based sessions until re-enabled.")
