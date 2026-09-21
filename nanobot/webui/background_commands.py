"""Owner-scoped, uncached WebUI observation of yielded exec commands."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.temporary_chats import TemporaryChatError

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from nanobot.webui.gateway_services import GatewayServices


class BackgroundCommandError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


async def background_command(
    gateway: GatewayServices, connection: ServerConnection, action: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Called only after transport authentication; never invoke an arbitrary process."""
    chat_id = payload.get("chat_id")
    if not is_valid_webui_chat_id(chat_id) or gateway.session_manager is None:
        raise BackgroundCommandError(404, "session_unavailable")
    sessions = gateway.session_manager
    key = webui_session_key(chat_id)

    async def check_owner() -> None:
        try:
            gateway.temporary_chats.message_policy(connection, chat_id, "")
        except TemporaryChatError as exc:
            raise BackgroundCommandError(404, "session_unavailable") from exc
        if sessions.get_cached(key) is None:
            saved = await asyncio.to_thread(sessions.read_session_metadata, key)
            if saved is None:
                raise BackgroundCommandError(404, "session_unavailable")

    await check_owner()
    manager = gateway.exec_sessions
    if manager is None:
        raise BackgroundCommandError(503, "command_observation_unavailable")
    if action == "background.list":
        result: dict[str, object] = {"commands": await manager.inspect_commands(key)}
    else:
        session_id = payload.get("session_id")
        after = payload.get("after", 0)
        if (not isinstance(session_id, str) or re.fullmatch(r"[0-9a-f]{12}", session_id) is None
                or type(after) is not int or not 0 <= after <= 2**53 - 1):
            raise BackgroundCommandError(400, "invalid_command_request")
        try:
            result = {"command": await manager.inspect_output(
                key, session_id, after, stop=action == "background.stop")}
        except KeyError as exc:
            raise BackgroundCommandError(404, "command_unavailable") from exc
        except (OSError, RuntimeError) as exc:
            raise BackgroundCommandError(500, "command_stop_failed") from exc
    # A stop awaits process-tree cleanup; discard a result whose temporary owner left meanwhile.
    await check_owner()
    return result
