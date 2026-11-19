"""Project shared channel conversations from committed model messages, not display facts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from nanobot.bus.events import INBOUND_META_TURN_ID
from nanobot.runtime_context import public_history_message
from nanobot.security.workspace_access import WorkspaceScope
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.keys import is_internal_session
from nanobot.session.manager import (
    SessionManager,
    _sanitize_assistant_replay_text,  # pyright: ignore[reportPrivateUsage]
)
from nanobot.utils.helpers import strip_think
from nanobot.webui.file_preview import WebUIFilePreviewError, resolve_file_path
from nanobot.webui.media_gateway import WebUIMediaGateway
from nanobot.webui.session_identity import channel_session_title, entry_channel_title
from nanobot.webui.transcript import (
    _WEBUI_REPLAY_IDENTITY_KEY,  # pyright: ignore[reportPrivateUsage]
    WEBUI_TRANSCRIPT_SCHEMA_VERSION,
    PromptSummary,
    _client_projection_event,  # pyright: ignore[reportPrivateUsage]
    _encode_page_cursor,  # pyright: ignore[reportPrivateUsage]
    _prompt_summary,  # pyright: ignore[reportPrivateUsage]
    _session_assistant_event,  # pyright: ignore[reportPrivateUsage]
    _session_user_event,  # pyright: ignore[reportPrivateUsage]
    decode_transcript_cursor,
    rewrite_local_markdown_images,
)

_PROJECTION_VERSION = 2
_DEFAULT_PAGE_LIMIT = 160
_MAX_PAGE_LIMIT = 1000
_MAX_PAGE_TEXT_CHARS = 4 * 1024 * 1024
_MAX_PROMPTS = 1000
_MAX_TOOL_CALLS_PER_ROUND = 64
_HISTORY_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,256}")
_TOOL_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
_WEB_TURN_RE = re.compile(r"user:([A-Za-z0-9._:-]{1,128})")
_IMAGE_BREADCRUMB_RE = re.compile(r"^\[image: (?:[/~]|[A-Za-z]:[\\/])[^\]\n]+\]\s*$")

_MessageStream = Iterator[tuple[int, dict[str, Any]]]


def external_session_title(key: str) -> str | None:
    return None if is_internal_session(key) else channel_session_title(key)


def has_public_channel_history(sessions: SessionManager, key: str) -> bool:
    if external_session_title(key) is None:
        return False
    header = sessions.read_history_header(key)
    return header is not None and sessions.types.public_history(header["metadata"])


@dataclass(frozen=True, slots=True)
class ChannelHistoryPage:
    limit: int
    before: int | None
    after: int | None

    @classmethod
    def from_query(
        cls, limit: str | None, before: str | None, after: str | None, direction: str | None,
    ) -> ChannelHistoryPage:
        if direction not in (None, "latest"):
            raise ValueError("invalid direction")
        if after is not None and (before is not None or direction is not None):
            raise ValueError("invalid navigation cursor")
        try:
            size = int(limit) if limit and limit.strip() else _DEFAULT_PAGE_LIMIT
        except ValueError as exc:
            raise ValueError("invalid limit") from exc
        return cls(max(1, min(size, _MAX_PAGE_LIMIT)), _cursor_index(before), _cursor_index(after))


def _cursor_index(value: str | None) -> int | None:
    if value is None:
        return None
    cursor = decode_transcript_cursor(value) if len(value) <= 128 else None
    if cursor is None or cursor.position != 0:
        raise ValueError("invalid navigation cursor")
    return cursor.turn


@dataclass(slots=True)
class ChannelHistoryResult:
    revision: str
    # An authorized matching ETag does not need a message scan.
    data: dict[str, Any] | None = None


def read_channel_history(
    sessions: SessionManager,
    key: str,
    *,
    variant: object,
    not_modified: Callable[[str], bool],
    project: Callable[[str, _MessageStream], dict[str, Any]],
) -> ChannelHistoryResult | None:
    def read() -> ChannelHistoryResult | None:
        if not has_public_channel_history(sessions, key):
            return None
        version = sessions.read_session_version(key)
        assert version is not None  # Same committed snapshot as the visibility check.
        # Invalidate cached projections after a display change even if the history is unchanged.
        identity = [_PROJECTION_VERSION, key, version, variant]
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        if not_modified(digest):
            return ChannelHistoryResult(digest)
        data = sessions.project_session_messages(key, lambda header, messages: project(header["generation"], messages))
        assert data is not None
        return ChannelHistoryResult(digest, data)

    return sessions.read_consistently(read)


@dataclass(frozen=True, slots=True)
class ChannelHistoryMedia:
    gateway: WebUIMediaGateway
    # Replay signs the alias so serving can distinguish it from live links
    # explicitly signed for an authenticated composer using the full key.
    chat_id: str
    scope: WorkspaceScope

    def attachments(self, paths: list[str], _local_paths: list[str] | None = None) -> list[dict[str, Any]]:
        allowed: list[str] = []
        borrowed: list[str] = []
        for raw in paths:
            try:
                path = resolve_file_path(raw, scope=self.scope, literal=True)
            except (RuntimeError, ValueError, WebUIFilePreviewError):
                continue
            resolved = str(path)
            allowed.append(resolved)
            if path.is_relative_to(self.scope.project_path):
                borrowed.append(resolved)
        return self.gateway.augment_transcript_user_media(allowed, borrowed, session_key=self.chat_id)

    def assistant_text(self, text: str) -> str:
        try:
            return rewrite_local_markdown_images(
                text, workspace_path=self.scope.project_path,
                sign_path=lambda path: {"url": self.gateway.local_attachment_url(str(path), session_key=self.chat_id)},
            )
        except (OSError, RuntimeError, ValueError):
            # A malformed URL or an unresolvable local path stays ordinary text.
            return text


def _history_id(raw: object) -> str | None:
    return raw if isinstance(raw, str) and _HISTORY_ID_RE.fullmatch(raw) else None


def _web_turn(input_id: str) -> str | None:
    match = _WEB_TURN_RE.fullmatch(input_id)
    return match[1] if match else None


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in cast(list[object], content):
        if not isinstance(block, dict):
            continue
        data = cast(dict[str, object], block)
        if data.get("type") == "text" and isinstance(text := data.get("text"), str):
            parts.append(text)
    return "\n".join(parts)


def _recorded_tool_events(calls: object, finished_tools: Collection[str]) -> list[dict[str, str]]:
    if not finished_tools or not isinstance(calls, list):
        return []
    events: list[dict[str, str]] = []
    for value in cast(list[object], calls)[:_MAX_TOOL_CALLS_PER_ROUND]:
        if not isinstance(value, dict):
            continue
        call = cast(dict[str, object], value)
        call_id = _history_id(call.get("id"))
        function = call.get("function")
        if call_id is None or call_id not in finished_tools or not isinstance(function, dict):
            continue
        name = cast(dict[str, object], function).get("name")
        if isinstance(name, str) and _TOOL_NAME_RE.fullmatch(name):
            # A result was recorded, but canonical history does not retain its status.
            # Never replay arguments, outputs, or provider-specific fields.
            events.append({"name": name, "call_id": call_id, "phase": "end"})
    return events


def _annotate_assistant(row: dict[str, Any], message: dict[str, Any]) -> None:
    if isinstance(refs := message.get("response_input_ids"), list):
        input_ids = list(dict.fromkeys(
            input_id for value in cast(list[object], refs) if (input_id := _history_id(value)) is not None
        ))
        row["response_input_ids"] = input_ids
        web_turns = [turn for ref in input_ids if (turn := _web_turn(ref)) is not None]
        if len(web_turns) == 1:
            row.update(turn_id=web_turns[0], turn_phase="activity" if row.get("kind") == "tool_hint" else "answer")
        if web_turns and len(web_turns) == len(input_ids):
            row["entry_channel"] = "WebUI"
    if isinstance(timestamp := message.get("timestamp"), str):
        try:
            row["created_at_ms"] = int(datetime.fromisoformat(timestamp).timestamp() * 1000)
        except (ValueError, OverflowError, OSError):
            pass


def _channel_text_record(key: str, role: str, message: dict[str, Any]) -> dict[str, Any] | None:
    public = public_history_message(message)
    text = _text(public.get("content"))
    # Legacy multimodal inputs can contain local-path placeholders; attachments
    # below are projected independently through the workspace/media policy.
    text = "\n".join(line for line in text.split("\n") if not _IMAGE_BREADCRUMB_RE.fullmatch(line))
    paths = public.get("media")
    fields = {"role": role, "content": text, "timestamp": public.get("timestamp"), "media": [
        value for value in cast(list[object], paths) if isinstance(value, str) and value
    ] if isinstance(paths, list) else []}
    if role == "assistant":
        fields["content"] = _sanitize_assistant_replay_text(strip_think(text))
        fields["latency_ms"] = public.get("latency_ms")
        return _session_assistant_event(key, fields)

    input_id = _history_id(public.get("input_id"))
    title = entry_channel_title(public.get("entry_channel"))
    if input_id is not None:
        fields["input_id"] = input_id
        turn_id = _web_turn(input_id)
        if title == "WebUI" and turn_id is not None and turn_id == public.get(INBOUND_META_TURN_ID):
            fields[INBOUND_META_TURN_ID] = turn_id
    row = _session_user_event(key, fields)
    if row is not None and title is not None:
        row["entry_channel"] = title
    return row


def _channel_record(
    key: str, chat_id: str, generation: str, index: int, message: dict[str, Any],
    *, finished_tools: Collection[str] = (),
) -> dict[str, Any] | None:
    role = message.get("role")
    if role not in ("user", "assistant") or message.get("_command") or is_hidden_history_message(message):
        return None
    if message.get("injected_event") == "subagent_result":
        return None
    if role == "assistant" and (calls := message.get("tool_calls")):
        if not (tools := _recorded_tool_events(calls, finished_tools)):
            return None
        row = {"event": "message", "kind": "tool_hint", "text": "", "tool_events": tools}
    else:
        row = _channel_text_record(key, role, message)
    if row is not None:
        if role == "assistant":
            _annotate_assistant(row, message)
        row["chat_id"] = chat_id
        row[_WEBUI_REPLAY_IDENTITY_KEY] = f"canonical:{key}:{generation}:{index}"
    return row


def build_channel_thread(
    key: str,
    chat_id: str,
    generation: str,
    messages: _MessageStream,
    *,
    page: ChannelHistoryPage,
    active_turn_id: str | None,
    running: bool,
    media: ChannelHistoryMedia,
) -> dict[str, Any]:
    selected: deque[tuple[int, dict[str, Any]]] = deque()
    text_chars = 0
    more_before = more_after = False
    finished_tools: set[str] = set()
    for index, message in messages:
        # In reverse order, the results of a round arrive just before the assistant's calls.
        # Collect them even outside the visible page, since its cursor can split the round.
        if message.get("role") == "tool":
            if (
                len(finished_tools) < _MAX_TOOL_CALLS_PER_ROUND
                and (call_id := _history_id(message.get("tool_call_id"))) is not None
                and not message.get("_recovery_interrupted")
                and not is_hidden_history_message(message)
            ):
                finished_tools.add(call_id)
            continue
        if page.before is not None and index >= page.before and more_after:
            finished_tools.clear()
            continue
        row = _channel_record(key, chat_id, generation, index, message, finished_tools=finished_tools)
        finished_tools.clear()
        if row is None:
            continue
        if page.before is not None and index >= page.before:
            more_after = True
            continue
        if page.after is not None:
            if index < page.after:
                more_before = True
                break
            selected.appendleft((index, row))
            text_chars += len(row["text"])
            while len(selected) > 1 and (len(selected) > page.limit or text_chars > _MAX_PAGE_TEXT_CHARS):
                _, removed = selected.pop()
                text_chars -= len(removed["text"])
                more_after = True
        else:
            text_chars += len(row["text"])
            if selected and (len(selected) == page.limit or text_chars > _MAX_PAGE_TEXT_CHARS):
                more_before = True
                break
            selected.appendleft((index, row))

    events: list[dict[str, Any]] = []
    completed: dict[str, None] = {}
    for _, row in selected:
        event = _client_projection_event(
            row, augment_user_media=media.attachments, augment_assistant_media=media.attachments,
            augment_assistant_text=media.assistant_text,
        )
        assert event is not None  # Only input, tool activity, and final assistant records are selected.
        if title := row.get("entry_channel"):
            event["entry_channel"] = title
        if event["event"] == "message" and "kind" not in event:
            for ref in event.get("response_input_ids", ()):
                if (turn := _web_turn(ref)) is not None and turn != active_turn_id:
                    completed[turn] = None
        events.append(event)
    return {
        "schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION,
        "sessionKey": key,
        "projection": "events",
        "events": events,
        "active_turn_id": active_turn_id,
        "has_pending_tool_calls": running,
        "completed_turn_ids": list(completed),
        "page": {
            "history_generation": generation,
            "before_cursor": _encode_page_cursor(selected[0][0]) if selected and more_before else None,
            "has_more_before": bool(selected) and more_before,
            "after_cursor": _encode_page_cursor(selected[-1][0] + 1) if selected and more_after else None,
            "has_more_after": bool(selected) and more_after,
            "loaded_event_count": len(events),
        },
    }


def build_channel_prompt_index(
    key: str, chat_id: str, generation: str, messages: _MessageStream,
) -> dict[str, Any]:
    prompts: list[PromptSummary] = []
    answers: dict[str, str] = {}
    for index, message in messages:
        row = _channel_record(key, chat_id, generation, index, message)
        if row is None:
            continue
        if row["event"] == "message":
            answer = row["text"][:240]
            if answer:
                for ref in row.get("response_input_ids", ()):
                    if len(answers) < _MAX_PROMPTS:
                        answers.setdefault(ref, answer)
            continue
        prompts.append(_prompt_summary(row, index, answers.pop(row.get("input_id", ""), "")))
        if len(prompts) == _MAX_PROMPTS:
            break
    prompts.reverse()
    return {"prompts": prompts, "replaceFrom": 0}
