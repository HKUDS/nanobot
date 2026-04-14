
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.agent.runner import AgentRunSpec, AgentRunResult

def _make_loop(channels_config=None, unified_session=False):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 1000
    
    from pathlib import Path
    workspace = MagicMock(spec=Path)
    workspace.__truediv__ = MagicMock(side_effect=lambda x: workspace)
    workspace.expanduser.return_value.resolve.return_value = workspace
    workspace.__str__.return_value = "/test/workspace"
    workspace.exists.return_value = False
    workspace.parent = workspace
    workspace.mkdir = MagicMock()

    with patch("nanobot.agent.loop.SessionManager") as MockSM, \
         patch("nanobot.agent.loop.SubagentManager"):
        
        def mock_get_or_create(key):
            s = MagicMock()
            s.key = key
            s.messages = []
            s.metadata = {}
            return s
        MockSM.return_value.get_or_create.side_effect = mock_get_or_create
        
        loop = AgentLoop(
            bus=bus, 
            provider=provider, 
            workspace=workspace, 
            context_window_tokens=10000,
            channels_config=channels_config,
            unified_session=unified_session
        )
    return loop, bus

class TestSecurityIsolation:
    @pytest.mark.asyncio
    async def test_session_key_isolation(self):
        """Point 2: Ensure session isolation by including sender_id ONLY for strict channels."""
        # Strict config: only 'alice' listed
        channels_config = MagicMock()
        channels_config.model_extra = {"telegram": {"allowFrom": ["alice"]}}
        loop_strict, _ = _make_loop(channels_config=channels_config)
        
        msg_a = InboundMessage(channel="telegram", sender_id="user_a", chat_id="group_1", content="hi")
        assert loop_strict._effective_session_key(msg_a) == "telegram:group_1:user_a"
        
        # Non-strict config: wildcard ["*"] -> back to old logic
        channels_config_wild = MagicMock()
        channels_config_wild.model_extra = {"telegram": {"allowFrom": ["*"]}}
        loop_wild, _ = _make_loop(channels_config=channels_config_wild)
        assert loop_wild._effective_session_key(msg_a) == "telegram:group_1"

        # Unified session should still return UNIFIED_SESSION_KEY
        loop_unified, _ = _make_loop(unified_session=True)
        assert loop_unified._effective_session_key(msg_a) == "unified:default"

    @pytest.mark.asyncio
    async def test_group_queueing_lock(self):
        """Point 3: Group-level queueing. Use channel:chat_id for the lock."""
        # Test with strict policy to ensure queueing works even with isolated sessions
        channels_config = MagicMock()
        channels_config.model_extra = {"telegram": {"allowFrom": ["alice", "bob"]}}
        loop, bus = _make_loop(channels_config=channels_config)
        
        run_order = []
        async def mock_run(spec: AgentRunSpec):
            session_key = spec.session_key
            sender_id = session_key.split(":")[-1]
            run_order.append(f"start_{sender_id}")
            await asyncio.sleep(0.2)
            run_order.append(f"end_{sender_id}")
            return AgentRunResult(final_content="ok", messages=[])
        
        loop.runner.run = AsyncMock(side_effect=mock_run)
        
        msg_a = InboundMessage(channel="telegram", sender_id="user_a", chat_id="group_1", content="hi")
        msg_b = InboundMessage(channel="telegram", sender_id="user_b", chat_id="group_1", content="hi")
        
        task_a = asyncio.create_task(loop._handle_inbound(msg_a))
        await asyncio.sleep(0.05)
        task_b = asyncio.create_task(loop._handle_inbound(msg_b))
        
        while any(loop._active_tasks.values()):
            await asyncio.sleep(0.1)
            
        assert run_order == ["start_user_a", "end_user_a", "start_user_b", "end_user_b"]

    @pytest.mark.asyncio
    async def test_is_privileged_logic(self):
        """Verify _is_privileged logic across different configs."""
        # 1. Strict config: only 'alice' is privileged
        channels_config = MagicMock()
        channels_config.model_extra = {"telegram": {"allowFrom": ["alice"]}}
        loop, _ = _make_loop(channels_config=channels_config)
        
        assert loop._is_privileged("telegram", "alice") is True
        assert loop._is_privileged("telegram", "bob") is False
        assert loop._is_privileged("cli", "any") is True
        
        # 2. Wildcard config: back to old logic (everyone privileged)
        channels_config.model_extra = {"telegram": {"allowFrom": ["*"]}}
        assert loop._is_privileged("telegram", "bob") is True
        
        # 3. Multiple specific users: still strict
        channels_config.model_extra = {"telegram": {"allowFrom": ["alice", "charlie"]}}
        assert loop._is_privileged("telegram", "charlie") is True
        assert loop._is_privileged("telegram", "bob") is False

        # 4. Specific user + wildcard: also strict (specific users get privilege, others don't)
        channels_config.model_extra = {"telegram": {"allowFrom": ["alice", "*"]}}
        assert loop._is_privileged("telegram", "alice") is True
        assert loop._is_privileged("telegram", "bob") is False

    @pytest.mark.asyncio
    async def test_tool_filtering_execution(self):
        """Point 1: Filter tools if the user is not privileged."""
        channels_config = MagicMock()
        channels_config.model_extra = {
            "telegram": {"allowFrom": ["admin"]}
        }
        loop, bus = _make_loop(channels_config=channels_config)
        
        # We need real tools to test filtering
        from nanobot.agent.tools.filesystem import ReadFileTool
        from nanobot.agent.tools.message import MessageTool
        loop.tools.register(ReadFileTool(workspace=loop.workspace))
        loop.tools.register(MessageTool(send_callback=bus.publish_outbound))
        
        captured_spec = []
        async def mock_run(spec: AgentRunSpec):
            captured_spec.append(spec)
            return AgentRunResult(final_content="ok", messages=[])
        loop.runner.run = AsyncMock(side_effect=mock_run)
        
        # 1. Non-admin user
        msg_user = InboundMessage(channel="telegram", sender_id="user", chat_id="c1", content="hi")
        await loop._handle_inbound(msg_user)
        while any(loop._active_tasks.values()): await asyncio.sleep(0.1)
        
        user_tools = captured_spec[0].tools.tool_names
        assert "read_file" not in user_tools
        assert "message" in user_tools # Non-CLI tool preserved
        
        # 2. Admin user
        msg_admin = InboundMessage(channel="telegram", sender_id="admin", chat_id="c1", content="hi")
        await loop._handle_inbound(msg_admin)
        while any(loop._active_tasks.values()): await asyncio.sleep(0.1)
        
        admin_tools = captured_spec[1].tools.tool_names
        assert "read_file" in admin_tools
        assert "message" in admin_tools

        # 3. Empty sender_id (should be non-privileged by default in strict channel)
        msg_empty = InboundMessage(channel="telegram", sender_id="", chat_id="c1", content="hi")
        await loop._handle_inbound(msg_empty)
        while any(loop._active_tasks.values()): await asyncio.sleep(0.1)
        
        empty_tools = captured_spec[2].tools.tool_names
        assert "read_file" not in empty_tools

    @pytest.mark.asyncio
    async def test_sender_id_propagation_to_context(self):
        """Verify that sender_id is included in the LLM runtime context."""
        loop, bus = _make_loop()
        loop.runner.run = AsyncMock(return_value=AgentRunResult(final_content="ok", messages=[]))
        
        msg = InboundMessage(channel="telegram", sender_id="123|Alice", chat_id="c1", content="hi")
        await loop._handle_inbound(msg)
        while any(loop._active_tasks.values()): await asyncio.sleep(0.1)
        
        # Check that the first user message contains the sender ID
        initial_messages = loop.runner.run.call_args[0][0].initial_messages
        user_msg = initial_messages[-1]["content"]
        assert "Sender: 123|Alice" in user_msg
