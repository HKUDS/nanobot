"""Proactive messaging service — periodic background engagement.

Follows the two-phase pattern established by ``HeartbeatService``:

Phase 1 (evaluate): Lightweight LLM call to decide if the bot should
proactively reach out to a conversation target.

Phase 2 (compose & deliver): Full agent loop to compose and deliver the
proactive message.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from nanobot.proactive.registry import ConversationRegistry, ConversationTarget

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_EVALUATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "proactive_decision",
            "description": "Decide whether to proactively message the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["send", "skip"],
                        "description": (
                            "send = proactively reach out to the user; "
                            "skip = nothing worth saying right now"
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "The proactive message to send (only when action is 'send'). "
                            "Should be natural and conversational, not forced."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief reason for the decision",
                    },
                },
                "required": ["action"],
            },
        },
    }
]

_SYSTEM_PROMPT = (
    "You are a proactive engagement evaluator for a chat assistant. "
    "Given context about the current time, a user's last activity, and "
    "recent conversation history, decide whether the assistant should "
    "proactively send a message.\n\n"
    "Good reasons to send:\n"
    "- It's a natural time for a greeting (morning, after work hours)\n"
    "- There's a pending topic from a previous conversation worth revisiting\n"
    "- The user asked the assistant to follow up on something\n"
    "- Enough time has passed that a check-in feels natural\n"
    "- There's a relevant external context (holiday, notable date)\n\n"
    "Bad reasons to send:\n"
    "- Nothing meaningful to say (don't send generic 'how are you' messages)\n"
    "- The user recently ended a conversation naturally\n"
    "- It would feel intrusive or spammy\n"
    "- It's quiet hours (late night / very early morning)\n\n"
    "If you decide to send, craft a brief, natural message. It should feel "
    "like a thoughtful friend reaching out, not a marketing notification."
)


class ProactiveService:
    """Periodic background service for proactive user engagement.

    Phase 1 (evaluate): Lightweight LLM call per active conversation target
    to decide whether to reach out.

    Phase 2 (compose & deliver): Delegates to ``on_execute`` / ``on_notify``
    callbacks (same pattern as HeartbeatService).
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        registry: ConversationRegistry,
        on_execute: Callable[[str, str, str], Coroutine[Any, Any, str | None]] | None = None,
        on_notify: Callable[[str, str, str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 3600,
        enabled: bool = False,
        max_per_day: int = 3,
        quiet_hours_start: int = 22,
        quiet_hours_end: int = 8,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.registry = registry
        self.on_execute = on_execute  # (message, channel, chat_id) -> response
        self.on_notify = on_notify  # (response, channel, chat_id) -> None
        self.interval_s = interval_s
        self.enabled = enabled
        self._max_daily = max_per_day
        self._quiet_start = quiet_hours_start
        self._quiet_end = quiet_hours_end
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the proactive service."""
        if not self.enabled:
            logger.info("Proactive messaging disabled")
            return
        if self._running:
            logger.warning("Proactive service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Proactive service started (every {}s, max {}/day, quiet {}-{})",
            self.interval_s, self._max_daily, self._quiet_start, self._quiet_end,
        )

    def stop(self) -> None:
        """Stop the proactive service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def _in_quiet_hours(self) -> bool:
        """Check if current local time is within quiet hours."""
        hour = datetime.now().hour
        if self._quiet_start > self._quiet_end:
            # Wraps midnight, e.g., 22-8
            return hour >= self._quiet_start or hour < self._quiet_end
        else:
            return self._quiet_start <= hour < self._quiet_end

    async def _run_loop(self) -> None:
        """Main proactive loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Proactive service error: {}", e)

    async def _tick(self) -> None:
        """Execute a single tick — evaluate all active targets."""
        if self._in_quiet_hours():
            logger.debug("Proactive: in quiet hours, skipping")
            return

        targets = self.registry.get_active_targets()
        if not targets:
            logger.debug("Proactive: no active targets")
            return

        for target in targets:
            if target.proactive_count_today >= self._max_daily:
                continue
            try:
                await self._evaluate_and_act(target)
            except Exception as e:
                logger.error(
                    "Proactive: error evaluating {}:{}: {}",
                    target.channel, target.chat_id, e,
                )

    async def _evaluate_and_act(self, target: ConversationTarget) -> None:
        """Evaluate a single target and optionally send a proactive message."""
        from nanobot.utils.helpers import current_time_str

        # Build context for evaluation
        idle_hours = (asyncio.get_event_loop().time() - target.last_activity) / 3600
        context = (
            f"Current time: {current_time_str()}\n"
            f"User's channel: {target.channel}\n"
            f"User last active: {idle_hours:.1f} hours ago\n"
            f"Proactive messages sent today: {target.proactive_count_today}\n"
        )

        # Phase 1: evaluate
        try:
            response = await self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                tools=_EVALUATE_TOOL,
                model=self.model,
                max_tokens=512,
                temperature=0.7,
            )
        except Exception:
            logger.exception("Proactive: LLM evaluation failed for {}", target.key)
            return

        if not response.has_tool_calls:
            logger.debug("Proactive: no tool call for {}, skipping", target.key)
            return

        args = response.tool_calls[0].arguments
        action = args.get("action", "skip")
        message = args.get("message", "")
        reason = args.get("reason", "")

        if action != "send" or not message:
            logger.info("Proactive: skip {} ({})", target.key, reason)
            return

        logger.info("Proactive: sending to {} ({})", target.key, reason)

        # Phase 2: compose and deliver
        if self.on_execute:
            result = await self.on_execute(message, target.channel, target.chat_id)
            if result and self.on_notify:
                await self.on_notify(result, target.channel, target.chat_id)
                self.registry.increment_proactive(target.channel, target.chat_id)
