"""Tests for the read_image tool and related loop persistence behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.session.manager import Session


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestReadImageTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        from nanobot.agent.tools.read_image import ReadImageTool

        return ReadImageTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_read_image_returns_multimodal_blocks(self, tool, tmp_path):
        image_path = tmp_path / "pixel.png"
        image_path.write_bytes(PNG_1X1)

        result = await tool.execute(path=str(image_path))

        assert isinstance(result, list)
        assert result[0]["type"] == "image_url"
        assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert result[1] == {
            "type": "text",
            "text": "[Image: pixel.png, 0 KB, image/png]",
        }

    @pytest.mark.asyncio
    async def test_read_image_rejects_non_image_file(self, tool, tmp_path):
        text_path = tmp_path / "note.txt"
        text_path.write_text("not an image", encoding="utf-8")

        result = await tool.execute(path=str(text_path))

        assert result == "Error: not a recognized image file (.txt)"


@pytest.mark.asyncio
async def test_save_turn_strips_base64_from_tool_image_results(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch.object(AgentLoop, "_register_default_tools", lambda self: None), \
         patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")

    session = Session(key="cli:test")
    loop._save_turn(
        session,
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "show image"},
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "read_image",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    {"type": "text", "text": "[Image: pixel.png, 1 KB, image/png]"},
                ],
            },
        ],
        skip=2,
    )

    assert len(session.messages) == 1
    saved = session.messages[0]
    assert saved["role"] == "tool"
    assert saved["content"] == [{"type": "text", "text": "[Image: pixel.png, 1 KB, image/png]"}]
    assert "timestamp" in saved
