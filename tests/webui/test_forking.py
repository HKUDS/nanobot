from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import nanobot.webui.forking as forking
from nanobot.session.webui_turns import WEBUI_TITLE_METADATA_KEY


def test_create_fork_rebuilds_missing_transcript_and_saves_clean_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forked = SimpleNamespace(messages=[{"role": "user", "content": "hello"}], metadata={})
    manager = MagicMock()
    manager.fork_session_before_user_index.return_value = forked
    rebuild = MagicMock()
    marker = MagicMock()
    monkeypatch.setattr(forking.uuid, "uuid4", lambda: "fork-id")
    monkeypatch.setattr(forking, "fork_transcript_before_user_index", lambda *_args: False)
    monkeypatch.setattr(forking, "write_session_messages_as_transcript", rebuild)
    monkeypatch.setattr(forking, "append_fork_marker", marker)

    result = forking.create_webui_chat_fork(
        manager,
        source_chat_id="source",
        before_user_index=2,
        title="  Useful fork  ",
    )

    assert result == ("fork-id", "websocket:fork-id")
    manager.fork_session_before_user_index.assert_called_once_with(
        "websocket:source",
        "websocket:fork-id",
        2,
    )
    rebuild.assert_called_once_with("websocket:fork-id", forked.messages)
    marker.assert_called_once_with("websocket:fork-id")
    assert forked.metadata[WEBUI_TITLE_METADATA_KEY] == "Useful fork"
    manager.save.assert_called_once_with(forked, fsync=True)


def test_create_fork_rolls_back_session_and_transcript_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MagicMock()
    manager.fork_session_before_user_index.return_value = SimpleNamespace(
        messages=[],
        metadata={},
    )
    delete_transcript = MagicMock()
    monkeypatch.setattr(forking.uuid, "uuid4", lambda: "failed-fork")
    monkeypatch.setattr(
        forking,
        "fork_transcript_before_user_index",
        MagicMock(side_effect=OSError("disk full")),
    )
    monkeypatch.setattr(forking, "delete_webui_transcript", delete_transcript)

    with pytest.raises(OSError, match="disk full"):
        forking.create_webui_chat_fork(
            manager,
            source_chat_id="source",
            before_user_index=1,
        )

    delete_transcript.assert_called_once_with("websocket:failed-fork")
    manager.delete_session.assert_called_once_with("websocket:failed-fork")


def test_create_fork_stops_before_transcript_work_when_source_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MagicMock()
    manager.fork_session_before_user_index.return_value = None
    fork_transcript = MagicMock()
    monkeypatch.setattr(forking, "fork_transcript_before_user_index", fork_transcript)

    result = forking.create_webui_chat_fork(
        manager,
        source_chat_id="missing",
        before_user_index=1,
    )

    assert result is None
    fork_transcript.assert_not_called()


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
    monkeypatch.setattr(forking, "create_webui_chat_fork", lambda *_args, **_kwargs: None)

    await forking.handle_webui_fork_chat(channel, connection, envelope)
    channel.send_webui_protocol_error.assert_awaited_once_with(
        connection,
        "invalid fork source or index",
    )

    channel.send_webui_protocol_error.reset_mock()
    monkeypatch.setattr(
        forking,
        "create_webui_chat_fork",
        MagicMock(side_effect=RuntimeError("broken transcript")),
    )
    await forking.handle_webui_fork_chat(channel, connection, envelope)

    warning.assert_called_once_with("fork_chat failed: {}", ANY)
    channel.send_webui_protocol_error.assert_awaited_once_with(connection, "fork_chat_failed")
