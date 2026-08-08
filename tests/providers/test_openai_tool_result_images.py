from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def test_chat_completions_moves_tool_images_after_parallel_results():
    image = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
        "_meta": {"path": "screen.png"},
    }
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {
            "role": "tool",
            "tool_call_id": "a",
            "content": [image, {"type": "text", "text": "clicked"}],
        },
        {"role": "tool", "tool_call_id": "b", "content": "other result"},
        {"role": "assistant", "content": "done"},
    ]

    result = OpenAICompatProvider._move_tool_images_to_user(messages)

    assert result[1]["content"] == "clicked"
    assert result[2] == messages[2]
    assert result[3]["role"] == "user"
    assert result[3]["content"][0] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
    }
    assert result[4] == messages[3]


def test_chat_completions_merges_tool_images_into_following_user_message():
    messages = [
        {
            "role": "tool",
            "tool_call_id": "a",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
        {"role": "user", "content": "continue"},
    ]

    result = OpenAICompatProvider._move_tool_images_to_user(messages)

    assert len(result) == 2
    assert result[0]["content"] == "(image returned)"
    assert result[1]["role"] == "user"
    assert result[1]["content"][-1] == {"type": "text", "text": "continue"}
