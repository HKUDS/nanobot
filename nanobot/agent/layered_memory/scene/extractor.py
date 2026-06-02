"""L2 scenario extraction via LLM (LM3-A)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l1_store import L1Memory, L1Store
from nanobot.agent.layered_memory.pipeline import L2TriggerReason
from nanobot.agent.layered_memory.scene.index import (
    SceneEntry,
    SceneIndex,
    normalize_slug,
    relative_scene_path,
)
from nanobot.config.schema import LayeredMemoryConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.prompt_templates import render_template

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_VALID_ACTIONS = frozenset({"create", "update", "skip"})
_LLM_TIMEOUT_S = 120.0
_LLM_MAX_TOKENS = 4096


@dataclass(frozen=True)
class ProposedScene:
    action: str
    slug: str
    title: str
    summary: str
    content_md: str
    source_atom_ids: tuple[str, ...]


class SceneExtractor:
    """Pipeline L2 handler: read L1 atoms → LLM synthesize → scene md + index."""

    __slots__ = ("_config", "_index", "_l1_store", "_provider")

    def __init__(
        self,
        workspace: Any,
        config: LayeredMemoryConfig,
        provider: LLMProvider,
        *,
        l1_store: L1Store | None = None,
        scene_index: SceneIndex | None = None,
    ) -> None:
        root = workspace if isinstance(workspace, Path) else Path(workspace)
        self._config = config
        self._provider = provider
        self._l1_store = l1_store or L1Store(root)
        self._index = scene_index or SceneIndex(root)

    async def run(
        self,
        session_key: str,
        *,
        reason: L2TriggerReason,
    ) -> None:
        atoms = self._l1_store.list_session(session_key)
        if not atoms:
            logger.debug(
                "layered_memory l2_extract_skip session={} reason={} (no L1 atoms)",
                session_key,
                reason.value,
            )
            return

        existing = self._index.load()
        scenes = await self._extract_scenes(session_key, atoms, existing)
        if not scenes:
            logger.info(
                "layered_memory l2_extract session={} reason={} written=0",
                session_key,
                reason.value,
            )
            return

        written = 0
        skipped = 0
        known_slugs = {entry.slug for entry in existing}
        for scene in scenes:
            if scene.action == "skip":
                skipped += 1
                continue
            slug = normalize_slug(scene.slug)
            if not slug or not scene.title.strip() or not scene.content_md.strip():
                skipped += 1
                continue
            if scene.action == "update" and slug not in known_slugs:
                skipped += 1
                continue
            if scene.action == "create" and slug in known_slugs:
                skipped += 1
                continue

            path = self._index.write_scene_markdown(slug, scene.content_md)
            session_keys = _merge_session_keys(existing, slug, session_key)
            entry = SceneEntry(
                slug=slug,
                title=scene.title.strip(),
                path=relative_scene_path(slug),
                session_keys=session_keys,
                updated_at=time.time(),
                summary=scene.summary.strip()[:200],
                source_atom_ids=list(scene.source_atom_ids),
            )
            self._index.upsert(entry)
            known_slugs.add(slug)
            written += 1
            logger.debug(
                "layered_memory l2_scene_written session={} slug={} path={}",
                session_key,
                slug,
                path,
            )

        logger.info(
            "layered_memory l2_extract session={} reason={} written={} skipped={}",
            session_key,
            reason.value,
            written,
            skipped,
        )

    async def _extract_scenes(
        self,
        session_key: str,
        atoms: list[L1Memory],
        existing: list[SceneEntry],
    ) -> list[ProposedScene]:
        atoms_text = format_atoms(atoms)
        existing_text = format_existing_scenes(existing)
        user_prompt = render_template(
            "agent/l2_scene_extraction.md",
            session_key=session_key,
            atoms=atoms_text,
            existing_scenes=existing_text,
        )
        messages = [
            {
                "role": "system",
                "content": "You synthesize scenario memory documents. Output valid JSON only.",
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
            logger.warning("layered_memory l2_extract timeout session={}", session_key)
            return []
        except Exception:
            logger.exception("layered_memory l2_extract llm_failed session={}", session_key)
            return []

        if response.finish_reason == "error":
            logger.warning(
                "layered_memory l2_extract provider_error session={} content={!r}",
                session_key,
                (response.content or "")[:200],
            )
            return []
        return parse_l2_response(response.content)

    def close(self) -> None:
        self._l1_store.close()


def format_atoms(atoms: list[L1Memory]) -> str:
    lines: list[str] = []
    for atom in atoms:
        lines.append(f"- [{atom.atom_id}] ({atom.memory_type}) {atom.content}")
    return "\n".join(lines) if lines else "(none)"


def format_existing_scenes(entries: list[SceneEntry]) -> str:
    if not entries:
        return "(none)"
    lines: list[str] = []
    for entry in entries[:20]:
        summary = entry.summary or "(no summary)"
        lines.append(f"- {entry.slug}: {entry.title} — {summary}")
    return "\n".join(lines)


def parse_l2_response(content: str | None) -> list[ProposedScene]:
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
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list):
        return []

    scenes: list[ProposedScene] = []
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        action = _normalize_action(item.get("action"))
        if action == "skip":
            scenes.append(
                ProposedScene(
                    action="skip",
                    slug="",
                    title="",
                    summary="",
                    content_md="",
                    source_atom_ids=(),
                )
            )
            continue
        slug = normalize_slug(str(item.get("slug", "")))
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        content_md = str(item.get("content_md", "")).strip()
        atom_ids = _normalize_atom_ids(item.get("source_atom_ids"))
        if not slug or not title or not content_md:
            continue
        scenes.append(
            ProposedScene(
                action=action,
                slug=slug,
                title=title,
                summary=summary,
                content_md=content_md,
                source_atom_ids=atom_ids,
            )
        )
    return scenes


def _normalize_action(raw: object) -> str:
    if not isinstance(raw, str):
        return "skip"
    value = raw.strip().lower()
    if value in _VALID_ACTIONS:
        return value
    return "skip"


def _normalize_atom_ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _merge_session_keys(
    existing: list[SceneEntry],
    slug: str,
    session_key: str,
) -> list[str]:
    keys: list[str] = []
    for entry in existing:
        if entry.slug == slug:
            keys.extend(entry.session_keys)
            break
    if session_key and session_key not in keys:
        keys.append(session_key)
    return keys
