import pytest

from nanobot.agent.tools.file_state import FileStateStore


def test_file_state_store_evicts_least_recently_used_session() -> None:
    store = FileStateStore(max_sessions=2)
    first = store.for_session("first")
    second = store.for_session("second")

    assert store.for_session("first") is first
    store.for_session("third")

    assert store.for_session("first") is first
    assert store.for_session("second") is not second


def test_file_state_store_discards_reset_session() -> None:
    store = FileStateStore()
    previous = store.for_session("websocket:chat")

    store.discard("websocket:chat")

    assert store.for_session("websocket:chat") is not previous


def test_file_state_store_requires_positive_capacity() -> None:
    with pytest.raises(ValueError, match="max_sessions must be positive"):
        FileStateStore(max_sessions=0)
