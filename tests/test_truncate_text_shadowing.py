import inspect
from types import SimpleNamespace


def test_sanitize_persisted_blocks_truncate_text_shadowing_regression() -> None:
    """Regression: avoid bool param shadowing imported truncate_text.

    Buggy behavior (historical):
    - loop.py imports `truncate_text` from helpers
    - `_sanitize_persisted_blocks(..., truncate_text: bool=...)` uses same name
    - when called with `truncate_text=True`, function body executes `truncate_text(text, ...)`
      which resolves to bool and raises `TypeError: 'bool' object is not callable`.

    This test asserts the fixed API exists and truncation works without raising.
    """

    from nanobot.agent.loop import AgentLoop

    sig = inspect.signature(AgentLoop._sanitize_persisted_blocks)
    assert "should_truncate_text" in sig.parameters
    assert "truncate_text" not in sig.parameters

    dummy = SimpleNamespace(max_tool_result_chars=5)
    content = [{"type": "text", "text": "0123456789"}]

    out = AgentLoop._sanitize_persisted_blocks(dummy, content, should_truncate_text=True)
    assert isinstance(out, list)
    assert out and out[0]["type"] == "text"
    assert isinstance(out[0]["text"], str)
    assert out[0]["text"] != content[0]["text"]


def test_sanitize_persisted_blocks_strips_audio_and_video() -> None:
    """Audio and video blocks with base64 payloads must be replaced with placeholders."""
    from nanobot.agent.loop import AgentLoop

    dummy = SimpleNamespace(max_tool_result_chars=1000)
    content = [
        {"type": "text", "text": "analyze this"},
        {
            "type": "input_audio",
            "input_audio": {"data": "aGVsbG8=", "format": "wav"},
            "_meta": {"path": "/tmp/voice.wav"},
        },
        {
            "type": "video_url",
            "video_url": {"url": "data:video/mp4;base64,aGVsbG8="},
            "_meta": {"path": "/tmp/clip.mp4"},
        },
    ]

    out = AgentLoop._sanitize_persisted_blocks(dummy, content)

    assert len(out) == 3
    assert out[0] == content[0]
    assert out[1] == {"type": "text", "text": "[audio: /tmp/voice.wav]"}
    assert out[2] == {"type": "text", "text": "[video: /tmp/clip.mp4]"}


def test_sanitize_persisted_blocks_strips_audio_video_without_meta() -> None:
    """When _meta is absent, fallback placeholders use bare label."""
    from nanobot.agent.loop import AgentLoop

    dummy = SimpleNamespace(max_tool_result_chars=1000)
    content = [
        {"type": "input_audio", "input_audio": {"data": "aGVsbG8=", "format": "wav"}},
        {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,aGVsbG8="}},
    ]

    out = AgentLoop._sanitize_persisted_blocks(dummy, content)

    assert len(out) == 2
    assert out[0] == {"type": "text", "text": "[audio]"}
    assert out[1] == {"type": "text", "text": "[video]"}

