"""Slice E1 — legacy single-tenant migration on startup."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.auth.migration import migrate_legacy_layout_if_needed


def _seed_legacy(base: Path, *, with_config: bool = True) -> None:
    """Materialise a synthetic single-tenant tree under ``base``."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "sessions").mkdir()
    (base / "workspace").mkdir()
    (base / "memory").mkdir()
    (base / "sessions" / "old.jsonl").write_text("legacy data")
    (base / "workspace" / "AGENTS.md").write_text("# legacy AGENTS")
    if with_config:
        (base / "config.json").write_text('{"legacy": true}')


def test_legacy_layout_archived_and_fresh_tree_created(tmp_path: Path) -> None:
    base = tmp_path / ".nanobot"
    _seed_legacy(base)

    archive = migrate_legacy_layout_if_needed(base)

    assert archive is not None
    assert archive.is_dir()
    assert archive.name.startswith(".nanobot.legacy.")
    assert (archive / "sessions" / "old.jsonl").read_text() == "legacy data"
    # Fresh tree exists with users/ scaffold and config carried over.
    assert base.is_dir()
    assert (base / "users").is_dir()
    assert (base / "config.json").read_text() == '{"legacy": true}'
    # No legacy subdirs in the fresh tree.
    assert not (base / "sessions").exists()
    assert not (base / "workspace").exists()


def test_idempotent_when_users_dir_present(tmp_path: Path) -> None:
    base = tmp_path / ".nanobot"
    base.mkdir()
    (base / "users").mkdir()
    (base / "sessions").mkdir()  # would normally trigger but users/ wins
    archive = migrate_legacy_layout_if_needed(base)
    assert archive is None
    assert (base / "sessions").is_dir()


def test_no_op_on_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    archive = migrate_legacy_layout_if_needed(missing)
    assert archive is None
    assert not missing.exists()


def test_no_op_on_clean_directory(tmp_path: Path) -> None:
    base = tmp_path / ".nanobot"
    base.mkdir()
    (base / "users").mkdir()
    archive = migrate_legacy_layout_if_needed(base)
    assert archive is None


def test_skip_env_short_circuits(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / ".nanobot"
    _seed_legacy(base)
    monkeypatch.setenv("NANOBOT_SKIP_LEGACY_MIGRATION", "1")
    archive = migrate_legacy_layout_if_needed(base)
    assert archive is None
    # Legacy tree untouched.
    assert (base / "sessions" / "old.jsonl").exists()


def test_archive_name_disambiguates_on_collision(tmp_path: Path, monkeypatch) -> None:
    """If two migrations happen within the same second, the second picks a
    suffixed archive path so neither overwrites the other."""
    base = tmp_path / ".nanobot"
    _seed_legacy(base)
    # Force the timestamp helper to return a fixed value so we can collide.
    fixed = "20260511-153000"
    monkeypatch.setattr("nanobot.auth.migration._now_iso", lambda: fixed)
    # Pre-create the path the first migration would target.
    (tmp_path / f".nanobot.legacy.{fixed}").mkdir()
    archive = migrate_legacy_layout_if_needed(base)
    assert archive is not None
    assert archive.name.endswith(".1") or archive.name.endswith(".2")


def test_migration_runs_without_config_json(tmp_path: Path) -> None:
    base = tmp_path / ".nanobot"
    _seed_legacy(base, with_config=False)
    archive = migrate_legacy_layout_if_needed(base)
    assert archive is not None
    assert (base / "users").is_dir()
    assert not (base / "config.json").exists()


def test_does_not_run_when_only_unrelated_files_present(tmp_path: Path) -> None:
    base = tmp_path / ".nanobot"
    base.mkdir()
    (base / "auth.db").touch()
    (base / "config.json").write_text("{}")
    archive = migrate_legacy_layout_if_needed(base)
    assert archive is None
    assert (base / "auth.db").exists()


@pytest.fixture(autouse=True)
def _unset_skip_env(monkeypatch):
    """Always start each test with the skip flag unset, regardless of host env."""
    monkeypatch.delenv("NANOBOT_SKIP_LEGACY_MIGRATION", raising=False)
    yield
