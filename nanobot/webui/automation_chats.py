"""Resolve authenticated WebUI choices to existing, same-scope session routes."""

from collections import Counter
from dataclasses import dataclass, replace
from typing import Any, cast

from nanobot.channels.notification_routes import notification_metadata
from nanobot.cron.binding import CronBinding
from nanobot.cron.types import CronJob
from nanobot.session.manager import (
    SessionManager,
    _metadata_title,  # pyright: ignore[reportPrivateUsage]
)
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.utils.helpers import truncate_text
from nanobot.webui.session_identity import is_webui_session_key
from nanobot.webui.workspaces import WebUIWorkspaceController


@dataclass(frozen=True)
class AutomationChat:
    id: str
    title: str
    binding: CronBinding
    handle: str
    available: bool

    def public_payload(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "channel": self.binding.channel,
                **({"unavailable": True} if not self.available else {})}


def automation_chats(
    job: CronJob, sessions: SessionManager, workspaces: WebUIWorkspaceController,
    channel_status: dict[str, Any],
) -> list[AutomationChat]:
    """Do not infer an external address by splitting an opaque session key.

    External chats must have a route captured by a real user turn. Only
    address metadata is copied; sender, turn owner and old workspace policy
    must never travel from the source job to the selected chat.
    """
    if (not job.payload.session_key or not job.payload.origin_channel
            or not job.payload.session_key.startswith(f"{job.payload.origin_channel}:")
            or job.payload.origin_channel in {"cli", "system"}):
        return []
    source = workspaces.automation_scope(
        job.payload.session_key or "", job.payload.origin_channel or "",
        job.payload.origin_metadata,
    )
    result: list[AutomationChat] = []
    previews = {row["key"]: row.get("preview", "") for row in sessions.list_sessions()}
    for handle in SessionHandleResolver(sessions).list_all():
        key = handle.session_key
        data = sessions.read_session_metadata(key)
        metadata: dict[str, Any] = data.get("metadata", {}) if data else {}
        if is_webui_session_key(key):
            channel, chat_id = key.split(":", 1)
            route_metadata = {}
        else:
            route = metadata.get("_compaction_route")
            if not isinstance(route, dict):
                continue
            route = cast(dict[str, Any], route)
            channel, chat_id = route.get("channel"), route.get("chat_id")
            if (not isinstance(channel, str) or not isinstance(chat_id, str)
                    or not chat_id or not key.startswith(f"{channel}:")
                    or channel in {"cli", "system", "websocket"}):
                continue
            route_metadata = notification_metadata(channel, route.get("metadata", {}))
        available = channel == "websocket" or bool(channel_status.get(channel, {}).get("running"))
        if not available and key != job.payload.session_key:
            continue
        target = workspaces.automation_scope(key, channel, {})
        if source.metadata() != target.metadata():
            continue
        result.append(AutomationChat(
            id=handle.id,
            title=(_metadata_title(metadata)
                   or truncate_text(" ".join(previews.get(key, "").split()), 60)
                   or f"@{handle.name}"),
            binding=CronBinding(key, channel, chat_id, route_metadata),
            handle=handle.name,
            available=available,
        ))
    names = Counter(chat.title for chat in result)
    return [replace(chat, title=f"{chat.title} · @{chat.handle}")
            if names[chat.title] > 1 else chat for chat in result]
