"""WebUI session read models exposed to interactive clients."""

from __future__ import annotations

from typing import Any, Protocol, cast

from loguru import logger as default_logger

from nanobot.providers.base import LLMUsage
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.session.recovery import recovery_state_from_metadata


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
