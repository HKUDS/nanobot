"""Tests for OllamaProvider."""

from __future__ import annotations

import pytest

from nanobot.providers.ollama_provider import OllamaProvider


@pytest.fixture
def provider():
    return OllamaProvider()


class TestConvertTools:
    def test_basic_tool(self, provider):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city name",
                            }
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        result = provider._convert_tools(tools)

        assert len(result) == 1
        fn = result[0].function
        assert fn.name == "get_weather"
        assert fn.description == "Get the weather for a location"
        assert fn.parameters.required == ["location"]
        prop = fn.parameters.properties["location"]
        assert prop.type == "string"
        assert prop.description == "The city name"

    def test_extra_json_schema_fields_are_dropped(self, provider):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "set_volume",
                    "description": "Set volume level",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "level": {
                                "type": "integer",
                                "description": "Volume 0-100",
                                "minimum": 0,
                                "maximum": 100,
                            }
                        },
                        "required": ["level"],
                    },
                },
            }
        ]
        result = provider._convert_tools(tools)

        prop = result[0].function.parameters.properties["level"]
        assert prop.type == "integer"
        assert prop.description == "Volume 0-100"
        # Extra JSON Schema fields are not present on the Property object
        assert not hasattr(prop, "minimum")
        assert not hasattr(prop, "maximum")

    def test_enum_field_is_preserved(self, provider):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "set_mode",
                    "description": "Set the mode",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": ["fast", "slow", "auto"],
                            }
                        },
                        "required": ["mode"],
                    },
                },
            }
        ]
        result = provider._convert_tools(tools)

        prop = result[0].function.parameters.properties["mode"]
        assert prop.enum == ["fast", "slow", "auto"]

    def test_items_field_is_preserved(self, provider):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_tags",
                    "description": "Add tags",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            }
                        },
                        "required": [],
                    },
                },
            }
        ]
        result = provider._convert_tools(tools)

        prop = result[0].function.parameters.properties["tags"]
        assert prop.type == "array"
        assert prop.items == {"type": "string"}

    def test_empty_tools_list(self, provider):
        assert provider._convert_tools([]) == []

    def test_multiple_tools(self, provider):
        tools = [
            {"type": "function", "function": {"name": "tool_a", "description": "", "parameters": {"type": "object", "properties": {}, "required": []}}},
            {"type": "function", "function": {"name": "tool_b", "description": "", "parameters": {"type": "object", "properties": {}, "required": []}}},
        ]
        result = provider._convert_tools(tools)

        assert len(result) == 2
        assert result[0].function.name == "tool_a"
        assert result[1].function.name == "tool_b"

    def test_tool_with_no_properties(self, provider):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "Ping the server",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
        ]
        result = provider._convert_tools(tools)

        fn = result[0].function
        assert fn.name == "ping"
        assert fn.parameters.properties == {}
        assert fn.parameters.required == []


class TestConvertMessages:
    def test_plain_string_content_passthrough(self):
        messages = [{"role": "user", "content": "hello"}]
        result = OllamaProvider._convert_messages(messages)

        assert result == [{"role": "user", "content": "hello"}]

    def test_does_not_mutate_input(self):
        original = {"role": "user", "content": "hello"}
        messages = [original]
        OllamaProvider._convert_messages(messages)

        assert original == {"role": "user", "content": "hello"}

    def test_list_content_flattened_to_string(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "text", "text": "this"},
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        assert result[0]["content"] == "describe this"
        assert "images" not in result[0]

    def test_image_url_extracted_to_images_field(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/pic.jpg"}},
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        assert result[0]["content"] == "what is this?"
        assert result[0]["images"] == ["https://example.com/pic.jpg"]

    def test_data_uri_prefix_stripped_from_image(self):
        b64 = "iVBORw0KGgoAAAANSUhEUgAAAAUA"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        assert result[0]["images"] == [b64]

    def test_multiple_images_collected(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
                    {"type": "image_url", "image_url": {"url": "https://example.com/b.jpg"}},
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        assert result[0]["images"] == [
            "https://example.com/a.jpg",
            "https://example.com/b.jpg",
        ]

    def test_no_images_field_when_no_images(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}
        ]
        result = OllamaProvider._convert_messages(messages)

        assert "images" not in result[0]

    def test_non_dict_parts_skipped(self):
        messages = [
            {"role": "user", "content": ["not a dict", {"type": "text", "text": "hello"}]}
        ]
        result = OllamaProvider._convert_messages(messages)

        assert result[0]["content"] == "hello"

    def test_tool_call_arguments_string_parsed_to_dict(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "Paris"}',
                        },
                    }
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        tc = result[0]["tool_calls"][0]
        assert tc["function"]["arguments"] == {"location": "Paris"}

    def test_tool_call_arguments_dict_left_unchanged(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": {"location": "Paris"},
                        },
                    }
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        tc = result[0]["tool_calls"][0]
        assert tc["function"]["arguments"] == {"location": "Paris"}

    def test_tool_call_invalid_json_arguments_becomes_empty_dict(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "bad_tool", "arguments": "{not valid json"},
                    }
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        tc = result[0]["tool_calls"][0]
        assert tc["function"]["arguments"] == {}

    def test_other_tool_call_fields_preserved(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "type": "function",
                        "function": {"name": "ping", "arguments": "{}"},
                    }
                ],
            }
        ]
        result = OllamaProvider._convert_messages(messages)

        tc = result[0]["tool_calls"][0]
        assert tc["id"] == "call_xyz"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "ping"

    def test_multiple_messages_all_converted(self):
        messages = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "f", "arguments": '{"x": 1}'}},
                ],
            },
        ]
        result = OllamaProvider._convert_messages(messages)

        assert len(result) == 3
        assert result[0]["content"] == "you are helpful"
        assert result[1]["content"] == "hi"
        assert result[2]["tool_calls"][0]["function"]["arguments"] == {"x": 1}
