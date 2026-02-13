from types import SimpleNamespace

from nanobot.providers.litellm_provider import LiteLLMProvider


def _build_response(content: str):
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=None)


def test_parse_plain_json_tool_call_from_content() -> None:
    provider = LiteLLMProvider(default_model="ollama/gpt-oss", provider_name="ollama_cloud")
    response = _build_response(
        'I will search now. {"name":"web_search","arguments":{"query":"best food in korea","count":5}}'
    )

    parsed = provider._parse_response(response)

    assert parsed.has_tool_calls is True
    assert parsed.tool_calls[0].name == "web_search"
    assert parsed.tool_calls[0].arguments["query"] == "best food in korea"


def test_parse_function_wrapped_tool_call_from_content() -> None:
    provider = LiteLLMProvider(default_model="ollama/gpt-oss", provider_name="ollama_cloud")
    response = _build_response(
        '{"function":{"name":"web_fetch","arguments":{"url":"https://example.com"}}}'
    )

    parsed = provider._parse_response(response)

    assert parsed.has_tool_calls is True
    assert parsed.tool_calls[0].name == "web_fetch"
    assert parsed.tool_calls[0].arguments["url"] == "https://example.com"
