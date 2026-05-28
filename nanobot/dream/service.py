"""Dreaming service — promote facts from daily notes into MEMORY.md sections.

Replaces the one-shot LLM rewrite consolidator's role as the *only* path
from raw observations to durable facts. Where consolidation compresses
into a paragraph and is destructive, dreaming *promotes* — it reads
verbatim daily notes (which are never compressed) and append-upserts
qualified facts into typed sections of MEMORY.md.

Pinned-section restoration (M4) protects safety facts already in
MEMORY.md from being smoothed by the consolidator. This service is the
complementary upstream: it ensures new safety-relevant observations from
daily notes get *into* Pinned in the first place.

See vault/typed-memory-port-from-openclaw.md.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent.memory import MemoryStore

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


_DREAM_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "promote_facts",
            "description": (
                "Promote facts extracted from daily notes into MEMORY.md "
                "sections. Each promotion is appended (or upserted if it "
                "already matches an existing entry). Be conservative — "
                "promote only durable, high-value facts; skip transient "
                "context. Anything safety-, health-, or identity-critical "
                "must go to the 'Pinned' section."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "promotions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section": {
                                    "type": "string",
                                    "description": (
                                        "Section name to add the fact to "
                                        "(case-insensitive). Use 'Pinned' "
                                        "for safety/identity-critical facts. "
                                        "Other sections must already exist "
                                        "in MEMORY_SCHEMA.md."
                                    ),
                                },
                                "fact": {
                                    "type": "string",
                                    "description": (
                                        "The fact to add. One bullet point, "
                                        "specific and dated where useful. "
                                        "Include the source date in square "
                                        "brackets at the start, e.g. "
                                        "'[2026-05-28] Glyn disclosed …'."
                                    ),
                                },
                                "salience": {
                                    "type": "string",
                                    "enum": ["safety", "decision", "preference", "event", "transient"],
                                    "description": "Why this fact warrants promotion.",
                                },
                            },
                            "required": ["section", "fact", "salience"],
                        },
                    },
                    "skipped_reason": {
                        "type": "string",
                        "description": "Optional: brief note if you decided nothing was worth promoting.",
                    },
                },
                "required": ["promotions"],
            },
        },
    }
]


class DreamingService:
    """Periodic LLM-driven pass that promotes daily-note facts into MEMORY.md."""

    SIDECAR_NAME = ".dreamed.json"

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        enabled: bool = False,
        interval_s: int = 24 * 60 * 60,
        days_window: int = 7,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.enabled = enabled
        self.interval_s = interval_s
        self.days_window = days_window
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def sidecar_path(self) -> Path:
        return MemoryStore(self.workspace).memory_dir / self.SIDECAR_NAME

    def _read_sidecar(self) -> dict:
        path = self.sidecar_path
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_sidecar(self, data: dict) -> None:
        self.sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Dreaming disabled")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Dreaming started (every {}s, window {} days)", self.interval_s, self.days_window)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self.tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Dreaming loop error")

    async def tick(self) -> dict:
        """Run one dreaming pass. Returns a summary dict (also useful for tests)."""
        store = MemoryStore(self.workspace)
        files = store.list_daily_files(days=self.days_window)
        if not files:
            logger.info("Dreaming: no daily notes in window — skipping")
            return {"status": "skipped", "reason": "no_daily_notes"}

        sidecar = self._read_sidecar()
        dreamed_dates: set[str] = set(sidecar.get("dreamed_dates", []))
        candidates = [p for p in files if p.stem not in dreamed_dates]
        if not candidates:
            logger.info("Dreaming: all {} daily notes already dreamed", len(files))
            return {"status": "skipped", "reason": "nothing_new"}

        logger.info(
            "Dreaming: {} candidate daily note(s) ({} already dreamed)",
            len(candidates), len(dreamed_dates),
        )

        schema = self._read_bootstrap_file("MEMORY_SCHEMA.md")
        user = self._read_bootstrap_file("USER.md")
        current_memory = store.read_long_term()
        daily_blob = "\n\n".join(
            f"### {p.name}\n{p.read_text(encoding='utf-8')}" for p in candidates
        )

        system_prompt = (
            "You are a memory promotion agent ('dreamer'). You read the "
            "verbatim daily notes from recent days, plus the current state "
            "of MEMORY.md, and you decide which facts to promote into the "
            "structured long-term memory.\n\n"
            "RULES:\n"
            "- Be conservative. Promote only durable, high-value facts.\n"
            "- For anything safety-, health-, or identity-critical: section "
            "must be 'Pinned'. The Pinned section is byte-protected across "
            "consolidations, so this is where critical specifics survive.\n"
            "- Other section names must already exist in MEMORY_SCHEMA.md "
            "(case-insensitive).\n"
            "- Don't promote facts that are already in MEMORY.md.\n"
            "- Start each fact with [YYYY-MM-DD] where possible.\n"
            "- Call promote_facts EXACTLY ONCE. Pass an empty `promotions` "
            "array if nothing qualifies."
        )

        user_prompt = (
            f"## MEMORY_SCHEMA.md\n{schema or '(not provided)'}\n\n"
            f"## USER.md\n{user or '(not provided)'}\n\n"
            f"## Current MEMORY.md\n{current_memory or '(empty)'}\n\n"
            f"## Recent Daily Notes (last {self.days_window} days, undreamed)\n"
            f"{daily_blob}"
        )

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=_DREAM_TOOL,
                model=self.model,
            )
        except Exception:
            logger.exception("Dreaming: LLM call failed")
            return {"status": "error", "reason": "llm_failed"}

        if not response.has_tool_calls:
            logger.warning("Dreaming: LLM did not call promote_facts, skipping")
            return {"status": "skipped", "reason": "no_tool_call"}

        args = response.tool_calls[0].arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning("Dreaming: failed to parse promote_facts arguments")
                return {"status": "error", "reason": "bad_arguments"}
        if not isinstance(args, dict):
            return {"status": "error", "reason": "bad_arguments"}

        promotions = args.get("promotions") or []
        promoted = 0
        skipped_existing = 0
        for p in promotions:
            if not isinstance(p, dict):
                continue
            section = p.get("section")
            fact = p.get("fact")
            if not (isinstance(section, str) and isinstance(fact, str) and fact.strip()):
                continue
            # Dedupe: if any existing line in the section starts with the same
            # date+prefix, skip. Cheap and conservative.
            existing = store.get_section(section) or ""
            normalised_fact = fact.strip()
            if normalised_fact in existing:
                skipped_existing += 1
                continue
            # Preserve the canonical "Pinned (do not compress)" heading style
            heading_line = (
                "## Pinned (do not compress)"
                if section.strip().lower() == store.PINNED_SECTION.lower()
                else None
            )
            store.append_to_section(
                section,
                f"- {normalised_fact.lstrip('- ').rstrip()}",
                heading_line=heading_line,
            )
            promoted += 1

        # Mark candidates as dreamed.
        for p in candidates:
            dreamed_dates.add(p.stem)
        sidecar["dreamed_dates"] = sorted(dreamed_dates)
        sidecar["last_run"] = datetime.now().isoformat(timespec="seconds")
        sidecar["last_promoted"] = promoted
        self._write_sidecar(sidecar)

        logger.info(
            "Dreaming done: {} promoted, {} skipped (already present), "
            "{} candidate notes marked dreamed",
            promoted, skipped_existing, len(candidates),
        )
        return {
            "status": "ok",
            "promoted": promoted,
            "skipped_existing": skipped_existing,
            "candidates": len(candidates),
        }

    def _read_bootstrap_file(self, name: str) -> str:
        p = self.workspace / name
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""
