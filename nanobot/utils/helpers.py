"""Utility functions for nanobot."""

import base64
import json
import mimetypes
import os
import re
import shutil
import stat
import time
import uuid
from contextlib import suppress
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import tiktoken
from loguru import logger

_TOOLS_TOKEN_CACHE_MAX_ENTRIES = 64
_TOOLS_TOKEN_CACHE: dict[int, tuple[tuple[int, ...], dict[bool, int]]] = {}


def sanitize_surrogates(text: str) -> str:
    """Reconstruct surrogate pairs and replace unpaired surrogates.

    Lone UTF-16 surrogate code points (``U+D800``..``U+DFFF``) cannot be
    encoded as UTF-8 and cause ``UnicodeEncodeError`` when the message is
    serialized for an HTTP request body. This helper round-trips through
    UTF-16 to reconstruct genuine surrogate pairs (produced e.g. by Windows
    console input for emoji) and substitutes lone surrogates with
    ``U+FFFD``.

    Non-string inputs are returned unchanged so this helper is safe to call
    on arbitrary message payload leaves.
    """
    if not isinstance(text, str):
        return text
    # Fast path: no surrogate code points → return the original object so
    # callers can rely on identity to detect an actual mutation.
    for ch in text:
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF:
            break
    else:
        return text
    return text.encode("utf-16-le", errors="surrogatepass").decode(
        "utf-16-le", errors="replace"
    )


def sanitize_surrogates_deep(value: Any) -> Any:
    """Recursively apply :func:`sanitize_surrogates` to every string leaf.

    Lists and dicts are rebuilt only when a nested string actually changes,
    so the common case (no surrogates present) returns the original object
    without allocations.
    """
    if isinstance(value, str):
        cleaned = sanitize_surrogates(value)
        return cleaned
    if isinstance(value, list):
        result_list: list[Any] = []
        mutated = False
        for item in value:
            new_item = sanitize_surrogates_deep(item)
            if new_item is not item:
                mutated = True
            result_list.append(new_item)
        return result_list if mutated else value
    if isinstance(value, dict):
        result_dict: dict[Any, Any] = {}
        mutated = False
        for key, item in value.items():
            new_item = sanitize_surrogates_deep(item)
            if new_item is not item:
                mutated = True
            result_dict[key] = new_item
        return result_dict if mutated else value
    if isinstance(value, tuple):
        result_tuple = tuple(sanitize_surrogates_deep(item) for item in value)
        return result_tuple if any(a is not b for a, b in zip(result_tuple, value)) else value
    return value


@lru_cache(maxsize=1)
def _get_token_encoding() -> Any:
    return tiktoken.get_encoding("cl100k_base")


def _cache_tools_token_count(
    tools_id: int,
    fingerprint: tuple[int, ...],
    counts: dict[bool, int],
) -> None:
    if (
        tools_id not in _TOOLS_TOKEN_CACHE
        and len(_TOOLS_TOKEN_CACHE) >= _TOOLS_TOKEN_CACHE_MAX_ENTRIES
    ):
        _TOOLS_TOKEN_CACHE.pop(next(iter(_TOOLS_TOKEN_CACHE)))
    _TOOLS_TOKEN_CACHE[tools_id] = (fingerprint, counts)


def _estimate_tools_tokens(
    enc: Any,
    tools: list[dict[str, Any]],
    *,
    leading_separator: bool,
) -> int:
    """Estimate stable tool definition tokens without re-encoding every loop."""
    # ToolRegistry keeps the returned definitions list alive until the registry changes.
    tools_id = id(tools)
    fingerprint = tuple(id(tool) for tool in tools)
    cached = _TOOLS_TOKEN_CACHE.get(tools_id)
    if cached and cached[0] == fingerprint:
        token_count = cached[1].get(leading_separator)
        if token_count is not None:
            return token_count
        counts = cached[1]
    else:
        counts = {}

    rendered = json.dumps(tools, ensure_ascii=False)
    if leading_separator:
        rendered = "\n" + rendered
    token_count = len(enc.encode(rendered))
    counts[leading_separator] = token_count
    _cache_tools_token_count(tools_id, fingerprint, counts)
    return token_count


def _tag_regex(tags: tuple[str, ...]) -> str:
    return rf"(?:{'|'.join(re.escape(tag) for tag in tags)})"


_THINKING_TAGS = ("think", "thinking", "thought")
_THINKING_TAG = _tag_regex(_THINKING_TAGS)
_INLINE_SELF_CLOSING_THINKING_TAG = r"(?:thinking)"
_THINKING_TAG_PREFIX = "|".join(
    sorted(
        {re.escape(tag[:i]) for tag in _THINKING_TAGS for i in range(1, len(tag) + 1)},
        key=len,
        reverse=True,
    )
)
_PARTIAL_THINKING_TAG = rf"</?(?:{_THINKING_TAG_PREFIX})>?"


def strip_think(text: str) -> str:
    """Remove thinking blocks, unclosed trailing tags, and tokenizer-level
    template leaks occasionally emitted by some models (notably Gemma 4's
    Ollama renderer).

    Covers:
      1. Well-formed `<think>...</think>`, `<thinking>...</thinking>`,
         and `<thought>...</thought>` blocks.
      2. Streaming prefixes where the block is never closed.
      3. *Malformed* opening tags missing the `>` — e.g. `<think广场…`. The
         model sometimes emits the tag name directly followed by user-facing
         content with no delimiter; without this step the literal `<think`
         leaks into the rendered message.
      4. Harmony-style channel markers like `<channel|>` / `<|channel|>`
         **at the start of the text** — conservative to avoid eating
         explanatory prose that mentions these tokens.
      5. Orphan closing tags `</think>` / `</thinking>` / `</thought>`
         **at the very start or end of the text** only, for the same reason.
      6. Trailing partial control tags split across stream chunks, such as
         `<thi`, `<thin`, or `<tho`.

    Since this is also applied before persisting to history (memory.py),
    the edge-only stripping of (4) and (5) is deliberate: stripping those
    tokens mid-text would silently rewrite any message where a user or the
    assistant discusses the tokens themselves.
    """
    # Well-formed blocks first.
    text = re.sub(rf"<(?P<tag>{_THINKING_TAG})>[\s\S]*?</(?P=tag)>", "", text)
    text = re.sub(rf"^\s*<{_THINKING_TAG}>[\s\S]*$", "", text)
    # Self-closing `<thinking/>` is an empty marker, not user-visible text.
    text = re.sub(rf"^\s*<{_INLINE_SELF_CLOSING_THINKING_TAG}/>\s*", "", text)
    text = re.sub(rf"\s*<{_INLINE_SELF_CLOSING_THINKING_TAG}/>\s*$", "", text)
    # Malformed opening tags: `<think` / `<thinking` / `<thought` where the next char is
    # NOT one that could continue a valid tag / identifier name. Explicitly
    # listing ASCII tag-name chars (letters, digits, `_`, `-`, `:`) plus
    # `>` / `/` — we can't use `\w` here because in Python's default
    # Unicode regex mode it matches CJK characters too, which would defeat
    # the primary fix for `<think广场…` leaks.
    text = re.sub(rf"<{_THINKING_TAG}(?![A-Za-z0-9_\-:>/])", "", text)
    # Edge-only orphan closing tags (start or end of text).
    text = re.sub(rf"^\s*</{_THINKING_TAG}>\s*", "", text)
    text = re.sub(rf"\s*</{_THINKING_TAG}>\s*$", "", text)
    # Edge-only channel markers (harmony / Gemma 4 variant leaks).
    text = re.sub(r"^\s*<\|?channel\|?>\s*", "", text)
    # Stream chunks may end in the middle of a control tag. Strip only known
    # control-token prefixes at the very end.
    partial_control_tag = (
        rf"{_PARTIAL_THINKING_TAG}|"
        r"<\|?(?:c|ch|cha|chan|chann|channe|channel)(?:\|?>?)?"
    )
    text = re.sub(rf"(?:{partial_control_tag})$", "", text)
    text = re.sub(r"^\s*<\|?$", "", text)
    return text.strip()


def strip_reasoning_tags(text: object) -> str:
    """Remove wrapper tags from text that is already known to be reasoning."""
    if not isinstance(text, str):
        return ""
    text = re.sub(rf"^\s*<{_THINKING_TAG}/>\s*", "", text)
    text = re.sub(rf"\s*<{_THINKING_TAG}/>\s*$", "", text)
    text = re.sub(rf"^\s*<{_THINKING_TAG}>\s*", "", text)
    text = re.sub(rf"\s*</{_THINKING_TAG}>\s*$", "", text)
    text = re.sub(rf"\s*(?:{_PARTIAL_THINKING_TAG})$", "", text)
    return text.strip()


def extract_think(text: str) -> tuple[str | None, str]:
    """Extract thinking content from inline thinking tags.

    Returns ``(thinking_text, cleaned_text)``. Only closed blocks are
    extracted; unclosed streaming prefixes are stripped from the cleaned
    text but not surfaced — :func:`strip_think` handles that case.
    """
    parts: list[str] = []
    for m in re.finditer(rf"<(?P<tag>{_THINKING_TAG})>([\s\S]*?)</(?P=tag)>", text):
        parts.append(m.group(2).strip())
    thinking = "\n\n".join(parts) if parts else None
    return thinking, strip_think(text)


class IncrementalThinkExtractor:
    """Stateful inline ``<think>`` extractor for streaming buffers.

    Streaming providers expose only a single content delta channel. When a
    model embeds reasoning in ``<think>...</think>`` blocks inside that
    channel, callers need to surface the reasoning incrementally as it
    arrives without re-emitting earlier text. This holds the "already
    emitted" cursor so the runner and the loop hook share one shape.
    """

    __slots__ = ("_emitted",)

    def __init__(self) -> None:
        self._emitted = ""

    def reset(self) -> None:
        self._emitted = ""

    async def feed(self, buf: str, emit: Any) -> bool:
        """Emit any new thinking text found in ``buf``.

        Returns True if anything was emitted this call. ``emit`` is an
        async callable taking a single string (typically
        ``hook.emit_reasoning``).
        """
        thinking, _ = extract_think(buf)
        if not thinking or thinking == self._emitted:
            return False
        new = thinking[len(self._emitted) :].strip()
        self._emitted = thinking
        if not new:
            return False
        await emit(new)
        return True


def extract_reasoning(
    reasoning_content: str | None,
    thinking_blocks: list[dict[str, Any]] | None,
    content: str | None,
) -> tuple[str | None, str | None]:
    """Return ``(reasoning_text, cleaned_content)`` from one model response.

    Single source of truth for "what reasoning did this response carry, and
    what answer text remains after we peel it out". Fallback order:

    1. Dedicated ``reasoning_content`` (DeepSeek-R1, Kimi, MiMo, OpenAI
       reasoning models, Bedrock).
    2. Anthropic ``thinking_blocks``.
    3. Inline ``<think>`` / ``<thought>`` blocks in ``content``.

    Only one source contributes per response; lower-priority sources are
    ignored if a higher-priority one is present, but inline ``<think>``
    tags are still stripped from ``content`` so they never leak into the
    final answer.
    """
    if reasoning_content:
        return strip_reasoning_tags(reasoning_content), strip_think(content) if content else content
    if thinking_blocks:
        parts = [
            strip_reasoning_tags(tb.get("thinking", ""))
            for tb in thinking_blocks
            if isinstance(tb, dict) and tb.get("type") == "thinking"
        ]
        joined = "\n\n".join(p for p in parts if p)
        return (joined or None), strip_think(content) if content else content
    if content:
        return extract_think(content)
    return None, content


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


def build_image_content_blocks(
    raw: bytes, mime: str, path: str, label: str
) -> list[dict[str, Any]]:
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


_IMAGE_BREADCRUMB_LINE_RE = re.compile(r"^\[image: ([^\]]+)\]\s*$")


def strip_media_image_breadcrumbs(text: str, media_paths: list[str]) -> str:
    """Remove ``[image: path]`` lines that only echo paths already in ``media``."""
    paths = {p for p in media_paths if isinstance(p, str) and p}
    if not paths or not text:
        return text
    lines = [
        line
        for line in text.splitlines()
        if not (
            (match := _IMAGE_BREADCRUMB_LINE_RE.match(line)) and match.group(1) in paths
        )
    ]
    return "\n".join(lines).strip()


def load_image_url_content_parts(
    media: list[str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load on-disk images into multimodal ``image_url`` parts.

    Returns ``(image_parts, unresolved_paths)``. Unresolved paths are missing
    files or non-image attachments that could not be encoded for vision.
    """
    if not media:
        return [], []

    images: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for path in media:
        if not isinstance(path, str) or not path:
            continue
        p = Path(path)
        if not p.is_file():
            unresolved.append(path)
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            unresolved.append(path)
            continue
        mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
        if not mime or not mime.startswith("image/"):
            unresolved.append(path)
            continue
        b64 = base64.b64encode(raw).decode()
        images.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            }
        )
    return images, unresolved


def build_user_content_with_media(
    text: str, media: list[str] | None
) -> str | list[dict[str, Any]]:
    """Build current-turn user content with optional base64-encoded images."""
    if not media:
        return text
    images, _unresolved = load_image_url_content_parts(media)
    if not images:
        return text
    return images + [{"type": "text", "text": text}]


def rehydrate_history_user_content(
    text: str, media: list[str] | None
) -> str | list[dict[str, Any]]:
    """Rebuild history user content for LLM replay, restoring vision when possible.

    Existing image files become ``image_url`` parts. Missing / non-image paths
    stay as ``[image: path]`` breadcrumbs. Redundant Feishu-style breadcrumb
    lines that only echo ``media`` paths are stripped so multimodal turns are
    not flooded with placeholders.
    """
    if not media:
        return text

    media_paths = [p for p in media if isinstance(p, str) and p]
    if not media_paths:
        return text

    images, unresolved = load_image_url_content_parts(media_paths)
    cleaned = strip_media_image_breadcrumbs(text or "", media_paths)
    if unresolved:
        crumbs = "\n".join(image_placeholder_text(p) for p in unresolved)
        cleaned = f"{cleaned}\n{crumbs}" if cleaned else crumbs

    if not images:
        return cleaned
    return images + [{"type": "text", "text": cleaned or ""}]


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

    tz = ZoneInfo(timezone) if timezone else None
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
_TRUNCATED_SUFFIX = "\n... (truncated)"


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
    return text[:max_chars] + _TRUNCATED_SUFFIX


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to a token budget with a stable suffix.

    Unlike :func:`truncate_text`, this measures actual tokens, so the cap holds
    regardless of language or content (CJK and code cost more tokens per char).
    Falls back to a conservative UTF-8 byte budget if tiktoken is unavailable.
    """
    if max_tokens <= 0:
        return text
    try:
        enc = _get_token_encoding()
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        suffix_tokens = enc.encode(_TRUNCATED_SUFFIX)
        body_budget = max_tokens - len(suffix_tokens)
        if body_budget <= 0:
            return enc.decode(tokens[:max_tokens])
        for candidate_budget in range(body_budget, -1, -1):
            result = enc.decode(tokens[:candidate_budget]) + _TRUNCATED_SUFFIX
            if len(enc.encode(result)) <= max_tokens:
                return result
        return enc.decode(tokens[:max_tokens])
    except Exception:
        if len(text.encode("utf-8")) <= max_tokens:
            return text
        suffix_bytes = len(_TRUNCATED_SUFFIX.encode("utf-8"))
        if max_tokens <= suffix_bytes:
            return _truncate_text_to_utf8_bytes(text, max_tokens)
        body = _truncate_text_to_utf8_bytes(text, max_tokens - suffix_bytes)
        return body + _TRUNCATED_SUFFIX


def _truncate_text_to_utf8_bytes(text: str, max_bytes: int) -> str:
    """Return the longest code-point prefix within a UTF-8 byte budget."""
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def recent_message_start_index(
    messages: list[dict[str, Any]],
    max_messages: int,
    *,
    extend_to_user: bool = False,
) -> int:
    """Return the start index for a recent replay window."""
    if max_messages <= 0:
        return len(messages)
    start_idx = max(0, len(messages) - max_messages)
    if not extend_to_user or len(messages) <= max_messages:
        return start_idx
    if any(messages[i].get("role") == "user" for i in range(start_idx, len(messages))):
        return start_idx

    recovered_user = next(
        (i for i in range(start_idx - 1, -1, -1) if messages[i].get("role") == "user"),
        None,
    )
    if recovered_user is None:
        return start_idx
    if recovered_user > 0 and messages[recovered_user - 1].get("_channel_delivery"):
        return recovered_user - 1
    return recovered_user


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
    existing_mode: int | None = None
    with suppress(OSError):
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            if existing_mode is not None:
                os.chmod(tmp, existing_mode)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        with suppress(OSError, NotImplementedError):
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
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
    except Exception:
        logger.exception("Failed to clean stale tool result buckets in {}", root)
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
    # Non-positive max_len cannot advance the cut pointer; return unsplit.
    if max_len <= 0:
        return [content]
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
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
        msg["reasoning_content"] = (
            strip_reasoning_tags(reasoning_content)
            if reasoning_content is not None
            else ""
        )
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg


def _estimate_prompt_tokens_with_source(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """Estimate prompt tokens and identify the counter used.

    Counts all fields that providers send to the LLM: content, tool_calls,
    reasoning_content, tool_call_id, name, plus per-message framing overhead.
    """
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

    message_payload = "\n".join(parts)
    per_message_overhead = len(messages) * 4
    try:
        enc = _get_token_encoding()
        tool_tokens = (
            _estimate_tools_tokens(enc, tools, leading_separator=bool(parts)) if tools else 0
        )
        message_tokens = len(enc.encode(message_payload)) if message_payload else 0
        return message_tokens + tool_tokens + per_message_overhead, "tiktoken"
    except Exception:
        tool_payload = (
            ("\n" if message_payload else "") + json.dumps(tools, ensure_ascii=False)
            if tools
            else ""
        )
        payload = message_payload + tool_payload
        estimated = len(payload.encode("utf-8"))
        return estimated + per_message_overhead, "heuristic"


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate prompt tokens with tiktoken and a conservative byte fallback."""
    estimated, _ = _estimate_prompt_tokens_with_source(messages, tools)
    return estimated


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate prompt tokens contributed by one persisted message."""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                parts.append(json.dumps(part, ensure_ascii=False))
                continue
            if part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
                continue
            if part.get("type") == "image_url":
                # Count like a path breadcrumb — not raw base64 — so history
                # windowing stays comparable to pre-rehydration behavior.
                meta = part.get("_meta") if isinstance(part.get("_meta"), dict) else {}
                path = meta.get("path") if isinstance(meta, dict) else None
                parts.append(image_placeholder_text(path if isinstance(path, str) else None))
                continue
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
        enc = _get_token_encoding()
        return max(4, len(enc.encode(payload)) + 4)
    except Exception:
        return max(4, len(payload.encode("utf-8")) + 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """Estimate prompt tokens via provider, tiktoken, then a byte heuristic."""
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        with suppress(Exception):
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
    estimated, source = _estimate_prompt_tokens_with_source(messages, tools)
    if estimated > 0:
        return int(estimated), source
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
    max_completion_tokens: int = 8192,
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
    # Budget mirrors Consolidator formula: ctx_window - max_completion - _SAFETY_BUFFER
    ctx_budget = max(ctx_total - int(max_completion_tokens) - 1024, 1)
    ctx_pct = min(int((context_tokens_estimate / ctx_budget) * 100), 999) if ctx_budget > 0 else 0
    ctx_used_str = (
        f"{context_tokens_estimate // 1000}k"
        if context_tokens_estimate >= 1000
        else str(context_tokens_estimate)
    )
    ctx_total_str = f"{ctx_total // 1000}k" if ctx_total > 0 else "n/a"
    token_line = f"\U0001f4ca Tokens: {last_in} in / {last_out} out"
    if cached and last_in:
        token_line += f" ({cached * 100 // last_in}% cached)"
    lines = [
        f"\U0001f408 nanobot v{version}",
        f"\U0001f9e0 Model: {model}",
        token_line,
        f"\U0001f4da Context: {ctx_used_str}/{ctx_total_str} ({ctx_pct}% of input budget)",
        f"\U0001f4ac Session: {session_msg_count} messages",
        f"\u23f1 Uptime: {uptime}",
        f"\u26a1 Tasks: {active_task_count} active",
    ]
    if search_usage_text:
        lines.append(search_usage_text)
    return "\n".join(lines)


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Creates missing files without overwriting user files."""
    from importlib.resources import files as pkg_files

    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        content = src.read_text(encoding="utf-8") if src else ""
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(tpl / "prompts" / "README.md", workspace / "prompts" / "README.md")
    _write(None, workspace / "memory" / "history.jsonl")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console

        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")

    # Initialize git for memory version control
    try:
        from nanobot.utils.gitstore import GitStore

        gs = GitStore(
            workspace,
            tracked_files=[
                "SOUL.md",
                "USER.md",
                "memory/MEMORY.md",
            ],
        )
        gs.init()
    except Exception:
        logger.exception("Failed to initialize git store for {}", workspace)

    return added


def load_bundled_template(template_name: str) -> str | None:
    """Read a bundled template file from the nanobot package."""
    from importlib.resources import files as pkg_files

    with suppress(Exception):
        tpl = pkg_files("nanobot") / "templates" / template_name
        if tpl.is_file():
            return tpl.read_text(encoding="utf-8")
    return None
