"""Tests for the UsageLogger utility."""

import json
from pathlib import Path

from nanobot.utils.usage_logger import UsageLogger


def test_log_creates_file_and_writes_jsonl(tmp_path: Path) -> None:
    """A single log() call should create usage.jsonl with one valid record."""
    logger = UsageLogger(tmp_path)
    usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

    logger.log(model="test/model", usage=usage, session_id="cli:direct")

    log_file = tmp_path / "logs" / "usage.jsonl"
    assert log_file.exists()

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["model"] == "test/model"
    assert record["prompt_tokens"] == 100
    assert record["completion_tokens"] == 50
    assert record["total_tokens"] == 150
    assert record["session_id"] == "cli:direct"
    assert "timestamp" in record


def test_log_appends_multiple_entries(tmp_path: Path) -> None:
    """Multiple log() calls should produce multiple JSONL lines."""
    logger = UsageLogger(tmp_path)
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    logger.log(model="m1", usage=usage)
    logger.log(model="m2", usage=usage)
    logger.log(model="m3", usage=usage)

    log_file = tmp_path / "logs" / "usage.jsonl"
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 3

    models = [json.loads(line)["model"] for line in lines]
    assert models == ["m1", "m2", "m3"]


def test_log_skips_empty_usage(tmp_path: Path) -> None:
    """Empty usage dict should be a no-op — no file writes."""
    logger = UsageLogger(tmp_path)

    logger.log(model="test/model", usage={})

    log_file = tmp_path / "logs" / "usage.jsonl"
    assert not log_file.exists()


def test_log_directory_created_on_init(tmp_path: Path) -> None:
    """UsageLogger should create the logs/ directory on init."""
    logs_dir = tmp_path / "logs"
    assert not logs_dir.exists()

    UsageLogger(tmp_path)

    assert logs_dir.is_dir()


def test_log_optional_fields_omitted_when_none(tmp_path: Path) -> None:
    """session_id and provider should be absent when not provided."""
    logger = UsageLogger(tmp_path)
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

    logger.log(model="x", usage=usage)

    log_file = tmp_path / "logs" / "usage.jsonl"
    record = json.loads(log_file.read_text().strip())
    assert "session_id" not in record
    assert "provider" not in record


def test_log_includes_provider_when_set(tmp_path: Path) -> None:
    """Provider field should appear when explicitly passed."""
    logger = UsageLogger(tmp_path)
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

    logger.log(model="x", usage=usage, provider="openrouter")

    log_file = tmp_path / "logs" / "usage.jsonl"
    record = json.loads(log_file.read_text().strip())
    assert record["provider"] == "openrouter"
