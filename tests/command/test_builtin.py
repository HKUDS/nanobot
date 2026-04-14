from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.command.builtin import cmd_stop, cmd_restart, cmd_status, cmd_new, cmd_dream, cmd_dream_restore, cmd_help
from nanobot.command.router import CommandContext
from tests.agent.test_hook_composite import _make_loop


@pytest.mark.asyncio
async def test_cmd_stop_return_value_has_metadata_source():
    """Test that cmd_stop returns metadata with 'source' = 'command'."""
    loop = _make_loop("/tmp")
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)

    out = await cmd_stop(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_stop_retains_original_metadata_from_ctx():
    """Test that cmd_stop retains all original metadata values from ctx.msg.metadata."""
    loop = _make_loop("/tmp")

    # Create a message with existing metadata
    original_metadata = {
        "user_id": "alice",
        "channel_type": "slack",
        "custom_field": "custom_value",
        "nested": {"key": "value"}
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/stop",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)

    out = await cmd_stop(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None

    # Verify original metadata values are retained
    assert out.metadata.get("user_id") == "alice"
    assert out.metadata.get("channel_type") == "slack"
    assert out.metadata.get("custom_field") == "custom_value"
    assert out.metadata.get("nested") == {"key": "value"}

    # Verify source was added/overwritten
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_stop_retains_metadata_with_empty_original():
    """Test that cmd_stop works correctly when original metadata is None or empty."""
    loop = _make_loop("/tmp")

    # Test with None metadata
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)

    out = await cmd_stop(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    # Should not have any other keys if original was None
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_stop_retains_metadata_with_empty_dict():
    """Test that cmd_stop works correctly when original metadata is empty dict."""
    loop = _make_loop("/tmp")

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/stop",
        metadata={}
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)

    out = await cmd_stop(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_stop_overwrites_source_if_present():
    """Test that cmd_stop properly overwrites 'source' if it was already present in metadata."""
    loop = _make_loop("/tmp")

    # Create a message with existing metadata that includes 'source'
    original_metadata = {
        "source": "original_value",
        "other_field": "other_value"
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/stop",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)

    out = await cmd_stop(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    # Source should be overwritten with 'command'
    assert out.metadata.get("source") == "command"
    # Other fields should still be retained
    assert out.metadata.get("other_field") == "other_value"


@pytest.mark.asyncio
async def test_cmd_restart_return_value_has_metadata_source():
    """Test that cmd_restart returns metadata with 'source' = 'command'."""
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/restart")
    ctx = CommandContext(msg=msg, session=None, key="", raw="/restart")

    out = await cmd_restart(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_restart_retains_original_metadata_from_ctx():
    """Test that cmd_restart retains all original metadata values from ctx.msg.metadata."""

    # Create a message with existing metadata
    original_metadata = {
        "user_id": "alice",
        "channel_type": "slack",
        "custom_field": "custom_value",
        "nested": {"key": "value"}
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/restart",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart")

    out = await cmd_restart(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None

    # Verify original metadata values are retained
    assert out.metadata.get("user_id") == "alice"
    assert out.metadata.get("channel_type") == "slack"
    assert out.metadata.get("custom_field") == "custom_value"
    assert out.metadata.get("nested") == {"key": "value"}

    # Verify source was added/overwritten
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_restart_retains_metadata_with_empty_original():
    """Test that cmd_restart works correctly when original metadata is None or empty."""

    # Test with None metadata
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/restart")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart")

    out = await cmd_restart(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    # Should not have any other keys if original was None
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_restart_retains_metadata_with_empty_dict():
    """Test that cmd_restart works correctly when original metadata is empty dict."""

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/restart",
        metadata={}
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart")

    out = await cmd_restart(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_restart_overwrites_source_if_present():
    """Test that cmd_restart properly overwrites 'source' if it was already present in metadata."""

    # Create a message with existing metadata that includes 'source'
    original_metadata = {
        "source": "original_value",
        "other_field": "other_value"
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/restart",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart")

    out = await cmd_restart(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    # Source should be overwritten with 'command'
    assert out.metadata.get("source") == "command"
    # Other fields should still be retained
    assert out.metadata.get("other_field") == "other_value"


@pytest.mark.asyncio
async def test_cmd_status_return_value_has_metadata_source():
    """Test that cmd_status returns metadata with 'source' = 'command'."""
    loop = _make_loop("/tmp")
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/status")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/status", loop=loop)

    out = await cmd_status(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_status_retains_original_metadata_from_ctx():
    """Test that cmd_status retains all original metadata values from ctx.msg.metadata."""
    loop = _make_loop("/tmp")

    # Create a message with existing metadata
    original_metadata = {
        "user_id": "alice",
        "channel_type": "slack",
        "custom_field": "custom_value",
        "nested": {"key": "value"}
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/status",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/status", loop=loop)

    out = await cmd_status(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None

    # Verify original metadata values are retained
    assert out.metadata.get("user_id") == "alice"
    assert out.metadata.get("channel_type") == "slack"
    assert out.metadata.get("custom_field") == "custom_value"
    assert out.metadata.get("nested") == {"key": "value"}

    # Verify source was added/overwritten
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_status_retains_metadata_with_empty_original():
    """Test that cmd_status works correctly when original metadata is None or empty."""
    loop = _make_loop("/tmp")

    # Test with None metadata
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/status")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/status", loop=loop)

    out = await cmd_status(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert out.metadata.get("render_as") == "text"
    assert len(out.metadata) == 2


@pytest.mark.asyncio
async def test_cmd_status_retains_metadata_with_empty_dict():
    """Test that cmd_status works correctly when original metadata is empty dict."""
    loop = _make_loop("/tmp")

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/status",
        metadata={}
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/status", loop=loop)

    out = await cmd_status(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert out.metadata.get("render_as") == "text"
    assert len(out.metadata) == 2


@pytest.mark.asyncio
async def test_cmd_status_overwrites_source_if_present():
    """Test that cmd_status properly overwrites 'source' if it was already present in metadata."""
    loop = _make_loop("/tmp")

    # Create a message with existing metadata that includes 'source'
    original_metadata = {
        "source": "original_value",
        "other_field": "other_value"
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/status",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/status", loop=loop)

    out = await cmd_status(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    # Source should be overwritten with 'command'
    assert out.metadata.get("source") == "command"
    # Other fields should still be retained
    assert out.metadata.get("other_field") == "other_value"


@pytest.mark.asyncio
async def test_cmd_status_has_render_as_text_metadata():
    """Test that cmd_status includes 'render_as' = 'text' in metadata."""
    loop = _make_loop("/tmp")
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/status")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/status", loop=loop)

    out = await cmd_status(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("render_as") == "text"


@pytest.mark.asyncio
async def test_cmd_new_return_value_has_metadata_source():
    """Test that cmd_new returns metadata with 'source' = 'command'."""
    loop = _make_loop("/tmp")
    loop._schedule_background = MagicMock()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/new")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/new", loop=loop)

    out = await cmd_new(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_new_retains_original_metadata_from_ctx():
    """Test that cmd_new retains all original metadata values from ctx.msg.metadata."""
    loop = _make_loop("/tmp")
    loop._schedule_background = MagicMock()

    # Create a message with existing metadata
    original_metadata = {
        "user_id": "alice",
        "channel_type": "slack",
        "custom_field": "custom_value",
        "nested": {"key": "value"}
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/new",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/new", loop=loop)

    out = await cmd_new(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None

    # Verify original metadata values are retained
    assert out.metadata.get("user_id") == "alice"
    assert out.metadata.get("channel_type") == "slack"
    assert out.metadata.get("custom_field") == "custom_value"
    assert out.metadata.get("nested") == {"key": "value"}

    # Verify source was added/overwritten
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_new_retains_metadata_with_empty_original():
    """Test that cmd_new works correctly when original metadata is None or empty."""
    loop = _make_loop("/tmp")
    loop._schedule_background = MagicMock()

    # Test with None metadata
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/new")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/new", loop=loop)

    out = await cmd_new(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    # Should not have any other keys if original was None
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_new_retains_metadata_with_empty_dict():
    """Test that cmd_new works correctly when original metadata is empty dict."""
    loop = _make_loop("/tmp")
    loop._schedule_background = MagicMock()

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/new",
        metadata={}
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/new", loop=loop)

    out = await cmd_new(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_new_overwrites_source_if_present():
    """Test that cmd_new properly overwrites 'source' if it was already present in metadata."""
    loop = _make_loop("/tmp")
    loop._schedule_background = MagicMock()

    # Create a message with existing metadata that includes 'source'
    original_metadata = {
        "source": "original_value",
        "other_field": "other_value"
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/new",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/new", loop=loop)

    out = await cmd_new(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    # Source should be overwritten with 'command'
    assert out.metadata.get("source") == "command"
    # Other fields should still be retained
    assert out.metadata.get("other_field") == "other_value"


@pytest.mark.asyncio
async def test_cmd_dream_return_value_has_metadata_source():
    """Test that cmd_dream returns metadata with 'source' = 'command'."""
    loop = _make_loop("/tmp")
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/dream")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", loop=loop)

    out = await cmd_dream(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_dream_with_empty_metadata():
    """Test that cmd_dream works correctly when original metadata is None."""
    loop = _make_loop("/tmp")

    # Test with None metadata
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/dream")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", loop=loop)

    out = await cmd_dream(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    # Should only have source key
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_cmd_dream_with_empty_dict_metadata():
    """Test that cmd_dream works correctly when original metadata is empty dict."""
    loop = _make_loop("/tmp")

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/dream",
        metadata={}
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", loop=loop)

    out = await cmd_dream(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    # Should only have source key
    assert len(out.metadata) == 1


@pytest.mark.asyncio
async def test_dream_restore_success_return_value_has_metadata_source() -> None:
    """Test that cmd_dream_restore returns metadata with 'source' = 'command' on success."""
    ctx = MagicMock()
    out = await cmd_dream_restore(ctx)

    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert out.metadata.get("render_as") == "text"


@pytest.mark.asyncio
async def test_dream_restore_when_git_not_initialized_has_metadata_source() -> None:
    """Test that cmd_dream_restore returns metadata with 'source' = 'command' on success."""
    ctx = MagicMock()
    ctx.loop = MagicMock()
    ctx.loop.consolidator = MagicMock()
    ctx.loop.consolidator.store = MagicMock()
    ctx.loop.consolidator.store.git = MagicMock()
    ctx.loop.consolidator.store.git.is_initialized = MagicMock(return_value=False)
    out = await cmd_dream_restore(ctx)

    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_help_return_value_has_metadata_source():
    """Test that cmd_help returns metadata with 'source' = 'command'."""
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/help")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/help")

    out = await cmd_help(ctx)

    assert out.metadata is not None
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_help_retains_original_metadata_from_ctx():
    """Test that cmd_help retains all original metadata values from ctx.msg.metadata."""

    # Create a message with existing metadata
    original_metadata = {
        "user_id": "alice",
        "channel_type": "slack",
        "custom_field": "custom_value",
        "nested": {"key": "value"}
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/help",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/help")

    out = await cmd_help(ctx)

    assert out.metadata is not None

    # Verify original metadata values are retained
    assert out.metadata.get("user_id") == "alice"
    assert out.metadata.get("channel_type") == "slack"
    assert out.metadata.get("custom_field") == "custom_value"
    assert out.metadata.get("nested") == {"key": "value"}

    # Verify source was added/overwritten
    assert out.metadata.get("source") == "command"


@pytest.mark.asyncio
async def test_cmd_help_retains_metadata_with_empty_original():
    """Test that cmd_help works correctly when original metadata is None or empty."""

    # Test with None metadata
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/help")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/help")

    out = await cmd_help(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert out.metadata.get("render_as") == "text"
    # Should not have any other keys if original was None
    assert len(out.metadata) == 2


@pytest.mark.asyncio
async def test_cmd_help_retains_metadata_with_empty_dict():
    """Test that cmd_help works correctly when original metadata is empty dict."""

    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/help",
        metadata={}
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/help")

    out = await cmd_help(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    assert out.metadata.get("source") == "command"
    assert out.metadata.get("render_as") == "text"
    assert len(out.metadata) == 2


@pytest.mark.asyncio
async def test_cmd_help_overwrites_source_if_present():
    """Test that cmd_help properly overwrites 'source' if it was already present in metadata."""

    # Create a message with existing metadata that includes 'source'
    original_metadata = {
        "source": "original_value",
        "other_field": "other_value"
    }
    msg = InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content="/help",
        metadata=original_metadata
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/help")

    out = await cmd_help(ctx)

    assert isinstance(out, OutboundMessage)
    assert out.metadata is not None
    # Source should be overwritten with 'command'
    assert out.metadata.get("source") == "command"
    # Other fields should still be retained
    assert out.metadata.get("other_field") == "other_value"
