"""Tests for browser automation tool."""

import base64
from unittest.mock import AsyncMock, Mock, patch

import pytest

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.browser import (
    BrowserActionTool,
    BrowserManager,
    BrowserSession,
)


class TestBrowserSession:
    """Test cases for BrowserSession class."""

    def test_browser_session_creation(self):
        """Test BrowserSession dataclass creation."""
        mock_context = Mock()
        mock_page = Mock()
        session = BrowserSession(
            id="test_session",
            context=mock_context,
            page=mock_page,
        )

        assert session.id == "test_session"
        assert session.context == mock_context
        assert session.page == mock_page


class TestBrowserManager:
    """Test cases for BrowserManager class."""

    def test_browser_manager_init(self):
        """Test BrowserManager initialization."""
        manager = BrowserManager(max_contexts=10, session_timeout=3600)

        assert manager._playwright is None
        assert manager._browser is None
        assert manager._sessions == {}
        assert manager._max_contexts == 10
        assert manager._session_timeout == 3600
        assert manager._browser_installed is None

    def test_browser_manager_defaults(self):
        """Test BrowserManager default values."""
        manager = BrowserManager()

        assert manager._max_contexts == 5
        assert manager._session_timeout == 1800

    def test_get_session_empty(self):
        """Test getting session when none exist."""
        manager = BrowserManager()

        session = manager.get_session("nonexistent")

        assert session is None

    def test_get_session_existing(self):
        """Test getting existing session."""
        manager = BrowserManager()
        mock_session = BrowserSession(id="test", context=Mock(), page=Mock())
        manager._sessions["test"] = mock_session

        session = manager.get_session("test")

        assert session is mock_session

    def test_session_count(self):
        """Test session count property."""
        manager = BrowserManager()

        assert manager.session_count == 0

        manager._sessions["test1"] = BrowserSession(id="test1", context=Mock(), page=Mock())
        manager._sessions["test2"] = BrowserSession(id="test2", context=Mock(), page=Mock())

        assert manager.session_count == 2

    def test_get_sessions_copy(self):
        """Test that get_sessions returns a copy."""
        manager = BrowserManager()
        mock_session = BrowserSession(id="test", context=Mock(), page=Mock())
        manager._sessions["test"] = mock_session

        sessions = manager.get_sessions()

        # Should be a copy, not the same object
        assert sessions is not manager._sessions
        assert sessions == manager._sessions

    def test_update_session_activity(self):
        """Test updating session activity."""
        manager = BrowserManager()
        manager._sessions["test"] = BrowserSession(id="test", context=Mock(), page=Mock())

        import time
        before = time.time()
        manager.update_session_activity("test")
        after = time.time()

        last_used = manager.get_session_last_used("test")
        assert before <= last_used <= after

    def test_get_session_last_used_nonexistent(self):
        """Test getting last used time for nonexistent session."""
        manager = BrowserManager()

        last_used = manager.get_session_last_used("nonexistent")

        assert last_used is None

    @pytest.mark.asyncio
    async def test_launch_browser(self, mock_playwright):
        """Test launching browser."""
        manager = BrowserManager()
        await manager.launch()

        assert manager._playwright is not None
        assert manager._browser is not None

    @pytest.mark.asyncio
    async def test_launch_browser_already_running(self, mock_playwright):
        """Test launching browser when already running."""
        manager = BrowserManager()
        await manager.launch()

        # Launch again - should not create new instances
        playwright_instance = manager._playwright
        browser_instance = manager._browser

        await manager.launch()

        assert manager._playwright is playwright_instance
        assert manager._browser is browser_instance

    @pytest.mark.asyncio
    async def test_create_session(self, mock_playwright):
        """Test creating a new browser session."""
        manager = BrowserManager()
        await manager.launch()

        session = await manager.create_session("test_session")

        assert session.id == "test_session"
        assert session.context is not None
        assert session.page is not None
        assert "test_session" in manager._sessions

    @pytest.mark.asyncio
    async def test_create_session_auto_id(self, mock_playwright):
        """Test creating session with auto-generated ID."""
        manager = BrowserManager()
        await manager.launch()

        session = await manager.create_session()

        assert session.id is not None
        assert len(session.id) == 8  # UUID[:8]
        assert session.id in manager._sessions

    @pytest.mark.asyncio
    async def test_create_session_max_contexts(self, mock_playwright):
        """Test creating session when max contexts reached."""
        manager = BrowserManager(max_contexts=2)
        await manager.launch()

        # Create max sessions
        await manager.create_session("session1")
        await manager.create_session("session2")

        # Try to create one more - should raise error
        with pytest.raises(RuntimeError, match="Max browser contexts"):
            await manager.create_session("session3")

    @pytest.mark.asyncio
    async def test_close_session(self, mock_playwright):
        """Test closing a specific session."""
        manager = BrowserManager()
        await manager.launch()
        session = await manager.create_session("test_session")

        success = await manager.close_session("test_session")

        assert success is True
        assert "test_session" not in manager._sessions

    @pytest.mark.asyncio
    async def test_close_session_nonexistent(self, mock_playwright):
        """Test closing nonexistent session."""
        manager = BrowserManager()

        success = await manager.close_session("nonexistent")

        assert success is False

    @pytest.mark.asyncio
    async def test_close_all(self, mock_playwright):
        """Test closing all sessions and browser."""
        manager = BrowserManager()
        await manager.launch()
        await manager.create_session("session1")
        await manager.create_session("session2")

        await manager.close()

        assert manager._sessions == {}
        assert manager._browser is None
        assert manager._playwright is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, mock_playwright):
        """Test cleanup of expired sessions."""
        manager = BrowserManager(session_timeout=1)  # 1 second timeout
        await manager.launch()
        await manager.create_session("session1")
        await manager.create_session("session2")

        # Mark one as old
        import time
        old_time = time.time() - 2
        manager._session_last_used["session1"] = old_time

        # Create new session to trigger cleanup
        await manager.create_session("session3")

        # Old session should be cleaned up
        assert "session1" not in manager._sessions
        assert "session2" in manager._sessions
        assert "session3" in manager._sessions


class TestBrowserActionTool:
    """Test cases for BrowserActionTool class."""

    def test_browser_action_tool_init(self):
        """Test BrowserActionTool initialization."""
        tool = BrowserActionTool(enable_vision=True)

        assert tool.name == "browser_action"
        assert tool._enable_vision is True
        assert tool._current_session_id is None

    def test_browser_action_tool_init_without_vision(self):
        """Test BrowserActionTool initialization without vision."""
        tool = BrowserActionTool(enable_vision=False)

        assert tool._enable_vision is False

    def test_browser_action_tool_default_session_id(self):
        """Test default session ID constant."""
        assert BrowserActionTool.DEFAULT_SESSION_ID == "default"

    def test_browser_action_tool_name(self):
        """Test tool name property."""
        tool = BrowserActionTool()
        assert tool.name == "browser_action"

    def test_browser_action_tool_description_with_vision(self):
        """Test tool description with vision enabled."""
        tool = BrowserActionTool(enable_vision=True)
        description = tool.description

        assert "Screenshot returns image for multimodal models" in description

    def test_browser_action_tool_description_without_vision(self):
        """Test tool description without vision."""
        tool = BrowserActionTool(enable_vision=False)
        description = tool.description

        assert "Screenshot returns text description only" in description

    def test_browser_action_tool_parameters(self):
        """Test tool parameters schema."""
        tool = BrowserActionTool()
        params = tool.parameters

        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert "session" in params["properties"]
        assert "url" in params["properties"]
        assert "selector" in params["properties"]
        assert "text" in params["properties"]
        assert "checked" in params["properties"]
        assert "script" in params["properties"]
        assert "timeout" in params["properties"]
        assert params["required"] == ["action"]

    def test_browser_action_tool_action_enum(self):
        """Test action enum values."""
        tool = BrowserActionTool()
        actions = tool.parameters["properties"]["action"]["enum"]

        expected_actions = [
            "launch", "new_session", "close_session", "list_sessions",
            "navigate", "click", "type", "check", "screenshot",
            "evaluate", "console", "network", "wait", "close"
        ]
        assert actions == expected_actions

    @pytest.mark.asyncio
    async def test_execute_launch(self, mock_playwright):
        """Test launch action."""
        tool = BrowserActionTool()
        result = await tool.execute(action="launch")

        assert isinstance(result, ToolResult)
        assert "Browser launched successfully" in result.content
        assert result.images is None

    @pytest.mark.asyncio
    async def test_execute_new_session(self, mock_playwright):
        """Test new_session action."""
        tool = BrowserActionTool()
        result = await tool.execute(action="new_session", session="test_session")

        assert isinstance(result, ToolResult)
        assert "Created new session: test_session" in result.content

    @pytest.mark.asyncio
    async def test_execute_new_session_auto_id(self, mock_playwright):
        """Test new_session action with auto-generated ID."""
        tool = BrowserActionTool()
        result = await tool.execute(action="new_session")

        assert isinstance(result, ToolResult)
        assert "Created new session:" in result.content

    @pytest.mark.asyncio
    async def test_execute_close_session(self, mock_playwright):
        """Test close_session action."""
        tool = BrowserActionTool()
        # First create a session
        await tool.execute(action="new_session", session="test_session")

        # Then close it
        result = await tool.execute(action="close_session", session="test_session")

        assert isinstance(result, ToolResult)
        assert "Closed session: test_session" in result.content

    @pytest.mark.asyncio
    async def test_execute_close_session_missing_id(self, mock_playwright):
        """Test close_session action without session_id."""
        tool = BrowserActionTool()
        result = await tool.execute(action="close_session")

        assert isinstance(result, ToolResult)
        assert "Error: session_id required" in result.content

    @pytest.mark.asyncio
    async def test_execute_list_sessions_empty(self, mock_playwright):
        """Test list_sessions action with no sessions."""
        tool = BrowserActionTool()
        result = await tool.execute(action="list_sessions")

        assert isinstance(result, ToolResult)
        assert "No active sessions" in result.content

    @pytest.mark.asyncio
    async def test_execute_list_sessions_with_sessions(self, mock_playwright):
        """Test list_sessions action with active sessions."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="session1")
        await tool.execute(action="new_session", session="session2")

        result = await tool.execute(action="list_sessions")

        assert isinstance(result, ToolResult)
        assert "Active sessions:" in result.content
        assert "session1" in result.content
        assert "session2" in result.content

    @pytest.mark.asyncio
    async def test_execute_navigate(self, mock_playwright):
        """Test navigate action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="navigate",
            session="test_session",
            url="https://example.com"
        )

        assert isinstance(result, ToolResult)
        assert "Navigated to https://example.com" in result.content
        assert "Session: test_session" in result.content

    @pytest.mark.asyncio
    async def test_execute_navigate_missing_url(self, mock_playwright):
        """Test navigate action without URL."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(action="navigate", session="test_session")

        assert isinstance(result, ToolResult)
        assert "Error: url required" in result.content

    @pytest.mark.asyncio
    async def test_execute_click(self, mock_playwright):
        """Test click action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="click",
            session="test_session",
            selector="#submit-button"
        )

        assert isinstance(result, ToolResult)
        assert "Clicked element: #submit-button" in result.content

    @pytest.mark.asyncio
    async def test_execute_type(self, mock_playwright):
        """Test type action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="type",
            session="test_session",
            selector="#input-field",
            text="Hello, World!"
        )

        assert isinstance(result, ToolResult)
        assert "Typed text into: #input-field" in result.content

    @pytest.mark.asyncio
    async def test_execute_type_missing_text(self, mock_playwright):
        """Test type action without text."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="type",
            session="test_session",
            selector="#input-field"
        )

        assert isinstance(result, ToolResult)
        assert "Error: text required" in result.content

    @pytest.mark.asyncio
    async def test_execute_check(self, mock_playwright):
        """Test check action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="check",
            session="test_session",
            selector="#checkbox",
            checked=True
        )

        assert isinstance(result, ToolResult)
        assert "Set #checkbox to checked" in result.content

    @pytest.mark.asyncio
    async def test_execute_screenshot_with_vision(self, mock_playwright):
        """Test screenshot action with vision enabled."""
        tool = BrowserActionTool(enable_vision=True)
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(action="screenshot", session="test_session")

        assert isinstance(result, ToolResult)
        assert "Screenshot captured" in result.content
        assert result.images is not None
        assert len(result.images) == 1
        assert result.images[0]["type"] == "image_url"
        assert "data:image/png;base64," in result.images[0]["image_url"]["url"]

    @pytest.mark.asyncio
    async def test_execute_screenshot_without_vision(self, mock_playwright):
        """Test screenshot action without vision."""
        tool = BrowserActionTool(enable_vision=False)
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(action="screenshot", session="test_session")

        assert isinstance(result, ToolResult)
        assert "Screenshot captured" in result.content
        assert "vision disabled" in result.content
        assert result.images is None

    @pytest.mark.asyncio
    async def test_execute_evaluate(self, mock_playwright):
        """Test evaluate action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="evaluate",
            session="test_session",
            script="document.title"
        )

        assert isinstance(result, ToolResult)
        assert "Script result:" in result.content

    @pytest.mark.asyncio
    async def test_execute_console(self, mock_playwright):
        """Test console action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(action="console", session="test_session")

        assert isinstance(result, ToolResult)
        assert "No console logs captured" in result.content

    @pytest.mark.asyncio
    async def test_execute_network(self, mock_playwright):
        """Test network action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(action="network", session="test_session")

        assert isinstance(result, ToolResult)
        assert "No network requests captured" in result.content

    @pytest.mark.asyncio
    async def test_execute_wait(self, mock_playwright):
        """Test wait action."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(
            action="wait",
            session="test_session",
            selector="#element",
            timeout=5000
        )

        assert isinstance(result, ToolResult)
        assert "Element found: #element" in result.content

    @pytest.mark.asyncio
    async def test_execute_close(self, mock_playwright):
        """Test close action."""
        tool = BrowserActionTool()
        await tool.execute(action="launch")

        result = await tool.execute(action="close")

        assert isinstance(result, ToolResult)
        assert "Browser closed" in result.content

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, mock_playwright):
        """Test unknown action."""
        tool = BrowserActionTool()
        result = await tool.execute(action="unknown")

        assert isinstance(result, ToolResult)
        assert "Unknown action: unknown" in result.content

    @pytest.mark.asyncio
    async def test_execute_auto_create_default_session(self, mock_playwright):
        """Test auto-creation of default session."""
        tool = BrowserActionTool()

        # Navigate without creating session first
        result = await tool.execute(
            action="navigate",
            url="https://example.com"
        )

        assert isinstance(result, ToolResult)
        assert "Session: default" in result.content
        assert "Navigated to https://example.com" in result.content

    @pytest.mark.asyncio
    async def test_execute_with_nonexistent_session(self, mock_playwright):
        """Test action with nonexistent session."""
        tool = BrowserActionTool()

        result = await tool.execute(
            action="navigate",
            session="nonexistent",
            url="https://example.com"
        )

        assert isinstance(result, ToolResult)
        assert "Error: Session 'nonexistent' not found" in result.content

    @pytest.mark.asyncio
    async def test_execute_without_playwright(self):
        """Test execution when Playwright is not available."""
        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", False):
            tool = BrowserActionTool()
            result = await tool.execute(action="launch")

            assert isinstance(result, ToolResult)
            assert "Error: Playwright is not installed" in result.content

    @pytest.mark.asyncio
    async def test_execute_error_handling(self, mock_playwright):
        """Test error handling in execute."""
        tool = BrowserActionTool()
        # Force an error by using invalid action
        result = await tool.execute(action="invalid")

        assert isinstance(result, ToolResult)
        assert "Error:" in result.content or "Unknown action" in result.content

    @pytest.mark.asyncio
    async def test_session_activity_tracking(self, mock_playwright):
        """Test that session activity is tracked."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="test_session")

        import time
        before = time.time()
        await tool.execute(action="navigate", session="test_session", url="https://example.com")
        after = time.time()

        last_used = tool._manager.get_session_last_used("test_session")
        assert before <= last_used <= after

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(self, mock_playwright):
        """Test that multiple sessions are isolated."""
        tool = BrowserActionTool()
        await tool.execute(action="new_session", session="session1")
        await tool.execute(action="new_session", session="session2")

        # Navigate in session1
        result1 = await tool.execute(
            action="navigate",
            session="session1",
            url="https://example1.com"
        )

        # Navigate in session2
        result2 = await tool.execute(
            action="navigate",
            session="session2",
            url="https://example2.com"
        )

        assert "Session: session1" in result1.content
        assert "Session: session2" in result2.content
        assert "example1.com" in result1.content
        assert "example2.com" in result2.content

    @pytest.mark.asyncio
    async def test_screenshot_image_format(self, mock_playwright):
        """Test that screenshot returns proper image format."""
        tool = BrowserActionTool(enable_vision=True)
        await tool.execute(action="new_session", session="test_session")

        result = await tool.execute(action="screenshot", session="test_session")

        assert result.images is not None
        assert len(result.images) == 1
        image = result.images[0]
        assert image["type"] == "image_url"
        assert "url" in image["image_url"]
        assert image["image_url"]["url"].startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_tool_result_to_message_content_with_images(self, sample_image_b64):
        """Test ToolResult.to_message_content with images."""
        from nanobot.agent.tools.base import ToolResult

        result = ToolResult(
            content="Screenshot captured",
            images=[{
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
            }]
        )

        content = result.to_message_content()

        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "image_url"
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "Screenshot captured"

    @pytest.mark.asyncio
    async def test_tool_result_to_message_content_without_images(self):
        """Test ToolResult.to_message_content without images."""
        from nanobot.agent.tools.base import ToolResult

        result = ToolResult(content="Text result", images=None)

        content = result.to_message_content()

        assert content == "Text result"

    @pytest.mark.asyncio
    async def test_tool_result_to_message_content_empty_images(self):
        """Test ToolResult.to_message_content with empty images list."""
        from nanobot.agent.tools.base import ToolResult

        result = ToolResult(content="Text result", images=[])

        content = result.to_message_content()

        assert content == "Text result"

    @pytest.mark.asyncio
    async def test_multiple_screenshots(self, mock_playwright):
        """Test taking multiple screenshots."""
        tool = BrowserActionTool(enable_vision=True)
        await tool.execute(action="new_session", session="test_session")

        result1 = await tool.execute(action="screenshot", session="test_session")
        result2 = await tool.execute(action="screenshot", session="test_session")

        assert result1.images is not None
        assert result2.images is not None
        # Each should have one image
        assert len(result1.images) == 1
        assert len(result2.images) == 1

    @pytest.mark.asyncio
    async def test_session_timeout_cleanup(self, mock_playwright):
        """Test that sessions are cleaned up after timeout."""
        tool = BrowserActionTool(session_timeout=1)  # 1 second timeout
        await tool.execute(action="new_session", session="test_session")

        # Wait for timeout
        import time
        time.sleep(1.1)

        # Create new session to trigger cleanup
        await tool.execute(action="new_session", session="new_session")

        # Old session should be cleaned up
        assert "test_session" not in tool._manager._sessions
        assert "new_session" in tool._manager._sessions
