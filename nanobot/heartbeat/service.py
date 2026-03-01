"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_MAX_SELECTED_LINES = 60

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (legacy)",
                    },
                    "task_intent": {
                        "type": "string",
                        "description": "Concise execution intent for phase-2",
                    },
                    "must_keep": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Critical constraints/requirements that must survive compression",
                    },
                    "source_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional line refs into HEARTBEAT.md, e.g. L3-L7 or 12-15",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


@dataclass
class HeartbeatDecision:
    action: str
    task_intent: str
    must_keep: list[str]
    source_refs: list[str]


@dataclass
class HeartbeatExecutionPayload:
    summary: str
    selected_sections: list[str]
    dropped_non_empty_lines: int


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``. It uses
    a prioritized payload that keeps critical constraints from HEARTBEAT.md
    instead of executing only a lossy summary string.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> HeartbeatDecision:
        """Phase 1: ask LLM to decide skip/run via virtual tool call."""
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {
                    "role": "user",
                    "content": (
                        "Review HEARTBEAT.md and decide whether to run tasks. "
                        "If action=run, include task_intent and keep critical constraints in must_keep/source_refs.\n\n"
                        f"{content}"
                    ),
                },
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return HeartbeatDecision(action="skip", task_intent="", must_keep=[], source_refs=[])

        args = response.tool_calls[0].arguments
        legacy_tasks = str(args.get("tasks", "")).strip()
        task_intent = str(args.get("task_intent", "")).strip() or legacy_tasks

        must_keep = [str(x).strip() for x in (args.get("must_keep") or []) if str(x).strip()]
        source_refs = [str(x).strip() for x in (args.get("source_refs") or []) if str(x).strip()]

        return HeartbeatDecision(
            action=str(args.get("action", "skip")),
            task_intent=task_intent,
            must_keep=must_keep,
            source_refs=source_refs,
        )

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    def _parse_ref_range(self, ref: str, max_line: int) -> tuple[int, int] | None:
        m = re.search(r"L?(\d+)\s*(?:-|\.\.|to)\s*L?(\d+)", ref, re.IGNORECASE)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
        else:
            m2 = re.search(r"L?(\d+)", ref, re.IGNORECASE)
            if not m2:
                return None
            a = b = int(m2.group(1))

        a = max(1, min(a, max_line))
        b = max(1, min(b, max_line))
        if a > b:
            a, b = b, a
        return a, b

    def _build_execution_payload(self, decision: HeartbeatDecision, content: str) -> HeartbeatExecutionPayload:
        """Build a prioritized payload that preserves critical heartbeat details."""
        lines = content.splitlines()
        max_line = len(lines)
        selected: list[str] = []

        def add_line(line: str) -> None:
            line = line.rstrip()
            if not line:
                return
            if line not in selected:
                selected.append(line)

        # 1) source_refs from phase-1 decision
        for ref in decision.source_refs:
            parsed = self._parse_ref_range(ref, max_line)
            if not parsed:
                continue
            start, end = parsed
            for idx in range(start - 1, end):
                add_line(lines[idx])
                if len(selected) >= _MAX_SELECTED_LINES:
                    break
            if len(selected) >= _MAX_SELECTED_LINES:
                break

        # 2) explicit must_keep phrases
        if len(selected) < _MAX_SELECTED_LINES:
            for key in decision.must_keep:
                kl = key.lower()
                for line in lines:
                    if kl and kl in line.lower():
                        add_line(line)
                        if len(selected) >= _MAX_SELECTED_LINES:
                            break
                if len(selected) >= _MAX_SELECTED_LINES:
                    break

        # 3) always keep high-priority constraints/checklists/deadlines
        priority_pat = re.compile(r"(^\s*[-*]\s*\[.?\]|\bmust\b|\bdeadline\b|\burgent\b|\bby\s+\d)", re.IGNORECASE)
        if len(selected) < _MAX_SELECTED_LINES:
            for line in lines:
                if priority_pat.search(line):
                    add_line(line)
                    if len(selected) >= _MAX_SELECTED_LINES:
                        break

        # 4) headings and then remaining non-empty context
        if len(selected) < _MAX_SELECTED_LINES:
            for line in lines:
                if line.startswith("#"):
                    add_line(line)
                    if len(selected) >= _MAX_SELECTED_LINES:
                        break

        if len(selected) < _MAX_SELECTED_LINES:
            for line in lines:
                add_line(line)
                if len(selected) >= _MAX_SELECTED_LINES:
                    break

        non_empty = [ln for ln in lines if ln.strip()]
        dropped = max(0, len(non_empty) - len(selected))

        return HeartbeatExecutionPayload(
            summary=(decision.task_intent or "").strip(),
            selected_sections=selected,
            dropped_non_empty_lines=dropped,
        )

    def _render_execution_input(self, payload: HeartbeatExecutionPayload) -> str:
        """Render backward-compatible phase-2 string for the current agent loop."""
        parts: list[str] = []
        if payload.summary:
            parts.append(payload.summary)
        parts.append("Use the following HEARTBEAT.md context (prioritized):")
        parts.extend(payload.selected_sections)
        if payload.dropped_non_empty_lines:
            parts.append(
                f"[Context truncated: omitted {payload.dropped_non_empty_lines} non-empty lines after prioritization. "
                "Preserve listed constraints and checklist items.]"
            )
        return "\n".join(parts)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            decision = await self._decide(content)

            if decision.action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                payload = self._build_execution_payload(decision, content)
                execution_input = self._render_execution_input(payload)
                logger.debug(
                    "Heartbeat payload: selected={} dropped={}",
                    len(payload.selected_sections),
                    payload.dropped_non_empty_lines,
                )
                response = await self.on_execute(execution_input)
                if response and self.on_notify:
                    logger.info("Heartbeat: completed, delivering response")
                    await self.on_notify(response)
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None

        decision = await self._decide(content)
        if decision.action != "run" or not self.on_execute:
            return None

        payload = self._build_execution_payload(decision, content)
        execution_input = self._render_execution_input(payload)
        return await self.on_execute(execution_input)
