import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from nanobot_mail_watcher.config import WorkerConfig
from nanobot_mail_watcher.himalaya import HimalayaClient, MessageTooLargeError


def _fake_himalaya(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "fake-himalaya"
    calls = tmp_path / "calls.jsonl"
    executable.write_text(
        f"""#!{sys.executable}
import json
import pathlib
import sys

calls = pathlib.Path({str(calls)!r})
with calls.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if "--version" in sys.argv:
    print("himalaya 2.1.0")
elif "status" in sys.argv:
    print(json.dumps({{"uid_validity": 808, "messages": 2}}))
elif "search" in sys.argv:
    print(json.dumps({{"uid_mode": True, "ids": [{{"id": 7}}, {{"id": 9}}]}}))
elif "read" in sys.argv:
    sys.stdout.buffer.write(b"From: sender@example.org\\r\\nSubject: Test\\r\\n\\r\\nBody")
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable, calls


def _config(binary: Path, tmp_path: Path, *, max_bytes: int = 1000) -> WorkerConfig:
    return WorkerConfig(
        database=tmp_path / "events.sqlite3",
        himalaya_binary=str(binary),
        himalaya_config=tmp_path / "himalaya.toml",
        dry_run=True,
        command_timeout_seconds=5,
        max_message_bytes=max_bytes,
        max_attempts=3,
        retry_base_seconds=1,
        stale_after_seconds=300,
        poll_seconds=1,
    )


def test_adapter_uses_argv_without_shell_and_parses_status(tmp_path: Path) -> None:
    binary, calls_path = _fake_himalaya(tmp_path)
    client = HimalayaClient(_config(binary, tmp_path))

    assert client.check_version() == "himalaya 2.1.0"
    assert client.uid_validity("work", "INBOX") == "808"
    assert client.search_uids("work", "INBOX") == ("7", "9")
    assert b"Subject: Test" in client.read_raw("work", "INBOX", "7")
    client.move("work", "INBOX", "Archive/Orders", "7")

    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    assert calls[1] == [
        f"--config={tmp_path / 'himalaya.toml'}",
        "--account=work",
        "--json",
        "imap",
        "status",
        "INBOX",
    ]
    assert calls[2] == [
        f"--config={tmp_path / 'himalaya.toml'}",
        "--account=work",
        "--json",
        "imap",
        "search",
        "--mailbox=INBOX",
    ]
    assert "--backend=imap" in calls[3]
    assert calls[4][-6:] == [
        "--backend=imap",
        "message",
        "move",
        "7",
        "--from=INBOX",
        "--to=Archive/Orders",
    ]


def test_adapter_enforces_message_size_limit(tmp_path: Path) -> None:
    binary, _ = _fake_himalaya(tmp_path)
    client = HimalayaClient(_config(binary, tmp_path, max_bytes=10))

    with pytest.raises(MessageTooLargeError):
        client.read_raw("work", "INBOX", "7")


def test_search_rejects_non_uid_mode_and_excessive_result_count(tmp_path: Path) -> None:
    executable = tmp_path / "fake-himalaya"
    executable.write_text(
        f"""#!{sys.executable}
import json
print(json.dumps({{"uid_mode": False, "ids": [{{"id": 1}}]}}))
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    client = HimalayaClient(_config(executable, tmp_path))

    with pytest.raises(RuntimeError, match="UID-mode"):
        client.search_uids("work", "INBOX")

    executable.write_text(
        f"""#!{sys.executable}
import json
print(json.dumps({{"uid_mode": True, "ids": [{{"id": 1}}, {{"id": 2}}]}}))
""",
        encoding="utf-8",
    )
    config = replace(_config(executable, tmp_path), reconcile_max_messages=1)

    with pytest.raises(RuntimeError, match="message limit"):
        HimalayaClient(config).search_uids("work", "INBOX")


def test_search_enforces_separate_response_byte_limit(tmp_path: Path) -> None:
    executable = tmp_path / "fake-himalaya"
    executable.write_text(
        f"""#!{sys.executable}
print("x" * 2000)
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    config = replace(_config(executable, tmp_path), reconcile_max_response_bytes=1024)

    with pytest.raises(MessageTooLargeError, match="1024 bytes"):
        HimalayaClient(config).search_uids("work", "INBOX")
