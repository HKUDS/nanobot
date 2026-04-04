from janniebot.session.manager import Session


def _assert_no_orphans(history: list[dict]) -> None:
    """Assert every tool result in history has a matching assistant tool_call."""
    declared = {
        tc["id"]
        for m in history if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
    }
    orphans = [
        m.get("tool_call_id") for m in history
        if m.get("role") == "tool" and m.get("tool_call_id") not in declared
    ]
    assert orphans == [], f"orphan tool_call_ids: {orphans}"


def _tool_turn(prefix: str, idx: int) -> list[dict]:
    """Helper: one assistant with 2 tool_calls + 2 tool results."""
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": f"{prefix}_{idx}_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": f"{prefix}_{idx}_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": f"{prefix}_{idx}_a", "name": "x", "content": "ok"},
        {"role": "tool", "tool_call_id": f"{prefix}_{idx}_b", "name": "y", "content": "ok"},
    ]


# --- Original regression test (from PR 2075) ---

def test_get_history_drops_orphan_tool_results_when_window_cuts_tool_calls():
    session = Session(key="telegram:test")
    session.messages.append({"role": "user", "content": "old turn"})
    for i in range(20):
        session.messages.extend(_tool_turn("old", i))
    session.messages.append({"role": "user", "content": "problem turn"})
    for i in range(25):
        session.messages.extend(_tool_turn("cur", i))
    session.messages.append({"role": "user", "content": "new telegram question"})

    history = session.get_history(max_messages=100)
    _assert_no_orphans(history)


# --- Positive test: legitimate pairs survive trimming ---

def test_legitimate_tool_pairs_preserved_after_trim():
    """Complete tool-call groups within the window must not be dropped."""
    session = Session(key="test:positive")
    session.messages.append({"role": "user", "content": "hello"})
    for i in range(5):
        session.messages.extend(_tool_turn("ok", i))
    session.messages.append({"role": "assistant", "content": "done"})

    history = session.get_history(max_messages=500)
    _assert_no_orphans(history)
    tool_ids = [m["tool_call_id"] for m in history if m.get("role") == "tool"]
    assert len(tool_ids) == 10
    assert history[0]["role"] == "user"


def test_retain_recent_legal_suffix_keeps_recent_messages():
    session = Session(key="test:trim")
    for i in range(10):
        session.messages.append({"role": "user", "content": f"msg{i}"})

    session.retain_recent_legal_suffix(4)

    assert len(session.messages) == 4
    assert session.messages[0]["content"] == "msg6"
    assert session.messages[-1]["content"] == "msg9"


def test_retain_recent_legal_suffix_adjusts_last_consolidated():
    session = Session(key="test:trim-cons")
    for i in range(10):
        session.messages.append({"role": "user", "content": f"msg{i}"})
    session.last_consolidated = 7

    session.retain_recent_legal_suffix(4)

    assert len(session.messages) == 4
    assert session.last_consolidated == 1


def test_retain_recent_legal_suffix_zero_clears_session():
    session = Session(key="test:trim-zero")
    for i in range(10):
        session.messages.append({"role": "user", "content": f"msg{i}"})
    session.last_consolidated = 5

    session.retain_recent_legal_suffix(0)

    assert session.messages == []
    assert session.last_consolidated == 0


def test_retain_recent_legal_suffix_keeps_legal_tool_boundary():
    session = Session(key="test:trim-tools")
    session.messages.append({"role": "user", "content": "old"})
    session.messages.extend(_tool_turn("old", 0))
    session.messages.append({"role": "user", "content": "keep"})
    session.messages.extend(_tool_turn("keep", 0))
    session.messages.append({"role": "assistant", "content": "done"})

    session.retain_recent_legal_suffix(4)

    history = session.get_history(max_messages=500)
    _assert_no_orphans(history)
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "keep"


# --- last_consolidated > 0 ---

def test_orphan_trim_with_last_consolidated():
    """Orphan trimming works correctly when session is partially consolidated."""
    session = Session(key="test:consolidated")
    for i in range(10):
        session.messages.append({"role": "user", "content": f"old {i}"})
        session.messages.extend(_tool_turn("cons", i))
    session.last_consolidated = 30

    session.messages.append({"role": "user", "content": "recent"})
    for i in range(15):
        session.messages.extend(_tool_turn("new", i))
    session.messages.append({"role": "user", "content": "latest"})

    history = session.get_history(max_messages=20)
    _assert_no_orphans(history)
    assert all(m.get("role") != "tool" or m["tool_call_id"].startswith("new_") for m in history)


# --- Edge: no tool messages at all ---

def test_no_tool_messages_unchanged():
    session = Session(key="test:plain")
    for i in range(5):
        session.messages.append({"role": "user", "content": f"q{i}"})
        session.messages.append({"role": "assistant", "content": f"a{i}"})

    history = session.get_history(max_messages=6)
    assert len(history) == 6
    _assert_no_orphans(history)


# --- Edge: all leading messages are orphan tool results ---

def test_all_orphan_prefix_stripped():
    """If the window starts with orphan tool results and nothing else, they're all dropped."""
    session = Session(key="test:all-orphan")
    session.messages.append({"role": "tool", "tool_call_id": "gone_1", "name": "x", "content": "ok"})
    session.messages.append({"role": "tool", "tool_call_id": "gone_2", "name": "y", "content": "ok"})
    session.messages.append({"role": "user", "content": "fresh start"})
    session.messages.append({"role": "assistant", "content": "hi"})

    history = session.get_history(max_messages=500)
    _assert_no_orphans(history)
    assert history[0]["role"] == "user"
    assert len(history) == 2


# --- Edge: empty session ---

def test_empty_session_history():
    session = Session(key="test:empty")
    history = session.get_history(max_messages=500)
    assert history == []


def test_get_history_preserves_reasoning_content():
    session = Session(key="test:reasoning")
    session.messages.append({"role": "user", "content": "hi"})
    session.messages.append({
        "role": "assistant",
        "content": "done",
        "reasoning_content": "hidden chain of thought",
    })

    history = session.get_history(max_messages=500)

    assert history == [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "done",
            "reasoning_content": "hidden chain of thought",
        },
    ]


# --- Window cuts mid-group: assistant present but some tool results orphaned ---

def test_window_cuts_mid_tool_group():
    """If the window starts between an assistant's tool results, the partial group is trimmed."""
    session = Session(key="test:mid-cut")
    session.messages.append({"role": "user", "content": "setup"})
    session.messages.append({
        "role": "assistant", "content": None,
        "tool_calls": [
            {"id": "split_a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
            {"id": "split_b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
        ],
    })
    session.messages.append({"role": "tool", "tool_call_id": "split_a", "name": "x", "content": "ok"})
    session.messages.append({"role": "tool", "tool_call_id": "split_b", "name": "y", "content": "ok"})
    session.messages.append({"role": "user", "content": "next"})
    session.messages.extend(_tool_turn("intact", 0))
    session.messages.append({"role": "assistant", "content": "final"})

    # Window of 6 should cut off the "setup" user msg and the assistant with split_a/split_b,
    # leaving orphan tool results for split_a at the front.
    history = session.get_history(max_messages=6)
    _assert_no_orphans(history)
