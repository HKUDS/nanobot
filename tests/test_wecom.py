"""Tests for WeCom channel."""

import base64
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.wecom import WeComChannel, WeComCrypto, parse_xml


@pytest.fixture
def wecom_crypto():
    """Create WeComCrypto instance."""
    aes_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    return WeComCrypto("test_token", aes_key, "test_corp_id")


@pytest.fixture
def wecom_config():
    """Create mock WeComConfig."""
    config = MagicMock()
    config.corp_id = "test_corp_id"
    config.agent_id = 1000001
    config.corp_secret = "test_secret"
    config.token = "test_token"
    config.encoding_aes_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    config.callback_port = 18791
    config.callback_path = "/wecom/callback"
    config.api_base = None
    config.allow_from = []
    return config


@pytest.fixture
def message_bus():
    """Create mock MessageBus."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    return bus


class TestWeComCrypto:
    """Test WeComCrypto."""
    
    def test_encrypt_decrypt(self, wecom_crypto):
        """Test encryption and decryption."""
        original = "<xml><test>Hello</test></xml>"
        encrypted, _, _, _ = wecom_crypto.encrypt(original)
        decrypted = wecom_crypto.decrypt(encrypted)
        assert decrypted == original
    
    def test_verify_url(self, wecom_crypto):
        """Test URL verification."""
        echo_str = "<xml>test</xml>"
        encrypted, sig, ts, nonce = wecom_crypto.encrypt(echo_str)
        decrypted = wecom_crypto.verify_url(sig, ts, nonce, encrypted)
        assert decrypted == echo_str
    
    def test_invalid_key(self):
        """Test invalid key handling."""
        with pytest.raises(ValueError):
            WeComCrypto("token", "invalid", "corp_id")


class TestParseXML:
    """Test XML parsing."""
    
    def test_parse_text_message(self):
        """Test parsing text message."""
        xml = """
        <xml>
            <FromUserName><![CDATA[user1]]></FromUserName>
            <MsgType><![CDATA[text]]></MsgType>
            <Content><![CDATA[Hello]]></Content>
            <MsgId>123</MsgId>
        </xml>
        """
        msg = parse_xml(xml)
        assert msg["from_user"] == "user1"
        assert msg["msg_type"] == "text"
        assert msg["content"] == "Hello"
    
    def test_parse_invalid_xml(self):
        """Test parsing invalid XML."""
        msg = parse_xml("invalid")
        assert msg == {}


class TestWeComChannel:
    """Test WeComChannel."""
    
    @pytest.mark.asyncio
    async def test_send_text_message(self, wecom_config, message_bus):
        """Test sending text message."""
        channel = WeComChannel(wecom_config, message_bus)
        channel._access_token = "test_token"
        channel._connected = True
        channel._http = AsyncMock()
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0}
        channel._http.post = AsyncMock(return_value=mock_response)
        
        msg = OutboundMessage(channel="wecom", chat_id="user1", content="Hello")
        await channel.send(msg)
        
        channel._http.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_markdown_message(self, wecom_config, message_bus):
        """Test sending markdown message."""
        channel = WeComChannel(wecom_config, message_bus)
        channel._access_token = "test_token"
        channel._connected = True
        channel._http = AsyncMock()
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0}
        channel._http.post = AsyncMock(return_value=mock_response)
        
        msg = OutboundMessage(channel="wecom", chat_id="user1", content="**bold**")
        await channel.send(msg)
        
        call_args = channel._http.post.call_args
        assert call_args[1]["json"]["msgtype"] == "markdown"
    
    @pytest.mark.asyncio
    async def test_message_deduplication(self, wecom_config, message_bus):
        """Test message deduplication."""
        channel = WeComChannel(wecom_config, message_bus)
        
        channel._processed_message_ids["msg1"] = None
        channel._processed_message_ids["msg1"] = None
        
        assert len(channel._processed_message_ids) == 1
    
    @pytest.mark.asyncio
    async def test_markdown_detection(self, wecom_config, message_bus):
        """Test markdown detection."""
        channel = WeComChannel(wecom_config, message_bus)
        
        assert channel._is_markdown("**bold**")
        assert channel._is_markdown("## Heading")
        assert channel._is_markdown("- list")
        assert not channel._is_markdown("Plain text")
    
    @pytest.mark.asyncio
    async def test_send_no_token(self, wecom_config, message_bus):
        """Test sending without token."""
        channel = WeComChannel(wecom_config, message_bus)
        channel._access_token = None
        
        msg = OutboundMessage(channel="wecom", chat_id="user1", content="Hello")
        await channel.send(msg)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
