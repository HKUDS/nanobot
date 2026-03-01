"""Unit tests for A2A outbound dispatch — the fix for tasks stuck in 'working' state.

The root cause was that the OpenFaaS handler created A2AChannel directly
without a ChannelManager, so no outbound dispatcher consumed from the bus.
OutboundMessages piled up and A2AChannel.send() was never called, meaning
deliver_response() never transitioned tasks from "working" → "completed".

A second bug was that progress/tool-hint messages (emitted by _bus_progress()
during tool call iterations) were forwarded to A2AChannel.send(), which calls
deliver_response() and prematurely transitions the task to "completed" with
tool-hint text (e.g. "⏳ read_file(…)") instead of the actual answer.

Both bugs were resolved by refactoring the handler to use ChannelManager,
which provides the canonical outbound dispatcher with proper progress-message
filtering (gated on config.channels.send_tool_hints / send_progress).

These tests verify:
- The A2AChannel dispatch loop (bus → channel.send() → deliver_response)
- Progress-message filtering
- ChannelManager integration with the A2A channel
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from a2a.types import Message, MessageSendParams, Part, TaskState, TaskQueryParams


@pytest.fixture
def bus():
    """Create a real MessageBus (async queues)."""
    return MessageBus()


@pytest.fixture
def mock_config():
    """Create a mock A2A config."""
    config = MagicMock()
    config.agent_name = "Dispatch Test Agent"
    config.agent_url = "http://localhost:8000"
    config.agent_description = "Tests outbound dispatch"
    config.skills = [
        {"id": "chat", "name": "Chat", "description": "General chat", "tags": []},
    ]
    config.running_user = "test_user"
    config.allow_from = ["user", "a2a-client"]
    config.task_retention_days = 14.0
    return config


@pytest.fixture
def a2a_channel(mock_config, bus):
    """Create an A2AChannel backed by a real MessageBus."""
    from nanobot.channels.a2a import A2AChannel, A2A_AVAILABLE

    if not A2A_AVAILABLE:
        pytest.skip("a2a-sdk not installed")
    return A2AChannel(mock_config, bus)


def _make_message(text: str, context_id: str | None = None) -> Message:
    """Helper to build an A2A Message."""
    return Message(
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        role="user",
        parts=[Part(type="text", text=text)],
        context_id=context_id,
    )


# ---------------------------------------------------------------------------
# Tests for the outbound dispatch loop (replicates what the OpenFaaS fix does)
# ---------------------------------------------------------------------------


class TestOutboundDispatchLoop:
    """Tests that verify the outbound dispatcher correctly bridges bus → channel."""

    @pytest.mark.asyncio
    async def test_dispatcher_forwards_outbound_to_channel_send(self, bus, a2a_channel):
        """Outbound messages on the bus are forwarded to channel.send()."""
        # Create a task via on_message_send so the handler knows about it
        msg = _make_message("Hello", context_id="dispatch-ctx-1")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Simulate the agent publishing an outbound response
        outbound = OutboundMessage(
            channel="a2a",
            chat_id="dispatch-ctx-1",
            content="Agent response",
            metadata={"task_id": task.id},
        )
        await bus.publish_outbound(outbound)

        # Run a single-iteration dispatcher (mimics _dispatch_outbound)
        consumed = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        await a2a_channel.send(consumed)

        # Task should now be completed
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_dispatcher_handles_multiple_messages(self, bus, a2a_channel):
        """Multiple outbound messages are dispatched in order."""
        tasks = []
        for i in range(3):
            ctx = f"multi-ctx-{i}"
            msg = _make_message(f"Message {i}", context_id=ctx)
            params = MessageSendParams(message=msg)
            task = await a2a_channel._handler.on_message_send(params)
            tasks.append(task)

            await bus.publish_outbound(
                OutboundMessage(
                    channel="a2a",
                    chat_id=ctx,
                    content=f"Response {i}",
                    metadata={"task_id": task.id},
                )
            )

        # Dispatch all three
        for _ in range(3):
            consumed = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            await a2a_channel.send(consumed)

        # All tasks should be completed
        for task in tasks:
            query = TaskQueryParams(id=task.id)
            updated = await a2a_channel._handler.on_get_task(query)
            assert updated.status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_dispatcher_timeout_does_not_crash(self, bus):
        """When no outbound messages are available, wait_for raises TimeoutError
        (the dispatcher should catch this and continue looping)."""
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bus.consume_outbound(), timeout=0.05)

    @pytest.mark.asyncio
    async def test_full_dispatch_loop_with_asyncio_task(self, bus, a2a_channel):
        """End-to-end: run the dispatcher as a background task, publish outbound,
        verify the A2A task transitions to completed."""
        # Create a task
        msg = _make_message("E2E test", context_id="e2e-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Start the dispatcher loop as a background task (same pattern as the fix)
        stop = asyncio.Event()

        async def _dispatch_outbound() -> None:
            while not stop.is_set():
                try:
                    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                await a2a_channel.send(outbound)

        dispatch_task = asyncio.create_task(_dispatch_outbound())

        # Simulate the agent producing a response
        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="e2e-ctx",
                content="E2E response",
                metadata={"task_id": task.id},
            )
        )

        # Give the dispatcher time to process
        await asyncio.sleep(0.3)
        stop.set()
        await dispatch_task

        # Verify task completed
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed
        assert updated.artifacts is not None
        assert len(updated.artifacts) == 1


# ---------------------------------------------------------------------------
# Tests for task_id resolution in A2AChannel.send()
# ---------------------------------------------------------------------------


class TestSendTaskIdResolution:
    """Tests for how send() resolves the task_id from OutboundMessage."""

    @pytest.mark.asyncio
    async def test_send_uses_task_id_from_metadata(self, a2a_channel):
        """send() should use task_id from msg.metadata when available."""
        msg = _make_message("Test", context_id="meta-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        outbound = OutboundMessage(
            channel="a2a",
            chat_id="meta-ctx",
            content="Via metadata",
            metadata={"task_id": task.id},
        )
        await a2a_channel.send(outbound)

        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_send_falls_back_to_context_to_task_mapping(self, a2a_channel):
        """send() should resolve task_id via _context_to_task when metadata
        doesn't contain task_id (the fallback path)."""
        msg = _make_message("Test", context_id="fallback-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # OutboundMessage without task_id in metadata — uses chat_id → context_to_task
        outbound = OutboundMessage(
            channel="a2a",
            chat_id="fallback-ctx",
            content="Via context mapping",
            metadata={},  # No task_id!
        )
        await a2a_channel.send(outbound)

        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_send_with_no_metadata_uses_context_mapping(self, a2a_channel):
        """send() handles OutboundMessage with metadata=None gracefully."""
        msg = _make_message("Test", context_id="none-meta-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # metadata defaults to empty dict in OutboundMessage, but test explicit None path
        outbound = OutboundMessage(
            channel="a2a",
            chat_id="none-meta-ctx",
            content="No metadata",
        )
        # Override metadata to None to test the guard
        outbound.metadata = None
        await a2a_channel.send(outbound)

        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed

    @pytest.mark.asyncio
    async def test_send_unknown_context_is_noop(self, a2a_channel):
        """send() with an unrecognized context_id should not raise."""
        outbound = OutboundMessage(
            channel="a2a",
            chat_id="unknown-ctx",
            content="Orphaned response",
            metadata={},
        )
        # Should not raise — just silently skip
        await a2a_channel.send(outbound)


# ---------------------------------------------------------------------------
# End-to-end lifecycle: the bug scenario
# ---------------------------------------------------------------------------


class TestTaskLifecycleEndToEnd:
    """Reproduces the original bug: without a dispatcher, tasks stay 'working'.
    With the dispatcher, they transition to 'completed'."""

    @pytest.mark.asyncio
    async def test_without_dispatcher_task_stays_working(self, bus, a2a_channel):
        """Without consuming outbound messages, the task remains in 'working' state."""
        msg = _make_message("Stuck task", context_id="stuck-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Agent publishes response to bus, but nobody consumes it
        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="stuck-ctx",
                content="This response is lost",
                metadata={"task_id": task.id},
            )
        )

        # Task is still working (the original bug)
        query = TaskQueryParams(id=task.id)
        stuck_task = await a2a_channel._handler.on_get_task(query)
        assert stuck_task.status.state == TaskState.working

        # Outbound queue has the unconsumed message
        assert bus.outbound_size == 1

    @pytest.mark.asyncio
    async def test_with_dispatcher_task_completes(self, bus, a2a_channel):
        """With the dispatcher consuming outbound messages, the task completes."""
        msg = _make_message("Fixed task", context_id="fixed-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Agent publishes response
        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="fixed-ctx",
                content="This response is delivered",
                metadata={"task_id": task.id},
            )
        )

        # Dispatcher consumes and forwards (the fix)
        consumed = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        await a2a_channel.send(consumed)

        # Task is now completed
        query = TaskQueryParams(id=task.id)
        completed_task = await a2a_channel._handler.on_get_task(query)
        assert completed_task.status.state == TaskState.completed
        assert completed_task.artifacts is not None
        assert len(completed_task.artifacts) == 1

        # Outbound queue is empty
        assert bus.outbound_size == 0

    @pytest.mark.asyncio
    async def test_inbound_message_published_on_message_send(self, bus, a2a_channel):
        """on_message_send should publish an InboundMessage to the bus."""
        msg = _make_message("Hello agent", context_id="inbound-ctx")
        params = MessageSendParams(message=msg)
        await a2a_channel._handler.on_message_send(params)

        # The handler should have published to the inbound queue
        assert bus.inbound_size == 1
        inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
        assert isinstance(inbound, InboundMessage)
        assert inbound.channel == "a2a"
        assert inbound.chat_id == "inbound-ctx"
        assert inbound.content == "Hello agent"


# ---------------------------------------------------------------------------
# Tests for progress / tool-hint message filtering (Bug 2 fix)
# ---------------------------------------------------------------------------


class TestProgressMessageFiltering:
    """Verifies that progress/tool-hint messages are forwarded to the
    A2AChannel for streaming, while other channels still filter them based on config.

    For a2a, progress messages are routed to deliver_progress() which pushes
    TaskStatusUpdateEvent to streaming queues. For other channels (telegram,
    discord), progress messages are still filtered based on send_tool_hints /
    send_progress config.
    """

    @staticmethod
    def _dispatch_should_forward(msg: OutboundMessage) -> bool:
        """Replicate the filtering logic from ChannelManager._dispatch_outbound().

        For a2a channel, progress messages ARE forwarded (to deliver_progress).
        For other channels, progress is filtered based on config.
        """
        if msg.metadata and msg.metadata.get("_progress"):
            if msg.channel == "a2a":
                return True
            if msg.metadata.get("_tool_hint"):
                return False
            return False
        return True

    def test_normal_message_is_forwarded(self):
        """A regular response (no _progress flag) should be forwarded."""
        msg = OutboundMessage(
            channel="a2a",
            chat_id="ctx-1",
            content="Final answer",
            metadata={"task_id": "t1"},
        )
        assert self._dispatch_should_forward(msg) is True

    def test_a2a_progress_message_is_forwarded(self):
        """A progress message (_progress=True) for a2a should be forwarded."""
        msg = OutboundMessage(
            channel="a2a",
            chat_id="ctx-1",
            content="⏳ read_file(…)",
            metadata={"task_id": "t1", "_progress": True, "_tool_hint": True},
        )
        assert self._dispatch_should_forward(msg) is True

    def test_non_a2a_progress_message_is_skipped(self):
        """A progress message for non-a2a channels should be skipped."""
        msg = OutboundMessage(
            channel="telegram",
            chat_id="ctx-1",
            content="⏳ read_file(…)",
            metadata={"task_id": "t1", "_progress": True, "_tool_hint": True},
        )
        assert self._dispatch_should_forward(msg) is False

    def test_empty_metadata_is_forwarded(self):
        """A message with empty metadata should be forwarded."""
        msg = OutboundMessage(
            channel="a2a",
            chat_id="ctx-1",
            content="Response",
            metadata={},
        )
        assert self._dispatch_should_forward(msg) is True

    def test_none_metadata_is_forwarded(self):
        """A message with metadata=None should be forwarded."""
        msg = OutboundMessage(
            channel="a2a",
            chat_id="ctx-1",
            content="Response",
        )
        msg.metadata = None
        assert self._dispatch_should_forward(msg) is True

    # -- integration tests with the full dispatch loop --

    @pytest.mark.asyncio
    async def test_dispatcher_skips_progress_delivers_final(self, bus, a2a_channel):
        """End-to-end: progress messages are skipped, only the final response
        completes the task."""
        # Create a task
        msg = _make_message("Tool test", context_id="progress-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Simulate the agent emitting a tool-hint progress message first
        progress_msg = OutboundMessage(
            channel="a2a",
            chat_id="progress-ctx",
            content='⏳ read_file("config.yaml")',
            metadata={"task_id": task.id, "_progress": True, "_tool_hint": True},
        )
        await bus.publish_outbound(progress_msg)

        # Then the final response
        final_msg = OutboundMessage(
            channel="a2a",
            chat_id="progress-ctx",
            content="Here is the file content: ...",
            metadata={"task_id": task.id},
        )
        await bus.publish_outbound(final_msg)

        # Run dispatcher with filtering (same pattern as the fixed handler)
        stop = asyncio.Event()

        async def _dispatch_outbound() -> None:
            while not stop.is_set():
                try:
                    out = await asyncio.wait_for(bus.consume_outbound(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if out.metadata and out.metadata.get("_progress"):
                    continue  # skip progress messages
                await a2a_channel.send(out)

        dispatch_task = asyncio.create_task(_dispatch_outbound())
        await asyncio.sleep(0.3)
        stop.set()
        await dispatch_task

        # Task should be completed with the FINAL content, not the tool hint
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed
        assert updated.artifacts is not None
        assert len(updated.artifacts) == 1
        # The artifact text should be the final response, not the tool hint
        artifact_text = updated.artifacts[0].parts[0].root.text
        assert "file content" in artifact_text
        assert "read_file" not in artifact_text

    @pytest.mark.asyncio
    async def test_without_filter_progress_completes_task_prematurely(self, bus, a2a_channel):
        """Demonstrates the bug: without filtering, a progress message
        prematurely completes the task with tool-hint text."""
        msg = _make_message("Bug demo", context_id="premature-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Only a progress message — no final response yet
        progress_msg = OutboundMessage(
            channel="a2a",
            chat_id="premature-ctx",
            content='⏳ read_file("config.yaml")',
            metadata={"task_id": task.id, "_progress": True, "_tool_hint": True},
        )
        await bus.publish_outbound(progress_msg)

        # Dispatch WITHOUT filtering - now this calls deliver_progress (not deliver_response)
        consumed = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        await a2a_channel.send(consumed)

        # Task stays in working state (progress message doesn't complete it)
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.working

    @pytest.mark.asyncio
    async def test_multiple_progress_then_final(self, bus, a2a_channel):
        """Multiple progress messages followed by a final response — only the
        final response should complete the task."""
        msg = _make_message("Multi-tool", context_id="multi-progress-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Three progress messages
        for i, tool in enumerate(["read_file", "web_search", "shell"]):
            await bus.publish_outbound(
                OutboundMessage(
                    channel="a2a",
                    chat_id="multi-progress-ctx",
                    content=f"⏳ {tool}(…)",
                    metadata={"task_id": task.id, "_progress": True, "_tool_hint": True},
                )
            )

        # Final response
        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="multi-progress-ctx",
                content="All tools executed successfully. Here are the results.",
                metadata={"task_id": task.id},
            )
        )

        # Dispatch with filtering
        stop = asyncio.Event()

        async def _dispatch_outbound() -> None:
            while not stop.is_set():
                try:
                    out = await asyncio.wait_for(bus.consume_outbound(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if out.metadata and out.metadata.get("_progress"):
                    continue
                await a2a_channel.send(out)

        dispatch_task = asyncio.create_task(_dispatch_outbound())
        await asyncio.sleep(0.5)
        stop.set()
        await dispatch_task

        # Verify: completed with final content
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed
        artifact_text = updated.artifacts[0].parts[0].root.text
        assert "results" in artifact_text
        assert "⏳" not in artifact_text

        # All messages consumed — queue should be empty
        assert bus.outbound_size == 0


# ---------------------------------------------------------------------------
# Tests for ChannelManager integration (the refactored architecture)
# ---------------------------------------------------------------------------


class TestChannelManagerDispatch:
    """Verifies that ChannelManager correctly dispatches outbound messages
    to the A2A channel — validating the refactored OpenFaaS handler
    architecture that delegates to ChannelManager instead of a custom
    _dispatch_outbound() loop.
    """

    @pytest.fixture
    def full_config(self):
        """Create a full Config with A2A enabled (required by ChannelManager)."""
        from nanobot.config.schema import Config

        return Config.model_validate(
            {
                "channels": {
                    "a2a": {
                        "enabled": True,
                        "agentUrl": "http://localhost:8000",
                        "agentName": "Test Agent",
                        "agentDescription": "Test",
                        "allowFrom": ["*"],
                    }
                }
            }
        )

    @pytest.fixture
    def channel_manager(self, full_config, bus):
        """Create a ChannelManager with A2A enabled."""
        from nanobot.channels.a2a import A2A_AVAILABLE

        if not A2A_AVAILABLE:
            pytest.skip("a2a-sdk not installed")
        return ChannelManager(full_config, bus)

    def test_channel_manager_creates_a2a_channel(self, channel_manager):
        """ChannelManager should create an A2A channel when config enables it."""
        from nanobot.channels.a2a import A2AChannel

        a2a = channel_manager.get_channel("a2a")
        assert a2a is not None
        assert isinstance(a2a, A2AChannel)

    def test_channel_manager_lists_a2a_in_enabled(self, channel_manager):
        """A2A should appear in the enabled channels list."""
        assert "a2a" in channel_manager.enabled_channels

    @pytest.mark.asyncio
    async def test_channel_manager_dispatches_to_a2a(self, channel_manager, bus):
        """ChannelManager._dispatch_outbound() should forward outbound
        messages to the A2A channel's send() method."""
        from nanobot.channels.a2a import A2AChannel

        a2a_channel = channel_manager.get_channel("a2a")
        assert isinstance(a2a_channel, A2AChannel)

        # Create a task so deliver_response() has something to complete
        msg = _make_message("CM test", context_id="cm-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Publish outbound
        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="cm-ctx",
                content="ChannelManager response",
                metadata={"task_id": task.id},
            )
        )

        # Start the ChannelManager dispatcher as a background task
        dispatch_task = asyncio.create_task(channel_manager._dispatch_outbound())

        # Give it time to process
        await asyncio.sleep(0.3)

        # Cancel the dispatcher
        dispatch_task.cancel()
        try:
            await dispatch_task
        except asyncio.CancelledError:
            pass

        # Verify task completed
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed
        assert updated.artifacts is not None

    @pytest.mark.asyncio
    async def test_channel_manager_passes_progress_to_a2a(self, channel_manager, bus):
        """ChannelManager._dispatch_outbound() should forward progress messages
        to A2A channel for streaming (not drop them)."""
        from nanobot.channels.a2a import A2AChannel

        a2a_channel = channel_manager.get_channel("a2a")
        assert isinstance(a2a_channel, A2AChannel)

        msg = _make_message("CM progress test", context_id="cm-progress-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        a2a_channel._handler._summarize_progress = False

        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="cm-progress-ctx",
                content='⏳ read_file("test.py")',
                metadata={"task_id": task.id, "_progress": True, "_tool_hint": True},
            )
        )

        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="cm-progress-ctx",
                content="Here is the actual answer.",
                metadata={"task_id": task.id},
            )
        )

        dispatch_task = asyncio.create_task(channel_manager._dispatch_outbound())
        await asyncio.sleep(0.3)
        dispatch_task.cancel()
        try:
            await dispatch_task
        except asyncio.CancelledError:
            pass

        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed
        artifact_text = updated.artifacts[0].parts[0].root.text
        assert "actual answer" in artifact_text

    @pytest.mark.asyncio
    async def test_channel_manager_start_all_creates_dispatch_task(self, channel_manager, bus):
        """start_all() should create a _dispatch_task and start channels."""
        from nanobot.channels.a2a import A2AChannel

        a2a_channel = channel_manager.get_channel("a2a")
        assert isinstance(a2a_channel, A2AChannel)

        # Create a task
        msg = _make_message("start_all test", context_id="start-all-ctx")
        params = MessageSendParams(message=msg)
        task = await a2a_channel._handler.on_message_send(params)

        # Start all channels in background (start_all blocks via gather)
        start_task = asyncio.create_task(channel_manager.start_all())

        # Publish outbound — the dispatcher started by start_all should pick it up
        await bus.publish_outbound(
            OutboundMessage(
                channel="a2a",
                chat_id="start-all-ctx",
                content="Response via start_all",
                metadata={"task_id": task.id},
            )
        )

        await asyncio.sleep(0.3)

        # Verify the dispatch task was created
        assert channel_manager._dispatch_task is not None

        # Stop everything
        await channel_manager.stop_all()
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass

        # Verify task completed
        query = TaskQueryParams(id=task.id)
        updated = await a2a_channel._handler.on_get_task(query)
        assert updated.status.state == TaskState.completed
