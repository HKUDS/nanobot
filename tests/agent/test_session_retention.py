from nanobot.session.manager import Session


def _assert_no_orphans(history: list[dict]) -> None:
    declared = {
        tc["id"]
        for m in history
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
    }
    orphans = [
        m.get("tool_call_id")
        for m in history
        if m.get("role") == "tool" and m.get("tool_call_id") not in declared
    ]
    assert orphans == [], f"orphan tool_call_ids: {orphans}"


def _delivery(content: str) -> dict:
    return {"role": "assistant", "content": content, "_channel_delivery": True}


def _tool_turn(prefix: str, idx: int) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"{prefix}_{idx}_a",
                    "type": "function",
                    "function": {"name": "x", "arguments": "{}"},
                },
                {
                    "id": f"{prefix}_{idx}_b",
                    "type": "function",
                    "function": {"name": "y", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": f"{prefix}_{idx}_a", "name": "x", "content": "ok"},
        {"role": "tool", "tool_call_id": f"{prefix}_{idx}_b", "name": "y", "content": "ok"},
    ]


def _contents(messages: list[dict]) -> list[str]:
    return [m.get("content") for m in messages]


def _has_delivery(messages: list[dict]) -> bool:
    return any(m.get("_channel_delivery") for m in messages)


# --- Hard-cap trimming must preserve a proactive delivery the user replied to ---


def test_retain_hard_cap_keeps_delivery_before_user():
    session = Session(key="test:cap-delivery")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append(_delivery("Remember to drink water"))
    session.messages.append({"role": "user", "content": "ok"})
    session.messages.append({"role": "assistant", "content": "great"})

    session.retain_recent_legal_suffix(3)

    assert _has_delivery(session.messages), "delivery dropped by hard-cap trim"
    assert _contents(session.messages) == [
        "Remember to drink water",
        "ok",
        "great",
    ]


def test_retain_hard_cap_matches_get_history_boundary():
    """The trimmed suffix must start on the same message as get_history()."""
    session = Session(key="test:cap-boundary")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append(_delivery("You have 3 pending tasks"))
    session.messages.append({"role": "user", "content": "show them"})
    session.messages.append({"role": "assistant", "content": "done"})

    expected = session.get_history(max_messages=3)

    session.retain_recent_legal_suffix(3)

    assert _contents(session.messages) == _contents(expected)


def test_retain_extend_to_user_keeps_delivery_before_recovered_user():
    session = Session(key="test:extend-delivery")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append({"role": "assistant", "content": "work"})
    session.messages.append(_delivery("Reminder: deploy at 17:00"))
    session.messages.append({"role": "user", "content": "ok"})
    session.messages.append({"role": "assistant", "content": "a1"})
    session.messages.append({"role": "assistant", "content": "a2"})
    session.messages.append({"role": "assistant", "content": "a3"})

    session.retain_recent_legal_suffix(3, extend_to_user=True)

    assert _has_delivery(session.messages), "delivery dropped by extend_to_user trim"
    assert session.messages[0]["content"] == "Reminder: deploy at 17:00"
    assert session.messages[-1]["content"] == "a3"


def test_retain_extend_to_user_matches_get_history_boundary():
    session = Session(key="test:extend-boundary")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append({"role": "assistant", "content": "work"})
    session.messages.append(_delivery("Reminder: review the draft"))
    session.messages.append({"role": "user", "content": "ok"})
    session.messages.append({"role": "assistant", "content": "a1"})
    session.messages.append({"role": "assistant", "content": "a2"})
    session.messages.append({"role": "assistant", "content": "a3"})

    expected = session.get_history(max_messages=3, extend_to_user=True)

    session.retain_recent_legal_suffix(3, extend_to_user=True)

    assert _contents(session.messages) == _contents(expected)


def test_retain_extend_to_user_does_not_extend_delivery_only_tail():
    session = Session(key="test:extend-no-user")
    for i in range(4):
        session.messages.append(_delivery(f"notification {i}"))

    session.retain_recent_legal_suffix(3, extend_to_user=True)

    assert _contents(session.messages) == [
        "notification 1",
        "notification 2",
        "notification 3",
    ]


# --- Only the immediately-preceding delivery is part of the anchor ---


def test_retain_keeps_only_immediate_delivery():
    session = Session(key="test:multi-delivery")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append(_delivery("old scheduled note"))
    session.messages.append(_delivery("new scheduled note"))
    session.messages.append({"role": "user", "content": "ok"})
    session.messages.append({"role": "assistant", "content": "great"})

    session.retain_recent_legal_suffix(3)

    kept = _contents(session.messages)
    assert kept == ["new scheduled note", "ok", "great"], kept


def test_retain_drops_delivery_not_adjacent_to_anchor_user():
    """A delivery that does not immediately precede the retained user turn is
    not part of the anchor and should not be force-retained."""
    session = Session(key="test:nonadjacent")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append(_delivery("unrelated scheduled note"))
    session.messages.append({"role": "assistant", "content": "reply"})
    session.messages.append({"role": "user", "content": "ok"})
    session.messages.append({"role": "assistant", "content": "great"})

    session.retain_recent_legal_suffix(2)

    assert not _has_delivery(session.messages)
    assert _contents(session.messages) == ["ok", "great"]


def test_compact_probe_keeps_delivery_in_visible_suffix():
    """compact_idle_session() trims a probe copy with extend_to_user=True; the
    visible suffix it keeps must still contain the delivery message."""
    tail = [
        {"role": "user", "content": "setup"},
        {"role": "assistant", "content": "work"},
        _delivery("Reminder: deploy at 17:00"),
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": "a2"},
        {"role": "assistant", "content": "a3"},
    ]
    probe = Session(key="test:probe", messages=tail)

    probe.retain_recent_legal_suffix(3, extend_to_user=True)

    assert _has_delivery(probe.messages)
    assert probe.messages[0]["content"] == "Reminder: deploy at 17:00"


# --- Trimming must stay coherent with the rest of replay ---


def test_retain_then_replay_keeps_delivery_and_no_orphans():
    session = Session(key="test:replay-after-trim")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append(_delivery("You have 3 pending tasks"))
    session.messages.append({"role": "user", "content": "show them"})
    session.messages.extend(_tool_turn("cur", 0))
    session.messages.append({"role": "assistant", "content": "done"})

    session.retain_recent_legal_suffix(6)

    assert _has_delivery(session.messages)
    history = session.get_history(max_messages=500)
    _assert_no_orphans(history)
    assert any(m.get("content") == "You have 3 pending tasks" for m in history)


def test_retain_keeps_delivery_when_user_inside_window():
    """When the capped window already contains a user, its immediately
    preceding delivery must stay attached to it."""
    session = Session(key="test:window-user")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append({"role": "assistant", "content": "a0"})
    session.messages.append(_delivery("Reminder"))
    session.messages.append({"role": "user", "content": "ok"})
    session.messages.append({"role": "assistant", "content": "a1"})
    session.messages.append({"role": "assistant", "content": "a2"})

    expected = session.get_history(max_messages=4)

    session.retain_recent_legal_suffix(4)

    assert _has_delivery(session.messages)
    assert _contents(session.messages) == _contents(expected)
