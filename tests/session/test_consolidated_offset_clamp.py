"""Reset a corrupt last_consolidated offset instead of hiding history (#4066)."""

import json
from pathlib import Path

from nanobot.session.manager import Session, SessionManager


def _session(count: int, last_consolidated: object) -> Session:
    msgs = [{"role": "user", "content": f"msg{i}"} for i in range(count)]
    return Session(key="chan:chat", messages=msgs, last_consolidated=last_consolidated)


def test_out_of_range_offset_is_reset():
    assert _session(10, 999).last_consolidated == 0
    assert _session(3, -5).last_consolidated == 0


def test_non_integer_offset_is_reset():
    for offset in ("999", None, 0.5, True):
        assert _session(3, offset).last_consolidated == 0


def test_loaded_corrupt_offset_keeps_messages(tmp_path: Path):
    offsets = {
        "string": "999",
        "null": None,
        "float": 0.5,
        "bool": True,
    }

    for name, offset in offsets.items():
        manager = SessionManager(tmp_path / name)
        path = manager._get_session_path("chan:chat")
        path.parent.mkdir(parents=True, exist_ok=True)
        message = {"role": "user", "content": f"survived {name}"}
        path.write_text(
            "\n".join([
                json.dumps({
                    "_type": "metadata",
                    "key": "chan:chat",
                    "metadata": {},
                    "last_consolidated": offset,
                }),
                json.dumps(message),
            ]) + "\n",
            encoding="utf-8",
        )

        session = manager.get_or_create("chan:chat")

        assert session.messages == [message]
        assert session.last_consolidated == 0
        assert session.get_history(max_messages=10) == [message]


def test_valid_offset_is_preserved():
    session = _session(10, 4)
    assert session.last_consolidated == 4
    assert session.last_archived == 4
    assert len(session.get_history()) == 8


def test_last_archived_field_migrates_with_legacy_alias(tmp_path: Path):
    manager = SessionManager(tmp_path)
    path = manager._get_session_path("chan:chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    path.write_text(
        "\n".join([
            json.dumps({
                "_type": "metadata",
                "key": "chan:chat",
                "metadata": {},
                "last_archived": 1,
            }),
            *(json.dumps(message) for message in messages),
        ]) + "\n",
        encoding="utf-8",
    )

    session = manager.get_or_create("chan:chat")

    assert session.last_archived == 1
    assert session.last_consolidated == 1
    manager.save(session)
    metadata = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert metadata["last_archived"] == 1
    assert metadata["last_consolidated"] == 1


def test_loaded_null_metadata_becomes_empty_dict(tmp_path: Path):
    """Session jsonl metadata:null must load as {} so agent .pop/.get work."""
    manager = SessionManager(tmp_path)
    path = manager._get_session_path("chan:chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "_type": "metadata",
            "key": "chan:chat",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "metadata": None,
            "last_consolidated": 0,
        }) + "\n",
        encoding="utf-8",
    )
    session = manager.get_or_create("chan:chat")
    assert session.metadata == {}
    session.metadata["title"] = "ok"
    assert session.metadata["title"] == "ok"
    session.metadata.pop("title", None)
    assert session.metadata == {}


def test_session_post_init_coerces_null_metadata():
    session = Session(key="chan:chat", metadata=None)  # type: ignore[arg-type]
    assert session.metadata == {}
