"""ADK function tools: plain Python functions with ToolContext for state access.

Each function's signature + docstring defines the tool schema (ADK auto-discovers).
Runtime context (workspace, API keys, callbacks) is accessed via tool_context.state.

State key conventions:
  app:workspace       — Path string to workspace root
  app:brave_api_key   — Brave Search API key
  app:exec_timeout    — Shell command timeout seconds
  app:exec_deny       — JSON list of deny regex patterns
  app:exec_allow      — JSON list of allow regex patterns
  app:exec_restrict   — "true" if restrict_to_workspace
  app:exec_path       — Extra PATH entries
  app:allowed_dir     — Directory restriction path (or empty)
  temp:channel        — Current message channel
  temp:chat_id        — Current message chat_id
  temp:message_id     — Current message_id
  temp:bus_publish     — (not stored; accessed via _bus_callback global)
  temp:sent_in_turn   — Whether message tool sent to same channel this turn
"""

from __future__ import annotations

import asyncio
import difflib
import html
import json
import os
import re
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse

import httpx
from google.adk.tools import ToolContext
from loguru import logger


# ── Shared state ─────────────────────────────────────────────────────────────

# The bus publish callback is set once at agent construction and shared across
# all tool invocations. We use a module-level reference because ToolContext.state
# only supports serializable values.
_bus_callback = None
_subagent_manager = None
_cron_service = None
_pending_results = None  # PendingResults heap for non-blocking generation
_gemini_api_key = None   # Set from config at startup; avoids env-var dependency


def set_runtime_refs(
    bus_publish=None,
    subagent_manager=None,
    cron_service=None,
    pending_results=None,
    gemini_api_key=None,
):
    """Set module-level references that tools need but can't be stored in state."""
    global _bus_callback, _subagent_manager, _cron_service, _pending_results, _gemini_api_key
    if bus_publish is not None:
        _bus_callback = bus_publish
    if subagent_manager is not None:
        _subagent_manager = subagent_manager
    if cron_service is not None:
        _cron_service = cron_service
    if pending_results is not None:
        _pending_results = pending_results
    if gemini_api_key is not None:
        _gemini_api_key = gemini_api_key


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_path(path: str, workspace: str, allowed_dir: str = "") -> Path:
    """Resolve path against workspace and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = Path(workspace) / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(Path(allowed_dir).resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


_MEDIA_ROOT = Path.home() / ".scorpion" / "media"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _get_session_key(tool_context: ToolContext | None) -> str:
    """Derive session key from tool context (channel:chat_id)."""
    if not tool_context:
        return "cli:direct"
    ch = tool_context.state.get("temp:channel", "cli")
    cid = tool_context.state.get("temp:chat_id", "direct")
    return f"{ch}:{cid}"


# ── File System Tools ────────────────────────────────────────────────────────


async def read_file(path: str, tool_context: ToolContext) -> str:
    """Read the contents of a file at the given path.

    Args:
        path: The file path to read.
    """
    workspace = tool_context.state.get("app:workspace", "")
    allowed_dir = tool_context.state.get("app:allowed_dir", "")
    try:
        file_path = _resolve_path(path, workspace, allowed_dir)
        if not file_path.exists():
            return f"Error: File not found: {path}"
        if not file_path.is_file():
            return f"Error: Not a file: {path}"
        return file_path.read_text(encoding="utf-8")
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(path: str, content: str, tool_context: ToolContext) -> str:
    """Write content to a file at the given path. Creates parent directories if needed.

    Args:
        path: The file path to write to.
        content: The content to write.
    """
    workspace = tool_context.state.get("app:workspace", "")
    allowed_dir = tool_context.state.get("app:allowed_dir", "")
    try:
        file_path = _resolve_path(path, workspace, allowed_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing file: {e}"


async def edit_file(path: str, old_text: str, new_text: str, tool_context: ToolContext) -> str:
    """Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file.

    Args:
        path: The file path to edit.
        old_text: The exact text to find and replace.
        new_text: The text to replace with.
    """
    workspace = tool_context.state.get("app:workspace", "")
    allowed_dir = tool_context.state.get("app:allowed_dir", "")
    try:
        file_path = _resolve_path(path, workspace, allowed_dir)
        if not file_path.exists():
            return f"Error: File not found: {path}"

        file_content = file_path.read_text(encoding="utf-8")

        if old_text not in file_content:
            return _edit_not_found(old_text, file_content, path)

        count = file_content.count(old_text)
        if count > 1:
            return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

        new_content = file_content.replace(old_text, new_text, 1)
        file_path.write_text(new_content, encoding="utf-8")
        return f"Successfully edited {file_path}"
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error editing file: {e}"


def _edit_not_found(old_text: str, content: str, path: str) -> str:
    """Build a helpful error when old_text is not found."""
    lines = content.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    window = len(old_lines)

    best_ratio, best_start = 0.0, 0
    for i in range(max(1, len(lines) - window + 1)):
        ratio = difflib.SequenceMatcher(None, old_lines, lines[i: i + window]).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, i

    if best_ratio > 0.5:
        diff = "\n".join(difflib.unified_diff(
            old_lines, lines[best_start: best_start + window],
            fromfile="old_text (provided)", tofile=f"{path} (actual, line {best_start + 1})",
            lineterm="",
        ))
        return (
            f"Error: old_text not found in {path}.\n"
            f"Best match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        )
    return f"Error: old_text not found in {path}. No similar text found. Verify the file content."


async def list_dir(path: str, tool_context: ToolContext) -> str:
    """List the contents of a directory.

    Args:
        path: The directory path to list.
    """
    workspace = tool_context.state.get("app:workspace", "")
    allowed_dir = tool_context.state.get("app:allowed_dir", "")
    try:
        dir_path = _resolve_path(path, workspace, allowed_dir)
        if not dir_path.exists():
            return f"Error: Directory not found: {path}"
        if not dir_path.is_dir():
            return f"Error: Not a directory: {path}"

        items = []
        for item in sorted(dir_path.iterdir()):
            prefix = "\U0001f4c1 " if item.is_dir() else "\U0001f4c4 "
            items.append(f"{prefix}{item.name}")

        if not items:
            return f"Directory {path} is empty"
        return "\n".join(items)
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error listing directory: {e}"


# ── Shell Execution ──────────────────────────────────────────────────────────

_DEFAULT_DENY_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\b",
    r"\bdel\s+/[fq]\b",
    r"\brmdir\s+/s\b",
    r"(?:^|[;&|]\s*)format\b",
    r"\b(mkfs|diskpart)\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\b(shutdown|reboot|poweroff)\b",
    r":\(\)\s*\{.*\};\s*:",
]


def _guard_command(command: str, cwd: str, deny: list, allow: list, restrict: bool) -> str | None:
    """Best-effort safety guard for potentially destructive commands."""
    cmd = command.strip()
    lower = cmd.lower()

    for pattern in deny:
        if re.search(pattern, lower):
            return "Error: Command blocked by safety guard (dangerous pattern detected)"

    if allow:
        if not any(re.search(p, lower) for p in allow):
            return "Error: Command blocked by safety guard (not in allowlist)"

    if restrict:
        if "..\\" in cmd or "../" in cmd:
            return "Error: Command blocked by safety guard (path traversal detected)"
        cwd_path = Path(cwd).resolve()
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", cmd)
        posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)
        for raw in win_paths + posix_paths:
            try:
                p = Path(raw.strip()).resolve()
            except Exception:
                continue
            if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                return "Error: Command blocked by safety guard (path outside working dir)"
    return None


async def exec_command(command: str, working_dir: str = "", tool_context: ToolContext = None) -> str:
    """Execute a shell command and return its output. Use with caution.

    Args:
        command: The shell command to execute.
        working_dir: Optional working directory for the command.
    """
    workspace = tool_context.state.get("app:workspace", "") if tool_context else ""
    timeout = int(tool_context.state.get("app:exec_timeout", "60")) if tool_context else 60
    deny_raw = tool_context.state.get("app:exec_deny", "") if tool_context else ""
    allow_raw = tool_context.state.get("app:exec_allow", "") if tool_context else ""
    restrict = tool_context.state.get("app:exec_restrict", "") == "true" if tool_context else False
    path_append = tool_context.state.get("app:exec_path", "") if tool_context else ""

    deny = json.loads(deny_raw) if deny_raw else _DEFAULT_DENY_PATTERNS
    allow = json.loads(allow_raw) if allow_raw else []

    cwd = working_dir or workspace or os.getcwd()
    guard_error = _guard_command(command, cwd, deny, allow, restrict)
    if guard_error:
        return guard_error

    env = os.environ.copy()
    if path_append:
        env["PATH"] = env.get("PATH", "") + os.pathsep + path_append

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            return f"Error: Command timed out after {timeout} seconds"

        output_parts = []
        if stdout:
            output_parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            stderr_text = stderr.decode("utf-8", errors="replace")
            if stderr_text.strip():
                output_parts.append(f"STDERR:\n{stderr_text}")
        if process.returncode != 0:
            output_parts.append(f"\nExit code: {process.returncode}")

        result = "\n".join(output_parts) if output_parts else "(no output)"
        max_len = 10000
        if len(result) > max_len:
            result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
        return result
    except Exception as e:
        return f"Error executing command: {e}"


# ── Web Tools ────────────────────────────────────────────────────────────────

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
_MAX_REDIRECTS = 5


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _to_markdown(raw_html: str) -> str:
    text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                  lambda m: f'[{_strip_tags(m[2])}]({m[1]})', raw_html, flags=re.I)
    text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                  lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
    text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
    text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
    text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
    return _normalize(_strip_tags(text))


async def web_search(query: str, count: int = 5, tool_context: ToolContext = None) -> str:
    """Search the web. Returns titles, URLs, and snippets.

    Args:
        query: Search query.
        count: Number of results (1-10, default 5).
    """
    api_key = ""
    if tool_context:
        api_key = tool_context.state.get("app:brave_api_key", "")
    if not api_key:
        from scorpion.config.loader import load_config
        try:
            api_key = load_config().tools.web.search.api_key or ""
        except Exception:
            pass
    if not api_key:
        return (
            "Error: Brave Search API key not configured. "
            "Set it in ~/.scorpion/config.json under tools.web.search.apiKey."
        )

    try:
        n = min(max(count, 1), 10)
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                timeout=10.0,
            )
            r.raise_for_status()

        results = r.json().get("web", {}).get("results", [])
        if not results:
            return f"No results for: {query}"

        lines = [f"Results for: {query}\n"]
        for i, item in enumerate(results[:n], 1):
            lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
            if desc := item.get("description"):
                lines.append(f"   {desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


async def web_fetch(url: str, extract_mode: str = "markdown", max_chars: int = 50000) -> str:
    """Fetch URL and extract readable content (HTML to markdown/text).

    Args:
        url: URL to fetch.
        extract_mode: Extraction mode: 'markdown' or 'text'.
        max_chars: Maximum characters to return.
    """
    from readability import Document

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return json.dumps({"error": f"Only http/https allowed, got '{parsed.scheme or 'none'}'", "url": url})
        if not parsed.netloc:
            return json.dumps({"error": "Missing domain", "url": url})
    except Exception as e:
        return json.dumps({"error": str(e), "url": url})

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            timeout=30.0,
        ) as client:
            r = await client.get(url, headers={"User-Agent": _USER_AGENT})
            r.raise_for_status()

        ctype = r.headers.get("content-type", "")

        if "application/json" in ctype:
            text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
        elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
            doc = Document(r.text)
            content = _to_markdown(doc.summary()) if extract_mode == "markdown" else _strip_tags(doc.summary())
            text = f"# {doc.title()}\n\n{content}" if doc.title() else content
            extractor = "readability"
        else:
            text, extractor = r.text, "raw"

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        return json.dumps({
            "url": url, "finalUrl": str(r.url), "status": r.status_code,
            "extractor": extractor, "truncated": truncated, "length": len(text), "text": text,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)


# ── Message Tool ─────────────────────────────────────────────────────────────


async def send_message(
    content: str,
    channel: str,
    chat_id: str,
    media: List[str],
    tool_context: ToolContext = None,
) -> str:
    """Send a message to the user. Use this when you want to communicate something.

    Args:
        content: The message content to send.
        channel: Optional target channel (telegram, discord, etc.).
        chat_id: Optional target chat/user ID.
        media: Optional list of file paths to attach (images, audio, documents).
    """
    from scorpion.bus.events import OutboundMessage

    ch = channel or (tool_context.state.get("temp:channel", "") if tool_context else "")
    cid = chat_id or (tool_context.state.get("temp:chat_id", "") if tool_context else "")
    mid = tool_context.state.get("temp:message_id", "") if tool_context else ""

    if not ch or not cid:
        return "Error: No target channel/chat specified"

    if _bus_callback is None:
        return "Error: Message sending not configured"

    meta = {"message_id": mid} if mid else {}
    # Propagate voice_reply flag so outbound TTS kicks in
    if tool_context and tool_context.state.get("temp:voice_reply") == "true":
        meta["voice_reply"] = True

    msg = OutboundMessage(
        channel=ch,
        chat_id=cid,
        content=content,
        media=media or [],
        metadata=meta,
    )

    try:
        await _bus_callback(msg)
        default_ch = tool_context.state.get("temp:channel", "") if tool_context else ""
        default_cid = tool_context.state.get("temp:chat_id", "") if tool_context else ""
        if ch == default_ch and cid == default_cid and tool_context:
            tool_context.state["temp:sent_in_turn"] = "true"
        media_info = f" with {len(media)} attachments" if media else ""
        return f"Message sent to {ch}:{cid}{media_info}"
    except Exception as e:
        return f"Error sending message: {e}"


# ── Spawn Tool ───────────────────────────────────────────────────────────────


async def spawn_task(task: str, label: str = "", tool_context: ToolContext = None) -> str:
    """Spawn a subagent to handle a task in the background. Use for complex or time-consuming independent tasks.

    Args:
        task: The task for the subagent to complete.
        label: Optional short label for the task (for display).
    """
    if _subagent_manager is None:
        return "Error: Subagent manager not configured"

    ch = tool_context.state.get("temp:channel", "cli") if tool_context else "cli"
    cid = tool_context.state.get("temp:chat_id", "direct") if tool_context else "direct"

    return await _subagent_manager.spawn(
        task=task,
        label=label or None,
        origin_channel=ch,
        origin_chat_id=cid,
        session_key=f"{ch}:{cid}",
    )


# ── Cron Tool ────────────────────────────────────────────────────────────────


async def cron(
    action: str,
    message: str = "",
    every_seconds: int = 0,
    cron_expr: str = "",
    tz: str = "",
    at: str = "",
    job_id: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Schedule reminders and recurring tasks. Actions: add, list, remove.

    Args:
        action: Action to perform: 'add', 'list', or 'remove'.
        message: Reminder message (for add).
        every_seconds: Interval in seconds (for recurring tasks).
        cron_expr: Cron expression like '0 9 * * *' (for scheduled tasks).
        tz: IANA timezone for cron expressions (e.g. 'America/Vancouver').
        at: ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00').
        job_id: Job ID (for remove).
    """
    from scorpion.cron.types import CronSchedule

    if _cron_service is None:
        return "Error: Cron service not configured"

    ch = tool_context.state.get("temp:channel", "") if tool_context else ""
    cid = tool_context.state.get("temp:chat_id", "") if tool_context else ""

    if action == "add":
        if not message:
            return "Error: message is required for add"
        if not ch or not cid:
            return "Error: no session context (channel/chat_id)"
        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"

        delete_after = False
        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz or None)
        elif at:
            dt = datetime.fromisoformat(at)
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        else:
            return "Error: either every_seconds, cron_expr, or at is required"

        job = _cron_service.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            deliver=True,
            channel=ch,
            to=cid,
            delete_after_run=delete_after,
        )
        return f"Created job '{job.name}' (id: {job.id})"

    elif action == "list":
        jobs = _cron_service.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)

    elif action == "remove":
        if not job_id:
            return "Error: job_id is required for remove"
        if _cron_service.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"

    return f"Unknown action: {action}"


# ── Creative Tools ───────────────────────────────────────────────────────────

_SAMPLE_RATE = 48000
_CHANNELS = 2
_SAMPLE_WIDTH = 2


def _get_gemini_key() -> str:
    if _gemini_api_key:
        return _gemini_api_key
    from scorpion.config.loader import load_config
    try:
        return load_config().providers.gemini.api_key or ""
    except Exception:
        return ""


async def generate_image(
    prompt: str,
    model: str = "imagen4",
    aspect: str = "1:1",
    count: int = 1,
    tool_context: ToolContext = None,
) -> str:
    """Generate images using Google Imagen 4 or Gemini. Non-blocking when running in gateway mode — results delivered on next turn.

    Args:
        prompt: Description of the image to generate.
        model: Model: imagen4 (default), imagen4-fast, imagen4-ultra, or gemini (context-aware).
        aspect: Aspect ratio: '1:1', '16:9', '9:16', '3:4', '4:3'.
        count: Number of images (1-4, default 1).
    """
    api_key = _get_gemini_key()
    if not api_key:
        return "Error: GEMINI_API_KEY not configured"

    # ── Non-blocking path: spawn background worker ────────────────────
    bus_active = (
        tool_context.state.get("app:bus_active", "") == "true"
        if tool_context else False
    )
    if _pending_results is not None and bus_active:
        from scorpion.adk.workers import worker_generate_image

        session_key = _get_session_key(tool_context)
        result_id = _pending_results.add(session_key, "image", prompt, {
            "model": model, "aspect": aspect, "count": count,
        })
        task = asyncio.create_task(worker_generate_image(
            result_id, prompt, model, aspect, count, api_key, _pending_results,
        ))
        _pending_results.register_task(result_id, task)
        logger.info("[ImageGen] Spawned worker {} — prompt={!r}", result_id, prompt[:60])
        return f"Image generation started in the background (id: {result_id}). The result will be available on the next turn."

    # ── Blocking fallback (CLI / process_direct) ──────────────────────
    out_dir = _MEDIA_ROOT / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        if model == "gemini":
            response = client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
            paths = []
            ts = _ts()
            idx = 0
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    ext = part.inline_data.mime_type.split("/")[-1]
                    if ext == "jpeg":
                        ext = "jpg"
                    suffix = f"_{idx}" if idx > 0 else ""
                    out_path = out_dir / f"image_{ts}{suffix}.{ext}"
                    out_path.write_bytes(part.inline_data.data)
                    paths.append(str(out_path))
                    logger.info("Generated image: {}", out_path)
                    idx += 1
            return "\n".join(paths) if paths else "Error: No images generated"

        model_map = {
            "imagen4": "imagen-4.0-generate-001",
            "imagen4-fast": "imagen-4.0-fast-generate-001",
            "imagen4-ultra": "imagen-4.0-ultra-generate-001",
        }
        model_id = model_map.get(model, "imagen-4.0-generate-001")

        response = client.models.generate_images(
            model=model_id,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=count,
                aspect_ratio=aspect,
                person_generation="allow_adult",
            ),
        )

        paths = []
        for i, img in enumerate(response.generated_images):
            suffix = f"_{i}" if count > 1 else ""
            out_path = out_dir / f"image_{_ts()}{suffix}.png"
            out_path.write_bytes(img.image.image_bytes)
            paths.append(str(out_path))
            logger.info("Generated image: {}", out_path)

        return "\n".join(paths) if paths else "Error: No images generated"
    except Exception as e:
        logger.error("Image generation failed: {}", e)
        return f"Error: {e}"


async def generate_video(
    prompt: str,
    duration: int = 8,
    aspect: str = "16:9",
    resolution: str = "720p",
    tool_context: ToolContext = None,
) -> str:
    """Generate videos using Google Veo 3.1. Takes 1-5 minutes. Non-blocking in gateway mode — result delivered on next turn.

    Args:
        prompt: Description of the video to generate.
        duration: Duration in seconds (4, 6, or 8, default 8).
        aspect: Aspect ratio: '16:9' or '9:16'.
        resolution: Resolution: '720p' or '1080p'.
    """
    api_key = _get_gemini_key()
    if not api_key:
        return "Error: GEMINI_API_KEY not configured"

    # ── Non-blocking path: spawn lightweight background worker ────────
    bus_active = (
        tool_context.state.get("app:bus_active", "") == "true"
        if tool_context else False
    )
    if _pending_results is not None and bus_active:
        from scorpion.adk.workers import worker_generate_video

        session_key = _get_session_key(tool_context)
        result_id = _pending_results.add(session_key, "video", prompt, {
            "duration": duration, "aspect": aspect, "resolution": resolution,
        })
        task = asyncio.create_task(worker_generate_video(
            result_id, prompt, duration, aspect, resolution, api_key, _pending_results,
        ))
        _pending_results.register_task(result_id, task)
        logger.info(
            "[VideoGen] Spawned worker {} — prompt={!r} duration={}s aspect={} res={}",
            result_id, prompt[:60], duration, aspect, resolution,
        )
        return (
            f"Video generation started in the background (id: {result_id}). "
            f"This takes 1-5 minutes. The result will be available on the next turn."
        )

    # ── Blocking fallback (CLI / process_direct) ──────────────────────
    out_dir = _MEDIA_ROOT / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        logger.info(
            "[VideoGen] Starting Veo 3.1 generation — prompt={!r} duration={}s aspect={} res={}",
            prompt[:80], duration, aspect, resolution,
        )

        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=aspect,
                duration_seconds=duration,
                resolution=resolution,
                number_of_videos=1,
            ),
        )
        logger.info("[VideoGen] Veo operation submitted, beginning poll loop...")

        def _poll():
            poll_count = 0
            while not operation.done:
                poll_count += 1
                logger.info(
                    "[VideoGen] Poll #{} (~{}s elapsed) — waiting for Veo...",
                    poll_count, poll_count * 10,
                )
                time.sleep(10)
                client.operations.get(operation)
            logger.info(
                "[VideoGen] Veo finished after {} polls (~{}s)",
                poll_count, poll_count * 10,
            )
            return operation

        op = await asyncio.get_event_loop().run_in_executor(None, _poll)

        if not op.response or not op.response.generated_videos:
            logger.warning("[VideoGen] Veo returned no videos")
            return "Error: No videos generated"

        video = op.response.generated_videos[0]
        logger.info("[VideoGen] Downloading generated video from Veo...")
        client.files.download(file=video.video)

        out_path = out_dir / f"video_{_ts()}.mp4"
        video.video.save(str(out_path))
        logger.info("[VideoGen] Video saved: {}", out_path)
        return str(out_path)
    except Exception as e:
        error_msg = str(e)
        logger.error("[VideoGen] Generation failed: {}", e)
        if "503" in error_msg or "Service Unavailable" in error_msg:
            return (
                "The video generation service is temporarily unavailable (503). "
                "Please try again in a few minutes."
            )
        return f"Error: {e}"


async def generate_music(
    prompt: str,
    duration: int = 30,
    bpm: int = 0,
    tool_context: ToolContext = None,
) -> str:
    """Generate instrumental music using Google Lyria RealTime. Non-blocking in gateway mode — result delivered on next turn.

    Args:
        prompt: Music style/mood description (e.g. 'upbeat jazz piano', 'ambient techno').
        duration: Duration in seconds (default 30, max 120).
        bpm: Beats per minute 60-200 (default: auto, pass 0 for auto).
    """
    api_key = _get_gemini_key()
    if not api_key:
        return "Error: GEMINI_API_KEY not configured"

    # ── Non-blocking path: spawn background worker ────────────────────
    bus_active = (
        tool_context.state.get("app:bus_active", "") == "true"
        if tool_context else False
    )
    if _pending_results is not None and bus_active:
        from scorpion.adk.workers import worker_generate_music

        session_key = _get_session_key(tool_context)
        result_id = _pending_results.add(session_key, "music", prompt, {
            "duration": duration, "bpm": bpm,
        })
        task = asyncio.create_task(worker_generate_music(
            result_id, prompt, duration, bpm, api_key, _pending_results,
        ))
        _pending_results.register_task(result_id, task)
        logger.info("[MusicGen] Spawned worker {} — prompt={!r}", result_id, prompt[:60])
        return f"Music generation started in the background (id: {result_id}). The result will be available on the next turn."

    # ── Blocking fallback (CLI / process_direct) ──────────────────────
    out_dir = _MEDIA_ROOT / "music"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1alpha"},
        )

        bytes_per_sec = _SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH
        target_bytes = duration * bytes_per_sec

        logger.info("Starting music generation: {} ({}s)", prompt, duration)
        audio_chunks: list[bytes] = []
        collected = 0

        async with client.aio.live.music.connect(model="models/lyria-realtime-exp") as session:
            await session.set_weighted_prompts(
                prompts=[types.WeightedPrompt(text=prompt, weight=1.0)]
            )

            config_kwargs: dict[str, Any] = dict(
                density=0.5, brightness=0.5, guidance=4.0, temperature=1.0,
            )
            if bpm:
                config_kwargs["bpm"] = bpm

            await session.set_music_generation_config(
                config=types.LiveMusicGenerationConfig(**config_kwargs)
            )
            await session.play()

            async for message in session.receive():
                try:
                    chunk = message.server_content.audio_chunks[0].data
                    if chunk:
                        audio_chunks.append(chunk)
                        collected += len(chunk)
                        if collected >= target_bytes:
                            await session.pause()
                            break
                except (AttributeError, IndexError):
                    continue

        if not audio_chunks:
            return "Error: No audio received from Lyria"

        pcm_data = b"".join(audio_chunks)
        out_path = out_dir / f"music_{_ts()}.wav"
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(_CHANNELS)
            wf.setsampwidth(_SAMPLE_WIDTH)
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(pcm_data)

        logger.info("Generated music: {} ({}s)", out_path, collected // bytes_per_sec)
        return str(out_path)
    except Exception as e:
        logger.error("Music generation failed: {}", e)
        return f"Error: {e}"


# ── Speech / TTS Tool ─────────────────────────────────────────────────────────

_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS = 1
_TTS_SAMPLE_WIDTH = 2


async def generate_speech(
    text: str,
    voice: str = "Kore",
    tool_context: ToolContext = None,
) -> str:
    """Generate a voice message from text using Gemini TTS. Non-blocking in gateway mode — result delivered on next turn.

    Args:
        text: The text to speak aloud.
        voice: Voice name: Kore, Charon, Fenrir, Aoede, Puck, Leda, Orus, Zephyr.
    """
    from scorpion.config.schema import TTS_MODEL

    api_key = _get_gemini_key()
    if not api_key:
        return "Error: GEMINI_API_KEY not configured"

    # ── Non-blocking path: spawn background worker ────────────────────
    bus_active = (
        tool_context.state.get("app:bus_active", "") == "true"
        if tool_context else False
    )
    if _pending_results is not None and bus_active:
        from scorpion.adk.workers import worker_generate_speech

        session_key = _get_session_key(tool_context)
        result_id = _pending_results.add(session_key, "speech", text[:80], {
            "voice": voice,
        })
        task = asyncio.create_task(worker_generate_speech(
            result_id, text, voice, api_key, _pending_results,
        ))
        _pending_results.register_task(result_id, task)
        logger.info("[SpeechGen] Spawned worker {} — voice={}", result_id, voice)
        return f"Speech generation started in the background (id: {result_id}). The result will be available on the next turn."

    # ── Blocking fallback (CLI / process_direct) ──────────────────────
    out_dir = _MEDIA_ROOT / "voicemessage"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=TTS_MODEL,
            contents=f"Say naturally: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )

        audio_data = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                audio_data = part.inline_data.data
                break

        if not audio_data:
            return "Error: No audio generated"

        out_path = out_dir / f"speech_{_ts()}.wav"
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(_TTS_CHANNELS)
            wf.setsampwidth(_TTS_SAMPLE_WIDTH)
            wf.setframerate(_TTS_SAMPLE_RATE)
            wf.writeframes(audio_data)

        logger.info("Generated speech: {} ({} bytes)", out_path, len(audio_data))
        return str(out_path)
    except Exception as e:
        logger.error("Speech generation failed: {}", e)
        return f"Error: {e}"


# ── Tool list for agent construction ─────────────────────────────────────────

ALL_TOOLS = [
    read_file,
    write_file,
    edit_file,
    list_dir,
    exec_command,
    web_search,
    web_fetch,
    send_message,
    spawn_task,
    cron,
    generate_image,
    generate_video,
    generate_music,
    generate_speech,
]

# Subset for subagents — general-purpose background tasks.
# Creative tools (video, image, music, speech) now use lightweight workers
# instead of full LLM subagents, so they're not included here.
SUBAGENT_TOOLS = [
    read_file,
    write_file,
    edit_file,
    list_dir,
    exec_command,
    web_search,
    web_fetch,
    send_message,
]
