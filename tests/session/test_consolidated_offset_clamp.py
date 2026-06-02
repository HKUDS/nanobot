"""Reset a corrupt last_consolidated offset instead of hiding history (#4066)."""

from nanobot.session.manager import Session


def _session(count: int, last_consolidated: int) -> Session:
    msgs = [{"role": "user", "content": f"msg{i}"} for i in range(count)]
    return Session(key="chan:chat", messages=msgs, last_consolidated=last_consolidated)


def test_out_of_range_offset_is_reset():
    assert _session(10, 999).last_consolidated == 0
    assert _session(3, -5).last_consolidated == 0


def test_valid_offset_is_preserved():
    session = _session(10, 4)
    assert session.last_consolidated == 4
    assert len(session.get_history()) == 6
