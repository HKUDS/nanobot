"""Runtime-specific helper functions and constants."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nanobot.utils.helpers import stringify_text_blocks

_MAX_REPEAT_EXTERNAL_LOOKUPS = 2
_MAX_REPEAT_TOOL_CALLS = 3

EMPTY_FINAL_RESPONSE_MESSAGE = (
    "I completed the tool steps but couldn't produce a final answer. "
    "Please try again or narrow the task."
)

FINALIZATION_RETRY_PROMPT = (
    "Please provide your response to the user based on the conversation above."
)

LENGTH_RECOVERY_PROMPT = (
    "Output limit reached. Continue exactly where you left off "
    "— no recap, no apology. Break remaining work into smaller steps if needed."
)


def empty_tool_result_message(tool_name: str) -> str:
    """Short prompt-safe marker for tools that completed without visible output."""
    return f"({tool_name} completed with no output)"


def ensure_nonempty_tool_result(tool_name: str, content: Any) -> Any:
    """Replace semantically empty tool results with a short marker string."""
    if content is None:
        return empty_tool_result_message(tool_name)
    if isinstance(content, str) and not content.strip():
        return empty_tool_result_message(tool_name)
    if isinstance(content, list):
        if not content:
            return empty_tool_result_message(tool_name)
        text_payload = stringify_text_blocks(content)
        if text_payload is not None and not text_payload.strip():
            return empty_tool_result_message(tool_name)
    return content


def is_blank_text(content: str | None) -> bool:
    """True when *content* is missing or only whitespace."""
    return content is None or not content.strip()


def build_finalization_retry_message() -> dict[str, str]:
    """A short no-tools-allowed prompt for final answer recovery."""
    return {"role": "user", "content": FINALIZATION_RETRY_PROMPT}


def build_length_recovery_message() -> dict[str, str]:
    """Prompt the model to continue after hitting output token limit."""
    return {"role": "user", "content": LENGTH_RECOVERY_PROMPT}


def external_lookup_signature(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Stable signature for repeated external lookups we want to throttle."""
    if tool_name == "web_fetch":
        url = str(arguments.get("url") or "").strip()
        if url:
            return f"web_fetch:{url.lower()}"
    if tool_name == "web_search":
        query = str(arguments.get("query") or arguments.get("search_term") or "").strip()
        if query:
            return f"web_search:{query.lower()}"
    return None


def repeated_external_lookup_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
) -> str | None:
    """Block repeated external lookups after a small retry budget."""
    signature = external_lookup_signature(tool_name, arguments)
    if signature is None:
        return None
    count = seen_counts.get(signature, 0) + 1
    seen_counts[signature] = count
    if count <= _MAX_REPEAT_EXTERNAL_LOOKUPS:
        return None
    logger.warning(
        "Blocking repeated external lookup {} on attempt {}",
        signature[:160],
        count,
    )
    return (
        "Error: repeated external lookup blocked. "
        "Use the results you already have to answer, or try a meaningfully different source."
    )


# ---------------------------------------------------------------------------
# General tool-call stagnation detection
# ---------------------------------------------------------------------------


def tool_call_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    """Stable signature for a tool call (name + sorted arguments).

    Returns a deterministic string key so the runner can detect when the
    model is calling the same tool with the same arguments repeatedly —
    a common symptom of the model getting stuck in a loop.
    """
    try:
        args_key = json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_key = str(arguments)
    return f"{tool_name}:{args_key}"


def repeated_tool_call_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
    *,
    max_repeats: int = _MAX_REPEAT_TOOL_CALLS,
) -> str | None:
    """Return an error string when the same tool+args combination repeats too many times.

    This is a generalised version of :func:`repeated_external_lookup_error`
    that covers **all** tools, not just web searches.  It catches the common
    failure mode where the model enters an infinite loop calling the same
    tool (e.g. ``read_file`` on ``history.jsonl``) without making progress.

    The caller should maintain a ``seen_counts`` dict across the entire
    ``AgentRunner.run()`` invocation and pass it on every tool execution.
    """
    sig = tool_call_signature(tool_name, arguments)
    count = seen_counts.get(sig, 0) + 1
    seen_counts[sig] = count
    if count <= max_repeats:
        return None
    logger.warning(
        "Blocking repeated tool call {} on attempt {} (max {})",
        sig[:200],
        count,
        max_repeats,
    )
    return (
        f"Error: you have already called {tool_name} with identical arguments "
        f"{max_repeats} times. Summarize the information you already have "
        "and provide your response to the user. Do not call this tool again "
        "with the same arguments."
    )
