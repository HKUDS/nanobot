from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.autocompact import AutoCompact
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import AgentDefaults, parse_duration
from nanobot.session.manager import Session, SessionManager


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
def manager(sessions_dir: Path) -> SessionManager:
    return SessionManager(workspace=sessions_dir.parent)


def _make_autocompact(
    manager: SessionManager,
    session_cleanup_seconds: float = 0,
) -> AutoCompact:
    consolidator = MagicMock()
    return AutoCompact(
        sessions=manager,
        consolidator=consolidator,
        session_ttl_minutes=0,
        session_cleanup_seconds=session_cleanup_seconds,
    )


def _save_session(manager: SessionManager, key: str, updated_at: datetime) -> Session:
    session = manager.get_or_create(key)
    session.updated_at = updated_at
    session.add_message("user", "hi")
    # Override updated_at after add_message (which sets it to now)
    session.updated_at = updated_at
    manager.save(session)
    return session


def _session_file_exists(sessions_dir: Path, key: str) -> bool:
    stem = key.replace(":", "_")
    return (sessions_dir / f"{stem}.jsonl").exists()


class TestParseDuration:
    def test_days(self) -> None:
        assert parse_duration("15d") == 15 * 86400

    def test_days_long(self) -> None:
        assert parse_duration("2days") == 2 * 86400

    def test_hours(self) -> None:
        assert parse_duration("24h") == 24 * 3600

    def test_hours_long(self) -> None:
        assert parse_duration("48hours") == 48 * 3600

    def test_minutes(self) -> None:
        assert parse_duration("30m") == 30 * 60

    def test_minutes_long(self) -> None:
        assert parse_duration("90min") == 90 * 60

    def test_zero(self) -> None:
        assert parse_duration("0") == 0

    def test_empty(self) -> None:
        assert parse_duration("") == 0

    def test_spaces(self) -> None:
        assert parse_duration("  15d  ") == 15 * 86400

    def test_case_insensitive(self) -> None:
        assert parse_duration("15D") == 15 * 86400
        assert parse_duration("10H") == 10 * 3600

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_no_unit_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("42")

    def test_invalid_unit_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("5w")


class TestCleanupExpired:
    def test_deletes_sessions_older_than_threshold(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        old_time = datetime.now() - timedelta(hours=25)
        _save_session(manager, "tg:111", old_time)

        assert _session_file_exists(sessions_dir, "tg:111")

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 1
        assert not _session_file_exists(sessions_dir, "tg:111")
        assert manager.get_or_create("tg:111").messages == []

    def test_skips_sessions_newer_than_threshold(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        recent_time = datetime.now() - timedelta(hours=12)
        _save_session(manager, "tg:222", recent_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 0
        assert _session_file_exists(sessions_dir, "tg:222")

    def test_skips_active_session_keys(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        old_time = datetime.now() - timedelta(hours=48)
        _save_session(manager, "tg:333", old_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired(active_session_keys=("tg:333",))

        assert deleted == 0
        assert _session_file_exists(sessions_dir, "tg:333")

    def test_skips_sessions_being_archived(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        old_time = datetime.now() - timedelta(hours=48)
        _save_session(manager, "tg:444", old_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        ac._archiving.add("tg:444")
        deleted = ac.cleanup_expired()

        assert deleted == 0
        assert _session_file_exists(sessions_dir, "tg:444")

    def test_disabled_when_seconds_zero(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        old_time = datetime.now() - timedelta(days=365)
        _save_session(manager, "tg:555", old_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=0)
        deleted = ac.cleanup_expired()

        assert deleted == 0
        assert _session_file_exists(sessions_dir, "tg:555")

    def test_handles_recent_session(self, manager: SessionManager) -> None:
        session = manager.get_or_create("tg:666")
        session.add_message("user", "hi")
        manager.save(session)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 0

    def test_logs_and_continues_on_delete_failure(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        old_time = datetime.now() - timedelta(hours=48)
        _save_session(manager, "tg:good", old_time)
        _save_session(manager, "tg:bad", old_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        original_delete = manager.delete_session

        def flaky_delete(key: str) -> bool:
            if key == "tg:bad":
                return False
            return original_delete(key)

        manager.delete_session = flaky_delete
        deleted = ac.cleanup_expired()

        assert deleted == 1
        assert not _session_file_exists(sessions_dir, "tg:good")

    def test_mixed_sessions_deletes_only_expired(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        very_old = datetime.now() - timedelta(hours=72)
        recent = datetime.now() - timedelta(hours=6)
        _save_session(manager, "tg:old1", very_old)
        _save_session(manager, "tg:recent1", recent)
        _save_session(manager, "tg:old2", very_old)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 2
        assert not _session_file_exists(sessions_dir, "tg:old1")
        assert not _session_file_exists(sessions_dir, "tg:old2")
        assert _session_file_exists(sessions_dir, "tg:recent1")

    def test_exact_boundary_not_expired(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        exact_time = datetime.now() - timedelta(seconds=24 * 3600)
        _save_session(manager, "tg:boundary", exact_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 1
        assert not _session_file_exists(sessions_dir, "tg:boundary")

    def test_one_second_before_threshold_not_expired(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        almost_time = datetime.now() - timedelta(seconds=24 * 3600 - 1)
        _save_session(manager, "tg:almost", almost_time)

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 0
        assert _session_file_exists(sessions_dir, "tg:almost")

    def test_updated_at_read_from_disk_not_cache(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        old_time = datetime.now() - timedelta(hours=48)
        session = _save_session(manager, "tg:disk", old_time)
        session.updated_at = datetime.now()

        ac = _make_autocompact(manager, session_cleanup_seconds=24 * 3600)
        deleted = ac.cleanup_expired()

        assert deleted == 1
        assert not _session_file_exists(sessions_dir, "tg:disk")


class TestConfigIntegration:
    def test_default_is_disabled(self) -> None:
        cfg = AgentDefaults()
        assert cfg.session_cleanup == "0"
        assert cfg.session_cleanup_seconds == 0

    def test_config_from_days(self) -> None:
        cfg = AgentDefaults(session_cleanup="15d")
        assert cfg.session_cleanup_seconds == 15 * 86400

    def test_config_from_camel_case(self) -> None:
        cfg = AgentDefaults.model_validate({"sessionCleanup": "7d"})
        assert cfg.session_cleanup == "7d"
        assert cfg.session_cleanup_seconds == 7 * 86400

    def test_config_backward_compat_alias(self) -> None:
        cfg = AgentDefaults.model_validate({"sessionCleanupHours": "24h"})
        assert cfg.session_cleanup_seconds == 24 * 3600

    def test_config_load_save_roundtrip(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"agents": {"defaults": {"sessionCleanup": "15d"}}})
        )
        cfg = load_config(config_path)
        assert cfg.agents.defaults.session_cleanup == "15d"
        assert cfg.agents.defaults.session_cleanup_seconds == 15 * 86400

        save_config(cfg, config_path)
        cfg2 = load_config(config_path)
        assert cfg2.agents.defaults.session_cleanup == "15d"

    def test_config_without_field_loads_default(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"agents": {"defaults": {"model": "test"}}}))
        cfg = load_config(config_path)
        assert cfg.agents.defaults.session_cleanup == "0"
        assert cfg.agents.defaults.session_cleanup_seconds == 0

    def test_invalid_duration_raises_on_access(self) -> None:
        cfg = AgentDefaults(session_cleanup="bad")
        with pytest.raises(ValueError, match="Invalid duration"):
            _ = cfg.session_cleanup_seconds

    def test_end_to_end_config_to_cleanup(
        self, manager: SessionManager, sessions_dir: Path
    ) -> None:
        cfg = AgentDefaults(session_cleanup="15d")
        ac = _make_autocompact(manager, session_cleanup_seconds=cfg.session_cleanup_seconds)

        old_time = datetime.now() - timedelta(days=16)
        _save_session(manager, "tg:expired", old_time)

        recent_time = datetime.now() - timedelta(days=10)
        _save_session(manager, "tg:active", recent_time)

        deleted = ac.cleanup_expired()
        assert deleted == 1
        assert not _session_file_exists(sessions_dir, "tg:expired")
        assert _session_file_exists(sessions_dir, "tg:active")
