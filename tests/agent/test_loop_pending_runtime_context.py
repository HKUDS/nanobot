from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.utils.document import extract_documents
from nanobot.bus.queue import MessageBus


def _make_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")


def _pending_to_user_message(loop: AgentLoop, pending_msg: InboundMessage) -> dict:
    content = pending_msg.content
    media = pending_msg.media if pending_msg.media else None
    if media:
        content, media = extract_documents(content, media)
        media = media or None
    user_content = loop.context._build_user_content(content, media)
    return {"role": "user", "content": user_content}


def _assert_no_runtime_markers(text: str) -> None:
    for forbidden in (
        "[Runtime Context",
        "[/Runtime Context]",
        "Current Time:",
        "Channel:",
        "Chat ID:",
        "[Resumed Session]",
    ):
        assert forbidden not in text


def test_pending_injected_user_message_excludes_runtime_context(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    pending_text = "follow up from pending queue"
    pending_msg = InboundMessage(
        channel="cli",
        chat_id="direct",
        sender_id="user",
        content=pending_text,
    )

    message = _pending_to_user_message(loop, pending_msg)

    assert message["role"] == "user"
    content = message["content"]
    assert isinstance(content, str)
    assert content == pending_text
    _assert_no_runtime_markers(content)


def test_pending_injected_multimodal_user_message_excludes_runtime_context(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake")
    pending_text = "see attachment"
    pending_msg = InboundMessage(
        channel="cli",
        chat_id="direct",
        sender_id="user",
        content=pending_text,
        media=[str(image_path)],
    )

    message = _pending_to_user_message(loop, pending_msg)

    assert message["role"] == "user"
    content = message["content"]
    assert isinstance(content, list)
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert text_blocks
    joined = "\n".join(str(b.get("text", "")) for b in text_blocks)
    assert pending_text in joined
    _assert_no_runtime_markers(joined)
