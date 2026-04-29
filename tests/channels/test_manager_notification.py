"""Tests for gateway lifecycle notification in channel manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config
from nanobot.bus.queue import MessageBus


class TestGatewayLifecycleNotification:
    """Test gateway lifecycle notification behavior."""

    @pytest.mark.asyncio
    async def test_configured_target_sends_to_expected_channel_chat_id(self):
        """Test that configured target sends onStart/onStop to the expected channel/chat id."""
        # Create a mock Feishu channel with notification config
        mock_channel = MagicMock()
        mock_channel.name = "feishu"
        mock_channel.enabled = True

        # Create notification config
        mock_notification_cfg = MagicMock()
        type(mock_notification_cfg).chat_id_list = PropertyMock(return_value=["oc_test123"])
        type(mock_notification_cfg).on_start_message = PropertyMock(return_value="Gateway started")
        type(mock_notification_cfg).on_stop_message = PropertyMock(return_value="Gateway stopped")

        # Set up channel config with nested notification
        mock_channel.config = MagicMock()
        mock_channel.config.notification = mock_notification_cfg

        # Mock the send method to capture outbound messages
        mock_channel.send = AsyncMock()

        # Create channel manager with mock channel
        mock_config = MagicMock(spec=Config)
        mock_config.channels = MagicMock()
        mock_config.channels.send_max_retries = 0
        mock_config.gateway = MagicMock()
        type(mock_config.gateway).on_start = PropertyMock(return_value=None)
        type(mock_config.gateway).on_stop = PropertyMock(return_value=None)
        mock_bus = MagicMock(spec=MessageBus)
        mock_bus.consume_outbound = AsyncMock()

        with patch.object(ChannelManager, '_init_channels'):
            manager = ChannelManager(config=mock_config, bus=mock_bus)
            manager.channels = {"feishu": mock_channel}

            # Test on_start notification
            await manager._send_gateway_lifecycle_notification("on_start")

            # Verify send was called with correct parameters via OutboundMessage
            mock_channel.send.assert_called_once()
            call_args = mock_channel.send.call_args[0][0]
            assert call_args.chat_id == "oc_test123"
            assert call_args.content == "Gateway started"

            # Reset mock for on_stop test
            mock_channel.send.reset_mock()

            # Test on_stop notification
            await manager._send_gateway_lifecycle_notification("on_stop")

            # Verify send was called with correct parameters
            mock_channel.send.assert_called_once()
            call_args = mock_channel.send.call_args[0][0]
            assert call_args.chat_id == "oc_test123"
            assert call_args.content == "Gateway stopped"

    @pytest.mark.asyncio
    async def test_missing_target_does_not_fallback_to_invalid_channel(self):
        """Test that missing target does not fall back to an invalid channel.name."""
        # Create a mock channel without notification config
        mock_channel = MagicMock()
        mock_channel.name = "feishu"
        mock_channel.enabled = True

        # No notification config or empty config
        mock_channel.config = MagicMock()
        mock_channel.config.notification = None

        # Mock the send method
        mock_channel.send = AsyncMock()

        # Create channel manager with mock channel
        mock_config = MagicMock(spec=Config)
        mock_config.channels = MagicMock()
        mock_config.channels.send_max_retries = 0
        mock_config.gateway = MagicMock()
        mock_config.gateway.on_start = None
        mock_config.gateway.on_stop = None
        mock_bus = MagicMock(spec=MessageBus)
        mock_bus.consume_outbound = AsyncMock()

        with patch.object(ChannelManager, '_init_channels'):
            manager = ChannelManager(config=mock_config, bus=mock_bus)
            manager.channels = {"feishu": mock_channel}

            # Test on_start notification - should not send anything
            await manager._send_gateway_lifecycle_notification("on_start")

            # Verify send was NOT called
            mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_external_channel_is_no_op(self):
        """Test that no external channel is a no-op."""
        # Create channel manager with no channels
        mock_config = MagicMock(spec=Config)
        mock_config.channels = MagicMock()
        mock_config.gateway = MagicMock()
        mock_bus = MagicMock(spec=MessageBus)
        mock_bus.consume_outbound = AsyncMock()

        with patch.object(ChannelManager, '_init_channels'):
            manager = ChannelManager(config=mock_config, bus=mock_bus)
            manager.channels = {}

            # Call the method - should be a no-op
            await manager._send_gateway_lifecycle_notification("on_start")

            # The method should complete without errors even with no channels
            # (This test verifies no exception is raised)

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_block_shutdown(self):
        """Test that notification failure does not block shutdown."""
        # Create a mock channel that raises an exception
        mock_channel = MagicMock()
        mock_channel.name = "feishu"
        mock_channel.enabled = True

        # Create notification config
        mock_notification_cfg = MagicMock()
        type(mock_notification_cfg).chat_id_list = PropertyMock(return_value=["oc_test123"])
        type(mock_notification_cfg).on_start_message = PropertyMock(return_value="Gateway started")

        mock_channel.config = mock_notification_cfg

        # Mock send to raise an exception
        mock_channel.send = AsyncMock(side_effect=Exception("Network error"))

        # Create channel manager with mock channel
        mock_config = MagicMock(spec=Config)
        mock_config.channels = MagicMock()
        mock_config.channels.send_max_retries = 0
        mock_config.gateway = MagicMock()
        type(mock_config.gateway).on_start = PropertyMock(return_value=None)
        type(mock_config.gateway).on_stop = PropertyMock(return_value=None)
        mock_bus = MagicMock(spec=MessageBus)
        mock_bus.consume_outbound = AsyncMock()

        with patch.object(ChannelManager, '_init_channels'):
            manager = ChannelManager(config=mock_config, bus=mock_bus)
            manager.channels = {"feishu": mock_channel}

            # Test that exception is caught and doesn't block execution
            # Should not raise any exception
            await manager._send_gateway_lifecycle_notification("on_start")

            # Verify send was called (and failed)
            mock_channel.send.assert_called_once()

            # The method should complete without raising exception
            # (verified by no exception being raised above)
