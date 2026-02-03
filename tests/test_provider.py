import asyncio
import os

import pytest

from nanobot.providers.lazyllm_provider import LazyLLMProvider


SOURCE = "doubao"
API_KEY = os.getenv("NANOBOT_TEST_DOUBAO_API_KEY", "")
MODEL = "doubao-seed-1-8-251228"


class TestLazyLLMProvider:
    def test_init_with_real_config(self):
        provider = LazyLLMProvider(
            api_key=API_KEY,
            source=SOURCE,
            default_model=MODEL,
            type="LLM",
        )

        assert provider.source == SOURCE
        assert provider.default_model == MODEL
        assert provider.model_type == "LLM"
        assert provider.client is not None

    def test_chat_with_real_key(self):
        if not API_KEY:
            pytest.skip("Set NANOBOT_TEST_DOUBAO_API_KEY to run real network test.")
        provider = LazyLLMProvider(
            api_key=API_KEY,
            source=SOURCE,
            default_model=MODEL,
            type="LLM",
        )

        response = asyncio.run(
            provider.chat(
                messages=[{"role": "user", "content": "只回复: ok"}],
                max_tokens=32,
                temperature=0.1,
            )
        )

        assert response.finish_reason != "error"
        assert response.content is not None

    def test_invalid_model_type_raises(self):
        with pytest.raises(ValueError):
            LazyLLMProvider(type="AUDIO")

    def test_multimodal_payload_conversion(self):
        provider = LazyLLMProvider(
            api_key=API_KEY,
            source=SOURCE,
            default_model=MODEL,
            type="VLM",
        )

        system_prompt, history, current_input = provider._messages_to_lazyllm_payload(
            [
                {"role": "system", "content": "你是视觉助手"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "描述这张图"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "https://picsum.photos/200/300"
                            },
                        },
                    ],
                },
            ]
        )

        assert system_prompt == "你是视觉助手"
        assert history == []
        assert isinstance(current_input, dict)
        assert "messages" in current_input
        assert current_input["messages"][0]["role"] == "user"
        assert isinstance(current_input["messages"][0]["content"], list)

    def test_parse_response_with_tool_calls(self):
        provider = LazyLLMProvider(
            api_key=API_KEY,
            source=SOURCE,
            default_model=MODEL,
            type="LLM",
        )

        response = provider._parse_response(
            {
                "content": "调用工具中",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "read_file",
                            "arguments": "{\"path\": \"README.md\"}",
                        },
                    }
                ],
                "finish_reason": "tool_calls",
            }
        )

        assert response.finish_reason == "tool_calls"
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"path": "README.md"}
