import json
from pathlib import Path

import filelock
import pytest

from nanobot.agent.skills_telemetry import (
    WARN_COALESCE_EVERY,
    BumpKind,  # noqa: F401
    SkillEntry,
    SkillTelemetry,
    TelemetryEntrySnapshot,
    TelemetrySnapshot,
    Writer,  # noqa: F401
)


class AlwaysTimeout:
    """Drop-in `filelock.FileLock` replacement that always times out.

    Used by tests that need to verify behavior when the cross-process
    filelock cannot be acquired.
    """

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        raise filelock.Timeout("lock")

    def __exit__(self, *a):
        return False


def _seed_disk(workspace: Path, entries: dict[str, dict]) -> Path:
    """Pre-populate the telemetry file as if reconcile() already ran.

    A7 will land the real reconcile() helper; A5's tests use this seed shim
    to simulate the post-reconcile state, since the strict bump-orphan-skip
    rule (spec §4.3 + invariant 3 + decision #31) means flush(writer="bump")
    only mutates entries that already exist on disk.
    """
    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": "2026-06-11T00:00:00Z",
        "entries": entries,
    }
    path = skills_dir / ".telemetry.json"
    path.write_text(json.dumps(payload))
    return path


def _zero_seed_entry(origin: str = "user") -> dict:
    return {
        "origin": origin, "shadowed": [],
        "views": 0, "uses": 0, "patches": 0,
        "entry_created_at": "2026-06-11T00:00:00Z",
        "last_view": None, "last_use": None,
    }


def test_construct_on_fresh_workspace_creates_parent_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    # NOTE: workspace 本身不存在，skills/ 不存在 —— 必须由 __init__ 自建
    telem = SkillTelemetry(workspace)
    assert (workspace / "skills").is_dir()
    snap = telem.snapshot()
    assert snap["schema_version"] == 1
    assert snap["entries"] == {}


def test_typeddict_keys_match_spec_field_table() -> None:
    # 静态检查 TypedDict 形态与 spec §4.2 一致
    assert set(SkillEntry.__annotations__) == {
        "name", "effective_origin", "shadowed_origins", "path",
    }
    assert set(TelemetryEntrySnapshot.__annotations__) == {
        "origin", "shadowed", "views", "uses", "patches",
        "entry_created_at", "last_view", "last_use",
    }
    assert set(TelemetrySnapshot.__annotations__) == {
        "schema_version", "updated_at", "entries",
    }


def test_bump_increments_correct_counter_and_timestamp(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.bump("foo", "view")
    telem.bump("foo", "view")
    telem.bump("foo", "use")
    snap = telem.snapshot()
    e = snap["entries"]["foo"]
    assert e["views"] == 2
    assert e["uses"] == 1
    assert e["patches"] == 0
    assert e["origin"] == "unknown"
    assert e["last_view"] is not None
    assert e["last_use"] is not None
    assert e["entry_created_at"] is not None


def test_bump_rejects_unknown_kind(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    with pytest.raises(ValueError):
        telem.bump("foo", "nope")  # type: ignore[arg-type]


def test_bump_dirty_flag_set(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    assert telem._dirty is False
    telem.bump("foo", "view")
    assert telem._dirty is True


def test_atomic_write_creates_file_and_no_tmp_residue(tmp_path: Path) -> None:
    import json

    from nanobot.agent.skills_telemetry import _atomic_write
    target = tmp_path / "data.json"
    _atomic_write(target, {"foo": 1})
    assert json.loads(target.read_text()) == {"foo": 1}
    leftover = list(tmp_path.glob("data.json.tmp*"))
    assert leftover == []


def test_atomic_write_overwrites_existing(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import _atomic_write
    target = tmp_path / "data.json"
    target.write_text('{"old": true}')
    _atomic_write(target, {"new": True})
    import json
    assert json.loads(target.read_text()) == {"new": True}


def test_safe_read_json_returns_default_on_missing(tmp_path: Path) -> None:
    from nanobot.agent.skills_telemetry import _safe_read_json
    result = _safe_read_json(tmp_path / "missing.json")
    assert result is None


def test_safe_read_json_handles_corrupt_file(tmp_path: Path) -> None:
    from loguru import logger

    from nanobot.agent.skills_telemetry import _safe_read_json
    messages = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{not json")
        result = _safe_read_json(corrupt)
    finally:
        logger.remove(sink_id)
    assert result is None
    backup = next(tmp_path.glob("corrupt.json.corrupted.*"), None)
    assert backup is not None, "corrupted file must be backed up"
    assert any("json_corruption" in m for m in messages)


def test_rmw_counters_incremental_add_on_existing_entry() -> None:
    from nanobot.agent.skills_telemetry import _rmw_merge
    on_disk = {
        "schema_version": 1,
        "updated_at": "2026-06-10T00:00:00Z",
        "entries": {
            "foo": {
                "origin": "user", "shadowed": [],
                "views": 100, "uses": 30, "patches": 0,
                "entry_created_at": "2026-06-01T00:00:00Z",
                "last_view": "2026-06-09T00:00:00Z",
                "last_use": None,
            }
        },
    }
    snapshot = {
        "foo": {
            "origin": "unknown", "shadowed": [],
            "views": 10, "uses": 3, "patches": 0,
            "entry_created_at": "2026-06-05T00:00:00Z",
            "last_view": "2026-06-11T01:00:00Z",
            "last_use": None,
        }
    }
    # last_synced_counts says "we previously flushed 7 views, 2 uses for foo"
    last_synced = {"foo": {"views": 7, "uses": 2, "patches": 0}}
    merged = _rmw_merge(on_disk, snapshot, last_synced, writer="bump")
    # Disk had 100 + delta(10-7=3) = 103
    assert merged["entries"]["foo"]["views"] == 103
    # Disk had 30 + delta(3-2=1) = 31
    assert merged["entries"]["foo"]["uses"] == 31
    # origin/shadowed preserved from on_disk (writer="bump" never touches origin)
    assert merged["entries"]["foo"]["origin"] == "user"
    # last_view = max(disk, snapshot)
    assert merged["entries"]["foo"]["last_view"] == "2026-06-11T01:00:00Z"
    # entry_created_at = min(disk, snapshot)
    assert merged["entries"]["foo"]["entry_created_at"] == "2026-06-01T00:00:00Z"


def test_rmw_bump_only_skips_orphan_entry_not_on_disk() -> None:
    from nanobot.agent.skills_telemetry import _rmw_merge
    on_disk = {"schema_version": 1, "updated_at": "x", "entries": {}}
    snapshot = {
        "foo": {
            "origin": "unknown", "shadowed": [],
            "views": 5, "uses": 0, "patches": 0,
            "entry_created_at": "2026-06-11T00:00:00Z",
            "last_view": "2026-06-11T00:00:00Z", "last_use": None,
        }
    }
    merged = _rmw_merge(on_disk, snapshot, {}, writer="bump")
    assert merged["entries"] == {}  # bump cannot resurrect entry reconcile killed


def test_rmw_reconcile_creates_new_entry() -> None:
    from nanobot.agent.skills_telemetry import _rmw_merge
    on_disk = {"schema_version": 1, "updated_at": "x", "entries": {}}
    snapshot = {
        "bar": {
            "origin": "agent", "shadowed": [],
            "views": 0, "uses": 0, "patches": 0,
            "entry_created_at": "2026-06-11T00:00:00Z",
            "last_view": None, "last_use": None,
        }
    }
    merged = _rmw_merge(on_disk, snapshot, {}, writer="reconcile")
    assert merged["entries"]["bar"]["origin"] == "agent"


def test_rmw_writer_reconcile_unknown_origin_does_not_overwrite_known() -> None:
    from nanobot.agent.skills_telemetry import _rmw_merge
    on_disk = {
        "schema_version": 1, "updated_at": "x",
        "entries": {"baz": {
            "origin": "user", "shadowed": [],
            "views": 1, "uses": 0, "patches": 0,
            "entry_created_at": "2026-06-01T00:00:00Z",
            "last_view": None, "last_use": None,
        }},
    }
    snapshot = {"baz": {
        "origin": "unknown", "shadowed": [],
        "views": 1, "uses": 0, "patches": 0,
        "entry_created_at": "2026-06-01T00:00:00Z",
        "last_view": None, "last_use": None,
    }}
    merged = _rmw_merge(on_disk, snapshot, {"baz": {"views": 1, "uses": 0, "patches": 0}},
                        writer="reconcile")
    assert merged["entries"]["baz"]["origin"] == "user"  # unknown never overwrites known


def test_rmw_preserves_unknown_top_level_fields() -> None:
    from nanobot.agent.skills_telemetry import _rmw_merge
    on_disk = {
        "schema_version": 2,
        "updated_at": "x",
        "entries": {"foo": {
            "origin": "user", "shadowed": [], "views": 1, "uses": 0, "patches": 0,
            "entry_created_at": "x", "last_view": None, "last_use": None,
            "cooldown_until": "2026-12-01T00:00:00Z",  # future field
        }},
        "future_top": {"hello": "world"},
    }
    snapshot = {"foo": {
        "origin": "user", "shadowed": [], "views": 1, "uses": 0, "patches": 0,
        "entry_created_at": "x", "last_view": None, "last_use": None,
    }}
    merged = _rmw_merge(on_disk, snapshot, {"foo": {"views": 1, "uses": 0, "patches": 0}},
                        writer="bump")
    assert merged["future_top"] == {"hello": "world"}
    assert merged["entries"]["foo"]["cooldown_until"] == "2026-12-01T00:00:00Z"


def test_flush_writes_disk_and_advances_last_synced(tmp_path: Path) -> None:
    import json
    workspace = tmp_path / "ws"
    _seed_disk(workspace, {"foo": _zero_seed_entry()})

    telem = SkillTelemetry(workspace)
    telem.bump("foo", "view")
    telem.bump("foo", "view")
    telem.flush()
    data = json.loads((workspace / "skills" / ".telemetry.json").read_text())
    assert data["entries"]["foo"]["views"] == 2
    assert telem._last_synced_counts["foo"]["views"] == 2
    assert telem._dirty is False


def test_flush_noop_when_not_dirty(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.flush()  # no bump → no-op
    assert not (tmp_path / "ws" / "skills" / ".telemetry.json").exists()


def test_flush_rmw_merges_external_disk_changes_between_flushes(tmp_path: Path) -> None:
    import json
    workspace = tmp_path / "ws"
    _seed_disk(workspace, {"shared": _zero_seed_entry()})

    # Process A: bump 5 views, flush, then bump 3 more
    # Meanwhile simulate "process B" by editing disk directly between flushes
    telem = SkillTelemetry(workspace)
    for _ in range(5):
        telem.bump("shared", "view")
    telem.flush()
    # External process bumps disk by 7 (simulating another nanobot writing)
    path = workspace / "skills" / ".telemetry.json"
    on_disk = json.loads(path.read_text())
    on_disk["entries"]["shared"]["views"] += 7
    path.write_text(json.dumps(on_disk))
    # Process A bumps 3 more, flush → should be 5+7+3 = 15
    for _ in range(3):
        telem.bump("shared", "view")
    telem.flush()
    final = json.loads(path.read_text())
    assert final["entries"]["shared"]["views"] == 15


def test_flush_single_flight_second_call_is_noop(tmp_path: Path, monkeypatch) -> None:
    import threading

    from nanobot.agent import skills_telemetry as st
    telem = SkillTelemetry(tmp_path / "ws")
    telem.bump("foo", "view")
    call_count = {"n": 0}
    orig = st._atomic_write
    started = threading.Event()
    block = threading.Event()

    def slow_write(path, payload):
        call_count["n"] += 1
        started.set()
        block.wait(timeout=2.0)
        orig(path, payload)

    monkeypatch.setattr(st, "_atomic_write", slow_write)
    t = threading.Thread(target=telem.flush)
    t.start()
    started.wait(timeout=2.0)
    telem.flush()  # second concurrent flush — must be no-op
    block.set()
    t.join(timeout=2.0)
    assert call_count["n"] == 1


def test_flush_filelock_timeout_preserves_dirty_and_last_synced(
    tmp_path: Path, monkeypatch
) -> None:
    from nanobot.agent import skills_telemetry as st
    telem = SkillTelemetry(tmp_path / "ws")
    telem.bump("foo", "view")
    monkeypatch.setattr(st.filelock, "FileLock", AlwaysTimeout)
    telem.flush()
    # disk file never created; in-memory state preserved
    assert not (tmp_path / "ws" / "skills" / ".telemetry.json").exists()
    assert telem._dirty is True
    assert telem._last_synced_counts == {}


def test_warn_throttle_emits_once_per_100_failures(
    tmp_path: Path, monkeypatch, loguru_caplog
) -> None:
    # Uses loguru_caplog (not bare caplog) because telemetry uses loguru;
    # see fixture docstring for the stdlib bridge rationale.
    from nanobot.agent import skills_telemetry as st
    telem = SkillTelemetry(tmp_path / "ws")
    monkeypatch.setattr(st.filelock, "FileLock", AlwaysTimeout)
    # Drive enough failures to cross WARN_COALESCE_EVERY twice but stop short
    # of the third multiple, so the assertion is keyed off the constant.
    n_failures = WARN_COALESCE_EVERY * 2 + WARN_COALESCE_EVERY // 2
    expected_warns = n_failures // WARN_COALESCE_EVERY
    for _ in range(n_failures):
        telem.bump("foo", "view")
        telem.flush()
    filelock_warns = [
        r for r in loguru_caplog.records if "filelock_timeout" in r.getMessage()
    ]
    # Coalesced every WARN_COALESCE_EVERY failures; the trailing remainder
    # (less than one full window) does not trigger an emission.
    assert len(filelock_warns) == expected_warns


# ---------------------------------------------------------------------------
# A7: reconcile() arrival / orphan / origin update + frozen disabled skills
# ---------------------------------------------------------------------------


def _make_entry(name: str, origin: str = "user", path: str = "/x/SKILL.md") -> SkillEntry:
    return {
        "name": name,
        "effective_origin": origin,
        "shadowed_origins": [],
        "path": path,
    }


def test_reconcile_creates_zero_entry_for_new_skill(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.reconcile([_make_entry("foo")])
    snap = telem.snapshot()
    e = snap["entries"]["foo"]
    assert e["origin"] == "user"
    assert e["views"] == 0
    assert e["uses"] == 0
    assert e["entry_created_at"] is not None


def test_reconcile_removes_orphan_entry(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.reconcile([_make_entry("foo")])
    telem.bump("foo", "view")
    telem.flush()
    # remove foo from known list → orphan
    telem.reconcile([])
    telem.flush()
    data = json.loads((tmp_path / "ws" / "skills" / ".telemetry.json").read_text())
    assert "foo" not in data["entries"]
    assert "foo" not in telem._last_synced_counts


def test_reconcile_freezes_disabled_skill_entry(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.reconcile([_make_entry("foo")])
    for _ in range(7):
        telem.bump("foo", "view")
    telem.flush()
    # disabled set means foo is neither in known_skills nor an orphan (frozen)
    telem.reconcile(known_skills=[], disabled_skills={"foo"})
    telem.flush()
    data = json.loads((tmp_path / "ws" / "skills" / ".telemetry.json").read_text())
    assert data["entries"]["foo"]["views"] == 7


def test_reconcile_does_not_touch_counters_for_existing_entry(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.reconcile([_make_entry("foo")])
    telem.bump("foo", "view")
    telem.bump("foo", "use")
    telem.flush()
    # Second reconcile with new effective origin — counters must be untouched
    telem.reconcile([_make_entry("foo", origin="agent")])
    telem.flush()
    data = json.loads((tmp_path / "ws" / "skills" / ".telemetry.json").read_text())
    assert data["entries"]["foo"]["views"] == 1
    assert data["entries"]["foo"]["uses"] == 1
    assert data["entries"]["foo"]["origin"] == "agent"


def test_reconcile_corrects_unknown_origin_lazy_entry(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.bump("foo", "view")  # lazy init with origin="unknown"
    telem.reconcile([_make_entry("foo", origin="agent")])
    telem.flush()
    data = json.loads((tmp_path / "ws" / "skills" / ".telemetry.json").read_text())
    assert data["entries"]["foo"]["origin"] == "agent"
    assert data["entries"]["foo"]["views"] == 1  # counter preserved
