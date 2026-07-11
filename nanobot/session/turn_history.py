"""Turn history persistence and interrupted-turn recovery."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.utils.helpers import image_placeholder_text
from nanobot.utils.helpers import truncate_text as truncate_text_fn

if TYPE_CHECKING:
    from nanobot.session.manager import Session

RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
PENDING_USER_TURN_KEY = "pending_user_turn"


def sanitize_persisted_blocks(
    content: list[dict[str, Any]],
    *,
    max_tool_result_chars: int,
    runtime_context_tag: str,
    should_truncate_text: bool = False,
    drop_runtime: bool = False,
) -> list[dict[str, Any]]:
    """Strip volatile multimodal payloads before writing session history."""
    filtered: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            filtered.append(block)
            continue

        if (
            drop_runtime
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and block["text"].startswith(runtime_context_tag)
        ):
            continue

        if block.get("type") == "image_url" and block.get("image_url", {}).get(
            "url", ""
        ).startswith("data:image/"):
            path = (block.get("_meta") or {}).get("path", "")
            filtered.append({"type": "text", "text": image_placeholder_text(path)})
            continue

        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text = block["text"]
            if should_truncate_text and len(text) > max_tool_result_chars:
                text = truncate_text_fn(text, max_tool_result_chars)
            filtered.append({**block, "text": text})
            continue

        filtered.append(block)

    return filtered


def save_turn(
    session: Session,
    messages: list[dict],
    skip: int,
    *,
    max_tool_result_chars: int,
    runtime_context_tag: str,
    turn_latency_ms: int | None = None,
) -> None:
    """Save new-turn messages into session, truncating large tool results."""
    declared_tool_call_ids = {
        str(tc["id"])
        for m in session.messages
        if m.get("role") == "assistant"
        for tc in m.get("tool_calls") or []
        if isinstance(tc, dict) and tc.get("id")
    }
    last_assistant_idx: int | None = None
    for m in messages[skip:]:
        entry = dict(m)
        role, content = entry.get("role"), entry.get("content")
        if role == "assistant" and not content and not entry.get("tool_calls"):
            continue  # skip empty assistant messages - they poison session context
        if role == "tool":
            tool_call_id = entry.get("tool_call_id")
            if not tool_call_id or str(tool_call_id) not in declared_tool_call_ids:
                # Undeclared tool results corrupt future provider requests.
                logger.warning(
                    "Dropping orphaned tool result {} from session {} during persistence",
                    tool_call_id or "(missing id)",
                    session.key,
                )
                continue
            if isinstance(content, str) and len(content) > max_tool_result_chars:
                entry["content"] = truncate_text_fn(content, max_tool_result_chars)
            elif isinstance(content, list):
                filtered = sanitize_persisted_blocks(
                    content,
                    max_tool_result_chars=max_tool_result_chars,
                    runtime_context_tag=runtime_context_tag,
                    should_truncate_text=True,
                )
                if not filtered:
                    # Preserve the tool_call/result pair after block filtering.
                    filtered = [
                        {"type": "text", "text": "[tool result omitted during persistence]"}
                    ]
                entry["content"] = filtered
        elif role == "user":
            if isinstance(content, str) and runtime_context_tag in content:
                # Strip the runtime-context block appended at the end.
                tag_pos = content.find(runtime_context_tag)
                before = content[:tag_pos].rstrip("\n ")
                if before:
                    entry["content"] = before
                else:
                    continue
            if isinstance(content, list):
                filtered = sanitize_persisted_blocks(
                    content,
                    max_tool_result_chars=max_tool_result_chars,
                    runtime_context_tag=runtime_context_tag,
                    drop_runtime=True,
                )
                if not filtered:
                    continue
                entry["content"] = filtered
        entry.setdefault("timestamp", datetime.now().isoformat())
        session.messages.append(entry)
        if role == "assistant":
            last_assistant_idx = len(session.messages) - 1
            declared_tool_call_ids.update(
                str(tc["id"])
                for tc in entry.get("tool_calls") or []
                if isinstance(tc, dict) and tc.get("id")
            )
    if turn_latency_ms is not None and last_assistant_idx is not None:
        session.messages[last_assistant_idx]["latency_ms"] = int(turn_latency_ms)
    session.updated_at = datetime.now()


def persist_subagent_followup(session: Session, msg: Any) -> bool:
    """Persist subagent follow-ups before prompt assembly so history stays durable.

    Returns True if a new entry was appended; False if the follow-up was
    deduped (same ``subagent_task_id`` already in session) or carries no
    content worth persisting.
    """
    if not msg.content:
        return False
    task_id = msg.metadata.get("subagent_task_id") if isinstance(msg.metadata, dict) else None
    if task_id and any(
        m.get("injected_event") == "subagent_result" and m.get("subagent_task_id") == task_id
        for m in session.messages
    ):
        return False
    session.add_message(
        "assistant",
        msg.content,
        sender_id=msg.sender_id,
        injected_event="subagent_result",
        subagent_task_id=task_id,
    )
    return True


def set_runtime_checkpoint(session: Session, payload: dict[str, Any]) -> None:
    """Persist the latest in-flight turn state into session metadata."""
    session.metadata[RUNTIME_CHECKPOINT_KEY] = payload


def mark_pending_user_turn(session: Session) -> None:
    session.metadata[PENDING_USER_TURN_KEY] = True


def clear_pending_user_turn(session: Session) -> None:
    session.metadata.pop(PENDING_USER_TURN_KEY, None)


def clear_runtime_checkpoint(session: Session) -> None:
    session.metadata.pop(RUNTIME_CHECKPOINT_KEY, None)


def checkpoint_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
    return (
        message.get("role"),
        message.get("content"),
        message.get("tool_call_id"),
        message.get("name"),
        message.get("tool_calls"),
        message.get("reasoning_content"),
        message.get("thinking_blocks"),
    )


def restore_runtime_checkpoint(session: Session) -> bool:
    """Materialize an unfinished turn into session history before a new request."""
    checkpoint = session.metadata.get(RUNTIME_CHECKPOINT_KEY)
    if not isinstance(checkpoint, dict):
        return False

    assistant_message = checkpoint.get("assistant_message")
    completed_tool_results = checkpoint.get("completed_tool_results") or []
    pending_tool_calls = checkpoint.get("pending_tool_calls") or []

    restored_messages: list[dict[str, Any]] = []
    if isinstance(assistant_message, dict):
        restored = dict(assistant_message)
        restored.setdefault("timestamp", datetime.now().isoformat())
        restored_messages.append(restored)
    for message in completed_tool_results:
        if isinstance(message, dict):
            restored = dict(message)
            restored.setdefault("timestamp", datetime.now().isoformat())
            restored_messages.append(restored)
    for tool_call in pending_tool_calls:
        if not isinstance(tool_call, dict):
            continue
        tool_id = tool_call.get("id")
        name = ((tool_call.get("function") or {}).get("name")) or "tool"
        restored_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": "Error: Task interrupted before this tool finished.",
                "timestamp": datetime.now().isoformat(),
            }
        )

    overlap = 0
    max_overlap = min(len(session.messages), len(restored_messages))
    for size in range(max_overlap, 0, -1):
        existing = session.messages[-size:]
        restored = restored_messages[:size]
        if all(
            checkpoint_message_key(left) == checkpoint_message_key(right)
            for left, right in zip(existing, restored)
        ):
            overlap = size
            break
    session.messages.extend(restored_messages[overlap:])

    clear_pending_user_turn(session)
    clear_runtime_checkpoint(session)
    return True


def restore_pending_user_turn(session: Session) -> bool:
    """Close a turn that only persisted the user message before crashing."""
    if not session.metadata.get(PENDING_USER_TURN_KEY):
        return False

    if session.messages and session.messages[-1].get("role") == "user":
        session.messages.append(
            {
                "role": "assistant",
                "content": "Error: Task interrupted before a response was generated.",
                "timestamp": datetime.now().isoformat(),
            }
        )
        session.updated_at = datetime.now()

    clear_pending_user_turn(session)
    return True
