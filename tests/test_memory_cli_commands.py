from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


class _FakeProfileMgr:
    def read_profile(self) -> dict[str, object]:
        return {"preferences": ["a"], "stable_facts": ["b"]}

    def write_profile(self, profile: dict[str, object]) -> None:
        pass

    def set_item_pin(self, field: str, text: str, pinned: bool) -> bool:
        if field == "bad":
            raise ValueError("bad field")
        return self._parent.pin_ok

    def mark_item_outdated(self, field: str, text: str) -> bool:
        if field == "bad":
            raise ValueError("bad field")
        return self._parent.outdated_ok


class _FakeConflictMgr:
    def list_conflicts(self, include_closed: bool = False) -> list[dict[str, object]]:
        return list(self._parent.conflict_rows)

    def resolve_conflict_details(self, index: int, action: str) -> dict[str, object]:
        if not self._parent.resolve_ok:
            return {"ok": False}
        return {
            "ok": True,
            "db_operation": "none",
            "db_ok": True,
            "old_memory_id": "",
            "new_memory_id": "",
        }


class _FakeIngester:
    def read_events(self, **kw: object) -> list[dict[str, object]]:
        return [{"id": "e1"}, {"id": "e2"}]

    def append_events(self, events: list[dict[str, object]]) -> int:
        return len(events)


class _FakeRetriever:
    def retrieve(self, query: str, top_k: int = 6, **kw: object) -> list[dict[str, object]]:
        if query == "none":
            return []
        return [{"timestamp": "2026-03-10", "type": "fact", "score": 0.9, "summary": "x"}]


class _FakeSnapshot:
    def rebuild_memory_snapshot(self, max_events: int = 30, write: bool = True) -> str:
        return "line1\nline2\n"

    def verify_memory(
        self, stale_days: int = 90, update_profile: bool = False
    ) -> dict[str, object]:
        return {
            "events": 2,
            "profile_items": 3,
            "open_conflicts": self._parent.conflicts_open,
            "stale_events": 0,
            "stale_profile_items": 0,
            "ttl_tracked_events": 1,
            "last_verified_at": "2026-03-11T00:00:00+00:00",
        }


class _FakeMaintenance:
    def reindex_from_structured_memory(self, **kw: object) -> dict[str, object]:
        return {
            "ok": True,
            "reason": "",
            "written": 4,
            "failed": 0,
            "events_indexed": 2,
            "events_before_compaction": 2,
            "events_after_compaction": 2,
            "events_superseded_dropped": 0,
            "events_duplicates_dropped": 0,
            "vector_points_after": 2,
            "reset": {
                "requested": True,
                "ok": True,
                "reason": "",
                "deleted_estimate": 1,
            },
        }

    def seed_structured_corpus(self, **kw: object) -> dict[str, object]:
        return {
            "ok": self._parent.seeded_ok,
            "reason": "" if self._parent.seeded_ok else "seed_failed",
            "seeded_profile_items": 1,
            "seeded_events": 1,
            "reindex": {"written": 1, "failed": 0, "vector_points_after": 1},
        }

    def _vector_points_count(self) -> int:
        return 0

    def _vector_rows_fn(self, limit: int = 200) -> list[dict[str, object]]:
        return []


class _FakeEvalRunner:
    def get_observability_report(self) -> dict[str, object]:
        return {
            "backend": {
                "vector_enabled": True,
                "vector_mode": "history",
                "vector_points_count": 3,
                "vector_search_count": 2,
                "history_rows_count": 6,
                "vector_health_state": "healthy",
                "vector_add_mode": "history",
            },
            "metrics": {},
            "kpis": {},
        }

    def evaluate_retrieval_cases(
        self, raw_cases: list[dict[str, object]], default_top_k: int = 6, **kw: object
    ) -> dict[str, object]:
        return {
            "cases": len(raw_cases),
            "summary": {"recall_at_k": 1.0, "precision_at_k": 1.0},
            "evaluated": [
                {
                    "query": "q",
                    "top_k": default_top_k,
                    "expected": ["x"],
                    "hits": ["x"],
                    "case_recall_at_k": 1.0,
                    "case_precision_at_k": 1.0,
                    "why_missed": [],
                }
            ],
        }

    def evaluate_rollout_gates(
        self, evaluation: dict[str, object], obs: dict[str, object]
    ) -> dict[str, object]:
        return {
            "passed": True,
            "checks": [
                {"name": "recall", "actual": 1.0, "op": ">=", "threshold": 0.5, "passed": True}
            ],
        }

    def save_evaluation_report(
        self,
        evaluation: dict[str, object],
        obs: dict[str, object],
        rollout: dict[str, object] | None = None,
        output_file: str | None = None,
    ) -> Path:
        out = (
            Path(output_file)
            if output_file
            else self._parent.workspace / "memory" / "reports" / "eval.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return out


class _FakeRolloutConfig:
    def get_status(self) -> dict[str, object]:
        return {"memory_rollout_mode": "enabled"}


class _FakeStore:
    conflicts_open = 0
    conflict_rows: list[dict[str, object]] = []
    resolve_ok = True
    pin_ok = True
    outdated_ok = True
    seeded_ok = True
    PROFILE_KEYS = (
        "preferences",
        "stable_facts",
        "active_projects",
        "relationships",
        "constraints",
    )

    def __init__(
        self, workspace: Path, rollout_overrides: dict[str, object] | None = None, **kw: object
    ):
        self.workspace = workspace
        self.profile_mgr = _FakeProfileMgr()
        self.profile_mgr._parent = self
        self.conflict_mgr = _FakeConflictMgr()
        self.conflict_mgr._parent = self
        self.ingester = _FakeIngester()
        self.retriever = _FakeRetriever()
        self.snapshot = _FakeSnapshot()
        self.snapshot._parent = self
        self.maintenance = _FakeMaintenance()
        self.maintenance._parent = self
        self.eval_runner = _FakeEvalRunner()
        self.eval_runner._parent = self
        self._rollout_config = _FakeRolloutConfig()


@pytest.fixture
def _patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Config:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.memory.MemoryStore", _FakeStore)
    return cfg


def test_memory_inspect_branches(_patched: Config) -> None:
    result = runner.invoke(app, ["memory", "inspect", "--query", "none"])
    assert result.exit_code == 0
    assert "Memory Inspect" in result.stdout
    assert "No memory retrieved" in result.stdout

    result2 = runner.invoke(app, ["memory", "inspect", "--query", "hit"])
    assert result2.exit_code == 0
    assert "Top Memories for: hit" in result2.stdout


def test_memory_metrics_shows_backend_health(_patched: Config, tmp_path: Path) -> None:
    result = runner.invoke(app, ["memory", "metrics"])
    assert result.exit_code == 0
    assert "Memory Backend Health" in result.stdout
    assert "Langfuse" in result.stdout


def test_memory_rebuild_reindex_compact(_patched: Config) -> None:
    rebuild = runner.invoke(app, ["memory", "rebuild", "--max-events", "10"])
    assert rebuild.exit_code == 0
    assert "Rebuilt memory snapshot" in rebuild.stdout

    reindex = runner.invoke(app, ["memory", "reindex", "--max-events", "5", "--no-reset"])
    assert reindex.exit_code == 0
    assert "Memory Reindex" in reindex.stdout

    compact = runner.invoke(app, ["memory", "compact", "--max-events", "5", "--reset"])
    assert compact.exit_code == 0
    assert "Memory Compaction" in compact.stdout


def test_memory_verify_and_conflicts(_patched: Config) -> None:
    _FakeStore.conflicts_open = 0
    ok = runner.invoke(app, ["memory", "verify", "--stale-days", "20"])
    assert ok.exit_code == 0
    assert "Memory Verification" in ok.stdout

    _FakeStore.conflicts_open = 2
    conflict = runner.invoke(app, ["memory", "verify"])
    assert conflict.exit_code == 2

    _FakeStore.conflict_rows = []
    no_rows = runner.invoke(app, ["memory", "conflicts"])
    assert no_rows.exit_code == 0
    assert "No conflicts found" in no_rows.stdout

    _FakeStore.conflict_rows = [
        {
            "index": 0,
            "field": "preferences",
            "old": "a",
            "new": "b",
            "old_memory_id": "o1",
            "new_memory_id": "n1",
            "status": "open",
        }
    ]
    rows = runner.invoke(app, ["memory", "conflicts", "--all"])
    assert rows.exit_code == 0
    assert "Memory Conflicts" in rows.stdout


def test_memory_eval_branches(_patched: Config, tmp_path: Path) -> None:
    # template creation path
    missing_cases = tmp_path / "missing_cases.json"
    first = runner.invoke(app, ["memory", "eval", "--cases-file", str(missing_cases)])
    assert first.exit_code == 1
    assert missing_cases.exists()

    # malformed benchmark payload path
    bad = tmp_path / "bad_cases.json"
    bad.write_text('{"cases": {}}', encoding="utf-8")
    malformed = runner.invoke(app, ["memory", "eval", "--cases-file", str(bad)])
    assert malformed.exit_code == 1
    assert "must contain a JSON array" in malformed.stdout

    # seeded args validation path
    seed_pair = runner.invoke(app, ["memory", "eval", "--seeded-profile", str(tmp_path / "p.json")])
    assert seed_pair.exit_code == 1

    good_cases = tmp_path / "cases.json"
    good_cases.write_text(
        json.dumps({"cases": [{"query": "q", "expected_any": ["x"]}]}), encoding="utf-8"
    )

    _FakeStore.seeded_ok = False
    p = tmp_path / "p.json"
    e = tmp_path / "e.jsonl"
    p.write_text("{}", encoding="utf-8")
    e.write_text("{}\n", encoding="utf-8")
    seed_fail = runner.invoke(
        app,
        [
            "memory",
            "eval",
            "--cases-file",
            str(good_cases),
            "--seeded-profile",
            str(p),
            "--seeded-events",
            str(e),
        ],
    )
    assert seed_fail.exit_code == 2

    _FakeStore.seeded_ok = True
    out = tmp_path / "out.json"
    success = runner.invoke(
        app,
        ["memory", "eval", "--cases-file", str(good_cases), "--export", "--output-file", str(out)],
    )
    assert success.exit_code == 0
    assert out.exists()
    assert "Memory Evaluation" in success.stdout


def test_memory_resolve_pin_unpin_outdated(_patched: Config) -> None:
    _FakeStore.resolve_ok = False
    fail_resolve = runner.invoke(app, ["memory", "resolve", "--index", "0", "--action", "keep_new"])
    assert fail_resolve.exit_code == 1

    _FakeStore.resolve_ok = True
    ok_resolve = runner.invoke(app, ["memory", "resolve", "--index", "0", "--action", "keep_new"])
    assert ok_resolve.exit_code == 0

    pin_bad = runner.invoke(app, ["memory", "pin", "--field", "bad", "--text", "x"])
    assert pin_bad.exit_code == 1

    _FakeStore.pin_ok = False
    pin_miss = runner.invoke(app, ["memory", "pin", "--field", "preferences", "--text", "x"])
    assert pin_miss.exit_code == 1
    _FakeStore.pin_ok = True
    pin_ok = runner.invoke(app, ["memory", "pin", "--field", "preferences", "--text", "x"])
    assert pin_ok.exit_code == 0

    unpin_ok = runner.invoke(app, ["memory", "unpin", "--field", "preferences", "--text", "x"])
    assert unpin_ok.exit_code == 0

    outdated_bad = runner.invoke(app, ["memory", "outdated", "--field", "bad", "--text", "x"])
    assert outdated_bad.exit_code == 1
    _FakeStore.outdated_ok = False
    outdated_miss = runner.invoke(
        app, ["memory", "outdated", "--field", "preferences", "--text", "x"]
    )
    assert outdated_miss.exit_code == 1
    _FakeStore.outdated_ok = True
    outdated_ok = runner.invoke(
        app, ["memory", "outdated", "--field", "preferences", "--text", "x"]
    )
    assert outdated_ok.exit_code == 0


def test_replay_deadletters_dry_run_and_no_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    none = runner.invoke(app, ["replay-deadletters"])
    assert none.exit_code == 0
    assert "No dead-letter file found" in none.stdout

    dead = tmp_path / "outbound_failed.jsonl"
    dead.write_text(
        json.dumps({"channel": "telegram", "chat_id": "1", "content": "hi"}) + "\n",
        encoding="utf-8",
    )
    dry = runner.invoke(app, ["replay-deadletters", "--dry-run"])
    assert dry.exit_code == 0
    assert "Dry run" in dry.stdout

    class _NoChannelManager:
        def __init__(self, config: Config, bus: object):
            self.channels = {}

    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _NoChannelManager)
    no_channel = runner.invoke(app, ["replay-deadletters"])
    assert no_channel.exit_code == 1
    assert "No channels available" in no_channel.stdout


def test_status_and_provider_login_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: tmp_path / "config.json")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "nanobot Status" in status.stdout

    unknown = runner.invoke(app, ["provider", "login", "unknown-provider"])
    assert unknown.exit_code == 1

    monkeypatch.setattr("nanobot.cli.provider._LOGIN_HANDLERS", {})
    no_impl = runner.invoke(app, ["provider", "login", "openai-codex"])
    assert no_impl.exit_code == 1

    monkeypatch.setattr("nanobot.cli.provider._LOGIN_HANDLERS", {"openai_codex": lambda: None})
    ok = runner.invoke(app, ["provider", "login", "openai-codex"])
    assert ok.exit_code == 0


def test_login_handlers_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # openai-codex import error branch
    import builtins

    original_import = builtins.__import__

    def _import_err(name, *args, **kwargs):
        if name == "oauth_cli_kit":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_err)
    codex = runner.invoke(app, ["provider", "login", "openai-codex"])
    assert codex.exit_code == 1

    # github-copilot exception path
    monkeypatch.setattr(
        "litellm.acompletion", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    gh = runner.invoke(app, ["provider", "login", "github-copilot"])
    assert gh.exit_code == 1


def test_login_openai_codex_success_and_failed_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Token:
        def __init__(self, access: str | None, account_id: str = "acct-1"):
            self.access = access
            self.account_id = account_id

    class _OauthModule:
        @staticmethod
        def get_token():
            return _Token(None)

        @staticmethod
        def login_oauth_interactive(print_fn, prompt_fn):
            return _Token("abc")

    import builtins

    original_import = builtins.__import__

    def _import_stub(name, *args, **kwargs):
        if name == "oauth_cli_kit":
            return _OauthModule
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_stub)
    ok = runner.invoke(app, ["provider", "login", "openai-codex"])
    assert ok.exit_code == 0
    assert "Authenticated with OpenAI Codex" in ok.stdout

    class _OauthFail:
        @staticmethod
        def get_token():
            return _Token(None)

        @staticmethod
        def login_oauth_interactive(print_fn, prompt_fn):
            return _Token(None)

    def _import_fail(name, *args, **kwargs):
        if name == "oauth_cli_kit":
            return _OauthFail
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_fail)
    fail = runner.invoke(app, ["provider", "login", "openai-codex"])
    assert fail.exit_code == 1
    assert "Authentication failed" in fail.stdout
