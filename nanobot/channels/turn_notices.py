"""Terminal turn notices for channels that display plain text."""

from nanobot.bus.outbound_events import TurnFailureNotice


def turn_failure_notice_text(notice: TurnFailureNotice) -> str:
    """Choose public copy by category; never display a provider or tool diagnostic."""
    if notice.failure_kind == "model":
        if notice.failure_error_kind == "empty_final_response_length":
            return "The model reached its output limit before returning a final answer."
        if notice.failure_error_kind == "empty_final_response":
            return "The model didn't return a final answer. Please try again."
        if notice.failure_error_kind == "billing":
            return "The model provider has no quota available. Check the provider account's billing and try again."
        return "The model request failed. Check the provider configuration or service status and try again."
    if notice.failure_kind == "tool":
        return "A tool failed before the request could be completed."
    return "An internal error prevented nanobot from completing the request. Please try again."
