"""Tests for BedrockProvider."""

import base64
from unittest.mock import MagicMock, patch

from nanobot.providers.bedrock_provider import BedrockProvider

# ---------------------------------------------------------------------------
# Helpers -- create provider without hitting real boto3
# ---------------------------------------------------------------------------

def _make_provider(**kwargs):
    """Create a BedrockProvider with _create_client patched out."""
    defaults = {"region": "us-east-1", "model": "bedrock/anthropic.claude-opus-4-6-v1"}
    defaults.update(kwargs)
    with patch.object(BedrockProvider, "_create_client", return_value=MagicMock()):
        return BedrockProvider(**defaults)


# ===========================================================================
# Model ID extraction
# ===========================================================================

class TestModelIdExtraction:
    def test_simple_model(self):
        assert BedrockProvider._extract_model_id("bedrock/anthropic.claude-opus-4-6-v1") == "anthropic.claude-opus-4-6-v1"

    def test_cross_region_model(self):
        assert BedrockProvider._extract_model_id("bedrock/us.anthropic.claude-opus-4-6-v1") == "us.anthropic.claude-opus-4-6-v1"

    def test_global_model_with_context(self):
        assert BedrockProvider._extract_model_id("bedrock/global.anthropic.claude-opus-4-6-v1[1m]") == "global.anthropic.claude-opus-4-6-v1[1m]"

    def test_no_prefix(self):
        assert BedrockProvider._extract_model_id("anthropic.claude-opus-4-6-v1") == "anthropic.claude-opus-4-6-v1"


# ===========================================================================
# Region inference
# ===========================================================================

class TestRegionInference:
    def test_us_prefix(self):
        assert BedrockProvider._infer_region("us.anthropic.claude-opus-4-6-v1") == "us-east-1"

    def test_eu_prefix(self):
        assert BedrockProvider._infer_region("eu.anthropic.claude-opus-4-6-v1") == "eu-west-1"

    def test_ap_prefix(self):
        assert BedrockProvider._infer_region("ap.anthropic.claude-opus-4-6-v1") == "ap-northeast-1"

    def test_global_prefix(self):
        assert BedrockProvider._infer_region("global.anthropic.claude-opus-4-6-v1") == "us-east-1"

    def test_no_cross_region_prefix(self):
        assert BedrockProvider._infer_region("anthropic.claude-opus-4-6-v1") is None


# ===========================================================================
# Message conversion
# ===========================================================================

class TestMessageConversion:
    def test_system_message_extracted(self):
        provider = _make_provider()
        system, msgs = provider._convert_messages([
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ])
        assert system == [{"text": "You are helpful."}]
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_text_message(self):
        provider = _make_provider()
        _, msgs = provider._convert_messages([{"role": "user", "content": "Hello"}])
        assert msgs == [{"role": "user", "content": [{"text": "Hello"}]}]

    def test_assistant_message(self):
        provider = _make_provider()
        _, msgs = provider._convert_messages([
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ])
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == [{"text": "Hello!"}]

    def test_tool_call_message(self):
        provider = _make_provider()
        _, msgs = provider._convert_messages([
            {"role": "user", "content": "Read file"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "/tmp/x"}'}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
        ])
        # Assistant message should have toolUse block
        assistant_blocks = msgs[1]["content"]
        tool_use = [b for b in assistant_blocks if "toolUse" in b]
        assert len(tool_use) == 1
        assert tool_use[0]["toolUse"]["name"] == "read_file"
        assert tool_use[0]["toolUse"]["input"] == {"path": "/tmp/x"}

        # Tool result should be a user message with toolResult block
        user_result = msgs[2]
        assert user_result["role"] == "user"
        tool_result = [b for b in user_result["content"] if "toolResult" in b]
        assert len(tool_result) == 1
        assert tool_result[0]["toolResult"]["toolUseId"] == "call_1"

    def test_image_message(self):
        provider = _make_provider()
        img_data = base64.b64encode(b"fake_png_data").decode()
        _, msgs = provider._convert_messages([{"role": "user", "content": [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_data}"}}
        ]}])
        blocks = msgs[0]["content"]
        assert blocks[0] == {"text": "What is this?"}
        assert "image" in blocks[1]
        assert blocks[1]["image"]["format"] == "png"

    def test_consecutive_same_role_merged(self):
        provider = _make_provider()
        _, msgs = provider._convert_messages([
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "World"},
        ])
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert len(msgs[0]["content"]) == 2


# ===========================================================================
# Tool conversion
# ===========================================================================

class TestToolConversion:
    def test_basic_tool(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }]
        result = BedrockProvider._convert_tools(tools)
        assert len(result) == 1
        spec = result[0]["toolSpec"]
        assert spec["name"] == "read_file"
        assert spec["description"] == "Read a file"
        assert spec["inputSchema"]["json"]["properties"]["path"]["type"] == "string"

    def test_empty_tools(self):
        assert BedrockProvider._convert_tools([]) == []

    def test_multiple_tools(self):
        tools = [
            {"type": "function", "function": {"name": "a", "description": "A", "parameters": {}}},
            {"type": "function", "function": {"name": "b", "description": "B", "parameters": {}}},
        ]
        result = BedrockProvider._convert_tools(tools)
        assert len(result) == 2
        assert result[0]["toolSpec"]["name"] == "a"
        assert result[1]["toolSpec"]["name"] == "b"


# ===========================================================================
# Chat method
# ===========================================================================

class TestChatMethod:
    async def test_basic_chat(self):
        provider = _make_provider()
        provider.client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hello!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
        }

        response = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

        assert response.content == "Hello!"
        assert response.finish_reason == "stop"
        assert response.usage["prompt_tokens"] == 10
        assert response.usage["completion_tokens"] == 5
        assert response.usage["total_tokens"] == 15

    async def test_chat_with_tool_calls(self):
        provider = _make_provider()
        provider.client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "call_1", "name": "read_file", "input": {"path": "/tmp/x"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
        }

        response = await provider.chat(
            messages=[{"role": "user", "content": "Read /tmp/x"}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
            }],
        )

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"path": "/tmp/x"}
        assert response.finish_reason == "tool_calls"

    async def test_chat_error_handling(self):
        from botocore.exceptions import ClientError

        provider = _make_provider()
        provider.client.converse.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )

        response = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

        assert response.finish_reason == "error"
        assert "Rate limited" in response.content

    async def test_chat_generic_error(self):
        provider = _make_provider()
        provider.client.converse.side_effect = RuntimeError("connection lost")

        response = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

        assert response.finish_reason == "error"
        assert "connection lost" in response.content

    async def test_chat_passes_system_and_tools(self):
        provider = _make_provider()
        provider.client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {},
        }

        await provider.chat(
            messages=[
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "Hi"},
            ],
            tools=[{
                "type": "function",
                "function": {"name": "t", "description": "d", "parameters": {}},
            }],
        )

        call_kwargs = provider.client.converse.call_args[1]
        assert "system" in call_kwargs
        assert call_kwargs["system"] == [{"text": "Be brief."}]
        assert "toolConfig" in call_kwargs


# ===========================================================================
# Authentication
# ===========================================================================

class TestAuthentication:
    def test_iam_auth_no_api_key(self):
        with patch("boto3.client") as mock_client:
            mock_client.return_value = MagicMock()
            BedrockProvider(
                region="us-east-1",
                model="bedrock/anthropic.claude-opus-4-6-v1",
            )
            mock_client.assert_called_once_with(
                "bedrock-runtime", region_name="us-east-1",
            )

    def test_api_key_auth(self):
        with patch("botocore.session.Session") as mock_sess_cls:
            mock_session = MagicMock()
            mock_sess_cls.return_value = mock_session
            mock_client = MagicMock()
            mock_session.create_client.return_value = mock_client

            BedrockProvider(
                api_key="test-key-123",
                region="us-east-1",
                model="bedrock/anthropic.claude-opus-4-6-v1",
            )
            mock_session.create_client.assert_called_once()
            # Verify the event handler was registered for bearer token
            mock_client.meta.events.register.assert_called_once()


# ===========================================================================
# Default model
# ===========================================================================

class TestGetDefaultModel:
    def test_returns_configured_model(self):
        provider = _make_provider(model="bedrock/anthropic.claude-opus-4-6-v1")
        assert provider.get_default_model() == "bedrock/anthropic.claude-opus-4-6-v1"

    def test_returns_custom_model(self):
        provider = _make_provider(model="bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0")
        assert provider.get_default_model() == "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"
