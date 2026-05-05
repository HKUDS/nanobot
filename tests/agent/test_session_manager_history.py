from nanobot.session.manager import Session


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
        "thinking_blocks": [{"type": "thinking", "thinking": "hidden chain of thought", "signature": "sig"}],
    })

    history = session.get_history(max_messages=500)

    assert history == [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "done",
            "reasoning_content": "hidden chain of thought",
            "thinking_blocks": [{
                "type": "thinking",
                "thinking": "hidden chain of thought",
                "signature": "sig",
            }],
        },
    ]


def test_get_history_annotates_user_turns_but_not_assistant_turns():
    """Only user turns carry the timestamp prefix.

    Annotating assistant turns trains the model (via in-context examples) to
    start its own replies with ``[Message Time: ...]``. User-side stamps are
    enough to pin adjacent assistant replies for relative-time reasoning.
    """
    session = Session(key="test:timestamps")
    session.messages.append({
        "role": "user",
        "content": "10 点提醒是昨天发生的",
        "timestamp": "2026-04-26T22:00:00",
    })
    session.messages.append({
        "role": "assistant",
        "content": "记下来了",
        "timestamp": "2026-04-26T22:00:05",
    })

    history = session.get_history(max_messages=500, include_timestamps=True)

    assert history == [
        {
            "role": "user",
            "content": "[Message Time: 2026-04-26T22:00:00]\n10 点提醒是昨天发生的",
        },
        {
            "role": "assistant",
            "content": "记下来了",
        },
    ]


def test_get_history_annotates_proactive_assistant_deliveries_with_timestamps():
    """Cron / heartbeat assistant pushes still carry a timestamp prefix.

    These proactive deliveries can sit hours away from the next user reply,
    so the model needs to know when they fired. They are rare enough that
    they don't act as in-context demonstrations encouraging the model to
    prefix its own normal replies with ``[Message Time: ...]``.
    """
    session = Session(key="test:proactive-timestamps")
    session.messages.append({
        "role": "assistant",
        "content": "记得喝水",
        "timestamp": "2026-04-26T15:00:00",
        "_channel_delivery": True,
    })
    session.messages.append({
        "role": "user",
        "content": "好",
        "timestamp": "2026-04-26T18:00:00",
    })

    history = session.get_history(max_messages=500, include_timestamps=True)

    assert history == [
        {
            "role": "assistant",
            "content": "[Message Time: 2026-04-26T15:00:00]\n记得喝水",
        },
        {
            "role": "user",
            "content": "[Message Time: 2026-04-26T18:00:00]\n好",
        },
    ]


def test_get_history_does_not_annotate_tool_results_with_timestamps():
    session = Session(key="test:tool-timestamps")
    session.messages.append({"role": "user", "content": "run tool"})
    session.messages.extend(_tool_turn("ts", 0))
    session.messages[-1]["timestamp"] = "2026-04-26T22:00:10"

    history = session.get_history(max_messages=500, include_timestamps=True)

    tool_result = history[-1]
    assert tool_result["role"] == "tool"
    assert tool_result["content"] == "ok"


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


# --- Image breadcrumbs: media kwarg is synthesized into content for replay ---


def test_get_history_synthesizes_image_breadcrumb_from_media_kwarg():
    """Persisted user turns carry image paths as a ``media`` kwarg; LLM
    replay must still see an ``[image: path]`` breadcrumb so the assistant's
    follow-up reply has a referent instead of trailing an empty user row."""
    session = Session(key="test:media")
    session.messages.append(
        {"role": "user", "content": "look", "media": ["/m/a.png", "/m/b.png"]}
    )
    session.messages.append({"role": "assistant", "content": "nice"})

    history = session.get_history(max_messages=500)

    assert history == [
        {"role": "user", "content": "look\n[image: /m/a.png]\n[image: /m/b.png]"},
        {"role": "assistant", "content": "nice"},
    ]


def test_get_history_synthesizes_breadcrumb_for_image_only_turn():
    """Turns with no text but attached images must not replay as empty
    strings — the LLM would otherwise see a bare user turn followed by an
    unexplained assistant answer."""
    session = Session(key="test:image-only")
    session.messages.append({"role": "user", "content": "", "media": ["/m/pic.png"]})
    session.messages.append({"role": "assistant", "content": "I see a cat"})

    history = session.get_history(max_messages=500)

    assert history[0] == {"role": "user", "content": "[image: /m/pic.png]"}


def test_get_history_ignores_media_kwarg_on_non_user_rows():
    """``media`` only ever appears on user entries in practice, but the
    synthesizer must be defensive: assistants / tools with list content
    don't get the breadcrumb pasted on top."""
    session = Session(key="test:defensive")
    session.messages.append(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "structured"}],
            "media": ["/m/x.png"],  # nonsense but shouldn't crash
        }
    )
    history = session.get_history(max_messages=500)
    # List content is passed through verbatim — the synthesizer only
    # rewrites plain-string content.
    assert history[0]["content"] == [{"type": "text", "text": "structured"}]


def test_get_history_respects_max_tokens(monkeypatch):
    session = Session(key="test:token-cap")
    session.messages.extend(
        [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a3"},
        ]
    )

    token_map = {"u1": 50, "a1": 50, "u2": 50, "a2": 50, "u3": 50, "a3": 50}
    monkeypatch.setattr(
        "nanobot.session.manager.estimate_message_tokens",
        lambda message: token_map.get(message.get("content"), 0),
    )

    history = session.get_history(max_messages=500, max_tokens=120)
    assert [m["content"] for m in history] == ["u3", "a3"]


def test_get_history_recovers_user_when_token_slice_would_be_assistant_only(monkeypatch):
    session = Session(key="test:assistant-only-slice")
    session.messages.extend(
        [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
    )
    token_map = {"u1": 100, "a1": 100, "u2": 100, "a2": 100}
    monkeypatch.setattr(
        "nanobot.session.manager.estimate_message_tokens",
        lambda message: token_map.get(message.get("content"), 0),
    )

    history = session.get_history(max_messages=500, max_tokens=100)
    assert [m["content"] for m in history] == ["u2", "a2"]


def test_retain_recent_legal_suffix_hard_cap_with_long_non_user_chain():
    session = Session(key="test:hard-cap-chain")
    session.messages.append({"role": "user", "content": "u0"})
    session.messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        }
    )
    for i in range(12):
        session.messages.append({"role": "assistant", "content": f"a{i}"})

    session.retain_recent_legal_suffix(6)

    assert len(session.messages) <= 6
