"""Session keys remain distinct even when their display filenames collide."""

from nanobot.session.manager import Session, SessionManager


def test_colliding_display_names_roundtrip_independently(tmp_path):
    manager = SessionManager(tmp_path)
    keys = ("telegram:a_b", "telegram:a:b", "telegram:a/b", "telegram:你好")
    for key in keys:
        session = Session(key=key)
        session.add_message("user", key)
        manager.save(session)
    assert manager.safe_key(keys[0]) == manager.safe_key(keys[1])
    assert len(manager.list_sessions()) == len(keys)
    for key in keys:
        assert manager.read_session_file(key)["messages"][0]["content"] == key
    manager.delete_session(keys[0])
    assert manager.read_session_snapshot(keys[1]) is not None
