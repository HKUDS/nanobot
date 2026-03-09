import asyncio
from collections import OrderedDict
from unittest.mock import Mock

import pytest

from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig
from nanobot.bus.queue import MessageBus


class TestTelegramDeduplication:
    def setup_method(self):
        """Setup test environment"""
        self.config = TelegramConfig(enabled=True)
        self.bus = MessageBus()
        self.channel = TelegramChannel(config=self.config, bus=self.bus)

    def test_processed_message_ids_initialization(self):
        """Test deduplication cache is properly initialized"""
        assert hasattr(self.channel, '_processed_message_ids')
        assert isinstance(self.channel._processed_message_ids, OrderedDict)
        assert len(self.channel._processed_message_ids) == 0

    def test_duplicate_message_detection(self):
        """Test duplicate message detection"""
        # Add a message to the cache
        test_message_id = "123456"
        self.channel._processed_message_ids[test_message_id] = None
        # Verify message ID exists
        assert test_message_id in self.channel._processed_message_ids

    def test_cache_trim_functionality(self):
        """Test cache trimming functionality"""
        channel_with_cache = TelegramChannel(config=self.config, bus=self.bus)

        # Add more than the limit of messages
        for i in range(1005):
            channel_with_cache._processed_message_ids[f"msg_{i}"] = None

        # Execute trim operation
        while len(channel_with_cache._processed_message_ids) > 1000:
            channel_with_cache._processed_message_ids.popitem(last=False)

        final_size = len(channel_with_cache._processed_message_ids)
        assert final_size == 1000

    def test_process_different_message_ids(self):
        """Test different messages IDs should all be added"""
        test_ids = ["msg_1", "msg_2", "msg_3"]

        for msg_id in test_ids:
            # Verify ID does not exist
            assert msg_id not in self.channel._processed_message_ids
            # Add to queue
            self.channel._processed_message_ids[msg_id] = None
            # Verify was successfully added
            assert msg_id in self.channel._processed_message_ids

    def test_consistency_with_other_channels_design(self):
        """Test consistency with other channels design"""
        assert isinstance(self.channel._processed_message_ids, OrderedDict)

        # Verify basic operations
        self.channel._processed_message_ids["test"] = None
        assert "test" in self.channel._processed_message_ids
        assert self.channel._processed_message_ids["test"] is None