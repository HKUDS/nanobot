"""Tests for L0 capture slice vs session save skip."""

from nanobot.agent.layered_memory.capture_slice import l0_capture_skip


def test_l0_capture_skip_when_user_persisted_early() -> None:
    assert l0_capture_skip(session_save_skip=2, user_persisted_early=True) == 1


def test_l0_capture_skip_unchanged_without_early_persist() -> None:
    assert l0_capture_skip(session_save_skip=2, user_persisted_early=False) == 2


def test_l0_capture_skip_never_negative() -> None:
    assert l0_capture_skip(session_save_skip=0, user_persisted_early=True) == 0
