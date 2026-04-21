"""PostHog analytics hook for nanobot's agent loop.

Fires: message_sent, agent_responded, feedback_submitted, user_onboarded,
household_member_added.

All calls are fire-and-forget. Classification runs as an async background task
so it never blocks the user response.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from nanobot.analytics.feedback import detect_feedback
from nanobot.analytics.identity import get_distinct_id, get_household_id

logger = logging.getLogger(__name__)

# How many seconds between messages to count as a followup
_FOLLOWUP_WINDOW_S = 300  # 5 minutes


class AnalyticsHook:
    """Non-blocking PostHog instrumentation wired into AgentLoop._process_message."""

    def __init__(self) -> None:
        self._client: Any = None
        self._initialized = False
        # Track last message timestamp per distinct_id for is_followup
        self._last_message: dict[str, float] = {}
        # Track seen distinct_ids for user_onboarded / household_member_added
        self._seen_users: set[str] = set()
        self._first_user_ts: float | None = None
        self._household_id = ""

    def _ensure_init(self) -> bool:
        """Lazy-init PostHog client. Returns True if client is live."""
        if self._initialized:
            return self._client is not None
        self._initialized = True
        api_key = os.environ.get("POSTHOG_API_KEY", "").strip()
        host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com").strip()
        self._household_id = get_household_id()
        if not api_key:
            logger.debug("POSTHOG_API_KEY not set — analytics disabled")
            return False
        try:
            from posthog import Posthog
            self._client = Posthog(api_key, host=host)
            atexit.register(self._client.shutdown)
            logger.info("PostHog analytics initialized (host={})", host)
            return True
        except ImportError:
            logger.warning("posthog package not installed — analytics disabled")
            return False

    def _base_props(self) -> dict:
        hid = self._household_id or get_household_id()
        return {"household_id": hid} if hid else {}

    def on_message_received(
        self,
        *,
        channel: str,
        sender_id: str,
        content: str,
        media: list[str],
        timestamp: datetime,
        is_guest: bool,
    ) -> dict[str, Any]:
        """Call at the start of _process_message. Returns context dict for on_response_sent."""
        return {
            "channel": channel,
            "sender_id": sender_id,
            "content": content,
            "media": media,
            "timestamp": timestamp,
            "is_guest": is_guest,
            "inbound_time": time.monotonic(),
        }

    async def on_response_sent(
        self,
        ctx: dict[str, Any],
        *,
        response_content: str | None,
        tools_used: set[str],
        escalation_triggered: bool = False,
        schedule_background: Any = None,
    ) -> None:
        """Call after the response OutboundMessage is built.

        Fires agent_responded immediately. Fires message_sent and feedback_submitted
        as background tasks (classification is async).
        """
        if not self._ensure_init():
            return

        channel = ctx["channel"]
        sender_id = ctx["sender_id"]
        content = ctx["content"]
        distinct_id = get_distinct_id(sender_id, channel)
        now = time.monotonic()
        latency_ms = int((now - ctx["inbound_time"]) * 1000)

        # ── agent_responded (immediate) ──────────────────────────────────
        self._client.capture(distinct_id, "agent_responded", {
            **self._base_props(),
            "channel": channel,
            "latency_ms": latency_ms,
            "tool_calls_count": len(tools_used),
            "tools_used": sorted(tools_used),
            "escalation_triggered": escalation_triggered,
            "response_length": len(response_content) if response_content else 0,
        })

        # ── feedback_submitted (immediate, cheap check) ──────────────────
        fb = detect_feedback(content)
        if fb:
            self._client.capture(distinct_id, "feedback_submitted", {
                **self._base_props(),
                "sentiment": fb.sentiment,
                "trigger": fb.trigger,
            })

        # ── user_onboarded / household_member_added (first-seen check) ───
        self._maybe_fire_onboarding(distinct_id, channel)

        # ── message_sent (background — waits for classification) ─────────
        is_followup = self._check_followup(distinct_id, now)

        coro = self._fire_message_sent(
            distinct_id=distinct_id,
            channel=channel,
            content=content,
            media=ctx["media"],
            is_followup=is_followup,
        )
        if schedule_background:
            schedule_background(coro)
        else:
            asyncio.create_task(coro)

    def _check_followup(self, distinct_id: str, now: float) -> bool:
        last = self._last_message.get(distinct_id)
        self._last_message[distinct_id] = now
        if last is None:
            return False
        return (now - last) < _FOLLOWUP_WINDOW_S

    def _maybe_fire_onboarding(self, distinct_id: str, channel: str) -> None:
        """Fire user_onboarded on first message from a new distinct_id."""
        if distinct_id in self._seen_users:
            return
        is_new_household = len(self._seen_users) == 0
        self._seen_users.add(distinct_id)

        if is_new_household:
            self._first_user_ts = time.time()

        # Identify person + set properties
        self._client.identify(distinct_id, {
            "household_id": self._household_id,
            "channel_first_seen": channel,
            "is_primary": is_new_household,
            "signup_source": "friends_launch",
        })

        self._client.capture(distinct_id, "user_onboarded", {
            **self._base_props(),
            "channel": channel,
            "is_new_household": is_new_household,
            "signup_source": "friends_launch",
        })

        if not is_new_household:
            days = 0
            if self._first_user_ts:
                days = int((time.time() - self._first_user_ts) / 86400)
            self._client.capture(distinct_id, "household_member_added", {
                **self._base_props(),
                "member_count_after": len(self._seen_users),
                "days_since_household_created": days,
            })

        # Group identify on every new user
        if self._household_id:
            self._client.group_identify("household", self._household_id, {})

    async def _fire_message_sent(
        self,
        *,
        distinct_id: str,
        channel: str,
        content: str,
        media: list[str],
        is_followup: bool,
    ) -> None:
        """Classify, then fire message_sent."""
        from nanobot.analytics.classify import classify_message_async

        tag = await classify_message_async(content)
        self._client.capture(distinct_id, "message_sent", {
            **self._base_props(),
            "channel": channel,
            "message_length": len(content),
            "has_attachment": bool(media),
            "use_case_tag": tag,
            "is_followup": is_followup,
        })

        # Group identify on every message_sent
        if self._household_id:
            self._client.group_identify("household", self._household_id, {})


# Module-level singleton
_hook: AnalyticsHook | None = None


def get_analytics_hook() -> AnalyticsHook:
    """Return the module-level analytics hook (lazy-created)."""
    global _hook
    if _hook is None:
        _hook = AnalyticsHook()
    return _hook
