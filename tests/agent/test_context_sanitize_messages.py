from pathlib import Path

from nanobot.agent.context import ContextBuilder


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def _mk_context(tmp_path: Path) -> ContextBuilder:
    workspace = _make_workspace(tmp_path)
    context = ContextBuilder(workspace)
    return context


def test_sanitize_messages_skips_multimodal_user_when_only_runtime_context(tmp_path: Path) -> None:
    context = _mk_context(tmp_path)
    runtime = context._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    messages = context._sanitize_messages(
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
    )
    assert messages == []


def test_sanitize_messages_keeps_image_placeholder_with_path_after_runtime_strip(tmp_path: Path) -> None:
    context = _mk_context(tmp_path)
    runtime = context._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    messages = context._sanitize_messages(
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/feishu/photo.jpg"}},
            ],
        }],
    )
    assert messages[0]["content"] == [{"type": "text", "text": "[image: /media/feishu/photo.jpg]"}]


def test_sanitize_messages_keeps_image_placeholder_without_meta(tmp_path: Path) -> None:
    context = _mk_context(tmp_path)
    runtime = context._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    messages = context._sanitize_messages(
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
    )
    assert messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_sanitize_messages_keeps_tool_results_under_16k(tmp_path: Path) -> None:
    context = _mk_context(tmp_path)
    content = "x" * 12_000

    messages = context._sanitize_messages(
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
    )

    assert messages[0]["content"] == content
