"""AgentLoop history-only ingest (no LLM / no outbound)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import INBOUND_META_HISTORY_ONLY, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.session.webui_turns import WebuiTurnCoordinator


def _make_full_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="should not run"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    WebuiTurnCoordinator(
        bus=loop.bus,
        sessions=loop.sessions,
        schedule_background=lambda coro: loop._schedule_background(coro),
    ).subscribe(loop.runtime_events)
    return loop


@pytest.mark.asyncio
async def test_dispatch_history_only_persists_without_llm_or_outbound(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._process_message = AsyncMock(return_value=None)  # type: ignore[method-assign]
    loop.provider.chat_with_retry = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("LLM must not run for history-only ingest"),
    )

    outbound: list = []
    original_publish = loop.bus.publish_outbound

    async def capture_outbound(msg):
        outbound.append(msg)
        await original_publish(msg)

    loop.bus.publish_outbound = capture_outbound  # type: ignore[method-assign]

    msg = InboundMessage(
        channel="feishu",
        sender_id="ou_alice",
        chat_id="oc_group",
        content="group chatter",
        metadata={INBOUND_META_HISTORY_ONLY: True},
    )
    await loop._dispatch(msg)

    loop._process_message.assert_not_awaited()
    loop.provider.chat_with_retry.assert_not_awaited()
    assert outbound == []

    session = loop.sessions.get_or_create("feishu:oc_group")
    assert [m["role"] for m in session.messages] == ["user"]
    assert session.messages[0]["content"] == "group chatter"
    assert session.metadata.get(AgentLoop._PENDING_USER_TURN_KEY) is None


@pytest.mark.asyncio
async def test_dispatch_history_only_then_mention_sees_prior_context(tmp_path: Path) -> None:
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    await loop._dispatch(
        InboundMessage(
            channel="feishu",
            sender_id="ou_alice",
            chat_id="oc_group",
            content="earlier context",
            metadata={INBOUND_META_HISTORY_ONLY: True},
        )
    )

    captured_history: list = []

    async def fake_process(msg, **kwargs):
        session = loop.sessions.get_or_create(msg.session_key)
        captured_history.extend(session.messages)
        return None

    loop._process_message = AsyncMock(side_effect=fake_process)  # type: ignore[method-assign]

    await loop._dispatch(
        InboundMessage(
            channel="feishu",
            sender_id="ou_alice",
            chat_id="oc_group",
            content="@bot what was said?",
        )
    )

    loop._process_message.assert_awaited_once()
    assert any(m.get("content") == "earlier context" for m in captured_history)


@pytest.mark.asyncio
async def test_dispatch_history_only_image_then_mention_rehydrates_vision(
    tmp_path: Path,
) -> None:
    """Listen-ingested images must become multimodal history on a later text @mention."""
    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    png = tmp_path / "photo.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    path = str(png)

    await loop._dispatch(
        InboundMessage(
            channel="feishu",
            sender_id="ou_alice",
            chat_id="oc_group",
            content=f"[image: {path}]",
            media=[path],
            metadata={INBOUND_META_HISTORY_ONLY: True},
        )
    )

    session = loop.sessions.get_or_create("feishu:oc_group")
    assert session.messages[0].get("media") == [path]

    captured_messages: list = []

    async def fake_process(msg, **kwargs):
        sess = loop.sessions.get_or_create(msg.session_key)
        history = sess.get_history(max_messages=500)
        captured_messages.extend(
            loop._build_initial_messages(msg, sess, history, None)
        )
        return None

    loop._process_message = AsyncMock(side_effect=fake_process)  # type: ignore[method-assign]

    await loop._dispatch(
        InboundMessage(
            channel="feishu",
            sender_id="ou_alice",
            chat_id="oc_group",
            content="@bot what is in the image?",
        )
    )

    loop._process_message.assert_awaited_once()
    prior_user = next(
        m
        for m in captured_messages
        if m.get("role") == "user" and isinstance(m.get("content"), list)
    )
    assert any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for part in prior_user["content"]
    )
    assert any(
        isinstance(part, dict)
        and part.get("type") == "image_url"
        and str(part.get("image_url", {}).get("url", "")).startswith("data:image/png;base64,")
        for part in prior_user["content"]
    )


@pytest.mark.asyncio
async def test_dispatch_five_history_only_images_then_mention_keeps_all_vision(
    tmp_path: Path,
) -> None:
    """Album-style listen: five image events then @mention must keep all five image_url blocks."""
    from nanobot.providers.base import LLMProvider

    loop = _make_full_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    paths: list[str] = []
    for i in range(5):
        png = tmp_path / f"photo_{i}.png"
        png.write_bytes(png_bytes)
        path = str(png)
        paths.append(path)
        await loop._dispatch(
            InboundMessage(
                channel="feishu",
                sender_id="ou_alice",
                chat_id="oc_group",
                content=f"[image: {path}]",
                media=[path],
                metadata={INBOUND_META_HISTORY_ONLY: True},
            )
        )

    session = loop.sessions.get_or_create("feishu:oc_group")
    assert len(session.messages) == 5
    assert [m.get("media") for m in session.messages] == [[p] for p in paths]

    captured_messages: list = []

    async def fake_process(msg, **kwargs):
        sess = loop.sessions.get_or_create(msg.session_key)
        history = sess.get_history(max_messages=500)
        initial = loop._build_initial_messages(msg, sess, history, None)
        # Mirror OpenAI-compat send path: consecutive multimodal users must
        # survive role alternation with all image_url blocks intact.
        captured_messages.extend(LLMProvider._enforce_role_alternation(initial))
        return None

    loop._process_message = AsyncMock(side_effect=fake_process)  # type: ignore[method-assign]

    await loop._dispatch(
        InboundMessage(
            channel="feishu",
            sender_id="ou_alice",
            chat_id="oc_group",
            content="@bot what do you think?",
        )
    )

    loop._process_message.assert_awaited_once()
    user_msgs = [m for m in captured_messages if m.get("role") == "user"]
    assert len(user_msgs) == 1
    content = user_msgs[0]["content"]
    assert isinstance(content, list)
    image_parts = [
        part for part in content if isinstance(part, dict) and part.get("type") == "image_url"
    ]
    assert len(image_parts) == 5
    assert any(
        isinstance(part, dict)
        and part.get("type") == "text"
        and "@bot what do you think?" in str(part.get("text", ""))
        for part in content
    )
