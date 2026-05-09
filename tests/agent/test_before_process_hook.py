"""Tests for the before_process hook in the agent loop.

Verifies that:
1. The hook is called before extract_documents when media is present.
2. Hook can inject media_text appended to message content.
3. Hook can modify the media list before extract_documents.
4. No hook registered → behavior is unchanged (no regression).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus

# ---------------------------------------------------------------------------
# 1x1 PNG (same as test_loop_save_turn.py)
# ---------------------------------------------------------------------------
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x00\x00\x02\x00\x01"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_png(tmp: Path, name: str) -> str:
    p = tmp / name
    p.write_bytes(_PNG_1X1)
    return str(p)


def _make_msg(tmp: Path, *, content: str = "look", media_count: int = 1) -> InboundMessage:
    media = [_write_png(tmp, f"img-{i}.png") for i in range(media_count)] if media_count else None
    return InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content=content,
        media=media,
    )


def _make_loop(tmp: Path, *, hooks: list[AgentHook] | None = None) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp,
        model="test-model",
        hooks=hooks,
    )


class _RecordingHook(AgentHook):
    """Captures the AgentHookContext passed to before_process."""

    def __init__(
        self,
        *,
        set_media_text: str | None = None,
        set_media: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.calls: list[AgentHookContext] = []
        self._media_text = set_media_text
        self._media = set_media

    async def before_process(self, context: AgentHookContext) -> None:
        self.calls.append(context)
        if self._media_text is not None:
            context.media_text = self._media_text
        if self._media is not None:
            context.media = self._media


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestHookCalled:
    """Verify before_process fires when media is present and hooks are registered."""

    @pytest.mark.asyncio
    async def test_called_with_media_and_hooks(self, tmp_path: Path) -> None:
        hook = _RecordingHook()
        loop = _make_loop(tmp_path, hooks=[hook])
        msg = _make_msg(tmp_path)

        # _process_message will fail at _run_agent_loop (no real LLM), but
        # the hook should have already fired by that point.
        with pytest.raises(Exception):
            await loop._process_message(msg)

        assert len(hook.calls) == 1
        ctx = hook.calls[0]
        assert ctx.media is not None
        assert len(ctx.media) == 1

    @pytest.mark.asyncio
    async def test_not_called_without_media(self, tmp_path: Path) -> None:
        hook = _RecordingHook()
        loop = _make_loop(tmp_path, hooks=[hook])
        msg = _make_msg(tmp_path, media_count=0)

        with pytest.raises(Exception):
            await loop._process_message(msg)

        assert len(hook.calls) == 0

    @pytest.mark.asyncio
    async def test_not_called_without_hooks(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, hooks=[])
        msg = _make_msg(tmp_path)

        # Should not crash — extract_documents runs normally, fails at LLM call.
        with pytest.raises(Exception):
            await loop._process_message(msg)


class TestHookModifiesContent:
    """Hook-set media_text gets appended to msg.content before extract_documents."""

    @pytest.mark.asyncio
    async def test_media_text_appended(self, tmp_path: Path) -> None:
        hook = _RecordingHook(set_media_text="[Image: a cat]")
        loop = _make_loop(tmp_path, hooks=[hook])
        msg = _make_msg(tmp_path, content="describe this")

        # Patch _run_agent_loop to capture the messages actually sent to LLM.
        captured: list[list[dict]] = []
        original_run = loop._run_agent_loop

        async def fake_run(messages, **kw):
            captured.append(messages)
            raise RuntimeError("stop")

        loop._run_agent_loop = fake_run

        with pytest.raises(RuntimeError, match="stop"):
            await loop._process_message(msg)

        assert len(captured) == 1
        user_msgs = [m for m in captured[0] if m.get("role") == "user"]
        assert any("[Image: a cat]" in str(m.get("content", "")) for m in user_msgs)


class TestHookModifiesMedia:
    """Hook can clear or filter the media list before extract_documents."""

    @pytest.mark.asyncio
    async def test_media_cleared(self, tmp_path: Path) -> None:
        """Hook clears media → extract_documents sees nothing, no image_url in LLM messages."""
        hook = _RecordingHook(set_media=[], set_media_text="[processed]")
        loop = _make_loop(tmp_path, hooks=[hook])
        msg = _make_msg(tmp_path, media_count=2, content="see images")

        captured: list[list[dict]] = []

        async def fake_run(messages, **kw):
            captured.append(messages)
            raise RuntimeError("stop")

        loop._run_agent_loop = fake_run

        with pytest.raises(RuntimeError, match="stop"):
            await loop._process_message(msg)

        # No image_url should appear in messages sent to LLM
        all_content = str(captured[0])
        assert "image_url" not in all_content
        assert "[processed]" in all_content

    @pytest.mark.asyncio
    async def test_media_partially_filtered(self, tmp_path: Path) -> None:
        """Hook removes one of two images → only one reaches extract_documents."""
        msg = _make_msg(tmp_path, media_count=2, content="see images")
        keep = [msg.media[0]] if msg.media else []

        hook = _RecordingHook(set_media=keep)
        loop = _make_loop(tmp_path, hooks=[hook])

        captured: list[list[dict]] = []

        async def fake_run(messages, **kw):
            captured.append(messages)
            raise RuntimeError("stop")

        loop._run_agent_loop = fake_run

        with pytest.raises(RuntimeError, match="stop"):
            await loop._process_message(msg)

        # Count image_url blocks — should be exactly 1
        user_msgs = [m for m in captured[0] if m.get("role") == "user"]
        for m in user_msgs:
            content = m.get("content", "")
            if isinstance(content, list):
                img_count = sum(1 for b in content if b.get("type") == "image_url")
                assert img_count == 1, f"expected 1 image, got {img_count}"
