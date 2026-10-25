"""WS envelope regressions; binary ingress is tested through the HTTP listener."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.websocket.runtime import (
    WebSocketChannel,
    WebSocketConfig,
)
from nanobot.runtime_context import RUNTIME_CONTEXT_INPUT_META
from nanobot.session import webui_turns as wth
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.webui.gateway_services import build_gateway_services


def _make_channel(
    session_manager: SessionManager | None = None, *, workspace: Path | None = None, restricted: bool = False,
) -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    cfg = {"enabled": True, "allowFrom": ["*"], "websocketRequiresToken": False}
    parsed = WebSocketConfig.model_validate(cfg)
    gateway = build_gateway_services(
        config=parsed,
        bus=bus,
        session_manager=session_manager,
        static_dist_path=None,
        workspace_path=workspace or Path.cwd(),
        default_restrict_to_workspace=restricted,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(cfg, bus, gateway=gateway)
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    return channel


@pytest.fixture(autouse=True)
def isolate_websocket_turn_state() -> None:
    wth._WEBSOCKET_ACTIVE_TURNS.clear()
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    wth._WEBSOCKET_TURN_IDS.clear()
    wth._WEBSOCKET_TURN_OWNERS.clear()
    yield
    wth._WEBSOCKET_ACTIVE_TURNS.clear()
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    wth._WEBSOCKET_TURN_IDS.clear()
    wth._WEBSOCKET_TURN_OWNERS.clear()


def test_max_message_bytes_keeps_existing_transport_guard() -> None:
    """Moving attachments to HTTP does not disable the configurable WS guard."""
    from nanobot.channels.websocket.runtime import WebSocketConfig

    default = WebSocketConfig().max_message_bytes
    assert default == 36 * 1024 * 1024
    assert WebSocketConfig(max_message_bytes=1048576).max_message_bytes == 1048576
    # The existing upper bound remains 40 MB.
    with pytest.raises(Exception):
        WebSocketConfig(max_message_bytes=41_943_040 + 1)


@pytest.mark.asyncio
async def test_message_without_media_backward_compatible(monkeypatch) -> None:
    """Existing clients that don't send ``media`` keep working unchanged."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {"type": "message", "chat_id": "abc123", "content": "hello"}
    monkeypatch.setattr(channel.gateway.uploads.store, "prune", lambda: pytest.fail("text send scanned upload staging"))

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    call = channel._handle_message.call_args
    assert call.kwargs["chat_id"] == "abc123"
    assert call.kwargs["content"] == "hello"
    # When no media, we pass ``media=None`` so downstream treats it as absent.
    assert call.kwargs["media"] is None


@pytest.mark.asyncio
async def test_webui_message_acceptance_echoes_turn_id() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "hello",
        "webui": True,
        "turn_id": "turn-accepted",
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    assert json.loads(mock_conn.send.await_args.args[0]) == {
        "event": "message_accepted",
        "chat_id": "abc123",
        "turn_id": "turn-accepted",
        "starts_turn": True,
        "active_turn_id": "turn-accepted",
        "started_at": wth.websocket_turn_wall_started_at("abc123"),
    }


@pytest.mark.asyncio
async def test_message_text_policy_is_independent_from_transport_limit() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "你" * 22_000,
        "turn_id": "turn-text-policy",
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err == {
        "event": "error",
        "chat_id": "abc123",
        "detail": "message_rejected",
        "reason": "text_too_large",
        "turn_id": "turn-text-policy",
    }


@pytest.mark.asyncio
async def test_message_forwards_normalized_cli_app_attachments() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "please use @drawio",
        "webui": True,
        "cli_apps": [
            {
                "name": "DrawIO",
                "display_name": "Draw.io",
                "category": "diagram",
                "entry_point": "cli-anything-drawio",
                "logo_url": "https://example.invalid/drawio.svg",
                "brand_color": "#F08705",
            },
            {"name": "bad name", "entry_point": "nope"},
        ],
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    metadata = channel._handle_message.call_args.kwargs["metadata"]
    assert metadata["webui"] is True
    assert metadata["cli_apps"] == [{
        "name": "drawio",
        "display_name": "Draw.io",
        "category": "diagram",
        "entry_point": "cli-anything-drawio",
        "logo_url": "https://example.invalid/drawio.svg",
        "brand_color": "#F08705",
    }]


@pytest.mark.asyncio
async def test_webui_message_forwards_verified_session_mentions(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    target = manager.get_or_create("websocket:pricing")
    target.metadata.update({"title": "Pricing", "title_user_edited": True})
    target.add_message("user", "Discuss cloud storage")
    manager.save(target)
    channel = _make_channel(manager)
    mock_conn = AsyncMock()
    channel._webui_connections.add(mock_conn)
    envelope = {
        "type": "message",
        "chat_id": "current",
        "content": "Use @pricing",
        "webui": True,
        "session_mentions": [{
            "name": "pricing",
            "session_key": "websocket:pricing",
            "title": "Untrusted title",
        }],
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    metadata = channel._handle_message.call_args.kwargs["metadata"]
    handle = await SessionHandleResolver(manager).ahandle_for_session("websocket:pricing")
    assert handle is not None
    assert metadata["session_mentions"] == [{
        **handle.public_payload(),
        "session_key": "websocket:pricing",
        "title": "Pricing",
    }]
    [block] = metadata[RUNTIME_CONTEXT_INPUT_META]
    assert block.source == "session_mentions"
    assert "websocket:pricing" in block.content


@pytest.mark.asyncio
async def test_message_rejected_when_media_item_shape_wrong(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "huh",
        # Not a dict — plain string at the top level.
        "media": ["data:image/png;base64,XXXX"],
    }

    with patch(
        "nanobot.webui.media_gateway.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["reason"] == "malformed"


@pytest.mark.asyncio
async def test_message_rejected_when_media_field_is_not_list() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "huh",
        "media": "not-a-list",
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "attachment_rejected"
    assert err["reason"] == "malformed"


@pytest.mark.asyncio
async def test_rejects_empty_text_without_media() -> None:
    """When no media is attached, whitespace-only content is still rejected
    (matches the existing behavior for backward compat)."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "   ",
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "missing content"


@pytest.mark.asyncio
async def test_non_string_content_still_rejected() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": 42,
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "missing content"


@pytest.mark.asyncio
async def test_reference_attachments_are_projected_to_other_clients(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    channel = _make_channel()
    origin, peer = AsyncMock(), AsyncMock()
    owner = channel.gateway.uploads.issue(origin)["token"]
    channel._attach(origin, "reference-chat")
    channel._attach(peer, "reference-chat")
    channel._webui_connections.add(origin)

    async def body():
        yield b"image"

    reference = await channel.gateway.uploads.store.upload(
        body(), owner=owner, mime="image/png", size=5,
    )
    await channel._dispatch_envelope(origin, "client", {
        "type": "message", "chat_id": "reference-chat", "content": "",
        "webui": True, "turn_id": "reference-turn",
        "media": [{"reference": reference, "name": "shot.png"}],
    })
    channel._handle_message.assert_awaited_once()
    assert Path(channel._handle_message.call_args.kwargs["media"][0]).read_bytes() == b"image"
    payload = json.loads(peer.send.await_args.args[0])
    assert payload["event"] == "user_message"
    assert payload["media_urls"][0]["name"] == "shot.png"
    assert payload["media_urls"][0]["url"].startswith("/api/media/")
    assert reference not in str(payload)
    accepted = json.loads(origin.send.await_args.args[0])
    assert accepted["event"] == "message_accepted"
    assert accepted["media_urls"] == payload["media_urls"]


@pytest.mark.asyncio
async def test_local_reference_inspection_send_recheck_and_no_staging(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    workspace = tmp_path / "project"
    workspace.mkdir()
    source = workspace / "clip #100%.mp4"
    source.write_bytes(b"\0video")
    channel = _make_channel(workspace=workspace, restricted=True)
    conn = AsyncMock()
    channel._webui_connections.add(conn)

    async def inspect(path):
        conn.send.reset_mock()
        await channel._dispatch_envelope(conn, "client", {
            "type": "webui_request", "request_id": "inspect", "action": "attachment.inspect",
            "payload": {"chat_id": "local-chat", "path": path},
        })
        return json.loads(conn.send.await_args.args[0])

    result = await inspect(source.name)
    assert result["ok"] is True
    local = result["result"]
    assert local["path"] == str(source)
    assert local["size"] == 6
    assert local["kind"] == "video"
    assert channel.gateway.uploads.store._entries == {}
    assert not list(channel.gateway.uploads.store.media_dir.glob("*"))
    assert channel._webui_request_operations == {}

    for invalid in ("missing.mp4", str(workspace), str(tmp_path / "outside.mp4")):
        failure = await inspect(invalid)
        assert failure["ok"] is False

    message = {
        "type": "message", "chat_id": "local-chat", "content": "keep my text",
        "webui": True, "turn_id": "local-turn", "media": [{"path": local["path"]}],
    }
    source.unlink()
    await channel._dispatch_envelope(conn, "client", message)
    assert json.loads(conn.send.await_args.args[0])["detail"] == "attachment_rejected"
    channel._handle_message.assert_not_awaited()
    source.write_bytes(b"latest video")
    await channel._dispatch_envelope(conn, "client", message)
    channel._handle_message.assert_awaited_once()
    assert channel._handle_message.await_args.kwargs["media"] == [str(source)]
    assert channel._handle_message.await_args.kwargs["metadata"]["local_media_paths"] == [str(source)]
    assert source.read_bytes() == b"latest video"
    assert not list(channel.gateway.uploads.store.media_dir.glob("*"))


@pytest.mark.asyncio
async def test_mixed_local_and_uploaded_video_limit_keeps_upload_for_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    source = tmp_path / "local.webm"
    source.write_bytes(b"video")
    channel = _make_channel(workspace=tmp_path, restricted=True)
    conn = AsyncMock()
    owner = channel.gateway.uploads.issue(conn)["token"]

    async def body():
        yield b"upload"

    ref = await channel.gateway.uploads.store.upload(body(), owner=owner, mime="video/mp4", size=6)
    await channel._dispatch_envelope(conn, "client", {
        "type": "message", "chat_id": "mixed-local", "content": "retained",
        "media": [{"path": str(source)}, {"reference": ref}],
    })
    assert json.loads(conn.send.await_args.args[0])["detail"] == "attachment_rejected"
    assert channel.gateway.uploads.store.resolve([ref], owner=owner)
    assert source.exists()
    channel._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_temporary_chat_disposal_never_deletes_borrowed_source(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    source = tmp_path / "original.txt"
    source.write_text("borrowed", encoding="utf-8")
    manager = SessionManager(tmp_path)
    channel = _make_channel(manager, workspace=tmp_path, restricted=True)
    conn = AsyncMock()
    channel._webui_connections.add(conn)
    chat_id = await channel.gateway.temporary_chats.create(conn, trusted_webui=True)
    await channel._dispatch_envelope(conn, "client", {
        "type": "message", "chat_id": chat_id, "content": "", "webui": True,
        "media": [{"path": str(source)}],
    })
    channel._handle_message.assert_awaited_once()
    url = channel.gateway.media.local_attachment_url(str(source), session_key=f"websocket:{chat_id}")
    sig, payload = url.split("/")[-2:]
    assert channel.gateway.http._handle_media_fetch(sig, payload).status_code == 200
    channel.gateway.uploads.store.discard_owner(channel.gateway.uploads.owner(conn))
    channel.gateway.uploads.store.prune()
    await channel.gateway.temporary_chats.discard(conn, chat_id)
    assert channel.gateway.http._handle_media_fetch(sig, payload).status_code == 404
    assert source.read_text(encoding="utf-8") == "borrowed"


@pytest.mark.asyncio
async def test_large_local_files_and_upload_share_count_but_not_byte_budget(tmp_path, monkeypatch):
    from nanobot.channels.websocket.attachment_policy import AttachmentIngressLimits

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    sources = [tmp_path / "large.mp4", tmp_path / "large.pdf"]
    for source in sources:
        with source.open("wb") as output:
            output.truncate(64 * 1024 * 1024 + 1)
    channel = _make_channel(workspace=tmp_path, restricted=True)
    channel.gateway.uploads.store.limits = AttachmentIngressLimits(max_file_bytes=8, max_total_bytes=8)
    conn = AsyncMock()
    owner = channel.gateway.uploads.issue(conn)["token"]

    async def body():
        yield b"uploaded"

    ref = await channel.gateway.uploads.store.upload(body(), owner=owner, mime="image/png", size=8)
    uploaded = channel.gateway.uploads.store.resolve([ref], owner=owner)[0]
    await channel._dispatch_envelope(conn, "client", {
        "type": "message", "chat_id": "large-local", "content": "read references",
        "media": [{"path": str(sources[0])}, {"reference": ref}, {"path": str(sources[1])}],
    })
    channel._handle_message.assert_awaited_once()
    assert channel._handle_message.await_args.kwargs["media"] == [str(sources[0]), uploaded, str(sources[1])]
    assert channel._handle_message.await_args.kwargs["metadata"]["local_media_paths"] == [str(source) for source in sources]
    assert all(source.stat().st_size == 64 * 1024 * 1024 + 1 for source in sources)
    assert [path for path in channel.gateway.uploads.store.media_dir.iterdir() if path.is_file()] == [Path(uploaded)]


@pytest.mark.parametrize("persisted", [False, True])
async def test_deleted_local_attachment_scope_never_reverts_to_default(tmp_path, monkeypatch, persisted):
    from nanobot.security.workspace_access import default_workspace_scope

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    project = tmp_path / "nested"
    project.mkdir()
    source = tmp_path / "original.txt"
    source.write_text("borrowed", encoding="utf-8")
    manager = SessionManager(tmp_path)
    channel = _make_channel(manager, workspace=tmp_path, restricted=True)
    workspaces = channel.gateway.workspaces
    key = "websocket:scoped-media"
    await workspaces.stage_scope("scoped-media", default_workspace_scope(project, False))
    if persisted:
        await workspaces.persist_scope("scoped-media", default_workspace_scope(project, False))
    url = channel.gateway.media.local_attachment_url(str(source), session_key=key)
    sig, payload = url.split("/")[-2:]

    def fetch():
        return channel.gateway.http._handle_media_fetch(sig, payload)

    assert bytes(fetch().body) == b"borrowed"
    await workspaces.stage_scope("scoped-media", default_workspace_scope(project, True))
    assert fetch().status_code == 403
    workspaces.discard_draft_scope(key)
    await manager.state.delete(key)
    assert fetch().status_code == 404
    assert source.read_text(encoding="utf-8") == "borrowed"
