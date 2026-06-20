from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.service import CronService
from nanobot.cron.session_turns import CRON_TRIGGER_META


def test_agent_loop_registers_cron_tool_with_configured_timezone(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=CronService(tmp_path / "cron" / "jobs.json"),
        timezone="Asia/Shanghai",
    )

    cron_tool = loop.tools.get("cron")

    assert isinstance(cron_tool, CronTool)
    assert cron_tool._default_timezone == "Asia/Shanghai"


def test_agent_loop_reads_cron_model_preset_metadata() -> None:
    assert AgentLoop._message_model_preset_override({"model_preset": " fast "}) is None
    assert (
        AgentLoop._message_model_preset_override({
            "model_preset": " fast ",
            CRON_TRIGGER_META: {"job_id": "job-1"},
        })
        == "fast"
    )
    assert (
        AgentLoop._message_model_preset_override({CRON_TRIGGER_META: {"modelPreset": "deep"}})
        == "deep"
    )


@pytest.mark.asyncio
async def test_agent_loop_ignores_missing_cron_model_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    seen = {}

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    async def _capture_process_message(*_args, **kwargs):
        seen["provider_override"] = kwargs["provider_override"]
        seen["model_override"] = kwargs["model_override"]
        seen["context_window_tokens_override"] = kwargs["context_window_tokens_override"]
        return OutboundMessage(channel="cli", chat_id="cron", content="ok")

    monkeypatch.setattr(loop, "_process_message", _capture_process_message)

    await loop._dispatch(
        InboundMessage(
            channel="cli",
            sender_id="cron",
            chat_id="cron",
            content="scheduled",
            metadata={CRON_TRIGGER_META: {"job_id": "job-1", "model_preset": "deleted"}},
        )
    )

    assert seen == {
        "provider_override": None,
        "model_override": None,
        "context_window_tokens_override": None,
    }


@pytest.mark.asyncio
async def test_agent_loop_run_override_does_not_mutate_default_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    override_provider = MagicMock()
    seen = {}

    class CaptureRunner:
        def __init__(self, provider_arg):
            seen["provider"] = provider_arg

        async def run(self, spec):
            seen["model"] = spec.model
            seen["context_window_tokens"] = spec.context_window_tokens
            return AgentRunResult(final_content="ok", messages=[], stop_reason="completed")

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    monkeypatch.setattr("nanobot.agent.loop.AgentRunner", CaptureRunner)
    session = loop.sessions.get_or_create("test:cron")

    await loop._run_agent_loop(
        [{"role": "user", "content": "cron"}],
        session=session,
        provider_override=override_provider,
        model_override="fast-model",
        context_window_tokens_override=12_345,
    )

    assert seen == {
        "provider": override_provider,
        "model": "fast-model",
        "context_window_tokens": 12_345,
    }
    assert loop.provider is provider
    assert loop.model == "test-model"
