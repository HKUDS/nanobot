import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop, TurnContext, TurnKind
from nanobot.agent.tools.filesystem import (
    AttachmentReadFileTool,
    FileToolsConfig,
    ReadFileTool,
)
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ChannelsConfig, ToolsConfig
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.utils.document import reference_non_image_attachments


def _make_loop(
    workspace: Path,
    channels_config: ChannelsConfig | None = None,
    tools_config: ToolsConfig | None = None,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=workspace,
        model="test-model",
        channels_config=channels_config,
        tools_config=tools_config,
        restrict_to_workspace=(
            tools_config.restrict_to_workspace
            if tools_config is not None
            else False
        ),
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
async def test_document_attachment_is_referenced_and_read_on_demand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    csv_path = media_dir / "report.csv"
    csv_path.write_text("name,value\nnanobot,1", encoding="utf-8")
    monkeypatch.setattr("nanobot.agent.tools.path_utils.get_media_dir", lambda: media_dir)

    loop = _make_loop(workspace, ChannelsConfig(extract_document_text=True))
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
    assert ctx.msg.media == [str(csv_path)]
    assert ctx.attachment_paths == [str(csv_path)]

    read_tool = ReadFileTool(workspace=workspace, allowed_dir=workspace)
    result = await read_tool.execute(path=str(csv_path))

    assert "1| name,value" in result
    assert "2| nanobot,1" in result


@pytest.mark.parametrize("file_tools_enabled", [True, False])
@pytest.mark.asyncio
async def test_attachment_read_access_survives_session_reload(
    tmp_path: Path,
    file_tools_enabled: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    custom_media_dir = tmp_path / "qq-custom-media"
    custom_media_dir.mkdir()
    attachment = custom_media_dir / "report.csv"
    attachment.write_text("name,value\nnanobot,7", encoding="utf-8")
    tools_config = ToolsConfig(
        file=FileToolsConfig(enable=file_tools_enabled),
        restrict_to_workspace=True,
    )

    first_loop = _make_loop(workspace, tools_config=tools_config)
    await first_loop._process_message(
        InboundMessage(
            channel="qq",
            sender_id="u",
            chat_id="c",
            content="keep this report",
            media=[str(attachment)],
        )
    )

    session = first_loop.sessions.get_or_create("qq:c")
    persisted_user = next(message for message in session.messages if message["role"] == "user")
    assert persisted_user["media"] == [str(attachment)]

    second_loop = _make_loop(workspace, tools_config=tools_config)
    if file_tools_enabled:
        assert isinstance(second_loop.tools.get("read_file"), ReadFileTool)
        assert not isinstance(second_loop.tools.get("read_file"), AttachmentReadFileTool)
    else:
        assert isinstance(second_loop.tools.get("read_file"), AttachmentReadFileTool)
    second_loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="read-attachment",
                    name="read_file",
                    arguments={"path": str(attachment)},
                )
            ],
            usage={},
        ),
        LLMResponse(content="read complete", tool_calls=[], usage={}),
    ])

    response = await second_loop._process_message(
        InboundMessage(
            channel="qq",
            sender_id="u",
            chat_id="c",
            content="read that attachment again",
        )
    )

    assert response is not None
    assert response.content == "read complete"
    final_request = second_loop.provider.chat_with_retry.await_args_list[-1].kwargs["messages"]
    tool_result = next(message for message in final_request if message["role"] == "tool")
    assert "2| nanobot,7" in tool_result["content"]


@pytest.mark.asyncio
async def test_process_direct_canonicalizes_relative_local_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()
    attachment = caller_dir / "relative.csv"
    attachment.write_text("name,value\nrelative,11", encoding="utf-8")
    monkeypatch.chdir(caller_dir)

    tools_config = ToolsConfig(
        file=FileToolsConfig(enable=False),
        restrict_to_workspace=True,
    )
    loop = _make_loop(workspace, tools_config=tools_config)
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="read-relative",
                    name="read_file",
                    arguments={"path": str(attachment.resolve())},
                )
            ],
            usage={},
        ),
        LLMResponse(content="relative read complete", tool_calls=[], usage={}),
    ])

    response = await loop.process_direct(
        "read this relative attachment",
        session_key="sdk:relative",
        media=["relative.csv"],
    )

    assert response is not None
    assert response.content == "relative read complete"
    first_request = loop.provider.chat_with_retry.await_args_list[0].kwargs["messages"]
    first_user_content = next(
        message["content"]
        for message in reversed(first_request)
        if message.get("role") == "user"
    )
    assert f"[Attachment: {attachment.resolve()}]" in str(first_user_content)
    session = loop.sessions.get_or_create("sdk:relative")
    persisted_user = next(message for message in session.messages if message["role"] == "user")
    assert persisted_user["media"] == [str(attachment.resolve())]
    final_request = loop.provider.chat_with_retry.await_args_list[-1].kwargs["messages"]
    tool_result = next(message for message in final_request if message["role"] == "tool")
    assert "2| relative,11" in tool_result["content"]


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
        return LLMResponse(content=f"answer-{call_count}", tool_calls=[], usage={})

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

    final_content, _, _, _, had_injections = await loop._run_agent_loop(
        [{"role": "user", "content": "hello"}],
        runtime=loop.llm_runtime(),
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


@pytest.mark.asyncio
async def test_pending_attachment_is_readable_and_persisted_with_file_tools_disabled(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    custom_media_dir = tmp_path / "custom-media"
    custom_media_dir.mkdir()
    first_attachment = custom_media_dir / "first.csv"
    first_attachment.write_text("name,value\nfirst,9", encoding="utf-8")
    second_attachment = custom_media_dir / "second.csv"
    second_attachment.write_text("name,value\nsecond,10", encoding="utf-8")
    tools_config = ToolsConfig(
        file=FileToolsConfig(enable=False),
        restrict_to_workspace=True,
    )
    loop = _make_loop(workspace, tools_config=tools_config)
    calls = 0
    captured_messages: list[list[dict]] = []

    async def chat_with_retry(*, messages: list[dict], **kwargs: object) -> LLMResponse:
        nonlocal calls
        calls += 1
        captured_messages.append([dict(message) for message in messages])
        if calls == 1:
            return LLMResponse(content="first answer", tool_calls=[], usage={})
        if calls == 2:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="read-pending-first",
                        name="read_file",
                        arguments={"path": str(first_attachment)},
                    ),
                    ToolCallRequest(
                        id="read-pending-second",
                        name="read_file",
                        arguments={"path": str(second_attachment)},
                    ),
                ],
                usage={},
            )
        return LLMResponse(content="pending read complete", tool_calls=[], usage={})

    loop.provider.chat_with_retry = chat_with_retry
    pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending_queue.put(
        InboundMessage(
            channel="qq",
            sender_id="u",
            chat_id="c",
            content="check first follow-up",
            media=[str(first_attachment)],
        )
    )
    await pending_queue.put(
        InboundMessage(
            channel="qq",
            sender_id="u",
            chat_id="c",
            content="check second follow-up",
            media=[str(second_attachment)],
        )
    )

    response = await loop._process_message(
        InboundMessage(
            channel="qq",
            sender_id="u",
            chat_id="c",
            content="start",
        ),
        pending_queue=pending_queue,
    )

    assert response is not None
    assert response.content == "pending read complete"
    tool_results = [
        message
        for message in captured_messages[-1]
        if message.get("role") == "tool"
    ]
    assert any("2| first,9" in result["content"] for result in tool_results)
    assert any("2| second,10" in result["content"] for result in tool_results)
    session = loop.sessions.get_or_create("qq:c")
    persisted_pending = next(
        message
        for message in session.messages
        if message.get("role") == "user"
        and "check first follow-up" in str(message.get("content"))
    )
    assert persisted_pending["media"] == [
        str(first_attachment),
        str(second_attachment),
    ]

    reloaded_loop = _make_loop(workspace, tools_config=tools_config)
    reloaded_loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="reload-first",
                    name="read_file",
                    arguments={"path": str(first_attachment)},
                ),
                ToolCallRequest(
                    id="reload-second",
                    name="read_file",
                    arguments={"path": str(second_attachment)},
                ),
            ],
            usage={},
        ),
        LLMResponse(content="reload read complete", tool_calls=[], usage={}),
    ])

    reloaded_response = await reloaded_loop._process_message(
        InboundMessage(
            channel="qq",
            sender_id="u",
            chat_id="c",
            content="read both follow-ups again",
        )
    )

    assert reloaded_response is not None
    assert reloaded_response.content == "reload read complete"
    final_request = reloaded_loop.provider.chat_with_retry.await_args_list[-1].kwargs["messages"]
    reloaded_tool_results = [
        message["content"]
        for message in final_request
        if message.get("role") == "tool"
    ]
    assert any("2| first,9" in result for result in reloaded_tool_results)
    assert any("2| second,10" in result for result in reloaded_tool_results)


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
