"""WebUI session read models exposed to interactive clients."""

from __future__ import annotations

from typing import Any, Protocol, cast

from loguru import logger as default_logger

from nanobot.providers.base import LLMUsage
from nanobot.session.goal_state import goal_state_ws_blob
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.session.recovery import recovery_state_from_metadata
from nanobot.session.webui_turns import websocket_turn_id, websocket_turn_wall_started_at


class SessionMetadataReader(Protocol):
    """Narrow persisted-session dependency used by WebUI projections."""

    def read_session_metadata(self, key: str) -> dict[str, Any] | None: ...


class WebUISessionProjection:
    """Project persisted session metadata into stable WebUI protocol fields."""

    def __init__(
        self,
        sessions: SessionMetadataReader | None,
        *,
        log: Any = default_logger,
    ) -> None:
        self._sessions = sessions
        self._log = log

    def attach_fields(self, session_key: str) -> dict[str, Any]:
        """Return the session runtime facts sent with an attach handshake."""
        if self._sessions is None:
            return {}
        snapshot = self._sessions.read_session_metadata(session_key)
        raw_metadata = snapshot.get("metadata") if snapshot is not None else None
        metadata = cast(dict[str, object], raw_metadata) if isinstance(raw_metadata, dict) else None

        fields: dict[str, Any] = {}
        try:
            fields["model_preset"] = model_preset_from_metadata(metadata)
        except ValueError:
            self._log.warning("ignoring invalid model preset metadata for session_key={}", session_key)
            fields["model_preset"] = None
        if metadata is None:
            return fields

        recovery_state = recovery_state_from_metadata(metadata)
        if recovery_state is not None:
            fields["recovery_state"] = recovery_state
        usage = LLMUsage.from_dict(metadata.get("_last_usage"))
        if usage is not None:
            fields["usage"] = usage.to_turn_dict()
        return fields

    def hydration_events(self, session_key: str, chat_id: str) -> tuple[dict[str, Any], ...]:
        """Return reconnect events for durable and same-process session state."""
        events: list[dict[str, Any]] = []
        goal_state = self.persisted_goal_state(session_key)
        if goal_state is not None:
            events.append(
                {
                    "event": "goal_state",
                    "chat_id": chat_id,
                    "goal_state": goal_state,
                }
            )
        active_turn = self.active_turn_status(chat_id)
        if active_turn is not None:
            started_at, turn_id = active_turn
            event: dict[str, Any] = {
                "event": "goal_status",
                "chat_id": chat_id,
                "status": "running",
                "started_at": started_at,
            }
            if turn_id is not None:
                event["turn_id"] = turn_id
            events.append(event)
        return tuple(events)

    def persisted_goal_state(self, session_key: str) -> dict[str, Any] | None:
        """Return an actionable persisted goal state for reconnect hydration."""
        if self._sessions is None:
            return None
        snapshot = self._sessions.read_session_metadata(session_key)
        raw_metadata = snapshot.get("metadata") if snapshot is not None else None
        metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
        goal_state = goal_state_ws_blob(metadata)
        if not goal_state.get("active") and goal_state.get("status") != "blocked":
            return None
        return goal_state

    @staticmethod
    def active_turn_status(chat_id: str) -> tuple[float, str | None] | None:
        """Return same-process running-turn state for reconnect hydration."""
        started_at = websocket_turn_wall_started_at(chat_id)
        if started_at is None:
            return None
        return started_at, websocket_turn_id(chat_id)
