"""Scheduled replies and explicit sends share the normal agent delivery path."""

import json
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config
from nanobot.cron.binding import CronBinding, binding_revision
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.session_turns import CRON_TRIGGER_META
from nanobot.cron.types import CronSchedule
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["reply", "legacy_message", "broadcast"])
async def test_moved_cron_keeps_reply_send_and_prompt_prefix_contract(tmp_path, monkeypatch, delivery):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace)
    bus = MessageBus()
    cron = CronService(tmp_path / "cron" / "jobs.json")
    attachment = workspace / "report.txt"
    attachment.write_text("Report attachment", encoding="utf-8")
    instructions = {
        "reply": "Remind me to drink water",
        "legacy_message": "Use message to send the reminder to the current chat",
        "broadcast": "Use message to send the report to telegram:extra and feishu:team with report.txt",
    }
    job = cron.add_job(
        "Reminder", CronSchedule(kind="every", every_ms=86400000), instructions[delivery],
        session_key="telegram:old", origin_channel="telegram", origin_chat_id="old",
    )
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (100, "test")
    requests = []
    runs = set()

    async def reply(**kwargs):
        ctx = current_request_context()
        assert ctx is not None
        trigger = ctx.metadata.get(CRON_TRIGGER_META)
        # Serialize at the provider boundary, before the runner appends tool results.
        requests.append(json.loads(json.dumps({
            "tools": kwargs["tools"], "messages": kwargs["messages"],
            "run": trigger["run_id"] if trigger else None,
        })))
        if trigger is None:
            return LLMResponse(content="Ready")
        run_id = trigger["run_id"]
        if run_id not in runs:
            runs.add(run_id)
            if delivery == "legacy_message":
                calls = [ToolCallRequest(id="reminder", name="message", arguments={
                    "content": "Drink water", "channel": "telegram", "chat_id": "new",
                })]
            elif delivery == "broadcast":
                calls = [ToolCallRequest(id=f"send-{index}", name="message", arguments={
                    "content": "Extra report", "channel": channel, "chat_id": chat,
                    "media": [str(attachment)],
                }) for index, (channel, chat) in enumerate([
                    ("telegram", "extra"), ("feishu", "team"),
                ])]
            else:
                calls = []
            if calls:
                return LLMResponse(content=None, tool_calls=calls, finish_reason="tool_calls")
        return LLMResponse(content="Drink water")

    provider.chat_stream_with_retry = reply
    agent = AgentLoop(bus=bus, provider=provider, workspace=workspace, model="test-model",
        session_manager=sessions, tools_config=Config().tools, cron_service=cron)
    await cron.start()
    try:
        await agent.process_direct("Prepare for the reminder", session_key="telegram:new",
                                   channel="telegram", chat_id="new")
        moved = cron.change_binding(job.id, revision=binding_revision(job),
            binding=CronBinding("telegram:new", "telegram", "new", {"message_thread_id": 42}),
            message=job.payload.message)
        assert moved.payload.message == instructions[delivery]
        for _ in range(2):
            while bus.outbound_size:
                await bus.consume_outbound()
            await run_bound_cron_job(moved, agent=agent, cron=cron)
            outbound = []
            while bus.outbound_size:
                message = await bus.consume_outbound()
                if message.event is None and message.content:
                    outbound.append(message)
            normal = [m for m in outbound if (m.channel, m.chat_id) == ("telegram", "new")]
            # Normal backend replies and legacy same-chat sends each arrive once.
            assert [m.content for m in normal] == ["Drink water"]
            assert normal[0].metadata["message_thread_id"] == 42
            extra = [m for m in outbound if m not in normal]
            assert [(m.channel, m.chat_id) for m in extra] == (
                [("telegram", "extra"), ("feishu", "team")] if delivery == "broadcast" else []
            )
            assert all(m.media == [str(attachment)] for m in extra)
            assert all("message_thread_id" not in m.metadata for m in extra)

        # Ordinary turns, separate cron runs and tool continuations use the same
        # system/tools prefix. Per-run instructions and runtime data stay at the end.
        def stable(row):
            return json.dumps([row["tools"], row["messages"][0]], ensure_ascii=False)

        assert all(stable(row) == stable(requests[0]) for row in requests)
        assert len(runs) == 2
        for run_id in runs:
            turn = [row for row in requests if row["run"] == run_id]
            assert turn[0]["messages"][-1]["role"] == "user"
            assert instructions[delivery] in turn[0]["messages"][-1]["content"]
            if len(turn) > 1:
                original = turn[0]["messages"]
                assert turn[1]["messages"][:len(original)] == original
                appended = turn[1]["messages"][len(original):]
                assert appended[0]["role"] == "assistant"
                assert appended[0]["tool_calls"]
                assert all(row["role"] == "tool" for row in appended[1:])
        assert sessions.read_session_file("telegram:old") is None
        history = sessions.read_session_file("telegram:new")
        assert "Drink water" in json.dumps(history)
    finally:
        cron.stop()
        await agent.aclose()
