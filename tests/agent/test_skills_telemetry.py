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
    from nanobot.agent.skills_telemetry import _atomic_write
    target = tmp_path / "data.json"
    _atomic_write(target, {"foo": 1})
    assert target.read_text() == '{"foo": 1}' or '"foo": 1' in target.read_text()
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
