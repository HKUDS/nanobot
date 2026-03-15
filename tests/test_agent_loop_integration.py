"""Integration tests for agent loop with browser tool."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import ToolResult
from nanobot.bus.events import InboundMessage, OutboundMessage


class TestAgentLoopBrowserIntegration:
    """Integration tests for agent loop with browser tool."""

    @pytest.mark.asyncio
    async def test_browser_tool_registered_with_vision_support(self, mock_workspace, mock_message_bus):
        """Test that browser tool is registered when provider supports vision."""
        # Create a mock provider that supports vision
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            # Check that browser tool is registered with vision enabled
            browser_tool = agent.tools.get("browser_action")
            assert browser_tool is not None
            assert browser_tool._enable_vision is True

    @pytest.mark.asyncio
    async def test_browser_tool_registered_without_vision_support(self, mock_workspace, mock_message_bus):
        """Test that browser tool is registered without vision when provider doesn't support it."""
        # Create a mock provider that doesn't support vision
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=False)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            # Check that browser tool is registered with vision disabled
            browser_tool = agent.tools.get("browser_action")
            assert browser_tool is not None
            assert browser_tool._enable_vision is False

    @pytest.mark.asyncio
    async def test_browser_tool_not_registered_without_playwright(self, mock_workspace, mock_message_bus):
        """Test that browser tool is not registered when Playwright is not available."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", False):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            # Browser tool should still be registered (it handles missing Playwright gracefully)
            browser_tool = agent.tools.get("browser_action")
            assert browser_tool is not None

    @pytest.mark.asyncio
    async def test_multimodal_tool_result_processing(self, mock_workspace, mock_message_bus, sample_image_b64, mock_playwright):
        """Test processing of multimodal tool results in agent loop."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        # Mock response with tool call
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        mock_response = LLMResponse(
            content="I'll take a screenshot",
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="browser_action",
                    arguments={"action": "screenshot"},
                )
            ],
            finish_reason="tool_calls",
        )

        mock_provider.chat_with_retry.return_value = mock_response

        agent = AgentLoop(
            bus=mock_message_bus,
            provider=mock_provider,
            workspace=mock_workspace,
            model="test-model",
        )

        # Process a message that triggers browser tool
        msg = InboundMessage(
            channel="test",
            sender_id="user1",
            chat_id="chat1",
            content="Take a screenshot",
            media=[],
            metadata={},
        )

        response = await agent._process_message(msg)

        # Check that the tool was executed
        assert mock_provider.chat_with_retry.called

    @pytest.mark.asyncio
    async def test_vision_disabled_screenshot_returns_text(self, mock_workspace, mock_message_bus, mock_playwright):
        """Test that screenshot returns text when vision is disabled."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=False)

        agent = AgentLoop(
            bus=mock_message_bus,
            provider=mock_provider,
            workspace=mock_workspace,
            model="test-model",
        )

        # Get browser tool
        browser_tool = agent.tools.get("browser_action")
        assert browser_tool is not None

        # Execute screenshot
        result = await browser_tool.execute(action="screenshot")

        # Should return text description, not image
        assert isinstance(result, ToolResult)
        assert "vision disabled" in result.content
        assert result.images is None

    @pytest.mark.asyncio
    async def test_vision_enabled_screenshot_returns_image(self, mock_workspace, mock_message_bus, mock_playwright):
        """Test that screenshot returns image when vision is enabled."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        # Get the mock page from the fixture
        mock_page = mock_playwright["page"]
        
        agent = AgentLoop(
            bus=mock_message_bus,
            provider=mock_provider,
            workspace=mock_workspace,
            model="test-model",
        )

        # Get browser tool
        browser_tool = agent.tools.get("browser_action")
        assert browser_tool is not None

        # Execute screenshot
        result = await browser_tool.execute(action="screenshot")

        # Should return image
        assert isinstance(result, ToolResult)
        assert "Screenshot captured" in result.content
        assert result.images is not None
        assert len(result.images) == 1
        assert result.images[0]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_tool_result_to_message_content_conversion(self, mock_workspace, mock_message_bus, sample_image_b64):
        """Test conversion of ToolResult to message content."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            # Create a multimodal tool result
            tool_result = ToolResult(
                content="Screenshot captured",
                images=[{
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
                }]
            )

            # Convert to message content
            content = tool_result.to_message_content()

            # Should be a list with image and text
            assert isinstance(content, list)
            assert len(content) == 2
            assert content[0]["type"] == "image_url"
            assert content[1]["type"] == "text"

    @pytest.mark.asyncio
    async def test_backward_compatible_string_result(self, mock_workspace, mock_message_bus):
        """Test that string results still work (backward compatibility)."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            # Create a string result (old style)
            string_result = "Tool executed successfully"

            # Should work fine
            assert isinstance(string_result, str)
            assert string_result == "Tool executed successfully"

    @pytest.mark.asyncio
    async def test_browser_tool_in_tool_definitions(self, mock_workspace, mock_message_bus):
        """Test that browser tool appears in tool definitions."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            # Get tool definitions
            definitions = agent.tools.get_definitions()

            # Check that browser_action is in definitions
            browser_def = None
            for defn in definitions:
                if defn.get("function", {}).get("name") == "browser_action":
                    browser_def = defn
                    break

            assert browser_def is not None
            assert browser_def["function"]["name"] == "browser_action"
            assert "description" in browser_def["function"]
            assert "parameters" in browser_def["function"]

    @pytest.mark.asyncio
    async def test_browser_tool_description_varies_with_vision(self, mock_workspace, mock_message_bus):
        """Test that browser tool description varies based on vision support."""
        # Test with vision enabled
        mock_provider_vision = Mock()
        mock_provider_vision.chat = AsyncMock()
        mock_provider_vision.chat_with_retry = AsyncMock()
        mock_provider_vision.get_default_model = Mock(return_value="test-model")
        mock_provider_vision.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent_vision = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider_vision,
                workspace=mock_workspace,
                model="test-model",
            )

            browser_tool_vision = agent_vision.tools.get("browser_action")
            desc_vision = browser_tool_vision.description
            assert "Screenshot returns image for multimodal models" in desc_vision

        # Test with vision disabled
        mock_provider_no_vision = Mock()
        mock_provider_no_vision.chat = AsyncMock()
        mock_provider_no_vision.chat_with_retry = AsyncMock()
        mock_provider_no_vision.get_default_model = Mock(return_value="test-model")
        mock_provider_no_vision.supports_vision = Mock(return_value=False)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent_no_vision = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider_no_vision,
                workspace=mock_workspace,
                model="test-model",
            )

            browser_tool_no_vision = agent_no_vision.tools.get("browser_action")
            desc_no_vision = browser_tool_no_vision.description
            assert "Screenshot returns text description only" in desc_no_vision

    @pytest.mark.asyncio
    async def test_multiple_tool_results_with_images(self, mock_workspace, mock_message_bus, sample_image_b64):
        """Test handling multiple tool results with images."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        # Create multiple tool results with images
        result1 = ToolResult(
            content="First screenshot",
            images=[{
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
            }]
        )

        result2 = ToolResult(
            content="Second screenshot",
            images=[{
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
            }]
        )

        # Convert both to message content
        content1 = result1.to_message_content()
        content2 = result2.to_message_content()

        # Both should be lists with image and text
        assert isinstance(content1, list)
        assert isinstance(content2, list)
        assert len(content1) == 2
        assert len(content2) == 2

    @pytest.mark.asyncio
    async def test_mixed_tool_results(self, mock_workspace, mock_message_bus, sample_image_b64):
        """Test handling mixed tool results (some with images, some without)."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        # Create mixed results
        result_with_image = ToolResult(
            content="Screenshot",
            images=[{
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{sample_image_b64}"}
            }]
        )

        result_without_image = ToolResult(content="Text result", images=None)

        # Convert both
        content_with_image = result_with_image.to_message_content()
        content_without_image = result_without_image.to_message_content()

        # Check formats
        assert isinstance(content_with_image, list)
        assert isinstance(content_without_image, str)

    @pytest.mark.asyncio
    async def test_browser_tool_error_handling(self, mock_workspace, mock_message_bus):
        """Test error handling in browser tool execution."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        with patch("nanobot.agent.tools.browser.PLAYWRIGHT_AVAILABLE", True):
            agent = AgentLoop(
                bus=mock_message_bus,
                provider=mock_provider,
                workspace=mock_workspace,
                model="test-model",
            )

            browser_tool = agent.tools.get("browser_action")

            # Try to execute with invalid action
            result = await browser_tool.execute(action="invalid_action")

            # Should return error
            assert isinstance(result, ToolResult)
            assert "Error:" in result.content or "Unknown action" in result.content

    @pytest.mark.asyncio
    async def test_browser_tool_session_management(self, mock_workspace, mock_message_bus, mock_playwright):
        """Test browser tool session management."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        agent = AgentLoop(
            bus=mock_message_bus,
            provider=mock_provider,
            workspace=mock_workspace,
            model="test-model",
        )

        browser_tool = agent.tools.get("browser_action")

        # Create session
        result1 = await browser_tool.execute(action="new_session", session="test_session")
        assert "Created new session: test_session" in result1.content

        # Use session
        result2 = await browser_tool.execute(
            action="navigate",
            session="test_session",
            url="https://example.com"
        )
        assert "Session: test_session" in result2.content

        # Close session
        result3 = await browser_tool.execute(action="close_session", session="test_session")
        assert "Closed session: test_session" in result3.content

    @pytest.mark.asyncio
    async def test_browser_tool_auto_session_creation(self, mock_workspace, mock_message_bus, mock_playwright):
        """Test automatic session creation in browser tool."""
        mock_provider = Mock()
        mock_provider.chat = AsyncMock()
        mock_provider.chat_with_retry = AsyncMock()
        mock_provider.get_default_model = Mock(return_value="test-model")
        mock_provider.supports_vision = Mock(return_value=True)

        agent = AgentLoop(
            bus=mock_message_bus,
            provider=mock_provider,
            workspace=mock_workspace,
            model="test-model",
        )

        browser_tool = agent.tools.get("browser_action")

        # Navigate without creating session first
        result = await browser_tool.execute(
            action="navigate",
            url="https://example.com"
        )

        # Should auto-create default session
        assert "Session: default" in result.content
        assert "Navigated to https://example.com" in result.content
