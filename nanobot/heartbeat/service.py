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


@dataclass
class HeartbeatSelectionBudget:
    refs_max_lines: int
    must_keep_max_matches: int
    priority_max_matches: int
    heading_max_lines: int
    context_fallback_max_lines: int
    max_render_chars: int


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
        timezone: str | None = None,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self.timezone = timezone
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
        from nanobot.utils.helpers import current_time_str

        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {
                    "role": "user",
                    "content": (
                        f"Current Time: {current_time_str(self.timezone)}\n\n"
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

    def _context_window_tokens_for_model(self) -> int:
        """Rough context-window estimate for adaptive heartbeat payload sizing."""
        m = (self.model or "").lower()
        if any(x in m for x in ("gpt-4o-mini", "gpt-4.1-mini", "claude-3-haiku", "gemini-1.5-flash")):
            return 8192
        if any(x in m for x in ("gpt-4o", "gpt-4.1", "claude-3-5-sonnet", "claude-3-7-sonnet", "gemini-1.5-pro")):
            return 32768
        if any(x in m for x in ("gpt-5", "o1", "o3", "claude-3-opus", "claude-4", "gemini-2")):
            return 131072
        return 32768

    def _selection_budget_for_model(self) -> HeartbeatSelectionBudget:
        """Per-model adaptive selection budget for heartbeat context."""
        window = self._context_window_tokens_for_model()
        heartbeat_tokens = int(window * 0.15)
        heartbeat_tokens = max(800, min(heartbeat_tokens, 6000))
        max_chars = heartbeat_tokens * 4

        # Approximate line budget from char budget with sane floor/ceiling.
        max_lines = max(40, min(max_chars // 80, 180))

        refs_max = max(8, min(max_lines // 4, 40))
        must_keep_max = max(8, min(max_lines // 4, 40))
        priority_max = max(12, min(max_lines // 3, 70))
        heading_max = max(6, min(max_lines // 6, 24))
        context_max = max_lines

        return HeartbeatSelectionBudget(
            refs_max_lines=refs_max,
            must_keep_max_matches=must_keep_max,
            priority_max_matches=priority_max,
            heading_max_lines=heading_max,
            context_fallback_max_lines=context_max,
            max_render_chars=max_chars,
        )

    def _build_execution_payload(self, decision: HeartbeatDecision, content: str) -> HeartbeatExecutionPayload:
        """Build a prioritized payload that preserves critical heartbeat details."""
        budget = self._selection_budget_for_model()
        lines = content.splitlines()
        max_line = len(lines)
        selected: list[str] = []

        refs_count = 0
        must_keep_count = 0
        priority_count = 0
        heading_count = 0
        context_count = 0

        def add_line(line: str) -> bool:
            line = line.rstrip()
            if not line:
                return False
            if line in selected:
                return False
            selected.append(line)
            return True

        # 1) source_refs from phase-1 decision
        for ref in decision.source_refs:
            parsed = self._parse_ref_range(ref, max_line)
            if not parsed:
                continue
            start, end = parsed
            for idx in range(start - 1, end):
                if refs_count >= budget.refs_max_lines:
                    break
                if add_line(lines[idx]):
                    refs_count += 1
            if refs_count >= budget.refs_max_lines:
                break

        # 2) explicit must_keep phrases
        for key in decision.must_keep:
            if must_keep_count >= budget.must_keep_max_matches:
                break
            kl = key.lower().strip()
            if not kl:
                continue
            for line in lines:
                if kl and kl in line.lower() and add_line(line):
                    must_keep_count += 1
                    if must_keep_count >= budget.must_keep_max_matches:
                        break

        # 3) always keep high-priority constraints/checklists/deadlines
        priority_pat = re.compile(r"(^\s*[-*]\s*\[.?\]|\bmust\b|\bdeadline\b|\burgent\b|\bby\s+\d)", re.IGNORECASE)
        for line in lines:
            if priority_count >= budget.priority_max_matches:
                break
            if priority_pat.search(line) and add_line(line):
                priority_count += 1

        # 4) headings and then remaining non-empty context
        for line in lines:
            if heading_count >= budget.heading_max_lines:
                break
            if line.startswith("#") and add_line(line):
                heading_count += 1

        for line in lines:
            if context_count >= budget.context_fallback_max_lines:
                break
            if add_line(line):
                context_count += 1

        # 5) final render-size trim (per-model adaptive)
        rendered_chars = 0
        trimmed: list[str] = []
        for line in selected:
            ln = len(line) + 1
            if rendered_chars + ln > budget.max_render_chars:
                break
            trimmed.append(line)
            rendered_chars += ln

        non_empty = [ln for ln in lines if ln.strip()]
        dropped = max(0, len(non_empty) - len(trimmed))

        return HeartbeatExecutionPayload(
            summary=(decision.task_intent or "").strip(),
            selected_sections=trimmed,
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
        from nanobot.utils.evaluator import evaluate_response

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

                if response:
                    should_notify = await evaluate_response(
                        response,
                        decision.task_intent,
                        self.provider,
                        self.model,
                    )
                    if should_notify and self.on_notify:
                        logger.info("Heartbeat: completed, delivering response")
                        await self.on_notify(response)
                    else:
                        logger.info("Heartbeat: silenced by post-run evaluation")
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
