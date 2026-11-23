"""Bookkeeping for explicit recovery inputs and ordinary iteration-limit stops."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, MutableMapping

from nanobot.runtime_context import RuntimeContextBlock, wrap_runtime_context_lines

if TYPE_CHECKING:
    from nanobot.agent.tools.context import RequestContext
    from nanobot.session.state import SessionState

INTERNAL_CONTINUATION_META = "_internal_continuation"
SKIP_USER_PERSIST_META = "_skip_user_persist"
_ITERATION_LIMIT_META = "_stopped_at_iteration_limit"


def record_iteration_limit(metadata: MutableMapping[str, Any], stop_reason: str) -> None:
    """Remember an ordinary execution stopped at its iteration limit."""
    if stop_reason == "max_iterations":
        metadata[_ITERATION_LIMIT_META] = True
    else:
        metadata.pop(_ITERATION_LIMIT_META, None)


async def iteration_limit_context(
    state: SessionState, request: RequestContext,
) -> RuntimeContextBlock | None:
    """Attach the previous terminal budget outcome to the new input suffix."""
    if not request.session_key or not request.persist_session:
        return None
    if internal_continuation_inbound(request.metadata):
        return None
    payload = await state.read_metadata(request.session_key)
    if payload is None or not payload["metadata"].get(_ITERATION_LIMIT_META):
        return None
    return RuntimeContextBlock(
        source="iteration_limit",
        content=wrap_runtime_context_lines([
            "The previous turn stopped at the tool-iteration limit without finishing its work.",
            "Follow the current request. Resume unfinished work only if the user asks for it.",
            "Completed tool calls and their results remain in the history; do not repeat them blindly.",
        ]),
    )


def internal_continuation_inbound(metadata: Mapping[str, Any] | None) -> bool:
    return bool(metadata and metadata.get(INTERNAL_CONTINUATION_META) is True)


def should_persist_user_message(metadata: Mapping[str, Any] | None) -> bool:
    if metadata and metadata.get(SKIP_USER_PERSIST_META) is True:
        return False
    return not internal_continuation_inbound(metadata)


def save_skip_for_turn(
    *, message_metadata: Mapping[str, Any] | None,
    initial_message_count: int, input_persisted_early: bool,
) -> int:
    if message_metadata and message_metadata.get(SKIP_USER_PERSIST_META) is True:
        return initial_message_count
    if internal_continuation_inbound(message_metadata):
        return initial_message_count
    return initial_message_count if input_persisted_early else initial_message_count - 1
