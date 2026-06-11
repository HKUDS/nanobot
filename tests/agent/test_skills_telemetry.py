from pathlib import Path

import pytest

from nanobot.agent.skills_telemetry import (
    BumpKind,  # noqa: F401
    SkillEntry,
    SkillTelemetry,
    TelemetryEntrySnapshot,
    TelemetrySnapshot,
    Writer,  # noqa: F401
)


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
    # last_synced has a record for foo → "we previously synced 3 views;
    # disk lost it → reconcile killed it."
    last_synced = {"foo": {"views": 3, "uses": 0, "patches": 0}}
    merged = _rmw_merge(on_disk, snapshot, last_synced, writer="bump")
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
    telem = SkillTelemetry(tmp_path / "ws")
    telem.bump("foo", "view")
    telem.bump("foo", "view")
    telem.flush()
    data = json.loads((tmp_path / "ws" / "skills" / ".telemetry.json").read_text())
    assert data["entries"]["foo"]["views"] == 2
    assert telem._last_synced_counts["foo"]["views"] == 2
    assert telem._dirty is False


def test_flush_noop_when_not_dirty(tmp_path: Path) -> None:
    telem = SkillTelemetry(tmp_path / "ws")
    telem.flush()  # no bump → no-op
    assert not (tmp_path / "ws" / "skills" / ".telemetry.json").exists()


def test_flush_rmw_preserves_concurrent_process_writes(tmp_path: Path) -> None:
    import json
    # Process A: bump 5 views, flush, then bump 3 more
    # Meanwhile simulate "process B" by editing disk directly between flushes
    telem = SkillTelemetry(tmp_path / "ws")
    for _ in range(5):
        telem.bump("shared", "view")
    telem.flush()
    # External process bumps disk by 7 (simulating another nanobot writing)
    path = tmp_path / "ws" / "skills" / ".telemetry.json"
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
