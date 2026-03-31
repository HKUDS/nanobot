"""Tests for the Twilio WhatsApp channel."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip if Twilio SDK not installed
try:
    import twilio  # noqa: F401
except ImportError:
    pytest.skip("Twilio dependencies not installed", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.twilio_whatsapp import TwilioWhatsAppChannel, TwilioWhatsAppConfig


def _make_channel(tmp_path: Path, **overrides) -> TwilioWhatsAppChannel:
    """Create a channel with a tmp outbound media dir."""
    defaults = {
        "enabled": True,
        "account_sid": "ACfake",
        "auth_token": "faketoken",
        "from_number": "whatsapp:+14155238886",
        "allow_from": ["*"],
        "public_url": "https://example.ngrok.app",
    }
    defaults.update(overrides)
    config = TwilioWhatsAppConfig.model_validate(defaults)
    bus = MessageBus()

    with patch(
        "nanobot.channels.twilio_whatsapp.get_media_dir",
        return_value=tmp_path / "media" / "twilio_whatsapp",
    ):
        ch = TwilioWhatsAppChannel(config, bus)

    # Replace the Twilio client with a mock
    ch._twilio = MagicMock()
    ch._twilio.messages.create = MagicMock()
    return ch


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------


def test_config_defaults():
    cfg = TwilioWhatsAppConfig()
    assert cfg.enabled is False
    assert cfg.webhook_path == "/twilio/whatsapp"
    assert cfg.webhook_port == 0
    assert cfg.validate_signature is False
    assert cfg.public_url == ""
    assert cfg.group_policy == "open"


def test_public_url_trailing_slash_stripped(tmp_path):
    ch = _make_channel(tmp_path, public_url="https://example.com/")
    assert ch._public_url == "https://example.com"


# ------------------------------------------------------------------
# send() — text
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_text_only(tmp_path):
    ch = _make_channel(tmp_path)
    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="hello",
    )

    await ch.send(msg)

    ch._twilio.messages.create.assert_called_once_with(
        from_="whatsapp:+14155238886",
        to="whatsapp:+1234567890",
        body="hello",
    )


@pytest.mark.asyncio
async def test_send_empty_message_is_noop(tmp_path):
    ch = _make_channel(tmp_path)
    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="",
    )

    await ch.send(msg)

    ch._twilio.messages.create.assert_not_called()


# ------------------------------------------------------------------
# send() — media with HTTP URLs (pass-through)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_http_media_url_passes_through(tmp_path):
    ch = _make_channel(tmp_path)
    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="",
        media=["https://example.com/photo.jpg"],
    )

    await ch.send(msg)

    ch._twilio.messages.create.assert_called_once_with(
        from_="whatsapp:+14155238886",
        to="whatsapp:+1234567890",
        media_url=["https://example.com/photo.jpg"],
    )


# ------------------------------------------------------------------
# send() — local media staging
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_local_media_stages_and_converts_to_url(tmp_path):
    ch = _make_channel(tmp_path)
    # Create a local file to send
    local_file = tmp_path / "chart.png"
    local_file.write_bytes(b"fake png data")

    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="",
        media=[str(local_file)],
    )

    await ch.send(msg)

    ch._twilio.messages.create.assert_called_once()
    call_kwargs = ch._twilio.messages.create.call_args.kwargs
    media_url = call_kwargs["media_url"][0]
    assert media_url.startswith("https://example.ngrok.app/twilio/whatsapp/media/")
    assert media_url.endswith(".png")

    # Verify the file was copied to outbound dir
    staged_filename = media_url.rsplit("/", 1)[-1]
    staged_path = ch._outbound_media_dir / staged_filename
    assert staged_path.exists()
    assert staged_path.read_bytes() == b"fake png data"


@pytest.mark.asyncio
async def test_send_local_media_without_public_url_skips(tmp_path):
    ch = _make_channel(tmp_path, public_url="")
    local_file = tmp_path / "chart.png"
    local_file.write_bytes(b"fake png data")

    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="",
        media=[str(local_file)],
    )

    await ch.send(msg)

    ch._twilio.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_send_missing_local_file_skips(tmp_path):
    ch = _make_channel(tmp_path)

    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="",
        media=["/nonexistent/file.png"],
    )

    await ch.send(msg)

    ch._twilio.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_send_mixed_text_and_media(tmp_path):
    ch = _make_channel(tmp_path)
    local_file = tmp_path / "doc.pdf"
    local_file.write_bytes(b"fake pdf")

    msg = OutboundMessage(
        channel="twilio_whatsapp",
        chat_id="whatsapp:+1234567890",
        content="Here is the report",
        media=[str(local_file)],
    )

    await ch.send(msg)

    assert ch._twilio.messages.create.call_count == 2
    # First call: text
    text_call = ch._twilio.messages.create.call_args_list[0]
    assert text_call.kwargs["body"] == "Here is the report"
    # Second call: media
    media_call = ch._twilio.messages.create.call_args_list[1]
    assert media_call.kwargs["media_url"][0].endswith(".pdf")


# ------------------------------------------------------------------
# _stage_media
# ------------------------------------------------------------------


def test_stage_media_preserves_extension(tmp_path):
    ch = _make_channel(tmp_path)
    local_file = tmp_path / "report.pdf"
    local_file.write_bytes(b"data")

    url = ch._stage_media(str(local_file))
    assert url is not None
    assert url.endswith(".pdf")


def test_stage_media_generates_unique_filenames(tmp_path):
    ch = _make_channel(tmp_path)
    local_file = tmp_path / "image.png"
    local_file.write_bytes(b"data")

    url1 = ch._stage_media(str(local_file))
    url2 = ch._stage_media(str(local_file))
    assert url1 != url2


# ------------------------------------------------------------------
# _serve_media
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_media_returns_file(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    ch = _make_channel(tmp_path)

    # Stage a file
    filename = f"{uuid.uuid4().hex}.png"
    staged = ch._outbound_media_dir / filename
    staged.write_bytes(b"image data")

    request = make_mocked_request("GET", f"/twilio/whatsapp/media/{filename}")
    request.match_info["filename"] = filename

    response = await ch._serve_media(request)
    assert isinstance(response, web.FileResponse)


@pytest.mark.asyncio
async def test_serve_media_returns_404_for_missing_file(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    ch = _make_channel(tmp_path)
    request = make_mocked_request("GET", "/twilio/whatsapp/media/nonexistent.png")
    request.match_info["filename"] = "nonexistent.png"

    response = await ch._serve_media(request)
    assert response.status == 404


@pytest.mark.asyncio
async def test_serve_media_rejects_path_traversal(tmp_path):
    from aiohttp.test_utils import make_mocked_request

    ch = _make_channel(tmp_path)

    # Create a file outside the outbound dir
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive")

    request = make_mocked_request("GET", "/twilio/whatsapp/media/../secret.txt")
    request.match_info["filename"] = "../secret.txt"

    response = await ch._serve_media(request)
    assert response.status == 404


# ------------------------------------------------------------------
# Webhook handling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_parses_inbound_message(tmp_path):
    from aiohttp.test_utils import make_mocked_request
    from multidict import CIMultiDict, MultiDict

    ch = _make_channel(tmp_path, validate_signature=False)
    ch._handle_message = AsyncMock()

    form_data = MultiDict(
        {
            "From": "whatsapp:+1234567890",
            "Body": "Hello bot",
            "MessageSid": "SM123",
            "ProfileName": "Test User",
            "NumMedia": "0",
        }
    )

    request = make_mocked_request(
        "POST",
        "/twilio/whatsapp",
        headers=CIMultiDict({"Content-Type": "application/x-www-form-urlencoded"}),
    )
    request.post = AsyncMock(return_value=form_data)

    response = await ch._handle_webhook(request)

    assert response.content_type == "application/xml"
    ch._handle_message.assert_awaited_once()
    kwargs = ch._handle_message.call_args.kwargs
    assert kwargs["sender_id"] == "+1234567890"
    assert kwargs["chat_id"] == "whatsapp:+1234567890"
    assert kwargs["content"] == "Hello bot"


@pytest.mark.asyncio
async def test_webhook_immediate_response(tmp_path):
    from aiohttp.test_utils import make_mocked_request
    from multidict import CIMultiDict, MultiDict

    ch = _make_channel(tmp_path, validate_signature=False, immediate_response="Thinking...")
    ch._handle_message = AsyncMock()

    form_data = MultiDict(
        {
            "From": "whatsapp:+1234567890",
            "Body": "Hi",
            "MessageSid": "SM456",
            "ProfileName": "User",
            "NumMedia": "0",
        }
    )

    request = make_mocked_request(
        "POST",
        "/twilio/whatsapp",
        headers=CIMultiDict({"Content-Type": "application/x-www-form-urlencoded"}),
    )
    request.post = AsyncMock(return_value=form_data)

    response = await ch._handle_webhook(request)

    assert "Thinking..." in response.text


@pytest.mark.asyncio
async def test_webhook_empty_twiml_when_no_immediate_response(tmp_path):
    from aiohttp.test_utils import make_mocked_request
    from multidict import CIMultiDict, MultiDict

    ch = _make_channel(tmp_path, validate_signature=False, immediate_response="")
    ch._handle_message = AsyncMock()

    form_data = MultiDict(
        {
            "From": "whatsapp:+1234567890",
            "Body": "Hi",
            "MessageSid": "SM789",
            "ProfileName": "User",
            "NumMedia": "0",
        }
    )

    request = make_mocked_request(
        "POST",
        "/twilio/whatsapp",
        headers=CIMultiDict({"Content-Type": "application/x-www-form-urlencoded"}),
    )
    request.post = AsyncMock(return_value=form_data)

    response = await ch._handle_webhook(request)

    assert response.text == "<Response></Response>"
