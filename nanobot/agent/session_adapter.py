"""SessionAdapter interface for channel-specific session behavior."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.bus.events import InboundMessage
    from nanobot.session.manager import Session, SessionManager


class SessionAdapter(ABC):
    """
    Hook interface for channels to customize session behavior.

    Called by AgentLoop during message processing to allow channels
    to implement custom session initialization and finalization logic.
    """

    async def on_session_load(
        self,
        session_manager: "SessionManager",
        inbound_msg: "InboundMessage",
        session: "Session",
    ) -> None:
        """
        Called after session is loaded, before message processing.

        Use this to:
        - Initialize empty sessions from parent sessions
        - Load related context
        - Set up session state

        Args:
            session_manager: SessionManager instance for creating/loading sessions
            inbound_msg: The inbound message being processed
            session: The loaded session (may be empty)
        """
        pass

    async def on_turn_complete(
        self,
        session_manager: "SessionManager",
        inbound_msg: "InboundMessage",
        session: "Session",
        new_messages: list[dict],
        response_metadata: dict,
    ) -> dict:
        """
        Called after turn is saved, before sending response.

        Use this to:
        - Tag messages in session for routing/filtering
        - Update response metadata for platform-specific routing
        - Save to multiple sessions if needed

        Args:
            session_manager: SessionManager instance
            inbound_msg: The original inbound message
            session: The session with newly added messages
            new_messages: List of messages added this turn
            response_metadata: Metadata dict to be sent with response

        Returns:
            Updated response metadata dict
        """
        return response_metadata
