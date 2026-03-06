from __future__ import annotations

import sqlite3
from pathlib import Path

from nanobot.agent.memory import _Mem0Adapter


class _FakeClient:
    def __init__(self, *, search_rows, all_rows):
        self._search_rows = search_rows
        self._all_rows = all_rows
        self.add_calls = []

    def search(self, *args, **kwargs):
        return {"results": self._search_rows}

    def get_all(self, *args, **kwargs):
        return {"results": self._all_rows}

    def add(self, *args, **kwargs):
        self.add_calls.append({"args": args, "kwargs": kwargs})
        # Simulate indexed row appearing after add.
        self._all_rows.append(
            {
                "id": "added-1",
                "memory": "API authentication method is OAuth2",
                "metadata": {"memory_type": "semantic", "topic": "knowledge", "source": "events"},
            }
        )
        return {"results": []}


def _adapter_with_client(client: _FakeClient) -> _Mem0Adapter:
    adapter = object.__new__(_Mem0Adapter)
    adapter.enabled = True
    adapter.client = client
    adapter.user_id = "nanobot"
    adapter.mode = "oss"
    adapter.error = None
    adapter._local_mem0_dir = None
    adapter.last_add_mode = "unknown"
    adapter._infer_true_disabled = False
    adapter._infer_true_disable_reason = ""
    return adapter


def test_search_falls_back_to_get_all_when_vector_search_empty():
    adapter = _adapter_with_client(
        _FakeClient(
            search_rows=[],
            all_rows=[
                {
                    "id": "m1",
                    "memory": "OAuth2 authentication is required for API access",
                    "metadata": {"memory_type": "semantic", "topic": "auth"},
                },
                {
                    "id": "m2",
                    "memory": "Deployment region is us-east-1",
                    "metadata": {"memory_type": "semantic", "topic": "infra"},
                },
            ],
        )
    )

    rows = adapter.search("oauth2 authentication", top_k=3)

    assert len(rows) == 1
    assert rows[0]["id"] == "m1"
    assert rows[0]["memory_type"] == "semantic"
    assert rows[0]["topic"] == "auth"


def test_search_fallback_returns_empty_when_no_lexical_overlap():
    adapter = _adapter_with_client(
        _FakeClient(
            search_rows=[],
            all_rows=[
                {
                    "id": "m1",
                    "memory": "Deployment region is us-east-1",
                    "metadata": {"memory_type": "semantic", "topic": "infra"},
                }
            ],
        )
    )

    rows = adapter.search("oauth2 authentication", top_k=3)

    assert rows == []


def test_search_falls_back_to_history_db_when_vector_and_get_all_empty(tmp_path: Path):
    mem0_dir = tmp_path / "mem0"
    mem0_dir.mkdir(parents=True, exist_ok=True)
    db_path = mem0_dir / "history.db"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE history (
            id TEXT PRIMARY KEY,
            memory_id TEXT,
            old_memory TEXT,
            new_memory TEXT,
            event TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_deleted INTEGER,
            actor_id TEXT,
            role TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO history (id, memory_id, new_memory, event, created_at, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "h1",
            "m-history-1",
            "API authentication method is OAuth2",
            "ADD",
            "2026-03-02T10:00:00+00:00",
            0,
        ),
    )
    conn.commit()
    conn.close()

    adapter = _adapter_with_client(_FakeClient(search_rows=[], all_rows=[]))
    adapter._local_mem0_dir = mem0_dir

    rows = adapter.search("oauth2 authentication", top_k=3, allow_history_fallback=True)

    assert len(rows) == 1
    assert rows[0]["id"] == "m-history-1"
    assert rows[0]["source"] == "history_db"


def test_get_all_fallback_respects_allowed_sources_and_blob_filter():
    adapter = _adapter_with_client(
        _FakeClient(
            search_rows=[],
            all_rows=[
                {
                    "id": "a",
                    "memory": "Constraint: commands must not mutate production.",
                    "metadata": {
                        "memory_type": "semantic",
                        "topic": "constraint",
                        "source": "profile",
                    },
                },
                {
                    "id": "b",
                    "memory": "/home/carlos/.nanobot/workspace/sessions/cli.jsonl:42:{...}",
                    "metadata": {
                        "memory_type": "semantic",
                        "topic": "history",
                        "source": "profile",
                    },
                },
                {
                    "id": "c",
                    "memory": "deploy failed due port conflict",
                    "metadata": {"memory_type": "episodic", "topic": "infra", "source": "chat"},
                },
            ],
        )
    )

    rows, stats = adapter.search(
        "constraint commands",
        top_k=5,
        return_stats=True,
        allowed_sources={"profile"},
        reject_blob_like=True,
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "a"
    assert stats["source_get_all"] == 1
    assert stats["rejected_blob_like"] >= 1


def test_add_text_prefers_infer_false_mode_for_oss():
    client = _FakeClient(search_rows=[], all_rows=[])
    adapter = _adapter_with_client(client)

    ok = adapter.add_text("API authentication method is OAuth2", metadata={"topic": "knowledge"})

    assert ok is True
    assert client.add_calls
    assert client.add_calls[0]["kwargs"].get("infer") is False
    assert adapter.last_add_mode == "infer_false_primary"
