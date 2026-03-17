from types import SimpleNamespace

from nanobot.providers.base import ToolCallRequest
from nanobot.providers.litellm_provider import LiteLLMProvider


def test_litellm_parse_response_preserves_tool_call_provider_fields() -> None:
    provider = LiteLLMProvider(default_model="gemini/gemini-3-flash")

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_123",
                            function=SimpleNamespace(
                                name="read_file",
                                arguments='{"path":"todo.md"}',
                                provider_specific_fields={"inner": "value"},
                            ),
                            provider_specific_fields={"thought_signature": "signed-token"},
                        )
                    ],
                ),
            )
        ],
        usage=None,
    )

    parsed = provider._parse_response(response)

    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].provider_specific_fields == {"thought_signature": "signed-token"}
    assert parsed.tool_calls[0].function_provider_specific_fields == {"inner": "value"}


def test_tool_call_request_serializes_provider_fields() -> None:
    tool_call = ToolCallRequest(
        id="abc123xyz",
        name="read_file",
        arguments={"path": "todo.md"},
        provider_specific_fields={"thought_signature": "signed-token"},
        function_provider_specific_fields={"inner": "value"},
    )

    message = tool_call.to_openai_tool_call()

    assert message["provider_specific_fields"] == {"thought_signature": "signed-token"}
    assert message["function"]["provider_specific_fields"] == {"inner": "value"}
    assert message["function"]["arguments"] == '{"path": "todo.md"}'
