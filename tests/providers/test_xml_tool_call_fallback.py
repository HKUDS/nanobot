"""Tests for XML tool call fallback parser.

When models like mimo-v2.5 or glm-5.1 emit tool calls as XML text in the
content field instead of the structured tool_calls field, the fallback
parser extracts them so they are executed instead of leaking to channels.
"""

from nanobot.providers.base import LLMResponse
from nanobot.providers.openai_compat_provider import (
    _apply_xml_tool_call_fallback,
    _extract_xml_tool_calls,
)


# ---------------------------------------------------------------------------
# _extract_xml_tool_calls
# ---------------------------------------------------------------------------


class TestExtractXmlToolCalls:
    """Unit tests for _extract_xml_tool_calls helper."""

    def test_no_xml_returns_unchanged(self):
        content, calls = _extract_xml_tool_calls("Hello world")
        assert content == "Hello world"
        assert calls == []

    def test_none_returns_unchanged(self):
        content, calls = _extract_xml_tool_calls(None)
        assert content is None
        assert calls == []

    def test_empty_string_returns_unchanged(self):
        content, calls = _extract_xml_tool_calls("")
        assert content == ""
        assert calls == []

    def test_single_tool_call_single_param(self):
        raw = "<function=read_file>\n<parameter=path>/etc/hosts</parameter>\n</function>"
        content, calls = _extract_xml_tool_calls(raw)
        assert content is None
        assert len(calls) == 1
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"path": "/etc/hosts"}

    def test_single_tool_call_multi_param(self):
        raw = (
            "<function=write_file>\n"
            "<parameter=path>/tmp/test.txt</parameter>\n"
            "<parameter=content>hello world</parameter>\n"
            "</function>"
        )
        content, calls = _extract_xml_tool_calls(raw)
        assert content is None
        assert len(calls) == 1
        assert calls[0].name == "write_file"
        assert calls[0].arguments == {"path": "/tmp/test.txt", "content": "hello world"}

    def test_tool_call_with_surrounding_text(self):
        raw = "gestalt\n<function=exec>\n<parameter=command>ls -la</parameter>\n</function>\nascus"
        content, calls = _extract_xml_tool_calls(raw)
        assert content == "gestalt\n\nascus"  # newline left after XML removal
        assert len(calls) == 1
        assert calls[0].name == "exec"
        assert calls[0].arguments == {"command": "ls -la"}

    def test_tool_name_with_dashes(self):
        raw = "<function=minimax-web_search>\n<parameter=query>test</parameter>\n</function>"
        content, calls = _extract_xml_tool_calls(raw)
        assert len(calls) == 1
        assert calls[0].name == "minimax-web_search"

    def test_param_value_with_special_chars(self):
        raw = (
            "<function=exec>\n"
            "<parameter=command>grep -r 'pattern' /var/log/ 2>/dev/null | head -20</parameter>\n"
            "</function>"
        )
        content, calls = _extract_xml_tool_calls(raw)
        assert len(calls) == 1
        assert "grep -r" in calls[0].arguments["command"]

    def test_param_value_with_json(self):
        raw = (
            "<function=call_tool>\n"
            '<parameter=data>{"key": "value", "nested": [1, 2]}</parameter>\n'
            "</function>"
        )
        content, calls = _extract_xml_tool_calls(raw)
        assert len(calls) == 1
        assert calls[0].arguments["data"] == '{"key": "value", "nested": [1, 2]}'

    def test_id_is_generated(self):
        raw = "<function=test>\n<parameter=x>1</parameter>\n</function>"
        content, calls = _extract_xml_tool_calls(raw)
        assert calls[0].id  # non-empty string
        assert len(calls[0].id) == 9  # matches _short_tool_id format

    def test_function_prefix_alone_no_close_is_not_matched(self):
        """Incomplete XML should not be parsed."""
        raw = "<function=read_file>\n<parameter=path>/etc/hosts</parameter>"
        content, calls = _extract_xml_tool_calls(raw)
        assert content == raw  # unchanged — no closing </function>
        assert calls == []


# ---------------------------------------------------------------------------
# _apply_xml_tool_call_fallback
# ---------------------------------------------------------------------------


class TestApplyXmlToolCallFallback:
    """Tests for _apply_xml_tool_call_fallback response wrapper."""

    def test_structured_tool_calls_untouched(self):
        """When structured tool_calls exist, do not apply fallback."""
        resp = LLMResponse(
            content="Using tool...",
            tool_calls=[__import__("nanobot.providers.base", fromlist=["ToolCallRequest"]).ToolCallRequest(
                id="tc_123", name="read_file", arguments={"path": "/etc/hosts"},
            )],
            finish_reason="tool_calls",
        )
        result = _apply_xml_tool_call_fallback(resp)
        assert result is resp  # same object, not modified

    def test_xml_in_content_converted_to_tool_calls(self):
        resp = LLMResponse(
            content="<function=read_file>\n<parameter=path>/etc/hosts</parameter>\n</function>",
            tool_calls=[],
            finish_reason="stop",
        )
        result = _apply_xml_tool_call_fallback(resp)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.finish_reason == "tool_calls"
        assert result.content is None  # XML stripped

    def test_no_xml_no_change(self):
        resp = LLMResponse(content="Hello!", tool_calls=[], finish_reason="stop")
        result = _apply_xml_tool_call_fallback(resp)
        assert result is resp

    def test_preserves_usage_and_reasoning(self):
        resp = LLMResponse(
            content="<function=exec>\n<parameter=command>echo hi</parameter>\n</function>",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            reasoning_content="I need to run a command",
        )
        result = _apply_xml_tool_call_fallback(resp)
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}
        assert result.reasoning_content == "I need to run a command"
