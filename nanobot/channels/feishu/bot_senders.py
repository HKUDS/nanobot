"""Allowlist and hop guard for Feishu messages authored by other bots.

Feishu pushes group events for bot authors when the app holds the
``im:message.group_at_msg.include_bot:readonly`` scope, and such a message still has to
mention the receiving bot (the platform never delivers unmentioned group messages).
nanobot drops every bot-authored message by default, because two bots mentioning each
other would otherwise reply back and forth without end.

Two opt-in knobs make multi-bot groups usable:

* ``allowBotSenders`` -- open_ids of peer bots that may trigger this bot. Empty (the
  default) keeps the drop-everything behaviour; ``["*"]`` allows any bot.
* ``botHopLimit`` -- how many consecutive bot-triggered turns one chat may have before
  the bot stops answering bot messages in it. A message from a human resets the counter,
  so a human stays in control of how far two bots take a conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def bot_sender_allowed(open_id: str, allow: list[str] | tuple[str, ...] | None) -> bool:
    """Return True when a bot author is listed in ``allow`` (``"*"`` allows any bot)."""
    entries = {
        entry.strip() for entry in (allow or []) if isinstance(entry, str) and entry.strip()
    }
    if not entries:
        return False
    return "*" in entries or (bool(open_id) and open_id in entries)


@dataclass
class BotHopGuard:
    """Track per-chat bot hops and remember which peer to mention on the reply."""

    limit: int = 2
    _hops: dict[str, int] = field(default_factory=dict)
    _peers: dict[str, str] = field(default_factory=dict)

    def accept(self, chat_id: str, open_id: str) -> bool:
        """Record an allowed bot message. False means the hop limit is reached."""
        if self.limit > 0 and self._hops.get(chat_id, 0) >= self.limit:
            return False
        self._hops[chat_id] = self._hops.get(chat_id, 0) + 1
        self._peers[chat_id] = open_id
        return True

    def human_message(self, chat_id: str) -> None:
        """Reset ``chat_id`` -- a human reopens the bot-to-bot budget."""
        self._hops[chat_id] = 0
        self._peers.pop(chat_id, None)

    def pending_peer(self, chat_id: str) -> str | None:
        return self._peers.get(chat_id)

    def consume_peer(self, chat_id: str) -> str | None:
        """Return and clear the peer that triggered the turn being answered now."""
        return self._peers.pop(chat_id, None)


__all__ = ["BotHopGuard", "bot_sender_allowed"]
