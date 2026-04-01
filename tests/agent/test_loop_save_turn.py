from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.session.manager import Session


def _mk_loop() -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop._TOOL_RESULT_MAX_CHARS = AgentLoop._TOOL_RESULT_MAX_CHARS
    return loop


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop()
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_with_path_after_runtime_strip() -> None:
    loop = _mk_loop()
    session = Session(key="test:image")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/feishu/photo.jpg"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image: /media/feishu/photo.jpg]"}]


def test_save_turn_keeps_image_placeholder_without_meta() -> None:
    loop = _mk_loop()
    session = Session(key="test:image-no-meta")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_keeps_tool_results_under_16k() -> None:
    loop = _mk_loop()
    session = Session(key="test:tool-result")
    content = "x" * 12_000

    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    assert session.messages[0]["content"] == content


def test_save_turn_appends_assistant_placeholder_when_last_is_tool() -> None:
    """When the final assistant message (no content, no tool_calls) is skipped,
    _save_turn must append a placeholder so the session doesn't end on a tool role,
    which would break provider message ordering requirements on the next turn."""
    loop = _mk_loop()
    session = Session(key="test:tool-last")

    loop._save_turn(
        session,
        [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "message", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "name": "message", "content": "Message sent to telegram:123"},
            {"role": "assistant", "content": None},  # empty final assistant — will be skipped
        ],
        skip=0,
    )

    # assistant(tool_calls) -> tool -> assistant(placeholder)
    assert len(session.messages) == 3
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[0].get("tool_calls") is not None
    assert session.messages[1]["role"] == "tool"
    assert session.messages[2]["role"] == "assistant"
    assert session.messages[2]["content"] == "[response sent via tool]"


def test_save_turn_no_placeholder_when_assistant_has_content() -> None:
    """No placeholder needed when the final assistant has text content."""
    loop = _mk_loop()
    session = Session(key="test:normal")

    loop._save_turn(
        session,
        [
            {"role": "assistant", "content": "Hello!"},
        ],
        skip=0,
    )

    assert len(session.messages) == 1
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[0]["content"] == "Hello!"


def test_save_turn_no_placeholder_when_last_is_user() -> None:
    """No placeholder needed when the last message is a user message."""
    loop = _mk_loop()
    session = Session(key="test:user-last")

    loop._save_turn(
        session,
        [
            {"role": "user", "content": "Hi there"},
        ],
        skip=0,
    )

    assert len(session.messages) == 1
    assert session.messages[0]["role"] == "user"
