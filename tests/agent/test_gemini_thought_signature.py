from types import SimpleNamespace

from nanobot.providers.base import ToolCallRequest


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
