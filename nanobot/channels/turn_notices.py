"""Terminal turn notices for channels that display plain text."""

from nanobot.bus.outbound_events import EmptyFinalResponseNotice


def empty_final_notice_text(notice: EmptyFinalResponseNotice) -> str:
    if notice.output_limited:
        return "The model reached its output limit before returning a final answer."
    return "The model didn't return a final answer. Please try again."
