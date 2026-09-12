from pathlib import Path

import pytest

from nanobot_mail_watcher.config import load_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_resolves_paths_and_policy(tmp_path: Path) -> None:
    config = load_config(
        _write(
            tmp_path / "mail.toml",
            """
[worker]
database = "state/events.sqlite3"
himalaya_config = "himalaya.toml"

[accounts.work]
source_mailboxes = ["INBOX"]
allowed_folders = ["Orders", "Review"]
unmatched_destination = "Review"

[[accounts.work.rules]]
name = "orders"
destination = "Orders"
sender_globs = ["*@shop.example"]
""",
        )
    )

    assert config.worker.dry_run is True
    assert config.worker.database == (tmp_path / "state/events.sqlite3").resolve()
    assert config.worker.himalaya_config == (tmp_path / "himalaya.toml").resolve()
    assert config.worker.reconcile_interval_seconds == 180
    assert config.worker.reconcile_max_messages == 5_000
    assert config.accounts["work"].rules[0].destination == "Orders"


def test_rejects_destination_outside_allowlist(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "mail.toml",
        """
[accounts.work]
allowed_folders = ["Review"]

[[accounts.work.rules]]
name = "bad"
destination = "Secret"
subject_contains = ["x"]
""",
    )
    with pytest.raises(ValueError, match="not in allowed_folders"):
        load_config(path)


def test_rejects_rule_without_conditions(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "mail.toml",
        """
[accounts.work]
allowed_folders = ["Review"]

[[accounts.work.rules]]
name = "everything"
destination = "Review"
""",
    )
    with pytest.raises(ValueError, match="at least one condition"):
        load_config(path)


def test_rejects_relative_himalaya_executable(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "mail.toml",
        """
[worker]
himalaya_binary = "himalaya"

[accounts.work]
allowed_folders = []
""",
    )
    with pytest.raises(ValueError, match="absolute path"):
        load_config(path)


def test_reconcile_interval_must_stay_between_two_and_five_minutes(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "mail.toml",
        """
[worker]
reconcile_interval_seconds = 60

[accounts.work]
allowed_folders = []
""",
    )
    with pytest.raises(ValueError, match="between 120 and 300"):
        load_config(path)


def test_all_folders_default_and_rules_optional(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path / "mail.toml", "[accounts.work]\n"))
    assert config.accounts["work"].folder_policy == "all"
    assert config.accounts["work"].rules == ()


def test_all_folders_accepts_legacy_rule_proposals_without_allowlist(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path / "mail.toml", '''
[accounts.work]
folder_policy = "all"
[[accounts.work.rules]]
name = "review"
destination = "Review"
subject_contains = ["invoice"]
'''))
    assert config.accounts["work"].rules[0].destination == "Review"


def test_explicit_legacy_sources_keep_restrictions(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path / "mail.toml", '[accounts.work]\nsource_mailboxes = ["INBOX"]\n'))
    assert config.accounts["work"].folder_policy == "allowlist"
