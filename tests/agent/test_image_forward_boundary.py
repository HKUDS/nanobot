"""Boundary tests: image-strip fallback vs. forwarding an uploaded file (#4345/#4346)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nanobot.agent import attachment_registry
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage
from nanobot.providers.base import LLMProvider

_HANDLE_RE = re.compile(r"\[image attachment: (attachment_\d+); cannot be viewed by this model\]")

# Minimal valid 1x1 PNG so _build_user_content recognizes the file as an image.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f9b0000000049454e44ae426082"
)


def _make_media(tmp_path: Path) -> Path:
    media_file = tmp_path / "media" / "uploaded.png"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(PNG_BYTES)
    return media_file


def _build_messages(tmp_path: Path, inbound_text: str, media_file: Path) -> list[dict]:
    builder = ContextBuilder(workspace=tmp_path)
    content = builder._build_user_content(inbound_text, [str(media_file)])
    assert isinstance(content, list)
    return [{"role": "user", "content": content}]


def _text_blocks(messages: list[dict]) -> str:
    return "\n".join(
        b.get("text") or ""
        for m in messages
        for b in (m.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "text"
    )


def test_stripped_image_signals_unviewable_and_leaks_no_path(tmp_path: Path) -> None:
    """The fix: stripped image becomes an unviewable marker with no server path."""
    attachment_registry.begin_turn()
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, "what is this?", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    assert stripped is not None

    texts = _text_blocks(stripped)
    assert "cannot be viewed" in texts
    assert str(media_file) not in texts  # no raw server path
    assert all(
        b.get("type") != "image_url"
        for m in stripped
        for b in (m.get("content") or [])
        if isinstance(b, dict)
    )


def test_full_path_breadcrumb_survives_strip_and_stays_forwardable(tmp_path: Path) -> None:
    """WhatsApp/Telegram (full-path content tag): forwarding still works, no regression."""
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, f"send this\n[image: {media_file}]", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    assert str(media_file) in _text_blocks(stripped)  # text breadcrumb untouched

    tool = MessageTool(workspace=tmp_path, restrict_to_workspace=False)
    resolved = tool._resolve_media([str(media_file)])
    assert resolved == [str(media_file)]
    assert Path(resolved[0]).is_file()


@pytest.mark.asyncio
async def test_stripped_image_forwardable_via_handle_no_path(tmp_path: Path) -> None:
    """The follow-up (#4345): a non-vision model can forward a stripped upload via its
    opaque handle — end to end through the real mint/strip/resolve path — and never sees
    a raw filesystem path.

    Drives the production wiring: begin_turn() installs the registry, _build_user_content
    mints the id into _meta, _strip_image_content emits the handle marker, and
    MessageTool.execute resolves that same id back to the path. The handle is read off the
    marker text exactly as a model would, so this proves the contexts actually share a
    registry — not a hand-built one.
    """
    attachment_registry.begin_turn()
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, "forward this to email", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    texts = _text_blocks(stripped)
    assert str(media_file) not in texts  # marker carries no raw path

    match = _HANDLE_RE.search(texts)
    assert match, f"expected a handle marker, got: {texts!r}"
    handle = match.group(1)

    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send, workspace=tmp_path, restrict_to_workspace=True)
    result = await tool.execute(
        content="here is the file",
        channel="telegram",
        chat_id="42",
        attachment_handles=[handle],
    )

    # Delivered the real uploaded file, even under workspace restriction, because the
    # path is server-minted from this turn's upload rather than model-supplied.
    assert len(sent) == 1
    assert sent[0].media == [str(media_file)]
    # Return string is count-only; it never echoes the resolved path.
    assert "1 attachment" in result
    assert str(media_file) not in result


def test_basename_only_breadcrumb_still_not_path_forwardable(tmp_path: Path) -> None:
    """A filename-only breadcrumb (WeCom-style) is still not a valid media path after
    strip — the opaque handle, not a guessed basename, is the supported forward route."""
    attachment_registry.begin_turn()
    media_file = _make_media(tmp_path)
    messages = _build_messages(tmp_path, "send this\n[image: uploaded.png]", media_file)

    stripped = LLMProvider._strip_image_content(messages)
    assert str(media_file) not in _text_blocks(stripped)  # leak gone

    tool = MessageTool(workspace=tmp_path, restrict_to_workspace=False)
    resolved = tool._resolve_media(["uploaded.png"])
    assert resolved != [str(media_file)]
    assert not Path(resolved[0]).is_file()


@pytest.mark.asyncio
async def test_handle_resolves_through_real_agent_loop(tmp_path: Path) -> None:
    """Integration guard: the registry set in the parent turn context must reach
    MessageTool.execute when the runner invokes it.

    Unlike the synchronous end-to-end test above, this drives the *real*
    ``_run_agent_loop`` (and thus the real runner tool-execution path). begin_turn()
    + mint() run in this coroutine exactly as _state_build does, then the provider
    asks the message tool to forward the handle. If a future refactor forks the tool
    context before begin_turn, resolve() returns None and the delivered media is
    empty — failing here instead of silently dropping every handle in production.
    """
    from unittest.mock import MagicMock

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    media_file = _make_media(tmp_path)
    attachment_registry.begin_turn()
    handle = attachment_registry.mint(str(media_file))

    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    message_tool = MessageTool(
        send_callback=_send, workspace=tmp_path, restrict_to_workspace=True
    )

    class _Tools:
        tool_names = ["message"]

        def get(self, name: str):
            return message_tool if name == "message" else None

        def get_definitions(self) -> list:
            return []

        def prepare_call(self, name: str, arguments: dict):
            return (message_tool, arguments, None) if name == "message" else (None, arguments, None)

    calls = {"n": 0}

    async def chat_with_retry(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="message",
                        arguments={
                            "content": "forwarding your file",
                            "channel": "telegram",
                            "chat_id": "1",
                            "attachment_handles": [handle],
                        },
                    )
                ],
            )
        return LLMResponse(content="done", tool_calls=[])

    provider = MagicMock()
    provider.chat_with_retry = chat_with_retry
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    loop.tools = _Tools()

    await loop._run_agent_loop(
        [],
        channel="telegram",
        chat_id="1",
        metadata={},
        session_key="telegram:1",
    )

    assert len(sent) == 1
    # The handle resolved through the runner to the real upload path.
    assert sent[0].media == [str(media_file)]
