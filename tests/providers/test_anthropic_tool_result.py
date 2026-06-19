"""Tests for AnthropicProvider._tool_result_block image_url conversion.

Regression for: tool results containing OpenAI-format image_url blocks
(e.g. from read_file on an image file, via build_image_content_blocks)
were passed to Anthropic unconverted, causing silent image drops with a
"Non-transient LLM error with image content, retrying without images"
warning.

Also tests that bare dicts without a "type" field are coerced to text
blocks, fixing Anthropic "content.0.type: Field required" rejections (#3993).
"""

from nanobot.providers.anthropic_provider import AnthropicProvider


def test_tool_result_block_converts_image_url_in_list_content():
    """image_url blocks inside tool_result list content must be translated
    to Anthropic-native image blocks; sibling text blocks pass through."""
    msg = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AAAA"},
                "_meta": {"path": "/tmp/x.png"},
            },
            {"type": "text", "text": "(Image file: /tmp/x.png)"},
        ],
    }
    block = AnthropicProvider._tool_result_block(msg)

    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_1"
    content = block["content"]
    assert isinstance(content, list)
    assert content[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "AAAA",
        },
    }
    assert content[1] == {"type": "text", "text": "(Image file: /tmp/x.png)"}


def test_tool_result_block_preserves_string_content():
    """String content must be passed through unchanged; the image-conversion
    path for lists must not affect the string path."""
    msg = {
        "role": "tool",
        "tool_call_id": "call_2",
        "content": "plain tool output",
    }
    block = AnthropicProvider._tool_result_block(msg)

    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_2"
    assert block["content"] == "plain tool output"


def test_convert_user_content_coerces_typeless_dict():
    """Bare dicts without a "type" field must be coerced to text blocks.
    Regression for #3993: tools returning plain dicts caused Anthropic to
    reject the request with "content.0.type: Field required"."""
    result = AnthropicProvider._convert_user_content([
        {"foo": "bar"},
        {"type": "text", "text": "ok"},
    ])
    assert result[0] == {"type": "text", "text": str({"foo": "bar"})}
    assert result[1] == {"type": "text", "text": "ok"}


def test_convert_user_content_coerces_mixed_typeless():
    """Multiple typeless items and non-dict items are all handled."""
    result = AnthropicProvider._convert_user_content([
        42,
        {"key": "val"},
    ])
    assert result[0] == {"type": "text", "text": "42"}
    assert result[1] == {"type": "text", "text": str({"key": "val"})}


def test_convert_assistant_message_repairs_history_tool_arguments():
    blocks = AnthropicProvider._assistant_blocks({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "toolu_1",
            "function": {"name": "read_file", "arguments": '{path:"foo.txt"}'},
        }],
    })

    assert blocks[0]["type"] == "tool_use"
    assert blocks[0]["input"] == {"path": "foo.txt"}


def test_anthropic_sanitizes_invalid_tool_ids_consistently():
    """Invalid restored IDs must be valid for Anthropic and keep pairs matched."""
    blocks = AnthropicProvider._assistant_blocks({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_abc|rs.same",
            "function": {"name": "read_file", "arguments": "{}"},
        }],
    })
    result = AnthropicProvider._tool_result_block({
        "role": "tool",
        "tool_call_id": "call_abc|rs.same",
        "content": "ok",
    })

    tool_id = blocks[0]["id"]
    assert tool_id == result["tool_use_id"]
    assert tool_id != "call_abc|rs.same"
    assert all(ch.isalnum() or ch in "_-" for ch in tool_id)


def test_anthropic_sanitized_tool_ids_avoid_simple_collisions():
    """Replacement-only sanitizing would collapse these two ids to call_a."""
    blocks = AnthropicProvider._assistant_blocks({
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call.a", "function": {"name": "a", "arguments": "{}"}},
            {"id": "call|a", "function": {"name": "b", "arguments": "{}"}},
        ],
    })

    ids = [block["id"] for block in blocks if block["type"] == "tool_use"]
    assert len(ids) == len(set(ids)) == 2
    assert all(all(ch.isalnum() or ch in "_-" for ch in tool_id) for tool_id in ids)
