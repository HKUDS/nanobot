"""Tests for SubagentManager."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager, SubagentStatus
from nanobot.agent.tools.filesystem import FileToolsConfig
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.security.workspace_access import build_workspace_scope
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(provider: LLMProvider) -> LLMRuntime:
    provider.generation = GenerationSettings()
    return LLMRuntime.capture(provider, "test", context_window_tokens=128_000)


@pytest.mark.asyncio
async def test_subagent_uses_tool_loader():
    """Verify subagent registers tools via ToolLoader, not hard-coded imports."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=Path("/tmp"),
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )
    tools = sm._build_tools()
    assert tools.has("read_file")
    assert tools.has("write_file")
    assert not tools.has("message")
    assert not tools.has("spawn")


@pytest.mark.asyncio
async def test_subagent_build_tools_isolates_file_read_state(tmp_path):
    """Each spawned subagent needs a fresh file-state cache."""
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )

    first_read = sm._build_tools().get("read_file")
    second_read = sm._build_tools().get("read_file")

    assert first_read is not second_read
    assert (await first_read.execute(path="note.txt")).startswith("1| hello")
    second_result = await second_read.execute(path="note.txt")
    assert second_result.startswith("1| hello")
    assert "File unchanged" not in second_result


def test_subagent_respects_file_tool_toggle(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
        tools_config=ToolsConfig(file=FileToolsConfig(enable=False)),
    )

    tools = sm._build_tools()

    file_tools = {
        "apply_patch",
        "edit_file",
        "find_files",
        "grep",
        "list_dir",
        "read_file",
        "write_file",
    }
    assert file_tools.isdisjoint(tools.tool_names)


def test_subagent_prompt_keeps_agent_paths_for_selected_project(tmp_path):
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    global_skill = agent_workspace / "skills" / "global-custom" / "SKILL.md"
    project_skill = project / "skills" / "project-custom" / "SKILL.md"
    global_skill.parent.mkdir(parents=True)
    project_skill.parent.mkdir(parents=True)
    global_skill.write_text("---\ndescription: global skill\n---\nGlobal", encoding="utf-8")
    project_skill.write_text("---\ndescription: project skill\n---\nProject", encoding="utf-8")
    manager = SubagentManager(
        workspace=agent_workspace,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )

    prompt = manager._build_subagent_prompt(workspace=project)

    assert "one root and relative SKILL.md paths" in prompt
    assert "Join them when using `read_file`" in prompt
    assert str(project.resolve()) not in prompt
    assert f"Nanobot's agent workspace: {agent_workspace.resolve()}" in prompt
    assert f"History log: {agent_workspace.resolve() / 'memory' / 'history.jsonl'}" in prompt
    assert "global-custom" in prompt
    assert "project-custom" not in prompt


def test_subagent_prompt_uses_relative_paths_in_agent_workspace(tmp_path):
    skill = tmp_path / "skills" / "custom" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\ndescription: custom skill\n---\nCustom", encoding="utf-8")
    manager = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )

    prompt = manager._build_subagent_prompt()

    assert str(tmp_path.resolve()) not in prompt
    assert "History log: memory/history.jsonl" in prompt
    assert "### Workspace skills (`skills`)" in prompt


@pytest.mark.asyncio
async def test_subagent_keeps_project_runtime_scope_with_agent_owned_tools(tmp_path):
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    agent_workspace.mkdir()
    project.mkdir()
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    manager = SubagentManager(
        workspace=agent_workspace,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )
    manager.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    manager._announce_result = AsyncMock()
    status = SubagentStatus(
        task_id="t1",
        label="label",
        task_description="task",
        started_at=0.0,
    )

    await manager._run_subagent(
        "t1",
        "task",
        "label",
        {"channel": "websocket", "chat_id": "direct"},
        status,
        _runtime(provider),
        workspace_scope=build_workspace_scope(project, "restricted"),
    )

    spec = manager.runner.run.call_args.args[0]
    assert spec.workspace == project
    assert spec.tools.get("read_file")._workspace == agent_workspace.resolve()


@pytest.mark.asyncio
async def test_subagent_forwards_fail_on_tool_error_to_runner(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
        fail_on_tool_error=False,
    )
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    status = SubagentStatus(
        task_id="t1",
        label="label",
        task_description="task",
        started_at=0.0,
    )

    await sm._run_subagent(
        "t1",
        "task",
        "label",
        {"channel": "cli", "chat_id": "direct"},
        status,
        _runtime(provider),
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.fail_on_tool_error is False


# ---------------------------------------------------------------------------
# Durable transcript persistence (issue #1363)
# ---------------------------------------------------------------------------


def _subagent_manager(tmp_path: Path, bus: MessageBus | None = None) -> SubagentManager:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    return SubagentManager(
        workspace=tmp_path,
        bus=bus or MessageBus(),
        max_tool_result_chars=16_000,
    )


def _runner_completes(result: AgentRunResult):
    """Mock ``runner.run`` the way the real runner behaves: it invokes the
    hook's ``on_finally`` with the end-of-run messages on every exit path.
    """
    from nanobot.agent.hook import AgentRunHookContext
    from nanobot.agent.runner import AgentRunSpec

    async def _run(spec: AgentRunSpec) -> AgentRunResult:
        await spec.hook.on_finally(
            AgentRunHookContext(messages=result.messages, stop_reason=result.stop_reason)
        )
        return result

    return _run


def _full_messages() -> list[dict]:
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "[]"},
        {"role": "assistant", "content": "done"},
    ]


@pytest.mark.asyncio
async def test_subagent_success_persists_transcript(tmp_path):
    """Success path writes a transcript with system/user/assistant+tool/tool rows."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(
        side_effect=_runner_completes(
            AgentRunResult(
                final_content="done",
                messages=_full_messages(),
                stop_reason="completed",
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        )
    )
    sm._announce_result = AsyncMock()
    status = SubagentStatus(task_id="t1", label="label", task_description="task", started_at=0.0)

    await sm._run_subagent(
        "t1", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
    )

    path = tmp_path / "memory" / "subagents" / "t1.jsonl"
    assert path.exists()
    records = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    import json

    parsed = [json.loads(line) for line in records]
    assert [r["role"] for r in parsed if "role" in r] == ["system", "user", "assistant", "tool", "assistant"]
    assert parsed[-1]["_transcript_meta"]["stop_reason"] == "completed"
    assert parsed[-1]["_transcript_meta"]["usage"]["prompt_tokens"] == 10


@pytest.mark.asyncio
async def test_subagent_tool_error_persists_transcript(tmp_path):
    """tool_error stop reason still persists the partial exchange."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(
        side_effect=_runner_completes(
            AgentRunResult(
                final_content=None,
                messages=_full_messages(),
                stop_reason="tool_error",
                tool_events=[{"name": "list_dir", "detail": "boom", "status": "error"}],
            )
        )
    )
    sm._announce_result = AsyncMock()
    status = SubagentStatus(task_id="t2", label="label", task_description="task", started_at=0.0)

    await sm._run_subagent(
        "t2", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
    )

    path = tmp_path / "memory" / "subagents" / "t2.jsonl"
    assert path.exists()
    assert status.phase == "done"
    assert status.stop_reason == "tool_error"


@pytest.mark.asyncio
async def test_subagent_max_iterations_persists_transcript(tmp_path):
    """max_iterations stop reason persists with stop_reason/usage metadata."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(
        side_effect=_runner_completes(
            AgentRunResult(
                final_content=None,
                messages=_full_messages(),
                stop_reason="max_iterations",
                usage={"prompt_tokens": 3},
            )
        )
    )
    sm._announce_result = AsyncMock()
    status = SubagentStatus(task_id="t3", label="label", task_description="task", started_at=0.0)

    await sm._run_subagent(
        "t3", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
    )

    import json

    path = tmp_path / "memory" / "subagents" / "t3.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[-1]["_transcript_meta"]["stop_reason"] == "max_iterations"
    assert records[-1]["_transcript_meta"]["usage"]["prompt_tokens"] == 3


@pytest.mark.asyncio
async def test_subagent_provider_error_persists_partial(tmp_path):
    """A provider exception persists a partial transcript with the error recorded."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(side_effect=ValueError("boom"))
    sm._announce_result = AsyncMock()
    status = SubagentStatus(task_id="t4", label="label", task_description="task", started_at=0.0)

    result = await sm._run_subagent(
        "t4", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
    )

    assert result == "Error: boom"
    assert status.phase == "error"
    import json

    path = tmp_path / "memory" / "subagents" / "t4.jsonl"
    assert path.exists()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[-1]["_transcript_meta"]["stop_reason"] == "error"
    assert "boom" in records[-1]["_transcript_meta"]["error"]


@pytest.mark.asyncio
async def test_subagent_cancellation_flushes_partial_transcript(tmp_path):
    """A cancelled task flushes the hook's last partial snapshot with the cancel reason."""
    from nanobot.agent.hook import AgentHookContext, AgentRunHookContext
    from nanobot.agent.runner import AgentRunSpec

    sm = _subagent_manager(tmp_path)
    partial = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "partial"}]

    async def _cancel_after_hook_capture(spec: AgentRunSpec) -> AgentRunResult:
        hook = spec.hook
        await hook.after_iteration(
            AgentHookContext(iteration=1, messages=list(partial), usage={"prompt_tokens": 2})
        )
        await hook.on_finally(AgentRunHookContext(messages=list(partial)))
        raise asyncio.CancelledError

    sm.runner.run = AsyncMock(side_effect=_cancel_after_hook_capture)
    sm._announce_result = AsyncMock()
    status = SubagentStatus(task_id="t5", label="label", task_description="task", started_at=0.0)

    with pytest.raises(asyncio.CancelledError):
        await sm._run_subagent(
            "t5", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
        )

    import json

    path = tmp_path / "memory" / "subagents" / "t5.jsonl"
    assert path.exists()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [r["content"] for r in records[:-1]] == ["task", "partial"]
    assert records[-1]["_transcript_meta"]["stop_reason"] == "cancelled"


@pytest.mark.asyncio
async def test_subagent_write_failure_does_not_change_outcome(tmp_path, monkeypatch):
    """A transcript write failure logs and continues; the announced outcome is unchanged."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=_full_messages(), stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    def _explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sm.transcripts, "write", _explode)
    status = SubagentStatus(task_id="t6", label="label", task_description="task", started_at=0.0)

    result = await sm._run_subagent(
        "t6", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
    )

    assert result == "ok"
    sm._announce_result.assert_awaited_once()
    # A failed persistence never advertises a transcript path (finding #8).
    assert sm._announce_result.call_args.kwargs.get("transcript_path") is None
    assert status.phase == "done"


@pytest.mark.asyncio
async def test_subagent_announce_failure_does_not_relabel_transcript(tmp_path):
    """An announce failure after a successful run never re-persists the
    transcript as error/cancelled (finding #9: persist-once)."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(
        side_effect=_runner_completes(
            AgentRunResult(final_content="ok", messages=_full_messages(), stop_reason="completed")
        )
    )
    sm._announce_result = AsyncMock(side_effect=RuntimeError("bus down"))
    status = SubagentStatus(task_id="t9", label="label", task_description="task", started_at=0.0)

    with pytest.raises(RuntimeError):
        await sm._run_subagent(
            "t9", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
        )

    import json

    path = tmp_path / "memory" / "subagents" / "t9.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[-1]["_transcript_meta"]["stop_reason"] == "completed"


@pytest.mark.asyncio
async def test_subagent_announce_metadata_carries_transcript_path(tmp_path):
    """Announce metadata carries transcript_path and subagent_task_id."""
    bus = MessageBus()
    sm = _subagent_manager(tmp_path, bus=bus)
    await sm._announce_result(
        "t7",
        "label",
        "task",
        "result",
        {"channel": "cli", "chat_id": "direct"},
        "ok",
        transcript_path="memory/subagents/t7.jsonl",
    )
    msg = bus.inbound.get_nowait()
    assert msg.metadata["subagent_task_id"] == "t7"
    assert msg.metadata["transcript_path"] == "memory/subagents/t7.jsonl"


@pytest.mark.asyncio
async def test_subagent_transcripts_isolated_from_main_history(tmp_path):
    """Transcripts never enter memory/history.jsonl or any session store."""
    sm = _subagent_manager(tmp_path)
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="done", messages=_full_messages(), stop_reason="completed")
    )
    sm._announce_result = AsyncMock()
    status = SubagentStatus(task_id="t8", label="label", task_description="task", started_at=0.0)

    await sm._run_subagent(
        "t8", "task", "label", {"channel": "cli", "chat_id": "direct"}, status, _runtime(MagicMock(spec=LLMProvider))
    )

    assert not (tmp_path / "memory" / "history.jsonl").exists()
    assert (tmp_path / "memory" / "subagents" / "t8.jsonl").exists()
    # No session files are created by a subagent run.
    assert not list(tmp_path.glob("sessions/*"))
