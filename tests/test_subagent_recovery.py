"""Tests for subagent checkpoint-based error recovery.

Validates that subagents can save checkpoints during execution and
resume from them after failure, avoiding full replay.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.checkpoint import CheckpointStore
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class ScriptedProvider(LLMProvider):
    """Provider that returns scripted responses, optionally raising on specific calls."""

    def __init__(self, responses: list[LLMResponse | Exception]):
        super().__init__()
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        if self._responses:
            resp = self._responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return LLMResponse(content="done", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


def _tool_response(tool_name: str = "list_dir", call_id: str = "c1") -> LLMResponse:
    """Create a response with a single tool call."""
    return LLMResponse(
        content="calling tool",
        tool_calls=[ToolCallRequest(id=call_id, name=tool_name, arguments={})],
    )


def _final_response(content: str = "task done") -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


class TestCheckpointSavedDuringExecution:
    """Verify checkpoints are saved after each tool execution."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_after_tool_call(self, tmp_path: Path, monkeypatch) -> None:
        """After a tool call, a checkpoint should be saved."""
        provider = ScriptedProvider(
            [
                _tool_response("list_dir", "c1"),
                _final_response("done"),
            ]
        )
        bus = MessageBus()

        async def fake_execute(self, name, args):
            return "file1.txt"

        monkeypatch.setattr(
            "nanobot.agent.tools.registry.ToolRegistry.execute",
            fake_execute,
        )

        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)
        await mgr._run_subagent("test-1", "list files", "list", {"channel": "cli", "chat_id": "d"})

        # Checkpoint should be cleaned up after success
        assert not mgr.checkpoints.has_checkpoint("test-1")

    @pytest.mark.asyncio
    async def test_checkpoint_persists_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        """When a tool call raises, the checkpoint from before the failure should exist."""
        call_count = {"n": 0}

        async def failing_execute(self, name, args):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "success result"
            raise RuntimeError("Tool crashed")

        monkeypatch.setattr(
            "nanobot.agent.tools.registry.ToolRegistry.execute",
            failing_execute,
        )

        provider = ScriptedProvider(
            [
                _tool_response("web_search", "c1"),  # iteration 1 - succeeds
                _tool_response("web_fetch", "c2"),  # iteration 2 - tool will fail
            ]
        )
        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        await mgr._run_subagent(
            "fail-1", "search and fetch", "search", {"channel": "t", "chat_id": "c"}
        )

        # Checkpoint should exist from the successful first iteration
        assert mgr.checkpoints.has_checkpoint("fail-1")
        checkpoint = mgr.checkpoints.load("fail-1")
        assert checkpoint is not None
        assert checkpoint.iteration == 1
        assert "web_search" in checkpoint.completed_tools

    @pytest.mark.asyncio
    async def test_error_message_includes_resume_hint(self, tmp_path: Path, monkeypatch) -> None:
        """Error announcement should include the resume command hint."""

        async def failing_execute(self, name, args):
            raise RuntimeError("Connection timeout")

        monkeypatch.setattr(
            "nanobot.agent.tools.registry.ToolRegistry.execute",
            failing_execute,
        )

        provider = ScriptedProvider([_tool_response("web_search", "c1")])
        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        await mgr._run_subagent("err-1", "search", "search", {"channel": "t", "chat_id": "c"})

        # Read the announced message
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
        assert 'resume="err-1"' in msg.content
        assert "failed" in msg.content


class TestResumeFromCheckpoint:
    """Verify subagents can resume from saved checkpoints."""

    @pytest.mark.asyncio
    async def test_resume_restores_state(self, tmp_path: Path, monkeypatch) -> None:
        """Resuming should start from the checkpoint's message history."""
        from nanobot.agent.checkpoint import CheckpointState

        # Pre-seed a checkpoint
        store = CheckpointStore(tmp_path)
        store.save(
            CheckpointState(
                task_id="resume-1",
                iteration=3,
                messages=[
                    {"role": "system", "content": "You are a subagent."},
                    {"role": "user", "content": "do task"},
                    {"role": "assistant", "content": "calling tool", "tool_calls": []},
                    {
                        "role": "tool",
                        "tool_call_id": "c1",
                        "name": "web_search",
                        "content": "results",
                    },
                ],
                task="do task",
                label="task label",
                origin={"channel": "t", "chat_id": "c"},
                completed_tools=["web_search"],
            )
        )

        captured_messages: list[list] = []

        async def tracking_chat(*, messages, **kwargs):
            captured_messages.append(list(messages))
            return _final_response("resumed and done")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = tracking_chat

        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        await mgr._run_subagent(
            "resume-1", "do task", "task label", {"channel": "t", "chat_id": "c"}
        )

        # The LLM should have received the checkpoint's messages (4 messages),
        # not fresh system+user (2 messages)
        assert len(captured_messages) == 1
        assert len(captured_messages[0]) == 4  # system + user + assistant + tool

    @pytest.mark.asyncio
    async def test_resume_continues_iteration_count(self, tmp_path: Path, monkeypatch) -> None:
        """Resumed subagent should continue counting from checkpoint iteration."""
        from nanobot.agent.checkpoint import CheckpointState

        store = CheckpointStore(tmp_path)
        store.save(
            CheckpointState(
                task_id="iter-1",
                iteration=10,
                messages=[
                    {"role": "system", "content": "subagent"},
                    {"role": "user", "content": "task"},
                ],
                task="task",
                label="label",
                origin={"channel": "c", "chat_id": "d"},
                completed_tools=["web_search"] * 10,
            )
        )

        call_count = {"n": 0}

        async def counting_chat(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 4:
                return _tool_response("list_dir", f"c{call_count['n']}")
            return _final_response("done")

        async def fake_execute(self, name, args):
            return "result"

        monkeypatch.setattr(
            "nanobot.agent.tools.registry.ToolRegistry.execute",
            fake_execute,
        )

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = counting_chat

        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        await mgr._run_subagent("iter-1", "task", "label", {"channel": "c", "chat_id": "d"})

        # Should have completed (iteration 10 + up to 5 more = 15 max)
        assert call_count["n"] == 5

    @pytest.mark.asyncio
    async def test_checkpoint_cleaned_up_after_successful_resume(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """After a resumed task completes successfully, checkpoint should be deleted."""
        from nanobot.agent.checkpoint import CheckpointState

        store = CheckpointStore(tmp_path)
        store.save(
            CheckpointState(
                task_id="clean-1",
                iteration=2,
                messages=[
                    {"role": "system", "content": "subagent"},
                    {"role": "user", "content": "task"},
                ],
                task="task",
                label="label",
                origin={"channel": "c", "chat_id": "d"},
            )
        )

        async def fake_chat(**kw):
            return _final_response("done")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = fake_chat

        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        await mgr._run_subagent("clean-1", "task", "label", {"channel": "c", "chat_id": "d"})

        assert not store.has_checkpoint("clean-1")


class TestSpawnWithResume:
    """Test the spawn() method's resume parameter."""

    @pytest.mark.asyncio
    async def test_spawn_resume_uses_existing_task_id(self, tmp_path: Path, monkeypatch) -> None:
        """When resuming, the task ID should match the checkpoint's task ID."""
        from nanobot.agent.checkpoint import CheckpointState

        store = CheckpointStore(tmp_path)
        store.save(
            CheckpointState(
                task_id="orig-id",
                iteration=1,
                messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "t"}],
                task="original task",
                label="orig label",
                origin={"channel": "cli", "chat_id": "direct"},
            )
        )

        async def fake_chat(**kw):
            return _final_response("done")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = fake_chat

        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        result = await mgr.spawn(task="original task", resume="orig-id")
        assert "orig-id" in result
        assert "orig label" in result

        # Wait for background task
        await asyncio.sleep(0.1)
        for task in list(mgr._running_tasks.values()):
            if not task.done():
                await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_spawn_resume_nonexistent_creates_new(self, tmp_path: Path, monkeypatch) -> None:
        """Resuming a nonexistent checkpoint should create a new task."""

        async def fake_chat(**kw):
            return _final_response("done")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = fake_chat

        bus = MessageBus()
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        result = await mgr.spawn(task="new task", resume="nonexistent-id")
        # Should get a new task ID, not "nonexistent-id"
        assert "nonexistent-id" not in result
        assert "started" in result

        await asyncio.sleep(0.1)
        for task in list(mgr._running_tasks.values()):
            if not task.done():
                await asyncio.wait_for(task, timeout=2.0)
