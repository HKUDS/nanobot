"""Runtime-specific helper functions and constants."""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.utils.helpers import stringify_text_blocks

_MAX_REPEAT_EXTERNAL_LOOKUPS = 2
_MAX_REPEAT_SAME_DOMAIN = 10

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


def external_lookup_domain(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Extract domain from web_fetch URLs for same-domain repeat detection."""
    if tool_name == "web_fetch":
        url = str(arguments.get("url") or "").strip()
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.lower()
                if domain and domain not in ("localhost", "127.0.0.1"):
                    return f"domain:{domain}"
            except Exception:
                pass
    return None


def repeated_external_lookup_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
) -> str | None:
    """Block repeated external lookups after a small retry budget."""
    # Check exact URL/query match first
    signature = external_lookup_signature(tool_name, arguments)
    if signature is not None:
        count = seen_counts.get(signature, 0) + 1
        seen_counts[signature] = count
        if count <= _MAX_REPEAT_EXTERNAL_LOOKUPS:
            pass  # continue to domain check below
        else:
            logger.warning(
                "Blocking repeated external lookup {} on attempt {}",
                signature[:160],
                count,
            )
            return (
                "Error: repeated external lookup blocked. "
                "Use the results you already have to answer, or try a meaningfully different source."
            )

    # Check same-domain repeats (catches different URLs from same site)
    domain_sig = external_lookup_domain(tool_name, arguments)
    if domain_sig is not None:
        domain_count = seen_counts.get(domain_sig, 0) + 1
        seen_counts[domain_sig] = domain_count
        if domain_count > _MAX_REPEAT_SAME_DOMAIN:
            logger.warning(
                "Blocking repeated domain lookup {} on attempt {}",
                domain_sig[:80],
                domain_count,
            )
            return (
                "Error: you have already fetched from this domain multiple times. "
                "Use the results you already have to answer, or try a different source."
            )
    return None
