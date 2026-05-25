"""Tests that _save_turn strips the runtime-context preamble before persisting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.session.manager import Session


def _make_loop():
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop


def test_save_strips_string_runtime_preamble() -> None:
    """A merged user message gets its runtime preamble stripped on save."""
    loop = _make_loop()
    session = Session(key="telegram:42")

    merged = (
        f"{ContextBuilder._RUNTIME_CONTEXT_TAG}\n"
        "Current Time: 2026-05-25 09:19\n"
        "Channel: telegram\n"
        "Chat ID: 42\n"
        "\n"
        "can you see earlier messages?"
    )
    messages = [
        {"role": "user", "content": merged},
        {"role": "assistant", "content": "Yes, I can see the prior turns."},
    ]
    loop._save_turn(session, messages, skip=0)

    assert len(session.messages) == 2
    user_saved = session.messages[0]
    assert user_saved["role"] == "user"
    assert user_saved["content"] == "can you see earlier messages?"
    assert ContextBuilder._RUNTIME_CONTEXT_TAG not in user_saved["content"]


def test_save_drops_user_with_only_runtime_preamble() -> None:
    """A user message containing only the preamble is skipped entirely."""
    loop = _make_loop()
    session = Session(key="telegram:42")

    only_preamble = (
        f"{ContextBuilder._RUNTIME_CONTEXT_TAG}\n"
        "Current Time: 2026-05-25 09:19\n"
    )
    loop._save_turn(session, [{"role": "user", "content": only_preamble}], skip=0)
    assert session.messages == []


def test_save_strips_list_runtime_part_then_collapses_to_text() -> None:
    """When user content is multi-part (image), the leading runtime text part is dropped."""
    loop = _make_loop()
    session = Session(key="telegram:42")

    multipart = [
        {"type": "text", "text": f"{ContextBuilder._RUNTIME_CONTEXT_TAG}\nCurrent Time: ...\nChannel: telegram"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        {"type": "text", "text": "describe this"},
    ]
    loop._save_turn(session, [{"role": "user", "content": multipart}], skip=0)

    assert len(session.messages) == 1
    saved = session.messages[0]
    assert "[user sent an image]" in saved["content"]
    assert "describe this" in saved["content"]
    assert ContextBuilder._RUNTIME_CONTEXT_TAG not in saved["content"]


def test_save_preserves_user_without_preamble() -> None:
    """Plain user messages (no preamble) are stored unchanged."""
    loop = _make_loop()
    session = Session(key="telegram:42")

    loop._save_turn(
        session,
        [{"role": "user", "content": "plain message"}],
        skip=0,
    )
    assert session.messages[0]["content"] == "plain message"
