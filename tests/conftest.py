"""Shared fixtures and configuration for nanobot tests."""

import asyncio
import base64
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Fixtures for common test objects
@pytest.fixture
def mock_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def mock_message_bus():
    """Create a mock MessageBus."""
    bus = Mock()
    bus.publish_inbound = AsyncMock()
    bus.publish_outbound = AsyncMock()
    return bus


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    return {
        "enabled": True,
        "allow_from": ["test_user"],
    }


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider."""
    provider = Mock()
    provider.chat = AsyncMock()
    provider.chat_with_retry = AsyncMock()
    provider.get_default_model = Mock(return_value="test-model")
    provider.supports_vision = Mock(return_value=True)
    return provider


@pytest.fixture
def sample_image_data():
    """Create sample image data for testing."""
    # Create a minimal 1x1 PNG image
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    return png_data


@pytest.fixture
def sample_image_b64(sample_image_data):
    """Create base64-encoded sample image."""
    return base64.b64encode(sample_image_data).decode()


@pytest.fixture
def mock_playwright():
    """Create a mock Playwright instance."""
    with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
        with patch("nanobot.agent.tools.browser.async_playwright") as mock_pw:
            mock_playwright_instance = AsyncMock()
            mock_pw.return_value = mock_playwright_instance
            
            # Mock browser
            mock_browser = AsyncMock()
            mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            
            # Mock context and page
            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            
            # Mock page methods
            mock_page.goto = AsyncMock()
            mock_page.title = AsyncMock(return_value="Test Page")
            mock_page.click = AsyncMock()
            mock_page.fill = AsyncMock()
            mock_page.set_checked = AsyncMock()
            mock_page.screenshot = AsyncMock(return_value=b"fake_screenshot")
            mock_page.evaluate = AsyncMock(return_value="result")
            mock_page.wait_for_selector = AsyncMock()
            mock_page.on = Mock()
            
            yield {
                "playwright": mock_playwright_instance,
                "browser": mock_browser,
                "context": mock_context,
                "page": mock_page,
            }


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_inbound_message():
    """Create a mock inbound message."""
    from nanobot.bus.events import InboundMessage
    
    return InboundMessage(
        channel="test",
        sender_id="test_user",
        chat_id="test_chat",
        content="Test message",
        media=[],
        metadata={},
    )


@pytest.fixture
def mock_outbound_message():
    """Create a mock outbound message."""
    from nanobot.bus.events import OutboundMessage
    
    return OutboundMessage(
        channel="test",
        chat_id="test_chat",
        content="Test response",
        metadata={},
    )


@pytest.fixture
def mock_session():
    """Create a mock session."""
    from nanobot.session.manager import Session
    
    return Session(key="test:chat")


@pytest.fixture
def mock_session_manager(mock_workspace):
    """Create a mock session manager."""
    from nanobot.session.manager import SessionManager
    
    return SessionManager(mock_workspace)


# Async test helpers
@pytest.fixture
async def async_mock_function():
    """Create an async mock function."""
    async def mock_func(*args, **kwargs):
        return "mocked_result"
    return mock_func


# File system helpers
@pytest.fixture
def create_test_file(mock_workspace):
    """Helper to create test files."""
    def _create(path: str, content: str = "test content"):
        file_path = mock_workspace / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return file_path
    return _create


@pytest.fixture
def create_test_dir(mock_workspace):
    """Helper to create test directories."""
    def _create(path: str):
        dir_path = mock_workspace / path
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path
    return _create


# Channel-specific fixtures
@pytest.fixture
def mock_discord_config():
    """Create mock Discord configuration."""
    return {
        "enabled": True,
        "token": "test_token",
        "allow_from": ["test_user"],
        "gateway_url": "wss://gateway.discord.gg/?v=10&encoding=json",
        "intents": 37377,
        "group_policy": "mention",
    }


@pytest.fixture
def mock_wecom_config():
    """Create mock WeCom configuration."""
    return {
        "enabled": True,
        "bot_id": "test_bot_id",
        "secret": "test_secret",
        "allow_from": ["test_user"],
        "welcome_message": "Welcome!",
    }


@pytest.fixture
def mock_qq_config():
    """Create mock QQ configuration."""
    return {
        "enabled": True,
        "app_id": "test_app_id",
        "secret": "test_secret",
        "allow_from": ["test_user"],
        "msg_format": "plain",
    }


@pytest.fixture
def mock_whatsapp_config():
    """Create mock WhatsApp configuration."""
    return {
        "enabled": True,
        "bridge_url": "ws://localhost:3001",
        "bridge_token": "test_token",
        "allow_from": ["+1234567890"],
    }


# Tool-related fixtures
@pytest.fixture
def mock_tool_registry():
    """Create a mock tool registry."""
    from nanobot.agent.tools.registry import ToolRegistry
    
    registry = ToolRegistry()
    return registry


@pytest.fixture
def mock_tool_result():
    """Create a mock tool result."""
    from nanobot.agent.tools.base import ToolResult
    
    return ToolResult(
        content="Tool executed successfully",
        images=None,
    )


@pytest.fixture
def mock_multimodal_tool_result(sample_image_b64):
    """Create a mock multimodal tool result with image."""
    from nanobot.agent.tools.base import ToolResult
    
    return ToolResult(
        content="Screenshot captured",
        images=[{
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
        }],
    )


# Provider-related fixtures
@pytest.fixture
def mock_provider_spec():
    """Create a mock provider spec."""
    from nanobot.providers.registry import ProviderSpec
    
    return ProviderSpec(
        name="test_provider",
        keywords=("test",),
        env_key="TEST_API_KEY",
        display_name="Test Provider",
        litellm_prefix="test",
        supports_vision=True,
    )


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    from nanobot.providers.base import LLMResponse, ToolCallRequest
    
    return LLMResponse(
        content="Test response",
        tool_calls=[
            ToolCallRequest(
                id="test_call_id",
                name="test_tool",
                arguments={"param": "value"},
            )
        ],
        finish_reason="stop",
    )


# Error handling fixtures
@pytest.fixture
def mock_exception():
    """Create a mock exception."""
    return Exception("Test exception")


@pytest.fixture
def mock_timeout_exception():
    """Create a mock timeout exception."""
    return asyncio.TimeoutError("Test timeout")


# Network-related fixtures
@pytest.fixture
def mock_http_response():
    """Create a mock HTTP response."""
    response = Mock()
    response.status_code = 200
    response.json = Mock(return_value={"data": "test"})
    response.text = "test response"
    response.content = b"test content"
    return response


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_http_response())
    client.post = AsyncMock(return_value=mock_http_response())
    client.aclose = AsyncMock()
    return client


# WebSocket-related fixtures
@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock(return_value='{"type": "test"}')
    ws.close = AsyncMock()
    return ws


# Logging fixtures
@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.debug = Mock()
    return logger


# Time-related fixtures
@pytest.fixture
def mock_datetime():
    """Create a mock datetime."""
    from datetime import datetime
    
    with patch("nanobot.session.manager.datetime") as mock_dt:
        mock_dt.now = Mock(return_value=datetime(2024, 1, 1, 12, 0, 0))
        mock_dt.fromisoformat = Mock(return_value=datetime(2024, 1, 1, 12, 0, 0))
        yield mock_dt


# JSON-related fixtures
@pytest.fixture
def sample_json_data():
    """Create sample JSON data for testing."""
    return {
        "key1": "value1",
        "key2": 123,
        "key3": True,
        "key4": None,
        "key5": ["item1", "item2"],
        "key6": {"nested": "data"},
    }


# Message-related fixtures
@pytest.fixture
def sample_messages():
    """Create sample messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
    ]


@pytest.fixture
def sample_multimodal_messages(sample_image_b64):
    """Create sample multimodal messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
                },
                {"type": "text", "text": "What do you see?"}
            ]
        },
    ]


# Configuration-related fixtures
@pytest.fixture
def mock_web_search_config():
    """Create mock web search configuration."""
    return {
        "provider": "brave",
        "apiKey": "test_api_key",
        "maxResults": 5,
    }


@pytest.fixture
def mock_exec_config():
    """Create mock execution configuration."""
    return {
        "timeout": 30,
        "restrict_to_workspace": False,
        "path_append": "",
    }


# MCP-related fixtures
@pytest.fixture
def mock_mcp_servers():
    """Create mock MCP servers configuration."""
    return {
        "test_server": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-test"],
        }
    }


# Cron-related fixtures
@pytest.fixture
def mock_cron_service():
    """Create a mock cron service."""
    service = Mock()
    service.add_job = Mock()
    service.remove_job = Mock()
    service.list_jobs = Mock(return_value=[])
    return service


# Memory-related fixtures
@pytest.fixture
def mock_memory_store(mock_workspace):
    """Create a mock memory store."""
    from nanobot.agent.memory import MemoryStore
    
    return MemoryStore(mock_workspace)


# Skills-related fixtures
@pytest.fixture
def mock_skills_loader(mock_workspace):
    """Create a mock skills loader."""
    from nanobot.agent.skills import SkillsLoader
    
    return SkillsLoader(mock_workspace)


# Context builder fixture
@pytest.fixture
def mock_context_builder(mock_workspace):
    """Create a mock context builder."""
    from nanobot.agent.context import ContextBuilder
    
    return ContextBuilder(mock_workspace)


# Agent loop fixture
@pytest.fixture
def mock_agent_loop(mock_workspace, mock_llm_provider, mock_message_bus):
    """Create a mock agent loop."""
    from nanobot.agent.loop import AgentLoop
    
    return AgentLoop(
        bus=mock_message_bus,
        provider=mock_llm_provider,
        workspace=mock_workspace,
        model="test-model",
    )


# Subagent manager fixture
@pytest.fixture
def mock_subagent_manager(mock_workspace, mock_llm_provider, mock_message_bus):
    """Create a mock subagent manager."""
    from nanobot.agent.subagent import SubagentManager
    
    return SubagentManager(
        provider=mock_llm_provider,
        workspace=mock_workspace,
        bus=mock_message_bus,
        model="test-model",
    )


# Memory consolidator fixture
@pytest.fixture
def mock_memory_consolidator(mock_workspace, mock_llm_provider, mock_session_manager):
    """Create a mock memory consolidator."""
    from nanobot.agent.memory import MemoryConsolidator
    
    return MemoryConsolidator(
        workspace=mock_workspace,
        provider=mock_llm_provider,
        model="test-model",
        sessions=mock_session_manager,
        context_window_tokens=65536,
        build_messages=Mock(return_value=[]),
        get_tool_definitions=Mock(return_value=[]),
    )
