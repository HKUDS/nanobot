"""Tests for the SimpleX CLI channel."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.simplex import SimplexChannel


@pytest.mark.asyncio
async def test_login_returns_false() -> None:
    channel = SimplexChannel({"enabled": True}, MagicMock())
    assert await channel.login(force=True) is False


@pytest.mark.asyncio
async def test_start_polls_and_forwards_inbound_messages(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "simplex-state.json"
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "stateFile": str(state_path),
            "pollInterval": 0.1,
            "bootstrap": "all",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    async def fake_run_receiver_once() -> list[tuple[str, str]]:
        channel._running = False
        return [("tok-1", "hello from simplex")]

    handle_mock = AsyncMock()
    monkeypatch.setattr(channel, "_run_receiver_once", fake_run_receiver_once)
    monkeypatch.setattr(channel, "_handle_message", handle_mock)
    monkeypatch.setattr("nanobot.channels.simplex.asyncio.sleep", AsyncMock())

    await channel.start()

    handle_mock.assert_awaited_once_with(
        sender_id="Alice",
        chat_id="simplex:alice",
        content="hello from simplex",
        media=[],
    )
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["last_seen_token"] == "tok-1"


@pytest.mark.asyncio
async def test_start_bootstrap_latest_skips_backfill(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "simplex-state.json"
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "stateFile": str(state_path),
            "pollInterval": 0.1,
            "bootstrap": "latest",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    async def fake_run_receiver_once() -> list[tuple[str, str]]:
        channel._running = False
        return [("tok-legacy", "old message")]

    handle_mock = AsyncMock()
    monkeypatch.setattr(channel, "_run_receiver_once", fake_run_receiver_once)
    monkeypatch.setattr(channel, "_handle_message", handle_mock)
    monkeypatch.setattr("nanobot.channels.simplex.asyncio.sleep", AsyncMock())

    await channel.start()

    handle_mock.assert_not_awaited()
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["last_seen_token"] == "tok-legacy"


@pytest.mark.asyncio
async def test_stop_sets_running_false() -> None:
    channel = SimplexChannel({"enabled": True, "chatId": "simplex:alice", "contact": "Alice"}, MagicMock())
    channel._running = True

    await channel.stop()

    assert channel.is_running is False


@pytest.mark.asyncio
async def test_send_routes_image_and_file_commands(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "photo.jpg"
    file_path = tmp_path / "voice.mp4"
    image_path.write_bytes(b"img")
    file_path.write_bytes(b"bin")

    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    commands: list[str] = []

    async def fake_run_simplex_command(command_text: str) -> tuple[int, str, str]:
        commands.append(command_text)
        return 0, "", ""

    monkeypatch.setattr(channel, "_run_simplex_command", fake_run_simplex_command)

    msg = OutboundMessage(
        channel="simplex",
        chat_id="simplex:alice",
        content="hello",
        media=[str(image_path), str(file_path)],
    )
    await channel.send(msg)

    assert commands[0] == "@Alice hello"
    assert commands[1].startswith("/img @Alice ")
    assert commands[2].startswith("/f @Alice ")


def test_extract_file_reference_parses_fr_and_filename() -> None:
    text = "sends file voice_20260505_102006.m4a (14.8 KiB / 15139 bytes) use /fr 2 [<dir>/ ..."

    assert SimplexChannel._extract_file_reference(text) == (2, "voice_20260505_102006.m4a")


@pytest.mark.asyncio
async def test_prepare_inbound_message_adds_media_and_transcription(monkeypatch) -> None:
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    media_path = "/tmp/voice_20260505_102006.m4a"
    monkeypatch.setattr(channel, "_retrieve_inbound_file", AsyncMock(return_value=media_path))
    monkeypatch.setattr(channel, "transcribe_audio", AsyncMock(return_value="hola des de veu"))

    content, media = await channel._prepare_inbound_message(
        "sends file voice_20260505_102006.m4a (14.8 KiB / 15139 bytes) use /fr 2 [<dir>/ ..."
    )

    assert media == [media_path]
    assert "[transcription: hola des de veu]" in content


@pytest.mark.asyncio
async def test_resolve_non_empty_media_rejects_zero_byte_file(monkeypatch, tmp_path: Path) -> None:
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )
    file_path = tmp_path / "voice.m4a"
    file_path.write_bytes(b"")
    monkeypatch.setattr("nanobot.channels.simplex.asyncio.sleep", AsyncMock())

    resolved = await channel._resolve_non_empty_media(file_path)

    assert resolved is None


@pytest.mark.asyncio
async def test_prepare_inbound_message_drops_zero_byte_retrieval(monkeypatch) -> None:
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    monkeypatch.setattr(channel, "_retrieve_inbound_file", AsyncMock(return_value=None))

    content, media = await channel._prepare_inbound_message(
        "sends file voice_20260505_102006.m4a (14.8 KiB / 15139 bytes) use /fr 2 [<dir>/ ..."
    )

    assert content.startswith("sends file voice_20260505_102006.m4a")
    assert "use /fr" not in content
    assert media == []


@pytest.mark.asyncio
async def test_prepare_inbound_message_sanitizes_fr_hint_when_media_exists(monkeypatch) -> None:
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    media_path = "/tmp/IMG_20260505.jpg"
    monkeypatch.setattr(channel, "_retrieve_inbound_file", AsyncMock(return_value=media_path))

    content, media = await channel._prepare_inbound_message(
        "sends file IMG_20260505.jpg (245.2 KiB / 251043 bytes) use /fr 6 [<dir>/ ..."
    )

    assert content.startswith("sends file IMG_20260505.jpg")
    assert "use /fr" not in content
    assert media == [media_path]


@pytest.mark.asyncio
async def test_retrieve_inbound_file_cancels_and_retries_when_already_receiving(monkeypatch, tmp_path: Path) -> None:
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )
    channel._inbound_media_dir = tmp_path

    target = tmp_path / "voice_20260505_115652.m4a"
    target.write_bytes(b"")

    run_mock = AsyncMock(
        side_effect=[
            (0, "file is already being received: voice_20260505_115652.m4a", ""),
            (0, "file is already being received: voice_20260505_115652.m4a", ""),
            (0, "cancelled receiving file 5", ""),
            (0, f"saving file 5 to {target}", ""),
        ]
    )

    async def fake_resolve(candidate: Path) -> str | None:
        if candidate.resolve(strict=False) != target.resolve(strict=False):
            return None
        return str(target) if target.stat().st_size > 0 else None

    async def fake_status(_: int) -> str | None:
        return None

    monkeypatch.setattr(channel, "_run_simplex_command", run_mock)
    monkeypatch.setattr(channel, "_resolve_non_empty_media", fake_resolve)
    monkeypatch.setattr(channel, "_query_fstatus_path", fake_status)

    async def grow_file_after_cancel(*args, **kwargs):
        call_index = run_mock.await_count
        result = await run_mock(*args, **kwargs)
        if call_index == 3:
            target.write_bytes(b"ok")
        return result

    monkeypatch.setattr(channel, "_run_simplex_command", grow_file_after_cancel)

    resolved = await channel._retrieve_inbound_file(5, "voice_20260505_115652.m4a")

    assert resolved == str(target)


@pytest.mark.asyncio
async def test_forward_messages_suppresses_voice_placeholder_before_fr_hint(tmp_path: Path) -> None:
    state_path = tmp_path / "simplex-state.json"
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "stateFile": str(state_path),
            "bootstrap": "all",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    channel._last_seen_token = None
    channel._recent_content_tokens = []
    channel._prepare_inbound_message = AsyncMock(
        return_value=(
            "sends file voice_20260505_102006.m4a (14.8 KiB / 15139 bytes) use /fr 2 [<dir>/ ...\n"
            "[transcription: prova]",
            ["/tmp/voice_20260505_102006.m4a"],
        )
    )
    handle_mock = AsyncMock()
    channel._handle_message = handle_mock

    await channel._forward_messages(
        [
            ("tok-voice", "voice message (00:03)"),
            (
                "tok-file",
                "sends file voice_20260505_102006.m4a (14.8 KiB / 15139 bytes) use /fr 2 [<dir>/ ...",
            ),
        ],
        state_path,
    )

    handle_mock.assert_awaited_once()
    kwargs = handle_mock.await_args.kwargs
    assert kwargs["content"].startswith("sends file voice_20260505_102006.m4a")
    assert kwargs["media"] == ["/tmp/voice_20260505_102006.m4a"]


@pytest.mark.asyncio
async def test_forward_messages_keeps_voice_placeholder_when_file_not_retrieved(tmp_path: Path) -> None:
    state_path = tmp_path / "simplex-state.json"
    channel = SimplexChannel(
        {
            "enabled": True,
            "chatId": "simplex:alice",
            "contact": "Alice",
            "stateFile": str(state_path),
            "bootstrap": "all",
            "allowFrom": ["*"],
        },
        MagicMock(),
    )

    channel._last_seen_token = None
    channel._recent_content_tokens = []

    async def fake_prepare(text: str) -> tuple[str, list[str]]:
        if text.startswith("sends file"):
            return text, []
        return text, []

    channel._prepare_inbound_message = AsyncMock(side_effect=fake_prepare)
    handle_mock = AsyncMock()
    channel._handle_message = handle_mock

    await channel._forward_messages(
        [
            ("tok-voice", "voice message (00:03)"),
            (
                "tok-file",
                "sends file voice_20260505_102006.m4a (14.8 KiB / 15139 bytes) use /fr 2 [<dir>/ ...",
            ),
        ],
        state_path,
    )

    assert handle_mock.await_count == 2
    first_call = handle_mock.await_args_list[0].kwargs
    second_call = handle_mock.await_args_list[1].kwargs
    assert first_call["content"] == "voice message (00:03)"
    assert first_call["media"] == []
    assert second_call["content"].startswith("sends file voice_20260505_102006.m4a")
    assert second_call["media"] == []


def test_channels_login_simplex_uses_builtin_channel() -> None:
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    runner = CliRunner()
    result = runner.invoke(app, ["channels", "login", "simplex", "--force"])

    assert result.exit_code == 1
    assert "SimpleX Login" in result.output
