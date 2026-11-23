import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import AsyncOpenAI

from nanobot.agent.context import TranscriptInput
from nanobot.agent.loop import AgentLoop, TurnContext, TurnKind
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ChannelsConfig
from nanobot.providers.base import LLMResponse
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ModelAPICapabilities
from nanobot.runtime_context import public_history_message
from nanobot.utils.document import reference_non_image_attachments


def _make_loop(
    workspace: Path,
    channels_config: ChannelsConfig | None = None,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))
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
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")

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
    assert public_history_message(persisted.messages[0])["content"] == (
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

    async def chat_stream_with_retry(*, messages: list[dict], **kwargs: object) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        captured_messages.append([dict(message) for message in messages])
        return LLMResponse(content=f"answer-{call_count}", tool_calls=[], usage=None)

    loop = _make_loop(workspace)
    loop.provider.chat_stream_with_retry = chat_stream_with_retry
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

    assert result.final_content == "answer-1"
    assert result.had_injections is True
    assert call_count == 1
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


@pytest.mark.asyncio
async def test_borrowed_image_origin_survives_canonical_reload(tmp_path: Path) -> None:
    from nanobot.webui.transcript import build_session_thread_response

    source = tmp_path / "borrowed.png"
    source.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
    ))
    loop = _make_loop(tmp_path)
    loop._run_agent_loop = AsyncMock(side_effect=RuntimeError("interrupt"))
    message = InboundMessage(
        channel="websocket", sender_id="u", chat_id="borrowed-origin", content="look",
        media=[str(source)], metadata={"local_media_paths": [str(source)]},
    )
    with pytest.raises(RuntimeError, match="interrupt"):
        await loop._process_message(message)
    loop.sessions.invalidate(message.session_key)
    persisted = loop.sessions.get_or_create(message.session_key)
    assert persisted.messages[0]["local_media_paths"] == [str(source)]
    augment = MagicMock(return_value=[{"kind": "image", "url": "/borrowed"}])
    response = build_session_thread_response(persisted, augment_user_media=augment)
    augment.assert_called_once_with([str(source)], [str(source)])
    assert response["events"][0]["text"] == "look"
    assert response["events"][0]["media_urls"][0]["url"] == "/borrowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["Compare these images", ""])
async def test_user_images_replay_in_order_after_cold_reload(tmp_path: Path, prompt: str) -> None:
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
    gif = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    first, second = tmp_path / "first.png", tmp_path / "second.gif"
    first.write_bytes(base64.b64decode(png))
    second.write_bytes(base64.b64decode(gif))
    expected = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/gif;base64,{gif}"}},
    ]
    if prompt:
        expected.append({"type": "text", "text": prompt})
    key = "websocket:image-reference"
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body["messages"])
        event = {
            "id": "chat_1", "created": 1, "object": "chat.completion.chunk", "model": body["model"],
            "choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": "stop"}],
        }
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n",
        )

    def new_loop() -> AgentLoop:
        provider = OpenAICompatProvider(
            api_key="fixture", default_model="gpt-4o",
            model_api=ModelAPICapabilities(("chat_completions",), "chat_completions"),
        )
        provider._client = AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        return AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="gpt-4o")

    loop = new_loop()
    try:
        await loop.process_direct(prompt, session_key=key, media=[str(first), str(second)])
    finally:
        await loop.aclose()

    first.unlink()
    cold = new_loop()
    try:
        await cold.process_direct("What was in the first image?", session_key=key)
        initial, following = requests
        first_request = initial[-1]["content"]
        assert first_request[:len(expected)] == expected
        previous = next(message for message in following if message["role"] == "user")
        assert previous["content"] == first_request
        stored = cold.sessions.get_or_create(key).messages[0]
        assert stored["media"] == [str(first), str(second)]
        assert "base64," not in repr(stored)
    finally:
        await cold.aclose()
