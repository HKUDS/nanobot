"""Tests for nanobot.session.manager — session persistence."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.session.manager import Session, SessionManager


class TestSessionManager:
    def test_get_or_create_new(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        session = mgr.get_or_create("test:1")
        assert session.key == "test:1"
        assert session.messages == []

    def test_get_or_create_cached(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        s1 = mgr.get_or_create("test:1")
        s2 = mgr.get_or_create("test:1")
        assert s1 is s2

    def test_save_and_load(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        session = mgr.get_or_create("test:save")
        session.messages.append({"role": "user", "content": "hello"})
        mgr.save(session)

        # Clear cache and reload
        mgr.invalidate("test:save")
        loaded = mgr.get_or_create("test:save")
        assert len(loaded.messages) == 1
        assert loaded.messages[0]["content"] == "hello"

    def test_invalidate(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        s1 = mgr.get_or_create("test:inv")
        mgr.invalidate("test:inv")
        s2 = mgr.get_or_create("test:inv")
        assert s1 is not s2

    def test_list_sessions(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        for name in ("a:1", "b:2"):
            s = mgr.get_or_create(name)
            s.messages.append({"role": "user", "content": "hi"})
            mgr.save(s)

        listing = mgr.list_sessions()
        assert len(listing) >= 2
        keys = {s["key"] for s in listing}
        assert "a:1" in keys
        assert "b:2" in keys

    def test_load_corrupted_file(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        path = mgr._get_session_path("bad:session")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json\n", encoding="utf-8")

        session = mgr.get_or_create("bad:session")
        assert session.messages == []  # Falls back to new session

    def test_load_with_metadata(self, tmp_path: Path):
        mgr = SessionManager(workspace=tmp_path)
        path = mgr._get_session_path("meta:test")
        path.parent.mkdir(parents=True, exist_ok=True)

        metadata_line = {
            "_type": "metadata",
            "key": "meta:test",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "metadata": {"agent": "coder"},
            "last_consolidated": 5,
        }
        msg = {"role": "user", "content": "loaded"}
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(metadata_line) + "\n")
            f.write(json.dumps(msg) + "\n")

        session = mgr.get_or_create("meta:test")
        assert session.last_consolidated == 5
        assert session.metadata == {"agent": "coder"}
        assert len(session.messages) == 1


class TestSession:
    def test_clear(self):
        s = Session(key="k")
        s.messages = [{"role": "user", "content": "hi"}]
        s.last_consolidated = 3
        s.clear()
        assert s.messages == []
        assert s.last_consolidated == 0

    def test_get_history_default(self):
        s = Session(key="k")
        for i in range(600):
            s.messages.append({"role": "user", "content": f"msg {i}"})
        window = s.get_history()
        assert len(window) <= 500  # default max_messages

    def test_get_history_custom(self):
        s = Session(key="k")
        for i in range(10):
            s.messages.append({"role": "user", "content": f"msg {i}"})
        window = s.get_history(max_messages=3)
        assert len(window) == 3
        assert window[-1]["content"] == "msg 9"

    def test_get_history_remaps_long_tool_call_ids(self):
        """Oversized tool_call IDs are replaced with deterministic hashes."""
        long_id_a = "call_" + "A" * 50  # 55 chars — exceeds 40-char limit
        long_id_b = "call_" + "B" * 50  # different long ID
        s = Session(key="k")
        s.messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": long_id_a,
                        "type": "function",
                        "function": {"name": "t1", "arguments": "{}"},
                    },
                    {
                        "id": long_id_b,
                        "type": "function",
                        "function": {"name": "t2", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": long_id_a, "name": "t1", "content": "ok"},
            {"role": "tool", "tool_call_id": long_id_b, "name": "t2", "content": "ok"},
        ]
        history = s.get_history()

        assistant_msg = history[1]
        tool_a = history[2]
        tool_b = history[3]

        # IDs are now ≤40 chars
        assert len(assistant_msg["tool_calls"][0]["id"]) <= 40
        assert len(assistant_msg["tool_calls"][1]["id"]) <= 40
        assert len(tool_a["tool_call_id"]) <= 40
        assert len(tool_b["tool_call_id"]) <= 40

        # Pairing preserved: assistant call ID matches the tool result ID
        assert assistant_msg["tool_calls"][0]["id"] == tool_a["tool_call_id"]
        assert assistant_msg["tool_calls"][1]["id"] == tool_b["tool_call_id"]

        # Different original IDs map to different short IDs (no collision)
        assert tool_a["tool_call_id"] != tool_b["tool_call_id"]

    def test_get_history_short_ids_unchanged(self):
        """IDs that are already ≤40 chars pass through untouched."""
        short_id = "call_abc123"
        s = Session(key="k")
        s.messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": short_id,
                        "type": "function",
                        "function": {"name": "t", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": short_id, "name": "t", "content": "ok"},
        ]
        history = s.get_history()
        assert history[1]["tool_calls"][0]["id"] == short_id
        assert history[2]["tool_call_id"] == short_id

    def test_get_history_repairs_orphaned_tool_calls(self):
        """Tool_calls without matching tool results should be stripped from history."""
        s = Session(key="k")
        s.messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "tc_ok", "type": "function", "function": {"name": "a"}},
                    {"id": "tc_orphan", "type": "function", "function": {"name": "b"}},
                ],
            },
            {"role": "tool", "tool_call_id": "tc_ok", "name": "a", "content": "result"},
            # tc_orphan has no tool result (crash mid-execution)
            {"role": "user", "content": "retry"},
        ]
        history = s.get_history()
        assistant = [m for m in history if m.get("tool_calls")][0]
        assert len(assistant["tool_calls"]) == 1
        assert assistant["tool_calls"][0]["id"] == "tc_ok"

    def test_get_history_drops_all_tool_calls_when_all_orphaned(self):
        """When all tool_calls are orphaned, the tool_calls key should be removed."""
        s = Session(key="k")
        s.messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "tc_lost", "type": "function", "function": {"name": "x"}},
                ],
            },
            {"role": "user", "content": "try again"},
        ]
        history = s.get_history()
        assistant = [m for m in history if m.get("role") == "assistant"][0]
        assert "tool_calls" not in assistant
