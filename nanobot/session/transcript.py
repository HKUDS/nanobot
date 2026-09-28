"""Commit runner transcripts to sessions using shared replay and sanitization rules."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from loguru import logger

from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, RUNTIME_CONTEXT_MESSAGE_META
from nanobot.session.manager import Session
from nanobot.session.recovery import PENDING_FOLLOWUP_ID_KEY, acknowledge_pending_followups
from nanobot.session.summary import SessionSummaryCheckpoint
from nanobot.utils.helpers import image_placeholder_text


def sanitize_persisted_blocks(
    content: list[object],
) -> list[object]:
    """Strip volatile multimodal payloads before writing session history."""
    filtered: list[object] = []
    for block in content:
        if not isinstance(block, dict):
            filtered.append(block)
            continue

        block_data = cast(dict[str, Any], block)
        image_url = cast(dict[str, Any], block_data.get("image_url", {}))
        if block_data.get("type") == "image_url" and str(
            image_url.get("url", "")
        ).startswith("data:image/"):
            internal_meta = cast(dict[str, Any], block_data.get("_meta") or {})
            path = cast(str, internal_meta.get("path", ""))
            filtered.append(
                {"type": "text", "text": image_placeholder_text(path)}
            )
            continue

        filtered.append(block_data)

    return filtered


def validated_checkpoint_boundary(
    checkpoint: SessionSummaryCheckpoint | None,
    *,
    skip: int,
    message_count: int,
    session_key: str,
) -> int | None:
    """Return a checkpoint boundary only when it belongs to this turn."""
    if checkpoint is None:
        return None
    boundary = checkpoint.transcript_boundary
    if skip - 1 <= boundary <= message_count:
        return boundary
    logger.warning(
        "Ignoring invalid summary boundary {} outside [{}, {}] for {}",
        boundary,
        skip - 1,
        message_count,
        session_key,
    )
    return None


def commit_turn(
    session: Session,
    messages: list[dict[str, Any]],
    skip: int,
    *,
    turn_latency_ms: int | None = None,
    summary_checkpoint: SessionSummaryCheckpoint | None = None,
    input_persisted_early: bool = False,
) -> None:
    """Commit new-turn messages and an optional summary boundary."""
    declared_tool_call_ids = {
        str(tc["id"])
        for m in session.messages
        if m.get("role") == "assistant"
        for tc_value in cast(Iterable[object], m.get("tool_calls") or [])
        if isinstance(tc_value, dict)
        for tc in (cast(dict[str, Any], tc_value),)
        if tc.get("id")
    }
    fulfilled_tool_call_ids = {
        str(m["tool_call_id"])
        for m in session.messages
        if m.get("role") == "tool" and m.get("tool_call_id")
    }
    last_assistant_idx: int | None = None
    saved_followup_ids: set[str] = set()
    checkpoint_boundary = validated_checkpoint_boundary(
        summary_checkpoint,
        skip=skip,
        message_count=len(messages),
        session_key=session.key,
    )

    # The trigger input may already be the session tail while still being
    # the first message after the replacement checkpoint.
    if summary_checkpoint is not None and checkpoint_boundary == skip - 1:
        insert_at = len(session.messages) - (1 if input_persisted_early else 0)
        session.commit_summary_checkpoint(
            summary_checkpoint.summary,
            insert_at=insert_at,
        )

    for message_index, message in enumerate(messages[skip:], start=skip):
        # Insert against the raw transcript index before filtering the
        # message so persistence cleanup cannot shift the H/Δ boundary.
        if summary_checkpoint is not None and checkpoint_boundary == message_index:
            session.commit_summary_checkpoint(summary_checkpoint.summary)

        entry = dict(message)
        followup_id_value = cast(object, entry.pop(PENDING_FOLLOWUP_ID_KEY, None))
        followup_ids = (
            [followup_id_value]
            if isinstance(followup_id_value, str)
            else [
                followup_id
                for followup_id in cast(list[object], followup_id_value)
                if isinstance(followup_id, str)
            ]
            if isinstance(followup_id_value, list)
            else []
        )
        internal_meta = cast(object, entry.pop("_meta", None))
        runtime_context_meta = (
            cast(dict[str, Any], internal_meta).get(
                RUNTIME_CONTEXT_MESSAGE_META
            )
            if isinstance(internal_meta, dict)
            else None
        )
        role, content = entry.get("role"), entry.get("content")
        if role == "assistant" and not content and not entry.get("tool_calls"):
            continue  # skip empty assistant messages — they poison session context
        if role == "tool":
            tool_call_id = entry.get("tool_call_id")
            tool_call_id_str = str(tool_call_id) if tool_call_id else ""
            if (
                not tool_call_id_str
                or tool_call_id_str not in declared_tool_call_ids
                or tool_call_id_str in fulfilled_tool_call_ids
            ):
                # Undeclared tool results corrupt future provider requests.
                logger.warning(
                    "Dropping invalid tool result {} from session {} during persistence",
                    tool_call_id_str or "(missing id)",
                    session.key,
                )
                continue
            fulfilled_tool_call_ids.add(tool_call_id_str)
            # Preserve model-visible text for replay; redact only inline images.
            if isinstance(content, list):
                filtered = sanitize_persisted_blocks(
                    cast(list[object], content),
                )
                if not filtered:
                    # Preserve the tool_call/result pair after block filtering.
                    filtered = [
                        {"type": "text", "text": "[tool result omitted during persistence]"}
                    ]
                entry["content"] = filtered
        elif role == "user":
            if isinstance(content, list):
                filtered = sanitize_persisted_blocks(
                    cast(list[object], content),
                )
                if not filtered:
                    continue
                entry["content"] = filtered
            if isinstance(runtime_context_meta, dict):
                entry[RUNTIME_CONTEXT_HISTORY_META] = runtime_context_meta
        entry.setdefault("timestamp", datetime.now().isoformat())
        session.messages.append(entry)
        if role == "user":
            saved_followup_ids.update(followup_id for followup_id in followup_ids if followup_id)
        if role == "assistant":
            last_assistant_idx = len(session.messages) - 1
            declared_tool_call_ids.update(
                str(tc["id"])
                for tc_value in cast(
                    Iterable[object],
                    entry.get("tool_calls") or [],
                )
                if isinstance(tc_value, dict)
                for tc in (cast(dict[str, Any], tc_value),)
                if tc.get("id")
            )
    if summary_checkpoint is not None and checkpoint_boundary == len(messages):
        session.commit_summary_checkpoint(summary_checkpoint.summary)
    if turn_latency_ms is not None and last_assistant_idx is not None:
        session.messages[last_assistant_idx]["latency_ms"] = int(turn_latency_ms)
    if saved_followup_ids:
        acknowledge_pending_followups(session, saved_followup_ids)
    session.updated_at = datetime.now()
