from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import nanobot.webui.forking as forking


@pytest.mark.parametrize(
    ("envelope", "detail"),
    [
        ({"source_chat_id": "bad/id", "before_user_index": 0}, "invalid source_chat_id"),
        ({"source_chat_id": "source", "before_user_index": True}, "invalid before_user_index"),
        ({"source_chat_id": "source", "before_user_index": -1}, "invalid before_user_index"),
    ],
)
@pytest.mark.asyncio
async def test_fork_handler_rejects_invalid_protocol_input(
    envelope: dict[str, object],
    detail: str,
) -> None:
    connection = object()
    channel = SimpleNamespace(
        send_webui_protocol_error=AsyncMock(),
        gateway=SimpleNamespace(session_manager=MagicMock()),
    )

    await forking.handle_webui_fork_chat(channel, connection, envelope)

    channel.send_webui_protocol_error.assert_awaited_once_with(connection, detail)


@pytest.mark.asyncio
async def test_fork_handler_reports_unavailable_session_manager() -> None:
    connection = object()
    channel = SimpleNamespace(
        send_webui_protocol_error=AsyncMock(),
        gateway=SimpleNamespace(session_manager=None),
    )

    await forking.handle_webui_fork_chat(
        channel,
        connection,
        {"source_chat_id": "source", "before_user_index": 0},
    )

    channel.send_webui_protocol_error.assert_awaited_once_with(
        connection,
        "session_manager_unavailable",
    )


@pytest.mark.asyncio
async def test_fork_handler_maps_invalid_source_and_internal_failure_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    channel = SimpleNamespace(
        send_webui_protocol_error=AsyncMock(),
        gateway=SimpleNamespace(session_manager=MagicMock()),
    )
    warning = MagicMock()
    monkeypatch.setattr(forking, "logger", SimpleNamespace(warning=warning))
    envelope = {"source_chat_id": "source", "before_user_index": 0}
    monkeypatch.setattr(forking, "create_webui_chat_fork", AsyncMock(return_value=None))

    await forking.handle_webui_fork_chat(channel, connection, envelope)
    channel.send_webui_protocol_error.assert_awaited_once_with(
        connection,
        "invalid fork source or index",
    )

    channel.send_webui_protocol_error.reset_mock()
    monkeypatch.setattr(
        forking,
        "create_webui_chat_fork",
        AsyncMock(side_effect=RuntimeError("broken transcript")),
    )
    await forking.handle_webui_fork_chat(channel, connection, envelope)

    warning.assert_called_once_with("fork_chat failed: {}", ANY)
    channel.send_webui_protocol_error.assert_awaited_once_with(connection, "fork_chat_failed")


@pytest.mark.parametrize("with_display", [False, True])
async def test_fork_copies_prefix_and_boundary_in_the_session_transaction(history, monkeypatch, with_display):
    sessions = history.sessions
    source = sessions.get_or_create("websocket:source")
    source.metadata.update(title="source title", session_handle="original", webui=True)
    for number in range(3):
        source.add_message("user", f"question {number}")
        source.add_message("assistant", f"answer {number}")
    sessions.save(source)
    if with_display:
        for number in range(3):
            history.append(source.key, {"event": "user", "text": f"question {number}"})
            history.append(source.key, {"event": "message", "text": f"answer {number}"})
            history.append(source.key, {"event": "turn_end"})
    monkeypatch.setattr(forking.uuid, "uuid4", lambda: "fork-id")
    result = await forking.create_webui_chat_fork(sessions, source_chat_id="source", before_user_index=2, title="  Useful fork  ")
    assert result == ("fork-id", "websocket:fork-id")
    forked = await sessions.state.get(result[1])
    assert [message["content"] for message in forked.messages] == ["question 0", "answer 0", "question 1", "answer 1"]
    assert forked.metadata["title"] == "Useful fork"
    assert forked.metadata.get("session_handle") != "original"
    payload = history.build(forked.key)
    visible = [event["text"] for event in payload["events"] if "text" in event]
    assert visible == ["question 0", "answer 0", "question 1", "answer 1"]
    assert payload["fork_boundary_event_index"] == len(payload["events"])
    assert (await sessions.state.get(source.key)).messages == source.messages


async def test_fork_missing_source_leaves_no_partial_session(history):
    assert await forking.create_webui_chat_fork(history.sessions, source_chat_id="missing", before_user_index=1) is None
    assert await history.sessions.state.list_sessions() == []
