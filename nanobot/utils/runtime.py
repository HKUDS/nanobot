"""Runtime-specific helper functions and constants."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import stringify_text_blocks

_MAX_REPEAT_EXTERNAL_LOOKUPS = 2

# Third same-target workspace violation in a turn escalates to "stop retrying".
_MAX_REPEAT_WORKSPACE_VIOLATIONS = 2

# ---- Loop detection ---------------------------------------------------------

# Max consecutive same (tool, args) before escalation (defaults).
_MAX_REPEATED_LOOPS = 3

# Max tool calls per time window before rate-limit warning (defaults).
# (count, seconds) -- e.g. 5 calls in 3 seconds.
RATE_LIMIT_WINDOW: tuple[int, float] = (5, 3.0)

EMPTY_FINAL_RESPONSE_MESSAGE = (
    "I completed the tool steps but couldn't produce a final answer. "
    "Please try again or narrow the task."
)

FINALIZATION_RETRY_PROMPT = (
    "Please provide your response to the user based on the conversation above."
)

LENGTH_RECOVERY_PROMPT = (
    "Output limit reached. Continue exactly where you left off "
    "-- no recap, no apology. Break remaining work into smaller steps if needed."
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


def loop_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    """Stable signature: 'tool_name:<sorted key=val pairs>'.

    Different from external_lookup_signature -- this is a **universal**
    per-tool+params key, not limited to web tools.  Stable across
    a single turn; does NOT cross turns.

    Strings are normalised (stripped + lowered) to avoid case/whitespace
    false negatives.  Complex values use a truncated ``repr`` as a
    discriminative collision key.

    Limitations:
    - ``list``/``dict`` element order matters: ``[\"a\", \"b\"]`` and
      ``[\"b\", \"a\"]`` produce different signatures even if semantically
      equivalent for some tools.
    - ``repr`` output may include memory addresses for unhashable or custom
      objects, making signatures unstable across runs.
    """
    parts = [tool_name]
    for k in sorted(arguments):
        v = arguments[k]
        if isinstance(v, (str, int, float, bool, type(None))):
            # Normalise strings to avoid case/whitespace false negatives
            sv = v.strip().lower() if isinstance(v, str) else v
            parts.append(f"{k}={sv}")
        else:
            # For complex values (dict, list), use truncated repr as a
            # reasonable collision key -- much more discriminative than
            # repr length alone.
            rv = repr(v)
            parts.append(f"{k}=<{type(v).__name__}:{rv[:64]}>")
    return ":".join(parts)


def repeated_loop_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
    *,
    max_loops: int | None = None,
) -> str | None:
    """Return a hard-block error when the same (tool, args) repeats too many times.

    Follows the same contract as :func:`repeated_external_lookup_error`:
    - Increments the counter internally.
    - Returns ``None`` while within budget.
    - Returns an ``"Error: …"`` string once the threshold is exceeded, and
      **for every subsequent call** thereafter (continuous hard block, not
      a periodic soft hint).

    The caller (``_run_tool``) should skip tool execution and return the
    error as the tool result when a non-None value is returned.

    Parameters
    ----------
    max_loops:
        Override the default threshold (``_MAX_REPEATED_LOOPS``).
        When ``None`` the module default is used.
    """
    threshold = max_loops if max_loops is not None else _MAX_REPEATED_LOOPS
    if threshold <= 0:
        return None  # disabled
    sig = loop_signature(tool_name, arguments)
    count = seen_counts.get(sig, 0) + 1
    seen_counts[sig] = count
    if count < threshold:
        return None
    # Once threshold is breached, return the error every time -- continuous
    # hard block.  The LLM cannot retry the same (tool, args) until it
    # changes strategy.
    logger.warning(
        "Loop blocked: {} called {} times (sig: {})",
        tool_name, count, sig[:120],
    )
    return (
        f"Error: loop guard blocked `{tool_name}`. You called it "
        f"with the same arguments {count} times. "
        "The tool was NOT executed.\n\n"
        "You appear to be stuck in a loop. The same approach has been "
        "tried repeatedly without producing useful new information.\n\n"
        "STOP trying variations. Instead:\n"
        "1. **Tell the user** what you have found so far\n"
        "2. **Ask the user** what they want you to do next\n"
        "3. Only use a different tool or arguments if you have genuinely "
        "new information to act on — do NOT guess at new parameters"
    )


def rate_limit_error(
    tool_name: str,
    timestamps: list[float],
    *,
    rate_window: tuple[int, float] | None = None,
) -> str | None:
    """Return a hard-block error when tool calls are too frequent.

    *timestamps* is a per-tool list of ``time.monotonic()`` values.
    The caller (``_run_tool``) appends before calling.

    Once the rate window is exceeded, the error is returned for **every
    subsequent call** (continuous hard block), not just at multiples of
    the threshold.

    Parameters
    ----------
    rate_window:
        Override the default ``(count, seconds)`` window.  When ``None``
        the module default ``RATE_LIMIT_WINDOW`` is used.
    """
    threshold_count, threshold_seconds = (
        rate_window if rate_window is not None else RATE_LIMIT_WINDOW
    )
    if len(timestamps) < threshold_count:
        return None
    recent = timestamps[-threshold_count:]
    if recent[-1] - recent[0] > threshold_seconds:
        return None
    # Once the rate window is breached, block every subsequent call
    # until the LLM slows down.
    return (
        f"Error: rate limit exceeded. {threshold_count} calls to "
        f"`{tool_name}` in {recent[-1] - recent[0]:.1f}s. "
        "The tool was NOT executed.\n\n"
        "You are calling tools too fast without processing results. "
        "STOP. Read the previous results carefully. "
        "If nothing useful was found, tell the user what you've learned "
        "and ask for guidance."
    )


# Workspace-boundary violations are soft errors, with per-target throttling.

_OUTSIDE_PATH_PATTERN = re.compile(r"(?:^|[\s|>'\"])((?:/[^\s\"'>;|<]+)|(?:~[^\s\"'>;|<]+))")


def workspace_violation_signature(
    tool_name: str,
    arguments: dict[str, Any],
) -> str | None:
    """Return a stable cross-tool signature for the outside-workspace target."""
    for key in ("path", "file_path", "target", "source", "destination"):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return _normalize_violation_target(val.strip())

    if tool_name in {"exec", "shell"}:
        cmd = str(arguments.get("command") or "").strip()
        if cmd:
            match = _OUTSIDE_PATH_PATTERN.search(cmd)
            if match:
                return _normalize_violation_target(match.group(1))
        cwd = str(arguments.get("working_dir") or "").strip()
        if cwd:
            return _normalize_violation_target(cwd)

    return None


def _normalize_violation_target(raw: str) -> str:
    """Normalize *raw* path so that equivalent spellings collide on the same key."""
    try:
        normalized = Path(raw).expanduser().resolve().as_posix()
    except Exception:
        normalized = raw.replace("\\", "/")
    return f"violation:{normalized}".lower()


def repeated_workspace_violation_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
) -> str | None:
    """Return an escalated error after repeated bypass attempts."""
    signature = workspace_violation_signature(tool_name, arguments)
    if signature is None:
        return None
    count = seen_counts.get(signature, 0) + 1
    seen_counts[signature] = count
    if count <= _MAX_REPEAT_WORKSPACE_VIOLATIONS:
        return None
    logger.warning(
        "Escalating repeated workspace bypass attempt {} (attempt {})",
        signature[:160],
        count,
    )
    target = signature.split("violation:", 1)[1] if "violation:" in signature else signature
    return (
        "Error: refusing repeated workspace-bypass attempts.\n"
        f"You have tried to access '{target}' (or an equivalent path) "
        f"{count} times in this turn. This is a hard policy boundary -- "
        "switching tools, shell tricks, working_dir overrides, symlinks, "
        "or base64 piping will NOT change the answer. Stop retrying. "
        "If the user genuinely needs this resource, tell them you cannot "
        "access it and ask how they want to proceed (e.g. copy the file "
        "into the workspace, or disable restrict_to_workspace for this run)."
    )
