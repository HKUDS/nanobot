"""Tests for the Python call channel."""

import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.python_call import PythonCallChannel
from nanobot.config.schema import PythonCallConfig


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def channel(bus):
    config = PythonCallConfig(enabled=True, allow_from=["*"])
    return PythonCallChannel(config, bus)


@pytest.mark.asyncio
async def test_start_stop(channel):
    """Channel can start and stop."""
    assert not channel.is_running
    await channel.start()
    assert channel.is_running
    await channel.stop()
    assert not channel.is_running


@pytest.mark.asyncio
async def test_call_returns_agent_response(channel, bus):
    """call() publishes inbound and resolves when outbound arrives."""
    await channel.start()

    async def fake_agent():
        """Simulate the agent: consume inbound, publish outbound."""
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.channel == "python_call"
        assert msg.content == "ping"
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="pong",
            )
        )

    # The channel.send() is called by the ChannelManager dispatcher;
    # simulate that here by bridging outbound to channel.send().
    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(channel.call("ping"), timeout=3)
    assert result == "pong"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_call_with_custom_chat_id(channel, bus):
    """call() with explicit chat_id uses that id."""
    await channel.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.chat_id == "my-session"
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id="my-session",
                content="ok",
            )
        )

    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(
        channel.call("hi", chat_id="my-session"), timeout=3
    )
    assert result == "ok"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_call_timeout(channel):
    """call() raises TimeoutError when no reply comes."""
    await channel.start()

    with pytest.raises(asyncio.TimeoutError):
        await channel.call("hello", timeout=0.1)

    await channel.stop()


@pytest.mark.asyncio
async def test_call_not_running(channel):
    """call() raises RuntimeError when channel is not running."""
    with pytest.raises(RuntimeError, match="not running"):
        await channel.call("hello")


@pytest.mark.asyncio
async def test_progress_messages_ignored(channel, bus):
    """Progress outbound messages do not resolve the pending future."""
    await channel.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        # Send a progress message first
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="thinking...",
                metadata={"_progress": True},
            )
        )
        # Then the real reply
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="done",
            )
        )

    async def dispatch_outbound():
        for _ in range(2):
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
            await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(channel.call("work"), timeout=3)
    assert result == "done"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_concurrent_calls(channel, bus):
    """Multiple concurrent calls are matched correctly by chat_id."""
    await channel.start()

    async def fake_agent():
        for _ in range(2):
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
            await bus.publish_outbound(
                OutboundMessage(
                    channel="python_call",
                    chat_id=msg.chat_id,
                    content=f"reply-to-{msg.content}",
                )
            )

    async def dispatch_outbound():
        for _ in range(2):
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
            await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    r1, r2 = await asyncio.gather(
        channel.call("a", chat_id="id-a"),
        channel.call("b", chat_id="id-b"),
    )
    assert r1 == "reply-to-a"
    assert r2 == "reply-to-b"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_stop_cancels_pending(channel, bus):
    """Stopping the channel cancels pending call futures."""
    await channel.start()

    call_task = asyncio.create_task(channel.call("hello", chat_id="pending-id"))
    # Let the call publish inbound
    await asyncio.sleep(0.05)

    await channel.stop()

    with pytest.raises((asyncio.CancelledError, RuntimeError)):
        await call_task


@pytest.mark.asyncio
async def test_access_denied(bus):
    """call() from a non-allowed sender does not produce inbound messages."""
    config = PythonCallConfig(enabled=True, allow_from=["allowed-user"])
    ch = PythonCallChannel(config, bus)
    await ch.start()

    # This call uses sender_id="python_caller" which is not in allow_from
    # _handle_message will deny access, so the inbound queue stays empty
    # and the call will time out.
    with pytest.raises(asyncio.TimeoutError):
        await ch.call("hello", timeout=0.2)

    assert bus.inbound_size == 0
    await ch.stop()


@pytest.mark.asyncio
async def test_session_id_produces_stable_chat_id(channel, bus):
    """session_id maps to a deterministic chat_id for session persistence."""
    await channel.start()

    received_chat_ids = []

    async def fake_agent():
        for _ in range(2):
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
            received_chat_ids.append(msg.chat_id)
            await bus.publish_outbound(
                OutboundMessage(
                    channel="python_call",
                    chat_id=msg.chat_id,
                    content="ok",
                )
            )

    async def dispatch_outbound():
        for _ in range(2):
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
            await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    await asyncio.wait_for(
        channel.call("msg1", session_id="alice"), timeout=3
    )
    await asyncio.wait_for(
        channel.call("msg2", session_id="alice"), timeout=3
    )

    # Both calls should use the same chat_id
    assert received_chat_ids[0] == received_chat_ids[1] == "session-alice"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_session_id_and_chat_id_mutually_exclusive(channel):
    """Providing both session_id and chat_id raises ValueError."""
    await channel.start()

    with pytest.raises(ValueError, match="mutually exclusive"):
        await channel.call("hi", chat_id="x", session_id="y")

    await channel.stop()


@pytest.mark.asyncio
async def test_default_session_id_from_config(bus):
    """When config has default_session_id, calls use it as chat_id."""
    config = PythonCallConfig(
        enabled=True, allow_from=["*"], default_session_id="default"
    )
    ch = PythonCallChannel(config, bus)
    await ch.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.chat_id == "session-default"
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="ok",
            )
        )

    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await ch.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(ch.call("hello"), timeout=3)
    assert result == "ok"

    await agent_task
    await dispatch_task
    await ch.stop()


@pytest.mark.asyncio
async def test_session_key_override(channel, bus):
    """session_key is passed through to the bus message."""
    await channel.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.session_key_override == "custom:shared-session"
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="ok",
            )
        )

    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(
        channel.call("hi", session_key="custom:shared-session"), timeout=3
    )
    assert result == "ok"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_metadata_passed_through(channel, bus):
    """Metadata (including config overrides) is forwarded to the bus."""
    await channel.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.metadata.get("system_prompt") == "You are a translator."
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="translated",
            )
        )

    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(
        channel.call(
            "hello",
            metadata={"system_prompt": "You are a translator."},
        ),
        timeout=3,
    )
    assert result == "translated"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_media_passed_through(channel, bus):
    """Media URLs are forwarded to the bus message."""
    await channel.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.media == ["https://example.com/image.png"]
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="got media",
            )
        )

    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await channel.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(
        channel.call("check this", media=["https://example.com/image.png"]),
        timeout=3,
    )
    assert result == "got media"

    await agent_task
    await dispatch_task
    await channel.stop()


@pytest.mark.asyncio
async def test_call_negative_timeout(channel):
    """call() raises ValueError for non-positive timeout."""
    await channel.start()

    with pytest.raises(ValueError, match="timeout must be positive"):
        await channel.call("hello", timeout=-1)

    with pytest.raises(ValueError, match="timeout must be positive"):
        await channel.call("hello", timeout=0)

    await channel.stop()


@pytest.mark.asyncio
async def test_explicit_session_id_overrides_default(bus):
    """Explicit session_id takes precedence over config default_session_id."""
    config = PythonCallConfig(
        enabled=True, allow_from=["*"], default_session_id="default"
    )
    ch = PythonCallChannel(config, bus)
    await ch.start()

    async def fake_agent():
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
        assert msg.chat_id == "session-override"
        await bus.publish_outbound(
            OutboundMessage(
                channel="python_call",
                chat_id=msg.chat_id,
                content="ok",
            )
        )

    async def dispatch_outbound():
        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=2)
        await ch.send(msg)

    agent_task = asyncio.create_task(fake_agent())
    dispatch_task = asyncio.create_task(dispatch_outbound())

    result = await asyncio.wait_for(
        ch.call("hi", session_id="override"), timeout=3
    )
    assert result == "ok"

    await agent_task
    await dispatch_task
    await ch.stop()
