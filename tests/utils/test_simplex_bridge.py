from nanobot.utils.simplex_bridge import (
    default_simplex_state_path,
    extract_simplex_reply_text,
)


def test_default_simplex_state_path_uses_safe_filename() -> None:
    path = default_simplex_state_path("simplex:Emili / Main")
    assert path.name == "simplex-Emili-Main.json"


def test_extract_simplex_reply_text_ignores_progress_and_other_chat_ids() -> None:
    assert extract_simplex_reply_text(
        {"event": "message", "chat_id": "simplex:emili", "text": "hello"},
        chat_id="simplex:emili",
    ) == "hello"
    assert extract_simplex_reply_text(
        {
            "event": "message",
            "chat_id": "simplex:emili",
            "text": "thinking",
            "kind": "progress",
        },
        chat_id="simplex:emili",
    ) is None
    assert extract_simplex_reply_text(
        {"event": "message", "chat_id": "simplex:other", "text": "hello"},
        chat_id="simplex:emili",
    ) is None
