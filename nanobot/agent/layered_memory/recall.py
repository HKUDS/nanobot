"""Turn-before recall: L1 FTS (+ optional USER.md profile note)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from nanobot.agent.layered_memory.l1_store import L1Memory, L1Store
from nanobot.agent.layered_memory.search_format import format_memory_tools_guide
from nanobot.agent.layered_memory.search_l1 import search_l1_memories
from nanobot.config.schema import LayeredMemoryRecallConfig

_USER_PROFILE_MAX_CHARS = 400


@dataclass(frozen=True)
class RecallResult:
    """Carrier for pre-turn memory injection into runtime lines."""

    prepend_lines: list[str] = field(default_factory=list)
    append_system: str | None = None


def perform_recall(
    *,
    workspace: Path,
    config: LayeredMemoryRecallConfig,
    query: str,
    session_key: str,
    l1_store: L1Store | None = None,
    include_tools_guide: bool = False,
) -> RecallResult:
    """Synchronous recall body (run via ``asyncio.to_thread`` from facade)."""
    store = l1_store or L1Store(workspace)
    memories = search_l1_memories(
        store,
        query.strip(),
        session_key,
        limit=config.top_k,
        strategy=config.strategy,
    )
    user_note = _read_user_profile_note(workspace)
    prepend = format_recall_prepend_lines(
        memories,
        user_profile=user_note,
        max_chars=config.max_prepend_chars,
        tools_guide=format_memory_tools_guide(max_calls=config.max_search_calls_per_turn)
        if include_tools_guide
        else None,
    )
    if prepend:
        logger.info(
            "layered_memory recall session={} atoms={} chars={}",
            session_key,
            len(memories),
            sum(len(line) for line in prepend),
        )
    else:
        logger.debug("layered_memory recall session={} empty", session_key)
    return RecallResult(prepend_lines=prepend)


def _read_user_profile_note(workspace: Path) -> str | None:
    """LM2-D L3 v2: read existing ``USER.md`` excerpt (no generation job)."""
    path = workspace / "USER.md"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
        if sum(len(part) + 1 for part in lines) >= _USER_PROFILE_MAX_CHARS:
            break
    text = " ".join(lines).strip()
    if not text:
        return None
    if len(text) > _USER_PROFILE_MAX_CHARS:
        text = text[: _USER_PROFILE_MAX_CHARS - 3] + "..."
    return text


def format_recall_prepend_lines(
    memories: list[L1Memory],
    *,
    user_profile: str | None,
    max_chars: int,
    tools_guide: list[str] | None = None,
) -> list[str]:
    """Build ``[Recalled memories]`` runtime block capped by ``max_prepend_chars``."""
    lines: list[str] = []
    if user_profile:
        lines.extend(["[User profile note]", user_profile])
    if memories:
        lines.append("[Recalled memories]")
        for mem in memories:
            lines.append(f"- ({mem.memory_type}) {mem.content}")
    if tools_guide:
        if lines:
            lines.append("")
        lines.extend(tools_guide)
    if not lines:
        return []
    return _truncate_recall_lines(lines, max_chars=max_chars)


def _truncate_recall_lines(lines: list[str], *, max_chars: int) -> list[str]:
    if max_chars <= 0:
        return []
    joined = "\n".join(lines)
    if len(joined) <= max_chars:
        return lines
    # Drop lowest-ranked memory lines first; keep headers.
    trimmed = list(lines)
    while len(trimmed) > 1 and len("\n".join(trimmed)) > max_chars:
        if trimmed and trimmed[-1].startswith("- ("):
            trimmed.pop()
            continue
        if len(trimmed) > 2 and trimmed[-1] == "[Recalled memories]":
            trimmed.pop()
            continue
        # Shrink user profile or last line by truncation.
        last = trimmed[-1]
        budget = max_chars - len("\n".join(trimmed[:-1])) - (1 if len(trimmed) > 1 else 0)
        if budget <= 0:
            trimmed.pop()
        else:
            trimmed[-1] = last[:budget]
            break
    if trimmed and len("\n".join(trimmed)) > max_chars:
        return ["\n".join(trimmed)[:max_chars]]
    return trimmed
