"""Utility functions for nanobot."""

import base64
import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import tiktoken
from loguru import logger


def strip_think(text: str) -> str:
    """Remove thinking blocks and any unclosed trailing tag."""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"^\s*<think>[\s\S]*$", "", text)
    # Gemma 4 and similar models use <thought>...</thought> blocks
    text = re.sub(r"<thought>[\s\S]*?</thought>", "", text)
    text = re.sub(r"^\s*<thought>[\s\S]*$", "", text)
    return text.strip()


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_image_content_blocks(raw: bytes, mime: str, path: str, label: str) -> list[dict[str, Any]]:
    """Build native image blocks plus a short text label."""
    b64 = base64.b64encode(raw).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": path},
        },
        {"type": "text", "text": label},
    ]


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


def current_time_str(timezone: str | None = None) -> str:
    """Return the current time string."""
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone) if timezone else None
    except (KeyError, Exception):
        tz = None

    now = datetime.now(tz=tz) if tz else datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    tz_name = timezone or (time.strftime("%Z") or "UTC")
    return f"{now.strftime('%Y-%m-%d %H:%M (%A)')} ({tz_name}, UTC{offset_fmt})"


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')
_TOOL_RESULT_PREVIEW_CHARS = 1200
_TOOL_RESULTS_DIR = ".nanobot/tool-results"
_TOOL_RESULT_RETENTION_SECS = 7 * 24 * 60 * 60
_TOOL_RESULT_MAX_BUCKETS = 32

def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def image_placeholder_text(path: str | None, *, empty: str = "[image]") -> str:
    """Build an image placeholder string."""
    return f"[image: {path}]" if path else empty


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text with a stable suffix."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def find_legal_message_start(messages: list[dict[str, Any]]) -> int:
    """Find the first index whose tool results have matching assistant calls."""
    declared: set[str] = set()
    start = 0
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict) and tc.get("id"):
                    declared.add(str(tc["id"]))
        elif role == "tool":
            tid = msg.get("tool_call_id")
            if tid and str(tid) not in declared:
                start = i + 1
                declared.clear()
                for prev in messages[start : i + 1]:
                    if prev.get("role") == "assistant":
                        for tc in prev.get("tool_calls") or []:
                            if isinstance(tc, dict) and tc.get("id"):
                                declared.add(str(tc["id"]))
    return start


def stringify_text_blocks(content: list[dict[str, Any]]) -> str | None:
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            return None
        if block.get("type") != "text":
            return None
        text = block.get("text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    return "\n".join(parts)


def _render_tool_result_reference(
    filepath: Path,
    *,
    original_size: int,
    preview: str,
    truncated_preview: bool,
) -> str:
    result = (
        f"[tool output persisted]\n"
        f"Full output saved to: {filepath}\n"
        f"Original size: {original_size} chars\n"
        f"Preview:\n{preview}"
    )
    if truncated_preview:
        result += "\n...\n(Read the saved file if you need the full output.)"
    return result


def _bucket_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _cleanup_tool_result_buckets(root: Path, current_bucket: Path) -> None:
    siblings = [path for path in root.iterdir() if path.is_dir() and path != current_bucket]
    cutoff = time.time() - _TOOL_RESULT_RETENTION_SECS
    for path in siblings:
        if _bucket_mtime(path) < cutoff:
            shutil.rmtree(path, ignore_errors=True)
    keep = max(_TOOL_RESULT_MAX_BUCKETS - 1, 0)
    siblings = [path for path in siblings if path.exists()]
    if len(siblings) <= keep:
        return
    siblings.sort(key=_bucket_mtime, reverse=True)
    for path in siblings[keep:]:
        shutil.rmtree(path, ignore_errors=True)


def _write_text_atomic(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def maybe_persist_tool_result(
    workspace: Path | None,
    session_key: str | None,
    tool_call_id: str,
    content: Any,
    *,
    max_chars: int,
) -> Any:
    """Persist oversized tool output and replace it with a stable reference string."""
    if workspace is None or max_chars <= 0:
        return content

    text_payload: str | None = None
    suffix = "txt"
    if isinstance(content, str):
        text_payload = content
    elif isinstance(content, list):
        text_payload = stringify_text_blocks(content)
        if text_payload is None:
            return content
        suffix = "json"
    else:
        return content

    if len(text_payload) <= max_chars:
        return content

    root = ensure_dir(workspace / _TOOL_RESULTS_DIR)
    bucket = ensure_dir(root / safe_filename(session_key or "default"))
    try:
        _cleanup_tool_result_buckets(root, bucket)
    except Exception as exc:
        logger.warning("Failed to clean stale tool result buckets in {}: {}", root, exc)
    path = bucket / f"{safe_filename(tool_call_id)}.{suffix}"
    if not path.exists():
        if suffix == "json" and isinstance(content, list):
            _write_text_atomic(path, json.dumps(content, ensure_ascii=False, indent=2))
        else:
            _write_text_atomic(path, text_payload)

    preview = text_payload[:_TOOL_RESULT_PREVIEW_CHARS]
    return _render_tool_result_reference(
        path,
        original_size=len(text_payload),
        preview=preview,
        truncated_preview=len(text_payload) > _TOOL_RESULT_PREVIEW_CHARS,
    )


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a provider-safe assistant message with optional reasoning fields."""
    msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning_content is not None or thinking_blocks:
        msg["reasoning_content"] = reasoning_content if reasoning_content is not None else ""
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate prompt tokens with tiktoken.

    Counts all fields that providers send to the LLM: content, tool_calls,
    reasoning_content, tool_call_id, name, plus per-message framing overhead.
    """
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        parts: list[str] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        txt = part.get("text", "")
                        if txt:
                            parts.append(txt)

            tc = msg.get("tool_calls")
            if tc:
                parts.append(json.dumps(tc, ensure_ascii=False))

            rc = msg.get("reasoning_content")
            if isinstance(rc, str) and rc:
                parts.append(rc)

            for key in ("name", "tool_call_id"):
                value = msg.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)

        if tools:
            parts.append(json.dumps(tools, ensure_ascii=False))

        per_message_overhead = len(messages) * 4
        return len(enc.encode("\n".join(parts))) + per_message_overhead
    except Exception:
        return 0


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate prompt tokens contributed by one persisted message."""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

    rc = message.get("reasoning_content")
    if isinstance(rc, str) and rc:
        parts.append(rc)

    payload = "\n".join(parts)
    if not payload:
        return 4
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return max(4, len(enc.encode(payload)) + 4)
    except Exception:
        return max(4, len(payload) // 4 + 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """Estimate prompt tokens via provider counter first, then tiktoken fallback."""
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            pass

    estimated = estimate_prompt_tokens(messages, tools)
    if estimated > 0:
        return int(estimated), "tiktoken"
    return 0, "none"


def build_status_content(
    *,
    version: str,
    model: str,
    start_time: float,
    last_usage: dict[str, int],
    context_window_tokens: int,
    session_msg_count: int,
    context_tokens_estimate: int,
    search_usage_text: str | None = None,
    active_task_count: int = 0,
) -> str:
    """Build a human-readable runtime status snapshot.
    
    Args:
        search_usage_text: Optional pre-formatted web search usage string
                           (produced by SearchUsageInfo.format()). When provided
                           it is appended as an extra section.
    """
    uptime_s = int(time.time() - start_time)
    uptime = (
        f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"
        if uptime_s >= 3600
        else f"{uptime_s // 60}m {uptime_s % 60}s"
    )
    last_in = last_usage.get("prompt_tokens", 0)
    last_out = last_usage.get("completion_tokens", 0)
    cached = last_usage.get("cached_tokens", 0)
    ctx_total = max(context_window_tokens, 0)
    ctx_pct = int((context_tokens_estimate / ctx_total) * 100) if ctx_total > 0 else 0
    ctx_used_str = f"{context_tokens_estimate // 1000}k" if context_tokens_estimate >= 1000 else str(context_tokens_estimate)
    ctx_total_str = f"{ctx_total // 1000}k" if ctx_total > 0 else "n/a"
    token_line = f"\U0001f4ca Tokens: {last_in} in / {last_out} out"
    if cached and last_in:
        token_line += f" ({cached * 100 // last_in}% cached)"
    lines = [
        f"\U0001f408 nanobot v{version}",
        f"\U0001f9e0 Model: {model}",
        token_line,
        f"\U0001f4da Context: {ctx_used_str}/{ctx_total_str} ({ctx_pct}%)",
        f"\U0001f4ac Session: {session_msg_count} messages",
        f"\u23f1 Uptime: {uptime}",
        f"\u26a1 Tasks: {active_task_count} active",
    ]
    if search_usage_text:
        lines.append(search_usage_text)
    return "\n".join(lines)    


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Only creates missing files."""
    from importlib.resources import files as pkg_files
    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "history.jsonl")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")

    # Initialize git for memory version control
    try:
        from nanobot.utils.gitstore import GitStore
        gs = GitStore(workspace, tracked_files=[
            "SOUL.md", "USER.md", "memory/MEMORY.md",
        ])
        gs.init()
    except Exception:
        logger.warning("Failed to initialize git store for {}", workspace)

    return added
