from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.session_messages import ListSessionsTool, SendSessionMessageTool
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandleDirectory
from nanobot.session.session_messages import (
    SESSION_MESSAGE_METADATA_KEY,
    SESSION_REPLY_TIMEOUT_METADATA_KEY,
)


def test_send_session_message_requires_an_explicit_boolean_reply_contract(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(tmp_path / "state")
    parameters = SendSessionMessageTool(
        sessions=sessions,
        bus=MessageBus(),
    ).parameters

    assert parameters["required"] == ["to", "content", "expect_reply"]
    assert parameters["properties"]["expect_reply"]["type"] == "boolean"
    timeout = parameters["properties"]["reply_timeout_seconds"]
    assert (timeout["type"], timeout["minimum"], timeout["maximum"]) == (
        "integer",
        5,
        60,
    )


def test_session_message_rate_limit_config_defaults_to_six_per_minute() -> None:
    assert ToolsConfig().max_session_messages_per_minute == 6
    configured = ToolsConfig.model_validate({"maxSessionMessagesPerMinute": 9})
    assert configured.max_session_messages_per_minute == 9

    with pytest.raises(ValueError):
        ToolsConfig(max_session_messages_per_minute=0)


def _session_message_metadata(*, expect_reply: bool = True) -> dict[str, object]:
    return {
        SESSION_MESSAGE_METADATA_KEY: {
            "message_id": "handle-message-1",
            "created_at_ms": 1,
            "expect_reply": expect_reply,
            "source": {
                "name": "reviewer",
                "session_key": "websocket:reviewer",
                "handle_id": "handle_reviewer",
                "color_slot": 1,
            },
            "target": {
                "name": "author",
                "session_key": "websocket:author",
            },
        },
    }


def _reply_timeout_metadata() -> dict[str, object]:
    return {
        SESSION_REPLY_TIMEOUT_METADATA_KEY: {
            "created_at_ms": 1,
            "message_id": "handle-message-1",
            "expect_reply": True,
            "timeout_seconds": 60,
            "source": {
                "name": "author",
                "session_key": "websocket:author",
                "handle_id": "handle_author",
                "color_slot": 2,
            },
            "target": {
                "name": "reviewer",
                "session_key": "websocket:reviewer",
            },
        },
    }


def _save_session(
    sessions: SessionManager,
    key: str,
    *,
    workspace: Path,
    title: str,
    webui: bool,
) -> None:
    session = sessions.get_or_create(key)
    session.metadata.update({
        "title": title,
        "webui": webui,
        WORKSPACE_SCOPE_METADATA_KEY: {
            "project_path": str(workspace.resolve()),
            "access_mode": "restricted",
        },
    })
    sessions.save(session, fsync=True)


def _empty_send_tool(tmp_path: Path) -> SendSessionMessageTool:
    return SendSessionMessageTool(
        sessions=SessionManager(tmp_path / "state"),
        bus=MessageBus(),
    )


@pytest.mark.asyncio
async def test_send_session_message_uses_configured_per_minute_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sessions = SessionManager(tmp_path / "state")
    for key in ("websocket:lead", "websocket:reviewer"):
        _save_session(sessions, key, workspace=workspace, title=key, webui=True)
    directory = SessionHandleDirectory(sessions)
    handles = directory.ensure_many(["websocket:lead", "websocket:reviewer"])
    reviewer = handles["websocket:reviewer"]
    tool = SendSessionMessageTool.create(ToolContext(
        config=ToolsConfig(max_session_messages_per_minute=1),
        workspace=str(workspace),
        bus=MessageBus(),
        sessions=sessions,
    ))

    with request_context(RequestContext(
        channel="websocket",
        chat_id="lead",
        session_key="websocket:lead",
        workspace=workspace,
    )):
        first = await tool.execute(
            to=f"@{reviewer.name}",
            content="First",
            expect_reply=False,
        )
        second = await tool.execute(
            to=f"@{reviewer.name}",
            content="Second",
            expect_reply=False,
        )

    assert first == f"Sent to @{reviewer.name}."
    assert isinstance(second, ToolResult)
    assert second.is_error
    assert "1 per minute" in str(second)


@pytest.mark.asyncio
async def test_send_session_message_queues_user_input_for_target_session(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sessions = SessionManager(tmp_path / "state")
    for key in ("websocket:lead", "websocket:reviewer"):
        _save_session(sessions, key, workspace=workspace, title=key, webui=True)
    directory = SessionHandleDirectory(sessions)
    reviewer = directory.ensure_many(["websocket:lead", "websocket:reviewer"])[
        "websocket:reviewer"
    ]
    bus = MessageBus()
    tool = SendSessionMessageTool(sessions=sessions, bus=bus, directory=directory)
    with request_context(RequestContext(
        channel="websocket",
        chat_id="lead",
        session_key="websocket:lead",
        turn_id="turn-1",
        workspace=workspace,
        metadata={"safe": "context"},
    )):
        result = await tool.execute(
            to=f"@{reviewer.name}",
            content="Review this",
            expect_reply=False,
        )

    assert result == f"Sent to @{reviewer.name}."
    inbound = bus.inbound.get_nowait()
    assert inbound.session_key_override == "websocket:reviewer"
    assert inbound.content == "Review this"


@pytest.mark.asyncio
async def test_send_session_message_requires_a_session_context(tmp_path: Path) -> None:
    tool = _empty_send_tool(tmp_path)

    result = await tool.execute(
        to="@reviewer",
        content="Review this",
        expect_reply=True,
        reply_timeout_seconds=60,
    )

    assert isinstance(result, ToolResult)
    assert result.is_error


@pytest.mark.asyncio
async def test_send_session_message_guides_a_requested_reply(tmp_path: Path) -> None:
    tool = _empty_send_tool(tmp_path)
    provider = tool.runtime_context_provider()

    block = await provider(RequestContext(
        channel="websocket",
        chat_id="author",
        metadata=_session_message_metadata(),
    ))

    assert block is not None
    assert block.source == "session_collaboration"
    assert block.content == "Message from @reviewer. Reply with send_session_message."


@pytest.mark.asyncio
async def test_send_session_message_omits_unrequested_reply_guidance(tmp_path: Path) -> None:
    tool = _empty_send_tool(tmp_path)
    provider = tool.runtime_context_provider()

    block = await provider(RequestContext(
        channel="websocket",
        chat_id="author",
        metadata=_session_message_metadata(expect_reply=False),
    ))

    assert block is not None
    assert block.source == "session_collaboration"
    assert block.content == "Message from @reviewer."


@pytest.mark.asyncio
async def test_send_session_message_guides_a_timed_out_reply(tmp_path: Path) -> None:
    tool = _empty_send_tool(tmp_path)
    provider = tool.runtime_context_provider()

    block = await provider(RequestContext(
        channel="system",
        chat_id="websocket:author",
        metadata=_reply_timeout_metadata(),
    ))

    assert block is not None
    assert block.source == "session_collaboration"
    assert block.content == "No reply from @reviewer after 60s."


@pytest.mark.asyncio
async def test_session_runtime_context_identifies_self_and_verified_mentions(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "state")
    source_key = "websocket:source"
    target_key = "websocket:handle"
    _save_session(sessions, source_key, workspace=project, title="Source", webui=True)
    _save_session(sessions, target_key, workspace=project, title="Session", webui=True)
    directory = SessionHandleDirectory(sessions)
    handles = directory.ensure_many([source_key, target_key])
    source = handles[source_key]
    handle = handles[target_key]
    provider = ListSessionsTool(sessions).runtime_context_provider()

    block = await provider(RequestContext(
        channel="websocket",
        chat_id="source",
        session_key=source_key,
        workspace=project,
        metadata={
            "session_handles": [{
                **handle.public_payload(),
                "session_key": handle.session_key,
            }],
        },
    ))

    assert block is not None
    assert block.source == "session_handle"
    assert block.content == (
        f"Your handle: @{source.name}.\n"
        f"Mentioned sessions: @{handle.name}."
    )


@pytest.mark.asyncio
async def test_list_sessions_returns_all_session_handles_across_workspaces(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    other_project = tmp_path / "other"
    project.mkdir()
    other_project.mkdir()
    sessions = SessionManager(tmp_path / "state")
    source_key = "websocket:source"
    target_key = "websocket:handle"
    external_key = "telegram:external"
    other_key = "websocket:other"
    _save_session(
        sessions,
        source_key,
        workspace=project,
        title="The source title must stay private",
        webui=True,
    )
    _save_session(
        sessions,
        target_key,
        workspace=project,
        title="The handle title must stay private",
        webui=True,
    )
    _save_session(
        sessions,
        external_key,
        workspace=project,
        title="External conversation",
        webui=False,
    )
    _save_session(
        sessions,
        other_key,
        workspace=other_project,
        title="Other workspace",
        webui=True,
    )
    directory = SessionHandleDirectory(sessions)

    tool = ListSessionsTool(sessions)
    with request_context(RequestContext(
        channel="websocket",
        chat_id="source",
        session_key=source_key,
        workspace=project,
    )):
        result = json.loads(await tool.execute())

    handles = directory.ensure_many([target_key, source_key, external_key, other_key])
    handle = handles[target_key]
    source = handles[source_key]
    external = handles[external_key]
    other = handles[other_key]
    assert result == sorted([
        f"@{handle.name}",
        f"@{external.name}",
        f"@{other.name}",
    ])
    assert f"@{source.name}" not in result
    encoded = json.dumps(result)
    assert "title" not in encoded
    assert "session_key" not in encoded
    assert str(project) not in encoded
    assert str(other_project) not in encoded
    assert tool.read_only is True


@pytest.mark.asyncio
async def test_list_sessions_requires_trusted_turn_context(tmp_path: Path) -> None:
    tool = ListSessionsTool(SessionManager(tmp_path / "state"))

    result = await tool.execute()

    assert isinstance(result, ToolResult)
    assert result.startswith("Error:")
    assert result.is_error


@pytest.mark.asyncio
async def test_list_sessions_supports_non_webui_source_and_allocates_all_handles(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionManager(tmp_path / "state")
    source_key = "telegram:source"
    target_key = "websocket:handle"
    _save_session(
        sessions,
        source_key,
        workspace=project,
        title="External source",
        webui=False,
    )
    _save_session(
        sessions,
        target_key,
        workspace=project,
        title="WebUI handle",
        webui=True,
    )
    directory = SessionHandleDirectory(sessions)
    tool = ListSessionsTool(sessions)

    request = RequestContext(
        channel="telegram",
        chat_id="source",
        session_key=source_key,
        workspace=project,
    )
    with request_context(request):
        result = await tool.execute()
    block = await tool.runtime_context_provider()(request)

    handles = directory.ensure_many([source_key, target_key])
    assert result == json.dumps([f"@{handles[target_key].name}"])
    assert block is not None
    assert block.content == f"Your handle: @{handles[source_key].name}."
    assert directory.store_path.exists()


def test_list_sessions_is_auto_discovered() -> None:
    discovered = ToolLoader().discover()
    assert ListSessionsTool in discovered
    assert SendSessionMessageTool in discovered
    assert not any(tool.__name__ == "ReplySessionTool" for tool in discovered)
