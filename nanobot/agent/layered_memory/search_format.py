"""Stable text formatting for memory search tools and recall guides."""

from __future__ import annotations

from nanobot.agent.layered_memory.l0_store import L0MessageRecord
from nanobot.agent.layered_memory.l1_store import L1Memory

_SNIPPET_MAX_CHARS = 400


def format_memory_tools_guide(*, max_calls: int) -> list[str]:
    return [
        "[Memory tools]",
        "- memory_search: distilled long-term facts/preferences (L1 atoms)",
        "- conversation_search: raw past dialogue snippets (L0)",
        f"- Combined limit: {max_calls} searches per turn",
    ]


def format_memory_search_results(query: str, memories: list[L1Memory]) -> str:
    if not memories:
        return f'No memory atoms found for query "{query}".'
    lines = [f'Found {len(memories)} memory atom(s) for query "{query}":', ""]
    for index, mem in enumerate(memories, start=1):
        turns = ", ".join(mem.source_turn_ids) if mem.source_turn_ids else "-"
        lines.append(f"{index}. [{mem.memory_type}] {mem.atom_id}")
        lines.append(f"   {mem.content}")
        lines.append(f"   (session: {mem.session_key}, turns: {turns})")
        if index < len(memories):
            lines.append("")
    return "\n".join(lines)


def format_conversation_search_results(
    query: str,
    messages: list[L0MessageRecord],
) -> str:
    if not messages:
        return f'No conversation messages found for query "{query}".'
    lines = [f'Found {len(messages)} message(s) for query "{query}":', ""]
    for index, row in enumerate(messages, start=1):
        snippet = _snippet(row.content)
        lines.append(
            f"{index}. [{row.role}] turn={row.turn_id or '-'} "
            f"l0_id={row.id} ts={row.timestamp_ms}"
        )
        lines.append(f"   {snippet}")
        if index < len(messages):
            lines.append("")
    return "\n".join(lines)


def _snippet(text: str, *, max_chars: int = _SNIPPET_MAX_CHARS) -> str:
    cleaned = text.replace("\n", " ").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3] + "..."
