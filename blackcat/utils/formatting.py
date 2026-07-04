import re
from typing import Any


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append("_")
        result.append(char.lower())
    return "".join(result)

def snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])

def convert_keys(data: Any) -> Any:
    """Convert camelCase keys to snake_case recursively."""
    if isinstance(data, dict):
        return {camel_to_snake(k): convert_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_keys(item) for item in data]
    return data

def convert_to_camel(data: Any) -> Any:
    """Convert snake_case keys to camelCase recursively."""
    if isinstance(data, dict):
        return {snake_to_camel(k): convert_to_camel(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_to_camel(item) for item in data]
    return data


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text with a stable suffix."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"

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

def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a provider-safe assistant message with optional reasoning fields."""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning_content is not None or thinking_blocks:
        msg["reasoning_content"] = reasoning_content if reasoning_content is not None else ""
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg

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


def strip_think(text: str) -> str:
    """Remove thinking blocks, unclosed trailing tags, and tokenizer-level
    template leaks occasionally emitted by some models (notably Gemma 4's
    Ollama renderer).

    Covers:
      1. Well-formed `<think>...</think>` and `<thought>...</thought>` blocks.
      2. Streaming prefixes where the block is never closed.
      3. *Malformed* opening tags missing the `>` — e.g. `<think广场…`. The
         model sometimes emits the tag name directly followed by user-facing
         content with no delimiter; without this step the literal `<think`
         leaks into the rendered message.
      4. Harmony-style channel markers like `<channel|>` / `<|channel|>`
         **at the start of the text** — conservative to avoid eating
         explanatory prose that mentions these tokens.
      5. Orphan closing tags `</think>` / `</thought>` **at the very start
         or end of the text** only, for the same reason.
      6. Trailing partial control tags split across stream chunks, such as
         `<thi`, `<thin`, or `<tho`.

    Since this is also applied before persisting to history (memory.py),
    the edge-only stripping of (4) and (5) is deliberate: stripping those
    tokens mid-text would silently rewrite any message where a user or the
    assistant discusses the tokens themselves.
    """
    # Well-formed blocks first.
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"^\s*<think>[\s\S]*$", "", text)
    text = re.sub(r"<thought>[\s\S]*?</thought>", "", text)
    text = re.sub(r"^\s*<thought>[\s\S]*$", "", text)
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)
    text = re.sub(r"^\s*<thinking>[\s\S]*$", "", text)
    # Self-closing thinking markers
    text = re.sub(r"<thinking\s*/>", "", text)
    # Malformed opening tags: `<think` / `<thought` where the next char is
    # NOT one that could continue a valid tag / identifier name. Explicitly
    # listing ASCII tag-name chars (letters, digits, `_`, `-`, `:`) plus
    # `>` / `/` — we can't use `\w` here because in Python's default
    # Unicode regex mode it matches CJK characters too, which would defeat
    # the primary fix for `<think广场…` leaks.
    text = re.sub(r"<think(?![A-Za-z0-9_\-:>/])", "", text)
    text = re.sub(r"<thinking(?![A-Za-z0-9_\-:>/])", "", text)
    text = re.sub(r"<thought(?![A-Za-z0-9_\-:>/])", "", text)
    # Edge-only orphan closing tags (start or end of text).
    text = re.sub(r"^\s*</think>\s*", "", text)
    text = re.sub(r"\s*</think>\s*$", "", text)
    text = re.sub(r"^\s*</thought>\s*", "", text)
    text = re.sub(r"\s*</thought>\s*$", "", text)
    # Edge-only channel markers (harmony / Gemma 4 variant leaks).
    text = re.sub(r"^\s*<\|?channel\|?>\s*", "", text)
    # Stream chunks may end in the middle of a control tag. Strip only known
    # control-token prefixes at the very end.
    partial_control_tag = (
        r"</?(?:t|th|thi|thin|think|thinking|tho|thou|thoug|though|thought)>?"
        r"|<\|?(?:c|ch|cha|chan|chann|channe|channel)(?:\|?>?)?"
    )
    text = re.sub(rf"(?:{partial_control_tag})$", "", text)
    text = re.sub(r"^\s*<\|?$", "", text)
    return text.strip()


def extract_think(text: str) -> tuple[str | None, str]:
    """Extract thinking content from inline ``<think>`` / ``<thought>`` blocks.

    Returns ``(thinking_text, cleaned_text)``. Only closed blocks are
    extracted; unclosed streaming prefixes are stripped from the cleaned
    text but not surfaced — :func:`strip_think` handles that case.
    """
    parts: list[str] = []
    for m in re.finditer(r"<think>([\s\S]*?)</think>", text):
        parts.append(m.group(1).strip())
    for m in re.finditer(r"<thought>([\s\S]*?)</thought>", text):
        parts.append(m.group(1).strip())
    for m in re.finditer(r"<thinking>([\s\S]*?)</thinking>", text):
        parts.append(m.group(1).strip())
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
        new = thinking[len(self._emitted):].strip()
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
            tb.get("thinking", "")
            for tb in thinking_blocks
            if isinstance(tb, dict) and tb.get("type") == "thinking"
        ]
        joined = "\n\n".join(p for p in parts if p)
        return (joined or None), strip_think(content) if content else content
    if content:
        return extract_think(content)
    return None, content


def strip_reasoning_tags(text: object) -> str:
    """Remove wrapper tags from text that is already known to be reasoning."""
    if not isinstance(text, str):
        return ""
    # Well-formed wrappers
    text = re.sub(r"^\s*<think>\s*", "", text)
    text = re.sub(r"\s*</think>\s*$", "", text)
    text = re.sub(r"^\s*<thinking>\s*", "", text)
    text = re.sub(r"\s*</thinking>\s*$", "", text)
    text = re.sub(r"^\s*<thinking/>\s*", "", text)
    text = re.sub(r"^\s*<thought>\s*", "", text)
    text = re.sub(r"\s*</thought>\s*$", "", text)
    # Partial trailing tags
    partial = r"</?(?:t|th|thi|thin|think|tho|thou|thoug|though|thought|thinking)>?"
    text = re.sub(rf"\s*(?:{partial})$", "", text)
    return text.strip()
