import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import TranscriptInput
from nanobot.agent.loop import AgentLoop, TurnContext, TurnKind
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ChannelsConfig
from nanobot.providers.base import LLMResponse
from nanobot.utils.document import reference_non_image_attachments


def _make_loop(
    workspace: Path,
    channels_config: ChannelsConfig | None = None,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=workspace,
        model="test-model",
        channels_config=channels_config,
    )


def _turn_context(loop: AgentLoop, msg: InboundMessage) -> TurnContext:
    return TurnContext(
        msg=msg,
        session_key=f"{msg.channel}:{msg.chat_id}",
        turn_id="turn-1",
        runtime=loop.llm_runtime(),
        kind=TurnKind.USER,
        delivery=loop.turn_delivery_factory.create(msg, f"{msg.channel}:{msg.chat_id}"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("extract_document_text", [True, False])
async def test_document_attachment_is_referenced_and_read_on_demand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extract_document_text: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    csv_path = media_dir / "report.csv"
    csv_path.write_text("name,value\nnanobot,1", encoding="utf-8")
    monkeypatch.setattr("nanobot.agent.tools.path_utils.get_media_dir", lambda: media_dir)

    loop = _make_loop(
        workspace,
        ChannelsConfig(extract_document_text=extract_document_text),
    )
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="c",
        content="import this report",
        media=[str(csv_path)],
    )
    ctx = _turn_context(loop, msg)

    await loop._restore_turn(ctx)

    assert ctx.msg.content == f"import this report\n\n[Attachment: {csv_path}]"
    assert "name,value" not in ctx.msg.content
    assert ctx.msg.media == []

    read_tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
    result = await read_tool.execute(path=str(csv_path))

    assert "1| name,value" in result
    assert "2| nanobot,1" in result


@pytest.mark.asyncio
async def test_document_reference_survives_session_reload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    doc_path = tmp_path / "report.csv"
    doc_path.write_text("name,value", encoding="utf-8")

    loop = _make_loop(workspace)
    loop._run_agent_loop = AsyncMock(side_effect=RuntimeError("interrupt"))  # type: ignore[method-assign]
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="persisted-attachment",
        content="review this",
        media=[str(doc_path)],
    )

    with pytest.raises(RuntimeError, match="interrupt"):
        await loop._process_message(msg)

    session_key = "websocket:persisted-attachment"
    loop.sessions.invalidate(session_key)
    persisted = loop.sessions.get_or_create(session_key)

    assert [message["role"] for message in persisted.messages] == ["user"]
    assert persisted.messages[0]["content"] == (
        f"review this\n\n[Attachment: {doc_path.resolve()}]"
    )
    assert "media" not in persisted.messages[0]


@pytest.mark.asyncio
async def test_pending_document_attachment_keeps_body_out_of_prompt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    doc_path = tmp_path / "followup.txt"
    doc_path.write_text("Do not inject this file body", encoding="utf-8")
    captured_messages: list[list[dict]] = []
    call_count = 0

    async def chat_with_retry(*, messages: list[dict], **kwargs: object) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(content=f"answer-{call_count}", tool_calls=[], usage=None)

    loop = _make_loop(workspace)
    loop.provider.chat_with_retry = chat_with_retry
    loop.tools.get_definitions = MagicMock(return_value=[])

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

    runtime = loop.llm_runtime()
    result = await loop._run_agent_loop(
        TranscriptInput(
            history=[{"role": "user", "content": "hello"}],
            current_message=None,
        ),
        runtime=runtime,
        request_context=RequestContext(channel="cli", chat_id="c", runtime=runtime),
        pending_queue=pending_queue,
    )

    assert result.final_content == "answer-2"
    assert result.had_injections is True
    injected_user_content = [
        message["content"]
        for message in captured_messages[-1]
        if message.get("role") == "user" and isinstance(message.get("content"), str)
    ][-1]
    assert "check this" in injected_user_content
    assert f"[Attachment: {doc_path}]" in injected_user_content
    assert "Do not inject this file body" not in injected_user_content


def test_attachment_references_still_preserve_images(tmp_path: Path) -> None:
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
        )
    )
    doc_path = tmp_path / "report.txt"
    doc_path.write_text("manual extraction target", encoding="utf-8")

    content, media = reference_non_image_attachments(
        "review these",
        [str(image_path), str(doc_path)],
    )

    assert media == [str(image_path)]
    assert f"[Attachment: {doc_path}]" in content
    assert "manual extraction target" not in content


def test_attachment_references_canonicalize_existing_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
        )
    )
    doc_path = tmp_path / "report.csv"
    doc_path.write_text("name,value", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    content, media = reference_non_image_attachments(
        "review these",
        [image_path.name, doc_path.name],
    )

    assert media == [str(image_path.resolve())]
    assert f"[Attachment: {doc_path.resolve()}]" in content
