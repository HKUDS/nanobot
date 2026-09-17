"""Tests for atomic session save and corrupt-file repair."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from filelock import Timeout

from nanobot.providers.base import ProviderConversationState
from nanobot.session.manager import Session, SessionManager


class TestAtomicSave:
    def test_save_creates_valid_jsonl(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        session = Session(key="test:1")
        session.add_message("user", "hello")
        session.add_message("assistant", "hi")

        mgr.save(session)

        path = mgr._get_session_path("test:1")
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        meta = json.loads(lines[0])
        assert meta["_type"] == "metadata"
        assert meta["key"] == "test:1"

        msg1 = json.loads(lines[1])
        assert msg1["role"] == "user"
        assert msg1["content"] == "hello"

    def test_no_tmp_file_left_after_successful_save(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        session = Session(key="test:clean")
        mgr.save(session)

        tmp_files = list(mgr.sessions_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_unique_tmp_file_cleaned_up_on_write_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        mgr = SessionManager(tmp_path)
        session = Session(key="test:fail")
        path = mgr._get_session_path("test:fail")
        stale_shared_tmp = path.with_suffix(".jsonl.tmp")
        unique_tmp = path.with_name(f".{path.name}.save-failure.tmp")

        path.parent.mkdir(parents=True, exist_ok=True)
        stale_shared_tmp.write_text("stale", encoding="utf-8")
        monkeypatch.setattr(
            "nanobot.session.manager.secrets.token_hex",
            lambda _length: "save-failure",
        )

        class BadMessage:
            def __init__(self, data):
                self.data = data

        original_dumps = json.dumps

        def failing_dumps(obj, **kwargs):
            if isinstance(obj, dict) and obj.get("role") == "assistant":
                raise OSError("simulated disk full")
            return original_dumps(obj, **kwargs)

        session = Session(key="test:fail")
        session.messages = [
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "will fail"},
        ]

        import unittest.mock
        with (
            unittest.mock.patch(
                "nanobot.session.manager.json.dumps",
                side_effect=failing_dumps,
            ),
            pytest.raises(OSError, match="simulated disk full"),
        ):
            mgr.save(session)

        assert not unique_tmp.exists()
        assert stale_shared_tmp.read_text(encoding="utf-8") == "stale"

    def test_overwrite_preserves_latest_data(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        session = Session(key="test:overwrite")

        session.add_message("user", "first")
        mgr.save(session)

        session.add_message("user", "second")
        mgr.save(session)

        mgr.invalidate("test:overwrite")
        loaded = mgr.get_or_create("test:overwrite")
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["content"] == "first"
        assert loaded.messages[1]["content"] == "second"

    def test_consecutive_saves_are_consistent(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        session = Session(key="test:consistency")

        for i in range(5):
            session.add_message("user", f"msg{i}")
            mgr.save(session)

        mgr.invalidate("test:consistency")
        loaded = mgr.get_or_create("test:consistency")
        assert len(loaded.messages) == 5
        for i in range(5):
            assert loaded.messages[i]["content"] == f"msg{i}"

    def test_managers_for_same_directory_coordinate_saves(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        sessions_root = tmp_path / "runtime"
        owner = SessionManager(workspace, sessions_root=sessions_root)
        peer = SessionManager(workspace, sessions_root=sessions_root)
        assert owner.sessions_dir == peer.sessions_dir

        session = Session(key="test:peer-manager")
        peer._jsonl_store._session_files_lock.timeout = 0
        with owner.locked_session_files(), pytest.raises(Timeout):
            peer.save(session)

        peer.save(session)
        assert peer._get_session_path(session.key).is_file()

    def test_provider_state_round_trips_in_private_record_only(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        secret = "encrypted-reasoning-blob"
        session = Session(
            key="test:provider-state",
            provider_state=ProviderConversationState(
                kind="openai_responses",
                provider="openai:https://api.openai.com/v1",
                model="gpt-5.6",
                version=1,
                payload={
                    "items": [
                        {
                            "type": "reasoning",
                            "encrypted_content": secret,
                        }
                    ]
                },
                pending_messages=[{"role": "user", "content": "continue"}],
            ),
        )
        session.add_message("user", "hello")
        mgr.save(session)

        records = [
            json.loads(line)
            for line in mgr._get_session_path(session.key)
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert [record.get("_type") for record in records] == [
            "metadata",
            "provider_state",
            None,
        ]
        assert secret in records[1]["state"]["payload"]["items"][0]["encrypted_content"]

        mgr.invalidate(session.key)
        loaded = mgr.get_or_create(session.key)
        assert loaded.provider_state is not None
        assert loaded.provider_state.to_private_record() == session.provider_state.to_private_record()

        public_payload = mgr.read_session_file(session.key)
        assert public_payload is not None
        assert public_payload["messages"] == [session.messages[0]]
        assert secret not in json.dumps(public_payload)
        assert secret not in json.dumps(mgr.list_sessions())

    def test_provider_state_does_not_consume_list_preview_budget(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        import nanobot.session.manager as session_manager

        monkeypatch.setattr(session_manager, "_SESSION_LIST_PREVIEW_MAX_CHARS", 100)
        mgr = SessionManager(tmp_path)
        session = Session(
            key="test:provider-state-preview",
            provider_state=ProviderConversationState(
                kind="openai_responses",
                provider="openai:test",
                model="test-model",
                version=1,
                payload={"items": [{"encrypted_content": "x" * 200}]},
            ),
        )
        session.add_message("user", "visible preview")
        mgr.save(session)

        assert mgr.list_sessions()[0]["preview"] == "visible preview"

    def test_clear_and_fork_discard_provider_state(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        state = ProviderConversationState(
            kind="openai_responses",
            provider="openai:test",
            model="gpt-5.6",
            version=1,
            payload={"items": []},
        )
        source = Session(key="test:state-source", provider_state=state)
        source.add_message("user", "hello")
        mgr.save(source)

        fork = mgr.fork_session_before_user_index(
            source.key,
            "test:state-fork",
            1,
        )
        assert fork is not None
        assert fork.provider_state is None

        source.clear()
        assert source.provider_state is None

    def test_invalid_provider_state_record_is_not_public_history(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:bad-provider-state")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "_type": "metadata",
                            "key": "test:bad-provider-state",
                            "created_at": datetime.now().isoformat(),
                            "updated_at": datetime.now().isoformat(),
                            "metadata": {},
                            "last_consolidated": 0,
                        }
                    ),
                    json.dumps(
                        {
                            "_type": "provider_state",
                            "state": {"kind": "openai_responses"},
                        }
                    ),
                    json.dumps({"role": "user", "content": "safe"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        loaded = mgr._load("test:bad-provider-state")
        assert loaded is not None
        assert loaded.provider_state is None
        assert loaded.messages == [{"role": "user", "content": "safe"}]


class TestRepairCorruptFile:
    def _write_corrupt_jsonl(self, path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_truncated_last_line_recovered(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:trunc")

        valid_meta = json.dumps({
            "_type": "metadata",
            "key": "test:trunc",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metadata": {},
            "last_consolidated": 0,
        })
        valid_msg = json.dumps({"role": "user", "content": "hello"})

        self._write_corrupt_jsonl(path, [
            valid_meta,
            valid_msg,
            '{"role": "assistant", "content": "partial...',
        ])

        session = mgr._load("test:trunc")
        assert session is not None
        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "hello"

    def test_corrupt_metadata_line_skipped(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:badmeta")

        self._write_corrupt_jsonl(path, [
            "NOT VALID JSON!!!",
            '{"role": "user", "content": "survived"}',
        ])

        session = mgr._load("test:badmeta")
        assert session is not None
        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "survived"

    def test_all_corrupt_lines_returns_none(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:allbad")

        self._write_corrupt_jsonl(path, [
            "garbage line 1",
            "garbage line 2",
            "{{invalid json",
        ])

        session = mgr._load("test:allbad")
        assert session is None

    def test_empty_file_returns_empty_session(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:empty")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

        session = mgr._load("test:empty")
        assert session is not None
        assert session.messages == []
        assert session.key == "test:empty"

    def test_repair_preserves_valid_messages_amid_corruption(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:mixed")

        self._write_corrupt_jsonl(path, [
            json.dumps({"_type": "metadata", "key": "test:mixed",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "metadata": {}, "last_consolidated": 0}),
            "BROKEN",
            json.dumps({"role": "user", "content": "msg1"}),
            '{"role": "assistant", "content": "broken',
            json.dumps({"role": "user", "content": "msg2"}),
        ])

        session = mgr._load("test:mixed")
        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "msg1"
        assert session.messages[1]["content"] == "msg2"

    def test_repair_with_bad_timestamp_uses_fallback(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:badts")

        self._write_corrupt_jsonl(path, [
            json.dumps({"_type": "metadata", "key": "test:badts",
                        "created_at": "not-a-date",
                        "updated_at": "also-bad",
                        "metadata": {}, "last_consolidated": 5}),
            json.dumps({"role": "user", "content": "hi"}),
        ])

        session = mgr._load("test:badts")
        assert session is not None
        # offset 5 exceeds the single loaded message; reset to avoid hiding history (#4066)
        assert session.last_consolidated == 0
        assert isinstance(session.created_at, datetime)

    def test_read_session_file_repairs_corrupt_jsonl(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:read-repair")

        self._write_corrupt_jsonl(path, [
            json.dumps({
                "_type": "metadata",
                "key": "test:read-repair",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "metadata": {"source": "repair"},
                "last_consolidated": 0,
            }),
            json.dumps({"role": "user", "content": "survived"}),
            '{"role": "assistant", "content": "partial...',
        ])

        payload = mgr.read_session_file("test:read-repair")
        assert payload is not None
        assert payload["key"] == "test:read-repair"
        assert payload["metadata"] == {"source": "repair"}
        assert payload["messages"] == [{"role": "user", "content": "survived"}]

    def test_list_sessions_keeps_repaired_corrupt_file(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:list-repair")

        self._write_corrupt_jsonl(path, [
            "NOT VALID JSON",
            json.dumps({
                "_type": "metadata",
                "key": "test:list-repair",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "metadata": {},
                "last_consolidated": 0,
            }),
            json.dumps({"role": "user", "content": "hello"}),
        ])

        sessions = mgr.list_sessions()
        assert any(s["key"] == "test:list-repair" for s in sessions)

    def test_get_or_create_returns_new_session_for_corrupt_file(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        path = mgr._get_session_path("test:fallback")

        self._write_corrupt_jsonl(path, ["{{{{"])

        session = mgr.get_or_create("test:fallback")
        assert session is not None
        assert session.messages == []
        assert session.key == "test:fallback"
