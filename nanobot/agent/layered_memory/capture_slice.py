"""Slice helpers for L0 capture vs session save (turn boundary)."""


def l0_capture_skip(*, session_save_skip: int, user_persisted_early: bool) -> int:
    """``session_save_skip`` may omit the user message when persisted early; L0 still needs it."""
    if user_persisted_early and session_save_skip > 0:
        return session_save_skip - 1
    return session_save_skip
