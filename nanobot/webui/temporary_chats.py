"""Connection-owned Temporary Chat behavior for the WebUI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_SESSION_DISCARD,
    InboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.security.workspace_access import WorkspaceScope
from nanobot.session.manager import Session, SessionManager
from nanobot.webui.workspaces import WebUIWorkspaceController

_TEMPORARY_CHAT_DISABLED_TOOLS = frozenset({
    "create_goal",
    "update_goal",
    "spawn",
    "cron",
})
_TEMPORARY_CHAT_COMMANDS = frozenset({"/model", "/stop"})


class TemporaryChatError(ValueError):
    """A stable WebUI protocol error for a Temporary Chat operation."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class TemporaryChatMessagePolicy:
    """Server-owned message rules for one active Temporary Chat."""

    session_key: str
    workspace_scope: WorkspaceScope
    require_existing_session: bool = True
    hydrate_transcript: bool = False
    persist_transcript: bool = False


class WebUITemporaryChats:
    """Own Temporary Chat creation, policy, attachments, and disposal."""

    def __init__(
        self,
        *,
        bus: MessageBus,
        session_manager: SessionManager | None,
        workspaces: WebUIWorkspaceController,
        logger: Any,
        channel_name: str = "websocket",
    ) -> None:
        self._bus = bus
        self._sessions = session_manager
        self._workspaces = workspaces
        self._logger = logger
        self._channel_name = channel_name
        self._owners: dict[str, object] = {}
        self._owner_chat_ids: dict[object, set[str]] = {}
        # Keep active sessions alive if the bounded manager cache evicts them
        # between WebUI turns. SessionPolicy remains the authority below.
        self._active_sessions: dict[str, Session] = {}
        # Retain policy-derived tombstones until shutdown so late outbound
        # events cannot create a durable transcript after a chat is discarded.
        self._known_transient_chat_ids: set[str] = set()
        self._media_paths: dict[str, set[str]] = {}

    def _session_key(self, chat_id: str) -> str:
        return f"{self._channel_name}:{chat_id}"

    def _cached_session_is_transient(self, chat_id: str) -> bool:
        if self._sessions is None:
            return False
        session = self._sessions.get_cached(self._session_key(chat_id))
        return session is not None and not session.policy.persist

    def create(self, owner: object, *, trusted_webui: bool) -> str:
        """Create a server-identified chat owned by one authenticated WebUI connection."""
        if not trusted_webui:
            raise TemporaryChatError("access_denied")
        if self._sessions is None:
            raise TemporaryChatError("temporary_chat_unavailable")

        chat_id = str(uuid.uuid4())
        session = self._sessions.get_or_create_transient(
            self._session_key(chat_id),
            disabled_tools=_TEMPORARY_CHAT_DISABLED_TOOLS,
        )
        if session.policy.persist:
            raise RuntimeError("Temporary Chat must use a non-persistent session policy")
        self._owners[chat_id] = owner
        self._owner_chat_ids.setdefault(owner, set()).add(chat_id)
        self._active_sessions[chat_id] = session
        self._known_transient_chat_ids.add(chat_id)
        return chat_id

    def message_policy(
        self,
        owner: object,
        chat_id: str,
        content: str,
    ) -> TemporaryChatMessagePolicy | None:
        """Return Temporary Chat rules, or ``None`` for an ordinary chat."""
        if not self._cached_session_is_transient(chat_id):
            if chat_id in self._known_transient_chat_ids:
                raise TemporaryChatError("temporary_chat_unavailable")
            return None
        if self._owners.get(chat_id) is not owner or self._sessions is None:
            raise TemporaryChatError("temporary_chat_unavailable")

        session = self._sessions.get_cached(self._session_key(chat_id))
        if session is None:
            raise TemporaryChatError("temporary_chat_unavailable")

        command = content.strip().split(maxsplit=1)[0].lower() if content.strip() else ""
        if command.startswith("/") and command not in _TEMPORARY_CHAT_COMMANDS:
            raise TemporaryChatError("temporary_chat_command_rejected")

        return TemporaryChatMessagePolicy(
            session_key=self._session_key(chat_id),
            workspace_scope=self._workspaces.restricted_default_scope(),
        )

    def validate_attach(self, chat_id: str) -> None:
        """Reject attempts to recover a non-persistent session."""
        if not self._cached_session_is_transient(chat_id):
            if chat_id in self._known_transient_chat_ids:
                raise TemporaryChatError("temporary_chat_unavailable")
            return
        raise TemporaryChatError("temporary_chat_unavailable")

    def validate_workspace_update(self, chat_id: str) -> None:
        """Prevent non-persistent sessions from acquiring durable workspace state."""
        if self._cached_session_is_transient(chat_id):
            raise TemporaryChatError("temporary_chat_workspace_rejected")
        if chat_id in self._known_transient_chat_ids:
            raise TemporaryChatError("temporary_chat_unavailable")

    def register_media(self, owner: object, chat_id: str, paths: list[str]) -> None:
        if not paths:
            return
        if self._owners.get(chat_id) is not owner:
            raise TemporaryChatError("temporary_chat_unavailable")
        self._media_paths.setdefault(chat_id, set()).update(paths)

    def chat_ids_for_owner(self, owner: object) -> tuple[str, ...]:
        return tuple(self._owner_chat_ids.get(owner, ()))

    def owns(self, owner: object, chat_id: str) -> bool:
        return self._owners.get(chat_id) is owner

    def should_persist_transcript(self, chat_id: str) -> bool:
        """Apply the session policy and retain it for late events after disposal."""
        return (
            not self._cached_session_is_transient(chat_id)
            and chat_id not in self._known_transient_chat_ids
        )

    def _discard_media(self, chat_id: str) -> None:
        for raw_path in self._media_paths.pop(chat_id, set()):
            try:
                Path(raw_path).unlink(missing_ok=True)
            except OSError:
                self._logger.warning("failed to remove a temporary WebUI attachment")

    def _forget_owner(self, owner: object, chat_id: str) -> None:
        self._owners.pop(chat_id, None)
        chat_ids = self._owner_chat_ids.get(owner)
        if chat_ids is None:
            return
        chat_ids.discard(chat_id)
        if not chat_ids:
            self._owner_chat_ids.pop(owner, None)

    async def discard(self, owner: object, chat_id: str) -> None:
        """Forget one owned chat and cancel any active work through the message bus."""
        if (
            not self._cached_session_is_transient(chat_id)
            or self._owners.get(chat_id) is not owner
        ):
            raise TemporaryChatError("temporary_chat_unavailable")

        session_key = self._session_key(chat_id)
        self._forget_owner(owner, chat_id)
        self._active_sessions.pop(chat_id, None)
        self._discard_media(chat_id)
        if self._sessions is not None:
            self._sessions.invalidate(session_key)
        await self._bus.publish_inbound(
            InboundMessage(
                channel=self._channel_name,
                sender_id="webui",
                chat_id=chat_id,
                content="",
                metadata={
                    INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_SESSION_DISCARD,
                },
                session_key_override=session_key,
            )
        )

    def close(self) -> None:
        """Release process-local resources during gateway shutdown."""
        for chat_id in tuple(self._owners):
            self._discard_media(chat_id)
            if self._sessions is not None:
                self._sessions.invalidate(self._session_key(chat_id))
        self._owners.clear()
        self._owner_chat_ids.clear()
        self._active_sessions.clear()
        self._known_transient_chat_ids.clear()
