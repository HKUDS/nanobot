"""Small restart-safe driver for active durable Goals."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.goals import (
    MAX_RECOVERY_ATTEMPTS,
    Goal,
    GoalConflictError,
    GoalError,
    GoalStore,
    compact_ref,
)
from nanobot.session.automation_turns import AutomationTurnSpec
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager

GOAL_DRIVER_META = "_goal_driver"
MAX_DRIVER_STALLS = 3


def _history_text(trigger: Mapping[str, Any]) -> str:
    return str(trigger.get("persist_content") or "Continue the durable Goal.")


GOAL_DRIVER_AUTOMATION_SPEC = AutomationTurnSpec(
    kind="goal_driver",
    trigger_meta_key=GOAL_DRIVER_META,
    history_fields={"goal_id": "goal_id"},
    text_builder=_history_text,
)


class GoalDriver:
    """Wake runnable Goals one bounded turn at a time."""

    def __init__(
        self,
        workspace: str | Path,
        bus: MessageBus,
        sessions: SessionManager,
        *,
        session_busy: Callable[[str], bool] = lambda _key: False,
        store_root: str | Path | None = None,
        interval: float = 5,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.bus = bus
        self.sessions = sessions
        self.session_busy = session_busy
        self.store = GoalStore.for_workspace(self.workspace, root=store_root)
        self.interval = interval
        self._scan_lock = asyncio.Lock()
        self._scheduled: set[str] = set()
        self._stopped = asyncio.Event()

    async def run(self, is_running: Callable[[], bool]) -> None:
        self._stopped.clear()
        while is_running():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("Goal driver scan failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def close(self) -> None:
        self._stopped.set()

    async def scan_once(self) -> None:
        if self._scan_lock.locked():
            return
        async with self._scan_lock:
            goals = await asyncio.to_thread(self.store.active)
            for goal in goals:
                if self.session_busy(goal.session_key):
                    continue
                try:
                    await self._drive(goal)
                except (GoalConflictError, GoalError, ValueError):
                    logger.debug("Goal {} changed while driver scanned it", goal.id)
                except Exception:
                    logger.exception("Goal driver failed for {}", goal.id)

    async def after_turn(self, msg: InboundMessage) -> None:
        trigger = msg.metadata.get(GOAL_DRIVER_META)
        if isinstance(trigger, dict):
            await self._record_turn(trigger)
        await self.scan_once()

    async def _drive(self, goal: Goal) -> None:
        if goal.id in self._scheduled:
            return
        driver = goal.state.get("driver") or {}
        nodes = goal.state.get("nodes") or {}
        running = [node for node in nodes.values() if node.get("status") == "running"]
        if running:
            await self._stop(
                goal,
                "waiting",
                "Execution was interrupted while a node was running; automatic replay could "
                "duplicate side effects.",
            )
            return
        if int(driver.get("stalls", 0)) >= MAX_DRIVER_STALLS:
            await self._stop(
                goal,
                "waiting",
                "The Goal was paused after three continuation turns made no durable progress.",
            )
            return

        reason = self._runnable_reason(goal)
        if reason is None:
            return
        if reason == "recovery_exhausted":
            await self._stop(
                goal,
                "waiting",
                "All runnable paths are blocked and automated recovery needs user input.",
            )
            return

        route = self._route(goal)
        if route is None:
            await self._stop(goal, "waiting", "The Goal has no usable delivery route.")
            return
        text = (
            "Continue the durable Goal for one bounded step. Read Goal Runtime Context, use the "
            "authoritative version, and persist every node transition. Expand coarse work when "
            "ready; replan blocked paths; do not treat this automation turn as user authority. "
            f"Driver reason: {reason}."
        )
        self._sync_ref(goal)
        self._scheduled.add(goal.id)
        try:
            await self.bus.publish_inbound(
                InboundMessage(
                    channel=route["channel"],
                    sender_id="goal-driver",
                    chat_id=route["chat_id"],
                    content=text,
                    metadata={
                        GOAL_DRIVER_META: {
                            "goal_id": goal.id,
                            "start_version": goal.version,
                            "persist_content": text,
                        }
                    },
                    session_key_override=goal.session_key,
                )
            )
        except BaseException:
            self._scheduled.discard(goal.id)
            raise

    @staticmethod
    def _runnable_reason(goal: Goal) -> str | None:
        nodes = goal.state.get("nodes") or {}
        if not nodes:
            return "initial_plan"
        if any(
            node.get("kind") == "coarse"
            and node.get("status") == "pending"
            and all(nodes[dep]["status"] == "succeeded" for dep in node.get("depends_on", []))
            for node in nodes.values()
        ):
            return "plan_expansion"
        if any(node.get("status") == "ready" for node in nodes.values()):
            return "ready_frontier"
        if goal.state.get("needs_replan"):
            return (
                "recovery_plan"
                if int(goal.state.get("recovery_attempts", 0)) < MAX_RECOVERY_ATTEMPTS
                else "recovery_exhausted"
            )
        retained = [node for node in nodes.values() if node.get("status") != "superseded"]
        if retained and all(node.get("status") == "succeeded" for node in retained):
            return "finalize"
        return None

    async def _record_turn(self, trigger: Mapping[str, Any]) -> None:
        goal_id = str(trigger.get("goal_id") or "")
        self._scheduled.discard(goal_id)
        goal = await asyncio.to_thread(self.store.get, goal_id)
        if goal is None or goal.status != "active":
            return
        try:
            updated = await asyncio.to_thread(
                self.store.apply,
                goal.id,
                goal.version,
                {
                    "action": "driver_turn",
                    "progressed": goal.version > int(trigger.get("start_version", 0)),
                },
            )
            self._sync_ref(updated)
        except (GoalConflictError, GoalError, TypeError, ValueError):
            logger.debug("Goal {} changed while recording its driver turn", goal.id)

    async def _stop(self, goal: Goal, status: str, reason: str) -> None:
        updated = await asyncio.to_thread(
            self.store.set_status,
            goal.id,
            goal.version,
            status,
            reason,
        )
        self._sync_ref(updated)
        route = self._route(goal)
        if route is not None:
            label = "paused" if status == "waiting" else "stopped"
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=route["channel"],
                    chat_id=route["chat_id"],
                    content=f"Long-running Goal {label}: {reason}",
                )
            )

    def _sync_ref(self, goal: Goal) -> None:
        session = self.sessions.get_or_create(goal.session_key)
        ref = compact_ref(goal, self.workspace)
        if session.metadata.get(GOAL_STATE_KEY) == ref:
            return
        session.metadata[GOAL_STATE_KEY] = ref
        self.sessions.save(session)

    @staticmethod
    def _route(goal: Goal) -> dict[str, str] | None:
        route = goal.state.get("route") or {}
        channel = str(route.get("channel") or "").strip()
        chat_id = str(route.get("chat_id") or "").strip()
        if not channel and ":" in goal.session_key:
            channel, chat_id = goal.session_key.split(":", 1)
        return {"channel": channel, "chat_id": chat_id} if channel and chat_id else None
