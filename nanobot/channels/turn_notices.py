"""Terminal turn notices for channels that display plain text."""

from nanobot.bus.outbound_events import TurnEndEvent
from nanobot.events import AgentEvent


def turn_failure_notice(event: AgentEvent | None) -> str | None:
    if (
        isinstance(event, TurnEndEvent)
        and event.outcome == "failed"
        and event.failure_kind == "model"
    ):
        if event.failure_error_kind == "empty_final_response_length":
            return "The model reached its output limit before returning a final answer."
        if event.failure_error_kind == "empty_final_response":
            return "The model didn't return a final answer. Please try again."
    return None
