import json
from pathlib import Path

from nanobot_mail_watcher.cli import run
from nanobot_mail_watcher.store import MailEventStore


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "mail.toml"
    path.write_text(
        f"""
[worker]
database = {str(tmp_path / "events.sqlite3")!r}
himalaya_binary = "/bin/false"

[accounts.work]
source_mailboxes = ["INBOX"]
allowed_folders = []
""",
        encoding="utf-8",
    )
    return path


def test_enqueue_env_reads_only_validated_carillon_environment(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    config_path = _config(tmp_path)
    monkeypatch.setenv("mailbox", "INBOX")
    monkeypatch.setenv("id", "42")

    assert run(["--config", str(config_path), "enqueue-env", "--account", "work"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["created"] is True
    assert MailEventStore(tmp_path / "events.sqlite3").counts()["pending"] == 1

    monkeypatch.setenv("id", "$(touch /tmp/must-not-run)")
    assert run(["--config", str(config_path), "enqueue-env", "--account", "work"]) == 1
    assert "positive decimal IMAP UID" in capsys.readouterr().err
    assert MailEventStore(tmp_path / "events.sqlite3").counts()["pending"] == 1


def test_enqueue_env_requires_fixed_event_names(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = _config(tmp_path)
    monkeypatch.delenv("mailbox", raising=False)
    monkeypatch.setenv("id", "42")

    assert run(["--config", str(config_path), "enqueue-env", "--account", "work"]) == 1
    assert "environment variable is missing: mailbox" in capsys.readouterr().err


def test_explicit_reconcile_cli_reports_discovered_uids(tmp_path: Path, capsys) -> None:
    executable = tmp_path / "fake-himalaya"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
if "status" in sys.argv:
    print(json.dumps({"uid_validity": 88}))
elif "search" in sys.argv:
    print(json.dumps({"uid_mode": True, "ids": [{"id": 7}]}))
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    config_path = _config(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        'himalaya_binary = "/bin/false"', f'himalaya_binary = "{executable}"'
    )
    config_path.write_text(text, encoding="utf-8")

    assert run(["--config", str(config_path), "reconcile"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["created"] == 1
    assert report["failed"] == 0
    assert MailEventStore(tmp_path / "events.sqlite3").counts()["pending"] == 1


def test_all_folder_hook_accepts_non_inbox_without_rules(tmp_path: Path, capsys) -> None:
    config = tmp_path / "mail.toml"
    config.write_text('[worker]\ndatabase="events.sqlite3"\n[accounts.work]\nfolder_policy="all"\n')
    assert run(["--config", str(config), "enqueue", "--account", "work",
                "--mailbox", "Archive/Subfolder", "--uid", "3"]) == 0
    assert '"created": true' in capsys.readouterr().out
