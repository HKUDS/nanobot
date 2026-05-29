import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop, TurnContext, TurnState
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ChannelsConfig
from nanobot.providers.base import LLMResponse


def _make_loop(tmp_path: Path, channels_config: ChannelsConfig | None = None) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        channels_config=channels_config,
    )


@pytest.mark.asyncio
async def test_state_restore_extracts_documents_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop(tmp_path)
    doc_path = tmp_path / "report.txt"
    doc_path.write_text("Quarterly revenue is $5M", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []

    def fake_extract_documents(content: str, media: list[str]) -> tuple[str, list[str]]:
        calls.append((content, media))
        return f"{content}\n\n[File: report.txt]\nQuarterly revenue is $5M", []

    monkeypatch.setattr("nanobot.agent.loop.extract_documents", fake_extract_documents)

    ctx = TurnContext(
        msg=InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content="summarize",
            media=[str(doc_path)],
        ),
        session_key="cli:c",
        state=TurnState.RESTORE,
        turn_id="turn-1",
    )

    assert await loop._state_restore(ctx) == "ok"

    assert calls == [("summarize", [str(doc_path)])]
    assert "Quarterly revenue" in ctx.msg.content
    assert ctx.msg.media == []


@pytest.mark.asyncio
async def test_state_restore_references_documents_when_extraction_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop(tmp_path, ChannelsConfig(extract_document_text=False))
    doc_path = tmp_path / "report.txt"
    doc_path.write_text("Quarterly revenue is $5M", encoding="utf-8")

    def fail_extract_documents(content: str, media: list[str]) -> tuple[str, list[str]]:
        raise AssertionError("document extraction should be disabled")

    monkeypatch.setattr("nanobot.agent.loop.extract_documents", fail_extract_documents)

    ctx = TurnContext(
        msg=InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content="summarize",
            media=[str(doc_path)],
        ),
        session_key="cli:c",
        state=TurnState.RESTORE,
        turn_id="turn-1",
    )

    assert await loop._state_restore(ctx) == "ok"

    assert "Quarterly revenue" not in ctx.msg.content
    assert f"[Attachment: {doc_path}]" in ctx.msg.content
    assert ctx.msg.media == []


@pytest.mark.asyncio
async def test_pending_followup_references_documents_when_extraction_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc_path = tmp_path / "followup.txt"
    doc_path.write_text("Do not inject this file body", encoding="utf-8")
    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages: list[dict], **kwargs: object) -> LLMResponse:
        call_count["n"] += 1
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(content=f"answer-{call_count['n']}", tool_calls=[], usage={})

    loop = _make_loop(tmp_path, ChannelsConfig(extract_document_text=False))
    loop.provider.chat_with_retry = chat_with_retry
    loop.tools.get_definitions = MagicMock(return_value=[])

    def fail_extract_documents(content: str, media: list[str]) -> tuple[str, list[str]]:
        raise AssertionError("document extraction should be disabled")

    monkeypatch.setattr("nanobot.agent.loop.extract_documents", fail_extract_documents)

    pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending_queue.put(
        InboundMessage(
            channel="cli",
            sender_id="u",
            chat_id="c",
            content="check this",
            media=[str(doc_path)],
        )
    )

    final_content, _, _, _, had_injections = await loop._run_agent_loop(
        [{"role": "user", "content": "hello"}],
        channel="cli",
        chat_id="c",
        pending_queue=pending_queue,
    )

    assert final_content == "answer-2"
    assert had_injections is True
    injected_user_content = [
        message["content"]
        for message in captured_messages[-1]
        if message.get("role") == "user" and isinstance(message.get("content"), str)
    ][-1]
    assert "check this" in injected_user_content
    assert f"[Attachment: {doc_path}]" in injected_user_content
    assert "Do not inject this file body" not in injected_user_content


def test_document_extraction_disabled_still_preserves_images(tmp_path: Path) -> None:
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
        )
    )
    doc_path = tmp_path / "report.txt"
    doc_path.write_text("manual extraction target", encoding="utf-8")

    content, media = AgentLoop._reference_non_image_attachments(
        "review these",
        [str(image_path), str(doc_path)],
    )

    assert media == [str(image_path)]
    assert f"[Attachment: {doc_path}]" in content
