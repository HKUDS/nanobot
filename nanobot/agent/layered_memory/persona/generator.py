"""L3 persona generation: scenes + L1 → ``USER.md`` (LM3-B)."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.layered_memory.l1_store import L1Memory, L1Store
from nanobot.agent.layered_memory.persona.backup import backup_user_md, user_file_path
from nanobot.agent.layered_memory.persona.lock import PersonaLock
from nanobot.agent.layered_memory.pipeline import L3TriggerReason
from nanobot.agent.layered_memory.scene.index import SceneEntry, SceneIndex
from nanobot.config.schema import LayeredMemoryConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.helpers import _write_text_atomic, ensure_dir
from nanobot.utils.prompt_templates import render_template

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_VALID_ACTIONS = frozenset({"update", "skip"})
_LLM_TIMEOUT_S = 120.0
_LLM_MAX_TOKENS = 4096
_SCENE_BODY_MAX_CHARS = 2000
_ATOM_LIMIT = 40


@dataclass(frozen=True)
class PersonaProposal:
    action: str
    content_md: str


class PersonaGenerator:
    """Pipeline L3 handler: L2 scenes + L1 atoms → ``USER.md`` under file lock."""

    __slots__ = (
        "_config",
        "_index",
        "_l1_store",
        "_lock",
        "_provider",
        "_workspace",
    )

    def __init__(
        self,
        workspace: Any,
        config: LayeredMemoryConfig,
        provider: LLMProvider,
        *,
        l1_store: L1Store | None = None,
        scene_index: SceneIndex | None = None,
        persona_lock: PersonaLock | None = None,
    ) -> None:
        root = workspace if isinstance(workspace, Path) else Path(workspace)
        self._workspace = root
        self._config = config
        self._provider = provider
        self._l1_store = l1_store or L1Store(root)
        self._index = scene_index or SceneIndex(root)
        persona_cfg = config.persona
        self._lock = persona_lock or PersonaLock(
            root,
            timeout_seconds=persona_cfg.lock_timeout_seconds,
        )

    async def run(
        self,
        session_key: str,
        *,
        reason: L3TriggerReason,
    ) -> None:
        if not self._config.persona_enabled():
            logger.debug(
                "layered_memory l3_skip session={} reason={} (persona disabled)",
                session_key,
                reason.value,
            )
            return

        scenes = self._index.load()
        atoms = self._fetch_recent_atoms()
        if not scenes and not atoms:
            logger.debug(
                "layered_memory l3_skip session={} reason={} (no scenes or atoms)",
                session_key,
                reason.value,
            )
            return

        proposal = await self._generate_persona(session_key, scenes, atoms)
        if proposal is None or proposal.action == "skip":
            logger.info(
                "layered_memory l3_persona session={} reason={} updated=0",
                session_key,
                reason.value,
            )
            return

        content = proposal.content_md.strip()
        if not content:
            logger.info(
                "layered_memory l3_persona session={} reason={} updated=0 (empty)",
                session_key,
                reason.value,
            )
            return

        max_chars = self._config.persona.max_user_chars
        if len(content) > max_chars:
            content = content[: max_chars - 3] + "..."

        try:
            await asyncio.to_thread(self._write_user_locked, content)
        except Exception:
            logger.exception(
                "layered_memory l3_persona_write_failed session={} reason={}",
                session_key,
                reason.value,
            )
            return

        logger.info(
            "layered_memory l3_persona session={} reason={} updated=1 chars={}",
            session_key,
            reason.value,
            len(content),
        )

    def _write_user_locked(self, content: str) -> None:
        persona_cfg = self._config.persona
        with self._lock.hold():
            if persona_cfg.backup_count > 0:
                backup_user_md(self._workspace, keep=persona_cfg.backup_count)
            path = user_file_path(self._workspace)
            ensure_dir(path.parent)
            _write_text_atomic(path, content.rstrip() + "\n")

    def _fetch_recent_atoms(self) -> list[L1Memory]:
        return self._l1_store.list_recent(_ATOM_LIMIT)

    async def _generate_persona(
        self,
        session_key: str,
        scenes: list[SceneEntry],
        atoms: list[L1Memory],
    ) -> PersonaProposal | None:
        current_user = _read_current_user(self._workspace)
        user_prompt = render_template(
            "agent/l3_persona_generation.md",
            session_key=session_key,
            current_user=current_user or "(empty)",
            scene_index=format_scene_index(scenes),
            scene_bodies=format_scene_bodies(self._workspace, self._index, scenes),
            atoms=format_atoms(atoms),
            max_user_chars=self._config.persona.max_user_chars,
        )
        messages = [
            {
                "role": "system",
                "content": "You synthesize a durable user persona for USER.md. Output valid JSON only.",
            },
            {"role": "user", "content": user_prompt},
        ]
        model = self._resolve_model()
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
            logger.warning("layered_memory l3_persona timeout session={}", session_key)
            return None
        except Exception:
            logger.exception("layered_memory l3_persona llm_failed session={}", session_key)
            return None

        if response.finish_reason == "error":
            logger.warning(
                "layered_memory l3_persona provider_error session={} content={!r}",
                session_key,
                (response.content or "")[:200],
            )
            return None
        proposals = parse_l3_response(response.content)
        return proposals[0] if proposals else None

    def _resolve_model(self) -> str | None:
        persona_model = self._config.persona.model
        if persona_model:
            return persona_model
        return self._config.pipeline.extraction_model

    def close(self) -> None:
        self._l1_store.close()


def _read_current_user(workspace: Path) -> str:
    path = user_file_path(workspace)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def format_scene_index(scenes: list[SceneEntry]) -> str:
    if not scenes:
        return "(none)"
    lines = [f"- {entry.slug}: {entry.title} — {entry.summary or '(no summary)'}" for entry in scenes]
    return "\n".join(lines)


def format_scene_bodies(workspace: Path, index: SceneIndex, scenes: list[SceneEntry]) -> str:
    if not scenes:
        return "(none)"
    chunks: list[str] = []
    for entry in scenes[:12]:
        path = index.scene_path(entry.slug)
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if len(body) > _SCENE_BODY_MAX_CHARS:
            body = body[: _SCENE_BODY_MAX_CHARS - 3] + "..."
        chunks.append(f"### {entry.slug}\n{body}")
    return "\n\n".join(chunks) if chunks else "(none)"


def format_atoms(atoms: list[L1Memory]) -> str:
    if not atoms:
        return "(none)"
    lines = [f"- [{atom.atom_id}] ({atom.memory_type}) {atom.content}" for atom in atoms]
    return "\n".join(lines)


def parse_l3_response(content: str | None) -> list[PersonaProposal]:
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

    items: list[object]
    if isinstance(data, dict):
        if "action" in data:
            items = [data]
        else:
            raw = data.get("persona") or data.get("proposals")
            items = raw if isinstance(raw, list) else []
    elif isinstance(data, list):
        items = data
    else:
        return []

    proposals: list[PersonaProposal] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        action = _normalize_action(item.get("action"))
        if action == "skip":
            proposals.append(PersonaProposal(action="skip", content_md=""))
            continue
        raw_content = item.get("content_md")
        if not isinstance(raw_content, str) or not raw_content.strip():
            continue
        proposals.append(
            PersonaProposal(
                action=action,
                content_md=raw_content.strip(),
            )
        )
    return proposals


def _normalize_action(raw: object) -> str:
    if not isinstance(raw, str):
        return "skip"
    value = raw.strip().lower()
    if value in _VALID_ACTIONS:
        return value
    return "skip"
