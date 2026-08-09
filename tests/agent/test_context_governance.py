from nanobot.agent.context_governance import ContextGovernor


def _image_result(label: str) -> list[dict]:
    return [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{label}"}},
        {"type": "text", "text": label},
    ]


def _assistant_tool_call(call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": "exec", "arguments": "{}"},
        }],
    }


def test_drop_orphan_tool_results_drops_missing_tool_call_id() -> None:
    messages = [
        _assistant_tool_call("call_1"),
        {"role": "tool", "name": "exec", "content": "missing id"},
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "ok"},
    ]

    result = ContextGovernor.drop_orphan_tool_results(messages)

    assert [m.get("tool_call_id") for m in result if m.get("role") == "tool"] == ["call_1"]


def test_drop_orphan_tool_results_drops_duplicate_tool_result() -> None:
    messages = [
        _assistant_tool_call("call_1"),
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "first"},
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "duplicate"},
    ]

    result = ContextGovernor.drop_orphan_tool_results(messages)

    tool_results = [m for m in result if m.get("role") == "tool"]
    assert len(tool_results) == 1
    assert tool_results[0]["content"] == "first"


def test_drop_stale_visual_tool_images_keeps_latest_per_tool() -> None:
    messages = [
        {"role": "tool", "name": "computer_use", "content": _image_result("history")},
        {"role": "tool", "name": "computer_use", "content": _image_result("old")},
        {"role": "tool", "name": "browser", "content": _image_result("browser")},
        {"role": "tool", "name": "computer_use", "content": _image_result("latest")},
    ]

    result = ContextGovernor.drop_stale_visual_tool_images(messages, start_index=1)

    assert result is not messages
    assert result[0]["content"] == messages[0]["content"]
    assert [block["type"] for block in result[1]["content"]] == ["text", "text"]
    assert result[2]["content"] == messages[2]["content"]
    assert result[3]["content"] == messages[3]["content"]
    assert messages[1]["content"][0]["type"] == "image_url"
