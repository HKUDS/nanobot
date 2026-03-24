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


def test_save_turn_skips_system_messages() -> None:
    """System messages (OpenViking memory injection, etc.) must not be persisted."""
    loop = _mk_loop()
    session = Session(key="test:no-system")

    loop._save_turn(
        session,
        [
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "## Your memories about the current conversation.\nviking://user/default/memories/..."},
            {"role": "assistant", "content": "Hi there!"},
        ],
        skip=0,
    )

    roles = [m["role"] for m in session.messages]
    assert "system" not in roles
    assert roles == ["user", "assistant"]
