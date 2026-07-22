from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.agent.tools.context import RequestContext
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    RuntimeContextBlock,
    append_runtime_context,
    public_history_message,
    resolve_runtime_context,
)
from nanobot.sdk.types import snapshot_from_session
from nanobot.session.manager import Session, _message_preview_text
from nanobot.session.webui_turns import _title_inputs
from nanobot.webui.transcript import _session_user_event


@pytest.mark.asyncio
async def test_resolve_runtime_context_preserves_provider_order() -> None:
    calls: list[str] = []

    async def first(_request: RequestContext):
        calls.append("first")
        return RuntimeContextBlock(source="first", content="one")

    async def second(_request: RequestContext):
        calls.append("second")
        return [RuntimeContextBlock(source="second", content="two")]

    blocks = await resolve_runtime_context(
        [first, second],
        RequestContext(channel="cli", chat_id="direct"),
    )

    assert calls == ["first", "second"]
    assert [(block.source, block.content) for block in blocks] == [
        ("first", "one"),
        ("second", "two"),
    ]


def test_public_history_removes_only_trusted_exact_suffix() -> None:
    block = RuntimeContextBlock(source="goal", content="private goal context")
    content, marker = append_runtime_context("visible user text", [block])
    assert marker is not None
    persisted = {
        "role": "user",
        "content": content,
        RUNTIME_CONTEXT_HISTORY_META: marker,
    }

    assert public_history_message(persisted) == {
        "role": "user",
        "content": "visible user text",
    }

    user_authored = {
        "role": "user",
        "content": "visible user text\n\nprivate goal context",
    }
    assert public_history_message(user_authored) == user_authored


def test_public_history_keeps_content_when_marker_does_not_match() -> None:
    message = {
        "role": "user",
        "content": "user-edited content",
        RUNTIME_CONTEXT_HISTORY_META: {
            "version": 1,
            "sources": ["goal"],
            "suffix": "different suffix",
        },
    }

    assert public_history_message(message) == {
        "role": "user",
        "content": "user-edited content",
    }


def test_sdk_snapshot_hides_runtime_context() -> None:
    block = RuntimeContextBlock(source="goal", content="private goal context")
    content, marker = append_runtime_context("visible user text", [block])
    session = SimpleNamespace(
        key="cli:direct",
        created_at=SimpleNamespace(isoformat=lambda: "created"),
        updated_at=SimpleNamespace(isoformat=lambda: "updated"),
        metadata={},
        messages=[{
            "role": "user",
            "content": content,
            RUNTIME_CONTEXT_HISTORY_META: marker,
        }],
    )

    snapshot = snapshot_from_session(session)

    assert snapshot.messages == [{"role": "user", "content": "visible user text"}]


def test_webui_preview_title_and_backfill_hide_runtime_context() -> None:
    block = RuntimeContextBlock(source="goal", content="private goal context")
    content, marker = append_runtime_context("visible user text", [block])
    persisted = {
        "role": "user",
        "content": content,
        RUNTIME_CONTEXT_HISTORY_META: marker,
    }
    session = Session(key="websocket:chat", messages=[persisted])

    assert _message_preview_text(persisted) == "visible user text"
    assert _title_inputs(session) == ("visible user text", "")
    event = _session_user_event("websocket:chat", persisted)
    assert event is not None
    assert event["text"] == "visible user text"
