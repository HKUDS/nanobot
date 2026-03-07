"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


_HEARTBEAT_TOOL = [{
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
                "tasks": {"type": "string", "description": "Natural-language summary of active tasks (legacy)"},
                "task_intent": {"type": "string", "description": "Concise execution intent for phase-2"},
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
}]

_PRIORITY_PAT = re.compile(r"(^\s*[-*]\s*\[.?\]|\bmust\b|\bdeadline\b|\burgent\b|\bby\s+\d)", re.IGNORECASE)
_DEFAULT_WINDOW_TOKENS = 32768


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
        if not self.heartbeat_file.exists():
            return None
        try:
            return self.heartbeat_file.read_text(encoding="utf-8")
        except Exception:
            return None

    async def _decide(self, content: str) -> HeartbeatDecision:
        response = await self.provider.chat(
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
            return HeartbeatDecision("skip", "", [], [])

        args = response.tool_calls[0].arguments
        task_intent = (str(args.get("task_intent", "")).strip() or str(args.get("tasks", "")).strip())
        must_keep = [str(x).strip() for x in (args.get("must_keep") or []) if str(x).strip()]
        source_refs = [str(x).strip() for x in (args.get("source_refs") or []) if str(x).strip()]
        return HeartbeatDecision(str(args.get("action", "skip")), task_intent, must_keep, source_refs)

    async def start(self) -> None:
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
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
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
            m = re.search(r"L?(\d+)", ref, re.IGNORECASE)
            if not m:
                return None
            a = b = int(m.group(1))
        a, b = max(1, min(a, max_line)), max(1, min(b, max_line))
        return (a, b) if a <= b else (b, a)

    def _context_window_tokens_for_model(self) -> int:
        try:
            if hasattr(self.provider, "get_model_context_window"):
                val = self.provider.get_model_context_window(self.model)
                if isinstance(val, int) and val > 0:
                    return val
        except Exception:
            pass
        ov = os.getenv("NANOBOT_HEARTBEAT_CONTEXT_WINDOW_TOKENS", "").strip()
        if ov.isdigit() and int(ov) > 0:
            return int(ov)
        return _DEFAULT_WINDOW_TOKENS

    def _selection_budget_for_model(self) -> HeartbeatSelectionBudget:
        window = self._context_window_tokens_for_model()
        heartbeat_tokens = max(800, min(int(window * 0.15), 6000))
        max_chars = heartbeat_tokens * 4
        max_lines = max(40, min(max_chars // 80, 180))
        return HeartbeatSelectionBudget(
            refs_max_lines=max(8, min(max_lines // 4, 40)),
            must_keep_max_matches=max(8, min(max_lines // 4, 40)),
            priority_max_matches=max(12, min(max_lines // 3, 70)),
            heading_max_lines=max(6, min(max_lines // 6, 24)),
            context_fallback_max_lines=max_lines,
            max_render_chars=max_chars,
        )

    def _build_execution_payload(self, decision: HeartbeatDecision, content: str) -> HeartbeatExecutionPayload:
        budget = self._selection_budget_for_model()
        logger.debug(
            "Heartbeat budget(model={}): refs={} must_keep={} priority={} heading={} context={} max_chars={}",
            self.model,
            budget.refs_max_lines,
            budget.must_keep_max_matches,
            budget.priority_max_matches,
            budget.heading_max_lines,
            budget.context_fallback_max_lines,
            budget.max_render_chars,
        )
        lines = content.splitlines()
        selected: list[str] = []
        seen: set[str] = set()

        def add(line: str) -> bool:
            line = line.rstrip()
            if not line or line in seen:
                return False
            seen.add(line)
            selected.append(line)
            return True

        # source refs
        refs_count = 0
        for ref in decision.source_refs:
            parsed = self._parse_ref_range(ref, len(lines))
            if not parsed:
                continue
            start, end = parsed
            for idx in range(start - 1, end):
                if refs_count >= budget.refs_max_lines:
                    break
                if add(lines[idx]):
                    refs_count += 1
            if refs_count >= budget.refs_max_lines:
                break

        # must_keep matches
        must_count = 0
        for key in decision.must_keep:
            if must_count >= budget.must_keep_max_matches:
                break
            k = key.lower().strip()
            if not k:
                continue
            for line in lines:
                if k in line.lower() and add(line):
                    must_count += 1
                    if must_count >= budget.must_keep_max_matches:
                        break

        # priority patterns
        pri_count = 0
        for line in lines:
            if pri_count >= budget.priority_max_matches:
                break
            if _PRIORITY_PAT.search(line) and add(line):
                pri_count += 1

        # headings
        head_count = 0
        for line in lines:
            if head_count >= budget.heading_max_lines:
                break
            if line.startswith("#") and add(line):
                head_count += 1

        # fallback context
        ctx_count = 0
        for line in lines:
            if ctx_count >= budget.context_fallback_max_lines:
                break
            if add(line):
                ctx_count += 1

        # char-limit trim
        trimmed: list[str] = []
        chars = 0
        for line in selected:
            ln = len(line) + 1
            if chars + ln > budget.max_render_chars:
                break
            trimmed.append(line)
            chars += ln

        non_empty = sum(1 for ln in lines if ln.strip())
        return HeartbeatExecutionPayload((decision.task_intent or "").strip(), trimmed, max(0, non_empty - len(trimmed)))

    def _render_execution_input(self, payload: HeartbeatExecutionPayload) -> str:
        parts = [payload.summary] if payload.summary else []
        parts += ["Use the following HEARTBEAT.md context (prioritized):", *payload.selected_sections]
        if payload.dropped_non_empty_lines:
            parts.append(
                f"[Context truncated: omitted {payload.dropped_non_empty_lines} non-empty lines after prioritization. "
                "Preserve listed constraints and checklist items.]"
            )
        return "\n".join(parts)

    async def _tick(self) -> None:
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
            if not self.on_execute:
                return
            payload = self._build_execution_payload(decision, content)
            execution_input = self._render_execution_input(payload)
            logger.debug("Heartbeat payload: selected={} dropped={}", len(payload.selected_sections), payload.dropped_non_empty_lines)
            response = await self.on_execute(execution_input)
            if response and self.on_notify:
                logger.info("Heartbeat: completed, delivering response")
                await self.on_notify(response)
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        content = self._read_heartbeat_file()
        if not content:
            return None
        decision = await self._decide(content)
        if decision.action != "run" or not self.on_execute:
            return None
        payload = self._build_execution_payload(decision, content)
        return await self.on_execute(self._render_execution_input(payload))
