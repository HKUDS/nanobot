"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus

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
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.

    Phase 2 (execution): publishes an InboundMessage to the bus with
    ``_source: "heartbeat"`` metadata. The agent processes it and applies
    post-run evaluation to decide whether to notify the user.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        bus: MessageBus,
        pick_target: Callable[[], tuple[str, str]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.bus = bus
        self.pick_target = pick_target or (lambda: ("cli", "heartbeat"))
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

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        """
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

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

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            channel, chat_id = self.pick_target()
            logger.info("Heartbeat: tasks found, publishing to bus ({}:{})...", channel, chat_id)
            msg = InboundMessage(
                channel=channel,
                sender_id="heartbeat",
                chat_id=chat_id,
                content=tasks,
                metadata={"_source": "heartbeat", "_task_context": tasks},
            )
            await self.bus.publish_inbound(msg)

        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return
        action, tasks = await self._decide(content)
        if action != "run":
            return
        channel, chat_id = self.pick_target()
        msg = InboundMessage(
            channel=channel,
            sender_id="heartbeat",
            chat_id=chat_id,
            content=tasks,
            metadata={"_source": "heartbeat", "_task_context": tasks},
        )
        await self.bus.publish_inbound(msg)
