import sqlite3
from pathlib import Path

from nanobot.utils.simplex_bridge import (
    default_simplex_state_path,
    extract_simplex_reply_text,
    fetch_received_text_messages,
    get_latest_received_item_id,
    load_last_seen_id,
    parse_receiver_line,
    save_last_seen_id,
)


def _seed_simplex_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE contacts (
            contact_id INTEGER PRIMARY KEY,
            local_display_name TEXT NOT NULL
        );
        CREATE TABLE chat_items (
            chat_item_id INTEGER PRIMARY KEY,
            contact_id INTEGER,
            item_sent INTEGER NOT NULL,
            item_deleted INTEGER NOT NULL DEFAULT 0,
            msg_content_tag TEXT,
            item_text TEXT NOT NULL,
            item_ts TEXT NOT NULL
        );
        INSERT INTO contacts (contact_id, local_display_name) VALUES
            (1, 'Emili'),
            (2, 'Other');
        INSERT INTO chat_items (
            chat_item_id, contact_id, item_sent, item_deleted, msg_content_tag, item_text, item_ts
        ) VALUES
            (10, 1, 0, 0, 'text', 'hola', '2026-04-23 10:00:00'),
            (11, 1, 1, 0, 'text', 'reply', '2026-04-23 10:00:01'),
            (12, 1, 0, 0, NULL, 'feature row', '2026-04-23 10:00:02'),
            (13, 2, 0, 0, 'text', 'ignore other contact', '2026-04-23 10:00:03'),
            (14, 1, 0, 1, 'text', 'deleted row', '2026-04-23 10:00:04'),
            (15, 1, 0, 0, 'text', 'adeu', '2026-04-23 10:00:05');
        """
    )
    conn.commit()
    conn.close()


def test_fetch_received_text_messages_filters_to_contact_and_inbound(tmp_path: Path) -> None:
    db_path = tmp_path / "simplex_v1_chat.db"
    _seed_simplex_db(db_path)

    messages = fetch_received_text_messages(db_path, "Emili", after_id=10)

    assert [msg.chat_item_id for msg in messages] == [15]
    assert messages[0].text == "adeu"


def test_get_latest_received_item_id_ignores_sent_deleted_and_non_text(tmp_path: Path) -> None:
    db_path = tmp_path / "simplex_v1_chat.db"
    _seed_simplex_db(db_path)

    assert get_latest_received_item_id(db_path, "Emili") == 15
    assert get_latest_received_item_id(db_path, "Missing") == 0


def test_last_seen_state_round_trip(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"

    assert load_last_seen_id(state_file) is None
    save_last_seen_id(state_file, 42)

    assert load_last_seen_id(state_file) == 42


def test_default_simplex_state_path_uses_safe_filename() -> None:
    path = default_simplex_state_path("simplex:Emili / Main")
    assert path.name == "simplex-Emili-Main.json"


def test_parse_receiver_line_matches_jsonl_shape() -> None:
    msg = parse_receiver_line(
        '{"id":15,"contact":"Emili","text":"hola","timestamp":"2026-04-23 10:00:05"}'
    )
    assert msg.chat_item_id == 15
    assert msg.contact_name == "Emili"
    assert msg.text == "hola"


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
