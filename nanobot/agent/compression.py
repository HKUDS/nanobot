"""Context compression utilities.

Provides token-budget-aware compression for LLM conversation contexts:

- **Token estimation** — fast heuristic (~4 chars/token) for budget decisions.
- **Synchronous compression** — truncate and drop old tool results.
- **Async summarisation** — LLM-based summarisation of older conversation
  segments when truncation alone is insufficient.

The ``_ChatProvider`` protocol avoids circular imports with the providers
package while allowing the summarisation phase to call the LLM.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any, Protocol

from loguru import logger

from nanobot.agent.prompt_loader import prompts
from nanobot.observability.langfuse import span as langfuse_span
from nanobot.observability.tracing import bind_trace

# ---------------------------------------------------------------------------
# Async provider protocol (avoids circular import with providers module)
# ---------------------------------------------------------------------------


class _ChatProvider(Protocol):
    """Minimal interface used by summarize_and_compress."""

    async def chat(
        self, *, messages: list[dict], tools: Any, model: str, temperature: float, max_tokens: int
    ) -> Any:
        """Send a chat completion request."""  # Protocol stub — no implementation needed


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Fast heuristic token count (~4 chars per token for English).

    Accurate enough for budget decisions without pulling in tiktoken.
    """
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across a message list."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
        # Count tool call arguments
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("arguments", ""))
            total += estimate_tokens(fn.get("name", ""))
    return total


def _collect_tail_tool_call_ids(tail: list[dict[str, Any]]) -> set[str]:
    """Return tool_call_ids referenced in *tail* messages (both assistant calls and tool results)."""
    ids: set[str] = set()
    for m in tail:
        # tool results reference a tool_call_id
        if m.get("role") == "tool" and m.get("tool_call_id"):
            ids.add(m["tool_call_id"])
        # assistant messages may have tool_calls whose results are in the tail
        for tc in m.get("tool_calls", []):
            tc_id = tc.get("id") or ""
            if tc_id:
                ids.add(tc_id)
    return ids


def _paired_drop_tools(
    middle: list[dict[str, Any]],
    tail: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop tool results from *middle* while preserving claim-evidence coherence.

    - Tool results whose ``tool_call_id`` is referenced by an assistant message
      in the *tail* are kept (the claim is visible, so the evidence must stay).
    - When a tool result is dropped, the corresponding assistant tool_call in
      *middle* is annotated with ``[result omitted]`` so the LLM knows evidence
      was compressed, not that it never existed.
    """
    tail_ids = _collect_tail_tool_call_ids(tail)

    # Identify which tool_call_ids from middle tool results we're dropping
    kept_ids: set[str] = set()
    dropped_ids: set[str] = set()
    result: list[dict[str, Any]] = []

    for m in middle:
        if m.get("role") == "tool":
            tc_id = m.get("tool_call_id", "")
            if tc_id in tail_ids:
                # The assistant call referencing this result is in the tail — keep it
                kept_ids.add(tc_id)
                result.append(m)
            else:
                dropped_ids.add(tc_id)
                # Drop the tool result (don't append)
        else:
            result.append(m)

    # Annotate assistant tool_calls in middle whose results were dropped
    if dropped_ids:
        for i, m in enumerate(result):
            if m.get("role") != "assistant" or not m.get("tool_calls"):
                continue
            calls = m["tool_calls"]
            needs_patch = any((tc.get("id") or "") in dropped_ids for tc in calls)
            if needs_patch:
                patched_calls = []
                for tc in calls:
                    tc_id = tc.get("id") or ""
                    if tc_id in dropped_ids:
                        # Mark that the result was omitted
                        patched = {**tc}
                        fn = {**patched.get("function", {})}
                        fn["_result_omitted"] = True
                        patched["function"] = fn
                        patched_calls.append(patched)
                    else:
                        patched_calls.append(tc)
                result[i] = {**m, "tool_calls": patched_calls}

    return result


def compress_context(
    messages: list[dict[str, Any]],
    max_tokens: int,
    *,
    preserve_recent: int = 6,
    tool_token_threshold: int = 200,
) -> list[dict[str, Any]]:
    """Drop or truncate old tool results to fit within *max_tokens*.

    Strategy (in order):
    1. Keep system message and the most recent *preserve_recent* messages intact.
    2. For older tool-result messages, truncate large outputs to a summary line.
    3. If still over budget, drop oldest tool-result messages entirely.

    Returns a new list (does not mutate the input).
    """
    if not messages:
        return messages

    current = estimate_messages_tokens(messages)
    if current <= max_tokens:
        return messages

    # Separate: system (index 0), middle, tail
    system = messages[:1]
    tail_start = max(1, len(messages) - preserve_recent)
    middle = list(messages[1:tail_start])
    tail = messages[tail_start:]

    # Phase 1: truncate large tool results in middle
    truncation_note = (
        "(output truncated to save context – use cache_get_slice "
        "with the cache key to retrieve full data)"
    )
    for i, m in enumerate(middle):
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and estimate_tokens(content) > 200:
                middle[i] = {**m, "content": content[:200] + f"\n{truncation_note}"}

    trial = system + middle + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 2: drop tool results from middle, preserving claim-evidence coherence
    middle = _paired_drop_tools(middle, tail)

    trial = system + middle + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 3: drop all middle messages (extreme case)
    logger.warning("Context compression dropped all middle messages to fit budget")
    bind_trace().debug(
        "compress_context phase=3_drop_all original_tokens={} final_messages={}",
        current,
        len(system + tail),
    )
    return system + tail


# ---------------------------------------------------------------------------
# Summarisation-based compression (async, uses LLM)
# ---------------------------------------------------------------------------

# In-process cache: hash of serialised middle → summary text.
# Capped at _SUMMARY_CACHE_MAX entries (LRU eviction via OrderedDict) to prevent
# unbounded growth over long-running processes (~1.6 MB per 1,000 sessions).
_SUMMARY_CACHE_MAX: int = 256
_summary_cache: OrderedDict[str, str] = OrderedDict()


def _hash_messages(msgs: list[dict[str, Any]]) -> str:
    """Fast content-based hash for caching summaries."""
    raw = json.dumps(msgs, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def summarize_and_compress(
    messages: list[dict[str, Any]],
    max_tokens: int,
    provider: "_ChatProvider",
    model: str,
    *,
    preserve_recent: int = 6,
    summary_max_tokens: int = 400,
    tool_token_threshold: int = 200,
) -> list[dict[str, Any]]:
    """Like :func:`compress_context` but uses an LLM call for Phase 3.

    When truncation alone isn't enough, the middle messages are summarised
    by the *provider* into a ``[Compressed Summary]`` system message, keeping
    key facts in the context window.

    Falls back to the synchronous drop-all behaviour if the LLM call fails.
    """
    if not messages:
        return messages

    current = estimate_messages_tokens(messages)
    if current <= max_tokens:
        return messages

    # Separate: system (index 0), middle, tail
    system = messages[:1]
    tail_start = max(1, len(messages) - preserve_recent)
    middle = list(messages[1:tail_start])
    tail = messages[tail_start:]

    # Phase 1: truncate large tool results in middle
    truncation_note = (
        "(output truncated to save context – use cache_get_slice "
        "with the cache key to retrieve full data)"
    )
    for i, m in enumerate(middle):
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and estimate_tokens(content) > tool_token_threshold:
                middle[i] = {
                    **m,
                    "content": content[:tool_token_threshold] + f"\n{truncation_note}",
                }

    trial = system + middle + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 2: drop tool results from middle, preserving claim-evidence coherence
    middle_no_tools = _paired_drop_tools(middle, tail)

    trial = system + middle_no_tools + tail
    if estimate_messages_tokens(trial) <= max_tokens:
        return trial

    # Phase 3 (enhanced): summarise middle messages via LLM
    if not middle:
        logger.warning("Context compression dropped all middle messages to fit budget")
        return system + tail

    cache_key = _hash_messages(middle)
    summary_text = _summary_cache.get(cache_key)

    if summary_text is None:
        # Build a digest of the middle messages for the summariser
        digest_parts: list[str] = []
        for m in middle:
            role = m.get("role", "?")
            content = m.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            # Include tool call names if present
            tc_names = [tc.get("function", {}).get("name", "") for tc in m.get("tool_calls", [])]
            line = f"[{role}] {content[:600]}"
            if tc_names:
                line += f" (calls: {', '.join(tc_names)})"
            digest_parts.append(line)

        digest = "\n".join(digest_parts)

        try:
            async with langfuse_span(
                name="compress",
                metadata={"middle_msgs": str(len(middle)), "model": model},
            ):
                resp = await provider.chat(
                    messages=[
                        {"role": "system", "content": prompts.get("compress")},
                        {"role": "user", "content": digest},
                    ],
                    tools=None,
                    model=model,
                    temperature=0.0,
                    max_tokens=summary_max_tokens,
                )
            summary_text = (resp.content or "").strip()
            if summary_text:
                _summary_cache[cache_key] = summary_text
                if len(_summary_cache) > _SUMMARY_CACHE_MAX:
                    _summary_cache.popitem(last=False)  # evict oldest entry
                bind_trace().debug(
                    "summarize_and_compress phase=3_llm middle_msgs={} summary_tokens={}",
                    len(middle),
                    estimate_tokens(summary_text),
                )
                logger.debug(
                    "Summarised {} middle messages into {} tokens",
                    len(middle),
                    estimate_tokens(summary_text),
                )
        except (RuntimeError, TimeoutError):
            logger.warning("LLM summarisation failed; falling back to drop-all")
            summary_text = None

    if summary_text:
        summary_msg: dict[str, Any] = {
            "role": "system",
            "content": (
                "[Compressed Summary — earlier conversation was elided to save context]\n\n"
                + summary_text
            ),
        }
        trial = system + [summary_msg] + tail
        if estimate_messages_tokens(trial) <= max_tokens:
            return trial

    # Absolute fallback: drop everything
    logger.warning("Context compression dropped all middle messages to fit budget")
    return system + tail
