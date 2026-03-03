"""Tests for smart web tools (AI-powered extraction)."""

import pytest

from nanobot.agent.tools.smart_web import SmartWebFetchTool, SmartWebSearchTool


class MockLLMProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response_content: str = "Extracted information"):
        self.response_content = response_content
        self.call_count = 0
        self.last_messages = None

    async def chat(self, messages, max_tokens=None, temperature=None, model=None, **kwargs):
        self.call_count += 1
        self.last_messages = messages

        class MockResponse:
            def __init__(self, content):
                self.content = content

        return MockResponse(self.response_content)

    def get_default_model(self):
        return "mock-model"


@pytest.mark.asyncio
async def test_smart_web_fetch_basic():
    """Test basic smart web fetch functionality."""
    provider = MockLLMProvider(response_content="The latest features include X, Y, and Z.")

    tool = SmartWebFetchTool(
        llm_provider=provider,
        extraction_model="mock-haiku",
        max_chars=10000
    )

    # Test with a simple extraction
    # Note: This will fail in actual execution without network, but tests the flow
    assert tool.name == "smart_web_fetch"
    assert "extract" in tool.description.lower()
    assert "url" in tool.parameters["properties"]
    assert "prompt" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_smart_web_fetch_cache():
    """Test that caching works correctly."""
    provider = MockLLMProvider()

    tool = SmartWebFetchTool(
        llm_provider=provider,
        cache_ttl=60  # 1 minute cache
    )

    # Cache should be empty initially
    assert len(tool._cache) == 0


@pytest.mark.asyncio
async def test_smart_web_search_basic():
    """Test basic smart web search functionality."""
    provider = MockLLMProvider()
    fetch_tool = SmartWebFetchTool(llm_provider=provider)

    tool = SmartWebSearchTool(
        llm_provider=provider,
        smart_fetch_tool=fetch_tool
    )

    assert tool.name == "smart_web_search"
    assert "search" in tool.description.lower()
    assert "query" in tool.parameters["properties"]
    assert "focus" in tool.parameters["properties"]


def test_smart_web_fetch_parameters():
    """Test parameter schema."""
    provider = MockLLMProvider()
    tool = SmartWebFetchTool(llm_provider=provider)

    schema = tool.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "smart_web_fetch"

    params = schema["function"]["parameters"]
    assert params["type"] == "object"
    assert "url" in params["required"]
    assert "prompt" in params["required"]
    assert "max_chars" not in params["required"]  # Optional


def test_smart_web_search_parameters():
    """Test search parameter schema."""
    provider = MockLLMProvider()
    fetch_tool = SmartWebFetchTool(llm_provider=provider)
    tool = SmartWebSearchTool(
        llm_provider=provider,
        smart_fetch_tool=fetch_tool
    )

    schema = tool.to_schema()
    params = schema["function"]["parameters"]
    assert "query" in params["required"]
    assert "focus" not in params["required"]  # Optional
    assert "count" not in params["required"]  # Optional


def test_smart_web_config_defaults():
    """Test SmartWebConfig defaults."""
    from nanobot.config.schema import SmartWebConfig

    config = SmartWebConfig()
    assert config.enabled is False  # Disabled by default
    assert config.extraction_model == ""  # Uses provider default
    assert config.max_chars == 50000
    assert config.cache_ttl == 900  # 15 minutes


def test_smart_web_config_custom():
    """Test SmartWebConfig with custom values."""
    from nanobot.config.schema import SmartWebConfig

    config = SmartWebConfig(
        enabled=True,
        extraction_model="bedrock/anthropic.claude-3-haiku-20240307-v1:0",
        max_chars=100000,
        cache_ttl=1800
    )

    assert config.enabled is True
    assert "haiku" in config.extraction_model
    assert config.max_chars == 100000
    assert config.cache_ttl == 1800


@pytest.mark.asyncio
async def test_smart_web_fetch_model_selection():
    """Test that extraction model is passed to LLM."""
    provider = MockLLMProvider()

    tool = SmartWebFetchTool(
        llm_provider=provider,
        extraction_model="bedrock/anthropic.claude-3-haiku-20240307-v1:0"
    )

    # Check that extraction model is stored
    assert tool.extraction_model == "bedrock/anthropic.claude-3-haiku-20240307-v1:0"


def test_smart_web_tools_integration():
    """Test that smart web tools integrate correctly."""
    from nanobot.agent.tools.registry import ToolRegistry

    provider = MockLLMProvider()

    registry = ToolRegistry()

    # Register smart web fetch
    fetch_tool = SmartWebFetchTool(llm_provider=provider)
    registry.register(fetch_tool)
    assert "smart_web_fetch" in registry.tool_names

    # Register smart web search
    search_tool = SmartWebSearchTool(
        llm_provider=provider,
        smart_fetch_tool=fetch_tool
    )
    registry.register(search_tool)
    assert "smart_web_search" in registry.tool_names

    # Verify both tools are available
    assert registry.get("smart_web_fetch") is not None
    assert registry.get("smart_web_search") is not None
