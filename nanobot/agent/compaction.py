"""Context compaction - summarize old messages to fit context window."""

import asyncio
from typing import Any

from loguru import logger


# Token estimation constants
CHARS_PER_TOKEN = 4  # Rough estimate
DEFAULT_CONTEXT_TOKENS = 128000  # Default context window
BASE_CHUNK_RATIO = 0.4
MIN_CHUNK_RATIO = 0.15
SAFETY_MARGIN = 1.2  # 20% buffer for estimation inaccuracy


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens in a single message."""
    content = message.get("content", "")
    if isinstance(content, list):
        # Handle multi-part content (images, etc.)
        total = 0
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += 85  # Base tokens for image reference
            elif isinstance(part, str):
                total += estimate_tokens(part)
        return total
    return estimate_tokens(str(content))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across all messages."""
    return sum(estimate_message_tokens(msg) for msg in messages)


def split_messages_by_token_share(
    messages: list[dict[str, Any]],
    parts: int = 2,
) -> list[list[dict[str, Any]]]:
    """
    Split messages into roughly equal token-sized chunks.
    
    Args:
        messages: List of messages to split.
        parts: Number of parts to split into.
    
    Returns:
        List of message chunks.
    """
    if not messages or parts <= 1:
        return [messages] if messages else []
    
    total_tokens = estimate_messages_tokens(messages)
    target_tokens = total_tokens / parts
    
    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = []
    current_tokens = 0
    
    for msg in messages:
        msg_tokens = estimate_message_tokens(msg)
        
        if current_tokens + msg_tokens > target_tokens and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = 0
        
        current_chunk.append(msg)
        current_tokens += msg_tokens
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Convert messages to plain text for summarization."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        
        if isinstance(content, list):
            # Extract text from multi-part content
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)
        
        parts.append(f"[{role}]: {content}")
    
    return "\n\n".join(parts)


async def summarize_messages(
    messages: list[dict[str, Any]],
    provider: Any,
    model: str | None = None,
) -> str:
    """
    Summarize a list of messages using the LLM.
    
    Args:
        messages: Messages to summarize.
        provider: LLM provider instance.
        model: Optional model override.
    
    Returns:
        Summary text.
    """
    if not messages:
        return "No prior history."
    
    text = messages_to_text(messages)
    
    summary_prompt = [
        {
            "role": "system",
            "content": (
                "You are a summarization assistant. Create a concise summary of the "
                "conversation below. Preserve:\n"
                "- Key decisions made\n"
                "- Important facts and context\n"
                "- Open questions or TODOs\n"
                "- Any constraints or preferences mentioned\n\n"
                "Be concise but complete. Output only the summary, no preamble."
            ),
        },
        {
            "role": "user",
            "content": f"Summarize this conversation:\n\n{text}",
        },
    ]
    
    try:
        response = await provider.chat(
            messages=summary_prompt,
            model=model,
            max_tokens=2048,
            temperature=0.3,
        )
        return response.content or "Summary unavailable."
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return f"[Summary failed: {e}]"


async def summarize_in_stages(
    messages: list[dict[str, Any]],
    provider: Any,
    model: str | None = None,
    parts: int = 2,
) -> str:
    """
    Summarize messages in stages for very long conversations.
    
    Splits into chunks, summarizes each, then merges summaries.
    
    Args:
        messages: Messages to summarize.
        provider: LLM provider instance.
        model: Optional model override.
        parts: Number of chunks to split into.
    
    Returns:
        Final merged summary.
    """
    chunks = split_messages_by_token_share(messages, parts)
    
    if len(chunks) <= 1:
        return await summarize_messages(messages, provider, model)
    
    # Summarize each chunk
    summaries = []
    for i, chunk in enumerate(chunks):
        logger.debug(f"Summarizing chunk {i+1}/{len(chunks)}")
        summary = await summarize_messages(chunk, provider, model)
        summaries.append(f"[Part {i+1}]: {summary}")
    
    # Merge summaries
    merge_prompt = [
        {
            "role": "system",
            "content": (
                "Merge these partial summaries into a single cohesive summary. "
                "Preserve decisions, TODOs, open questions, and any constraints."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(summaries),
        },
    ]
    
    try:
        response = await provider.chat(
            messages=merge_prompt,
            model=model,
            max_tokens=2048,
            temperature=0.3,
        )
        return response.content or "\n\n".join(summaries)
    except Exception as e:
        logger.error(f"Summary merge failed: {e}")
        return "\n\n".join(summaries)


def prune_history_for_context(
    messages: list[dict[str, Any]],
    max_context_tokens: int = DEFAULT_CONTEXT_TOKENS,
    max_history_share: float = 0.5,
    parts: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """
    Prune message history to fit within context budget.
    
    Args:
        messages: All messages.
        max_context_tokens: Maximum context window tokens.
        max_history_share: Max fraction of context for history (0.5 = 50%).
        parts: Number of chunks for splitting.
    
    Returns:
        Tuple of (kept_messages, dropped_messages, dropped_tokens).
    """
    budget_tokens = int(max_context_tokens * max_history_share)
    kept_messages = messages.copy()
    dropped_messages: list[dict[str, Any]] = []
    dropped_tokens = 0
    
    while kept_messages and estimate_messages_tokens(kept_messages) > budget_tokens:
        chunks = split_messages_by_token_share(kept_messages, parts)
        
        if len(chunks) <= 1:
            break
        
        # Drop the oldest chunk
        dropped = chunks[0]
        dropped_messages.extend(dropped)
        dropped_tokens += estimate_messages_tokens(dropped)
        kept_messages = [msg for chunk in chunks[1:] for msg in chunk]
    
    return kept_messages, dropped_messages, dropped_tokens


async def compact_context(
    messages: list[dict[str, Any]],
    provider: Any,
    max_context_tokens: int = DEFAULT_CONTEXT_TOKENS,
    max_history_share: float = 0.5,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Compact conversation context by summarizing old messages.
    
    Args:
        messages: All conversation messages.
        provider: LLM provider for summarization.
        max_context_tokens: Maximum context window tokens.
        max_history_share: Max fraction of context for history.
        model: Optional model override for summarization.
    
    Returns:
        Tuple of (new_messages, summary_of_dropped).
        The summary should be prepended to system prompt.
    """
    current_tokens = estimate_messages_tokens(messages)
    budget_tokens = int(max_context_tokens * max_history_share)
    
    if current_tokens <= budget_tokens:
        # No compaction needed
        return messages, None
    
    logger.info(
        f"Compacting context: {current_tokens} tokens -> {budget_tokens} budget"
    )
    
    # Prune and get dropped messages
    kept, dropped, dropped_tokens = prune_history_for_context(
        messages, max_context_tokens, max_history_share
    )
    
    if not dropped:
        return messages, None
    
    # Summarize dropped messages
    summary = await summarize_in_stages(dropped, provider, model)
    
    kept_tokens = estimate_messages_tokens(kept)
    logger.info(
        f"Compacted: dropped {len(dropped)} msgs ({dropped_tokens} tokens), "
        f"kept {len(kept)} msgs ({kept_tokens} tokens)"
    )
    
    return kept, summary


class ContextCompactor:
    """
    Manages context compaction for a conversation.
    
    Tracks summaries and handles incremental compaction.
    """
    
    def __init__(
        self,
        provider: Any,
        max_context_tokens: int = DEFAULT_CONTEXT_TOKENS,
        max_history_share: float = 0.5,
        model: str | None = None,
    ):
        self.provider = provider
        self.max_context_tokens = max_context_tokens
        self.max_history_share = max_history_share
        self.model = model
        self.accumulated_summary: str | None = None
    
    async def maybe_compact(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Compact messages if needed, updating accumulated summary.
        
        Args:
            messages: Current conversation messages.
        
        Returns:
            Potentially compacted message list.
        """
        kept, new_summary = await compact_context(
            messages,
            self.provider,
            self.max_context_tokens,
            self.max_history_share,
            self.model,
        )
        
        if new_summary:
            if self.accumulated_summary:
                # Merge with existing summary
                self.accumulated_summary = (
                    f"{self.accumulated_summary}\n\n"
                    f"[More recent context]: {new_summary}"
                )
            else:
                self.accumulated_summary = new_summary
        
        return kept
    
    async def compact(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Force context compaction regardless of current size.
        
        Args:
            messages: Current conversation messages.
        
        Returns:
            Compacted message list.
        """
        if not messages:
            return messages
        
        # Force compaction by summarizing messages
        logger.info(f"Force compacting {len(messages)} messages")
        
        # Summarize all messages
        summary = await summarize_in_stages(messages, self.provider, self.model)
        
        if summary:
            if self.accumulated_summary:
                self.accumulated_summary = (
                    f"{self.accumulated_summary}\n\n"
                    f"[More recent context]: {summary}"
                )
            else:
                self.accumulated_summary = summary
        
        # Return empty list - the summary is in accumulated_summary
        # which should be added to system prompt
        return []
    
    def get_summary_prompt(self) -> str | None:
        """Get the accumulated summary to include in system prompt."""
        if not self.accumulated_summary:
            return None
        return (
            f"\n\n## Prior Conversation Summary\n\n"
            f"The following summarizes earlier parts of this conversation:\n\n"
            f"{self.accumulated_summary}"
        )
    
    def clear(self) -> None:
        """Clear accumulated summary."""
        self.accumulated_summary = None
