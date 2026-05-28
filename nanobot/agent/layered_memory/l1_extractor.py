"""L1 atom extraction via LLM (LM2-C)."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l0_store import L0MessageRecord, L0Store
from nanobot.agent.layered_memory.l1_dedup import is_duplicate
from nanobot.agent.layered_memory.l1_store import L1MemoryType, L1Store
from nanobot.agent.layered_memory.pipeline import PipelineTriggerReason
from nanobot.config.schema import LayeredMemoryConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.prompt_templates import render_template

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_VALID_TYPES = frozenset({"preference", "fact", "event", "rule"})
_LLM_TIMEOUT_S = 120.0
_LLM_MAX_TOKENS = 2048


@dataclass(frozen=True)
class ProposedAtom:
    memory_type: L1MemoryType
    content: str
    source_turn_ids: tuple[str, ...]


class L1Extractor:
    """Pipeline L1 handler: read L0 → LLM extract → dedup → L1 store."""

    __slots__ = ("_config", "_l0_store", "_l1_store", "_provider")

    def __init__(
        self,
        workspace: Any,
        config: LayeredMemoryConfig,
        provider: LLMProvider,
        *,
        l0_store: L0Store | None = None,
        l1_store: L1Store | None = None,
    ) -> None:
        from pathlib import Path

        root = workspace if isinstance(workspace, Path) else Path(workspace)
        self._config = config
        self._provider = provider
        self._l0_store = l0_store or L0Store(root)
        self._l1_store = l1_store or L1Store(root)

    async def run(
        self,
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        records = self._fetch_l0_records(session_key, turn_ids, chunk)
        if not records:
            logger.debug(
                "layered_memory l1_extract_skip session={} reason={} (no L0 rows)",
                session_key,
                reason.value,
            )
            return

        dialogue = format_dialogue(records)
        atoms = await self._extract_atoms(session_key, dialogue, turn_count=chunk or len(turn_ids))
        if not atoms:
            logger.info(
                "layered_memory l1_extract session={} reason={} inserted=0 skipped=0",
                session_key,
                reason.value,
            )
            return

        pipeline_cfg = self._config.pipeline
        max_per_session = pipeline_cfg.max_memories_per_session
        enable_dedup = pipeline_cfg.enable_l1_dedup
        l0_by_turn = _index_l0_ids_by_turn(records)

        inserted = 0
        skipped = 0
        for atom in atoms:
            if self._l1_store.count_session(session_key) >= max_per_session:
                skipped += 1
                continue
            if is_duplicate(
                atom.content,
                self._l1_store,
                session_key=session_key,
                enable_dedup=enable_dedup,
            ):
                skipped += 1
                continue
            source_l0 = _resolve_source_l0_ids(atom.source_turn_ids, l0_by_turn, records)
            source_turns = atom.source_turn_ids or _distinct_turn_ids(records)
            atom_id = await asyncio.to_thread(
                self._l1_store.insert,
                session_key=session_key,
                memory_type=atom.memory_type,
                content=atom.content,
                source_l0_ids=source_l0,
                source_turn_ids=source_turns,
            )
            if atom_id:
                inserted += 1
            else:
                skipped += 1

        logger.info(
            "layered_memory l1_extract session={} reason={} inserted={} skipped={}",
            session_key,
            reason.value,
            inserted,
            skipped,
        )

    def _fetch_l0_records(
        self,
        session_key: str,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> list[L0MessageRecord]:
        if turn_ids:
            return self._l0_store.fetch_for_turns(session_key, turn_ids)
        if chunk > 0:
            return self._l0_store.fetch_recent_turns(session_key, chunk)
        return []

    async def _extract_atoms(
        self,
        session_key: str,
        dialogue: str,
        *,
        turn_count: int,
    ) -> list[ProposedAtom]:
        if not dialogue.strip():
            return []
        user_prompt = render_template(
            "agent/l1_extraction.md",
            session_key=session_key,
            turn_count=turn_count,
            dialogue=dialogue,
        )
        messages = [
            {
                "role": "system",
                "content": "You extract durable user memory atoms. Output valid JSON only.",
            },
            {"role": "user", "content": user_prompt},
        ]
        model = self._config.pipeline.extraction_model
        try:
            response = await asyncio.wait_for(
                self._provider.chat(
                    messages,
                    model=model,
                    max_tokens=_LLM_MAX_TOKENS,
                    temperature=0.2,
                ),
                timeout=_LLM_TIMEOUT_S,
            )
        except TimeoutError:
            logger.warning("layered_memory l1_extract timeout session={}", session_key)
            return []
        except Exception:
            logger.exception("layered_memory l1_extract llm_failed session={}", session_key)
            return []

        if response.finish_reason == "error":
            logger.warning(
                "layered_memory l1_extract provider_error session={} content={!r}",
                session_key,
                (response.content or "")[:200],
            )
            return []
        return parse_l1_response(response.content)

    def close(self) -> None:
        self._l0_store.close()
        self._l1_store.close()


def format_dialogue(records: list[L0MessageRecord]) -> str:
    """Format L0 rows as a readable transcript for the extraction prompt."""
    lines: list[str] = []
    current_turn: str | None = None
    for row in records:
        if row.turn_id and row.turn_id != current_turn:
            current_turn = row.turn_id
            lines.append(f"\n--- turn: {current_turn} ---")
        role = row.role
        if row.name:
            role = f"{role}/{row.name}"
        lines.append(f"{role}: {row.content}")
    return "\n".join(lines).strip()


def parse_l1_response(content: str | None) -> list[ProposedAtom]:
    if not content:
        return []
    text = _JSON_FENCE_RE.sub("", content.strip()).strip()
    data: object
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return []
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return []

    if not isinstance(data, dict):
        return []
    raw_atoms = data.get("atoms")
    if not isinstance(raw_atoms, list):
        return []

    atoms: list[ProposedAtom] = []
    for item in raw_atoms:
        if not isinstance(item, dict):
            continue
        memory_type = _normalize_type(item.get("type"))
        raw_content = item.get("content")
        if not isinstance(raw_content, str) or not raw_content.strip():
            continue
        turn_ids = _normalize_turn_ids(item.get("source_turn_ids"))
        atoms.append(
            ProposedAtom(
                memory_type=memory_type,
                content=raw_content.strip()[:500],
                source_turn_ids=turn_ids,
            )
        )
    return atoms


def _normalize_type(raw: object) -> L1MemoryType:
    if not isinstance(raw, str):
        return "fact"
    value = raw.strip().lower()
    if value in _VALID_TYPES:
        return value  # type: ignore[return-value]
    return "fact"


def _normalize_turn_ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(str(x).strip() for x in raw if str(x).strip())


def _index_l0_ids_by_turn(records: list[L0MessageRecord]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for row in records:
        key = row.turn_id or ""
        out.setdefault(key, []).append(row.id)
    return out


def _resolve_source_l0_ids(
    turn_ids: tuple[str, ...],
    l0_by_turn: dict[str, list[int]],
    records: list[L0MessageRecord],
) -> tuple[int, ...]:
    if turn_ids:
        ids: list[int] = []
        for tid in turn_ids:
            ids.extend(l0_by_turn.get(tid, []))
        if ids:
            return tuple(ids)
    return tuple(row.id for row in records)


def _distinct_turn_ids(records: list[L0MessageRecord]) -> tuple[str, ...]:
    seen: list[str] = []
    for row in records:
        if row.turn_id and row.turn_id not in seen:
            seen.append(row.turn_id)
    return tuple(seen)
