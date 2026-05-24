"""PostTask skill creation: trigger gates and (later) LLM-driven proposals."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from nanobot.agent.evolution.models import TurnTrace
from nanobot.config.schema import EvolutionConfig

# Human-readable skip reasons returned by ``should_trigger`` (None = proceed).
SKIP_EVOLUTION_DISABLED = "evolution disabled"
SKIP_TOOL_CALLS_LOW = "tool_call_count below min_tool_calls"
SKIP_OUTCOME = "outcome not success"
SKIP_STOP_REASON = "stop_reason not completed"
SKIP_NO_TOOL_CALLS = "no tool calls recorded"
SKIP_SUBAGENT = "subagent turn"
SKIP_COOLDOWN = "session cooldown active"


@dataclass(frozen=True, slots=True)
class PostTaskGateResult:
    """Outcome of PostTask trigger gate evaluation."""

    should_run: bool
    skip_reason: str = ""

    @classmethod
    def allow(cls) -> PostTaskGateResult:
        return cls(should_run=True)

    @classmethod
    def skip(cls, reason: str) -> PostTaskGateResult:
        return cls(should_run=False, skip_reason=reason)


class PostTaskCooldownStore:
    """Persist last PostTask run time per session under ``{workspace}/.nanobot/``."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace.expanduser().resolve() / ".nanobot" / "post_task_cooldown.json"
        self._memory: dict[str, float] = {}
        self._loaded = False

    def is_active(self, session_key: str, cooldown_minutes: int) -> bool:
        """Return True when *session_key* is still inside the cooldown window."""
        if cooldown_minutes <= 0:
            return False
        last = self._read().get(session_key)
        if last is None:
            return False
        return (time.time() - last) < cooldown_minutes * 60

    def mark(self, session_key: str) -> None:
        """Record that PostTask ran for *session_key* now."""
        data = self._read()
        data[session_key] = time.time()
        self._write(data)

    def _read(self) -> dict[str, float]:
        if self._loaded:
            return dict(self._memory)
        if not self._path.exists():
            self._loaded = True
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("PostTask cooldown file unreadable ({}): {}", self._path, exc)
            self._loaded = True
            return {}
        if not isinstance(raw, dict):
            self._loaded = True
            return {}
        memory: dict[str, float] = {}
        for key, value in raw.items():
            try:
                memory[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        self._memory = memory
        self._loaded = True
        return dict(self._memory)

    def _write(self, data: dict[str, float]) -> None:
        self._memory = dict(data)
        self._loaded = True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class PostTaskEvolver:
    """Turn-boundary skill creation (E1). Step 1: trigger gates only."""

    def __init__(
        self,
        workspace: Path,
        config: EvolutionConfig,
        *,
        cooldown_store: PostTaskCooldownStore | None = None,
    ) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._config = config
        self._cooldown = cooldown_store or PostTaskCooldownStore(self._workspace)

    @property
    def cooldown_store(self) -> PostTaskCooldownStore:
        return self._cooldown

    def evaluate_gate(self, trace: TurnTrace, *, is_subagent: bool) -> PostTaskGateResult:
        """Return whether PostTask should run for *trace*."""
        reason = self.should_trigger(trace, is_subagent=is_subagent)
        if reason is None:
            return PostTaskGateResult.allow()
        return PostTaskGateResult.skip(reason)

    def should_trigger(self, trace: TurnTrace, *, is_subagent: bool) -> str | None:
        """Return a skip reason string, or ``None`` when all gates pass."""
        if not self._config.post_task_enabled():
            return SKIP_EVOLUTION_DISABLED

        if is_subagent:
            return SKIP_SUBAGENT

        post_task = self._config.post_task

        if trace.tool_call_count < post_task.min_tool_calls:
            return SKIP_TOOL_CALLS_LOW

        if not trace.tool_calls:
            return SKIP_NO_TOOL_CALLS

        if trace.outcome != "success":
            return SKIP_OUTCOME

        if trace.stop_reason != "completed":
            return SKIP_STOP_REASON

        if self._cooldown.is_active(trace.session_key, post_task.cooldown_minutes):
            return SKIP_COOLDOWN

        return None
