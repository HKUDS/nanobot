"""Tests for the UsageLogger utility."""

import json
from pathlib import Path

import pytest

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


def test_log_directory_created_lazily(tmp_path: Path) -> None:
    """UsageLogger should NOT create the logs/ directory on init (lazy creation)."""
    logs_dir = tmp_path / "logs"
    assert not logs_dir.exists()

    logger = UsageLogger(tmp_path)
    assert not logs_dir.exists()  # dir not created yet

    logger.log(model="x", usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
    assert logs_dir.is_dir()  # created on first write


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




@pytest.mark.asyncio
async def test_integration_agent_loop_logs_usage(tmp_path: Path) -> None:
    """Integration: AgentLoop should log usage after each LLM call."""
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMResponse

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="hello",
        tool_calls=[],
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    ))

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
    )

    messages = [{"role": "user", "content": "hi"}]
    final, tools_used, _ = await loop._run_agent_loop(
        messages, session_key="test:session"
    )

    assert final == "hello"
    log_file = tmp_path / "logs" / "usage.jsonl"
    assert log_file.exists()

    record = json.loads(log_file.read_text().strip())
    assert record["model"] == "test-model"
    assert record["prompt_tokens"] == 100
    assert record["session_id"] == "test:session"
