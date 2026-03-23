"""Conversation registry for tracking active chat targets.

Maintains a persistent record of conversations that the bot has interacted
with, enabling proactive messaging to know *where* to send messages.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger


@dataclass
class ConversationTarget:
    """A registered conversation target for proactive messages."""

    channel: str
    chat_id: str
    last_activity: float = 0.0  # time.time() of last user message
    proactive_count_today: int = 0  # daily rate limit tracker
    last_proactive_date: str = ""  # ISO date string; resets count on new day

    @property
    def key(self) -> str:
        return f"{self.channel}:{self.chat_id}"

    def reset_daily_count_if_needed(self) -> None:
        """Reset proactive_count_today if the date has changed."""
        today = date.today().isoformat()
        if self.last_proactive_date != today:
            self.proactive_count_today = 0
            self.last_proactive_date = today


class ConversationRegistry:
    """Tracks active conversations for proactive messaging.

    Persists to ``{workspace}/proactive/targets.json`` so state survives
    restarts.
    """

    _MAX_TARGETS = 200  # Prune beyond this to avoid unbounded growth

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._targets: dict[str, ConversationTarget] = {}
        self._store_path = workspace / "proactive" / "targets.json"

    def record_activity(self, channel: str, chat_id: str) -> None:
        """Record user activity on a conversation (called from _process_message)."""
        if channel in {"cli", "system"}:
            return  # Don't track internal channels
        key = f"{channel}:{chat_id}"
        if key in self._targets:
            self._targets[key].last_activity = time.time()
        else:
            self._targets[key] = ConversationTarget(
                channel=channel,
                chat_id=chat_id,
                last_activity=time.time(),
            )
        # Auto-save on activity to keep state fresh
        self._prune_stale()
        self.save()

    def get_active_targets(self, max_idle_hours: int = 24) -> list[ConversationTarget]:
        """Get targets with recent activity within max_idle_hours."""
        cutoff = time.time() - max_idle_hours * 3600
        active = []
        for target in self._targets.values():
            if target.last_activity >= cutoff:
                target.reset_daily_count_if_needed()
                active.append(target)
        return sorted(active, key=lambda t: t.last_activity, reverse=True)

    def increment_proactive(self, channel: str, chat_id: str) -> None:
        """Record that a proactive message was sent to this target."""
        key = f"{channel}:{chat_id}"
        target = self._targets.get(key)
        if target:
            target.reset_daily_count_if_needed()
            target.proactive_count_today += 1
            target.last_proactive_date = date.today().isoformat()
            self.save()

    def _prune_stale(self) -> None:
        """Remove oldest targets if we exceed _MAX_TARGETS."""
        if len(self._targets) <= self._MAX_TARGETS:
            return
        sorted_targets = sorted(
            self._targets.items(), key=lambda kv: kv[1].last_activity
        )
        while len(sorted_targets) > self._MAX_TARGETS:
            key, _ = sorted_targets.pop(0)
            del self._targets[key]

    def load(self) -> None:
        """Load targets from disk."""
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for item in data.get("targets", []):
                target = ConversationTarget(
                    channel=item["channel"],
                    chat_id=item["chat_id"],
                    last_activity=item.get("last_activity", 0.0),
                    proactive_count_today=item.get("proactive_count_today", 0),
                    last_proactive_date=item.get("last_proactive_date", ""),
                )
                self._targets[target.key] = target
            logger.info("Proactive registry: loaded {} targets", len(self._targets))
        except Exception as e:
            logger.warning("Failed to load proactive registry: {}", e)

    def save(self) -> None:
        """Save targets to disk."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "targets": [asdict(t) for t in self._targets.values()],
        }
        self._store_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
