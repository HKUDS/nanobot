"""Contract and security regressions for the MyTool runtime boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.runtime_control import (
    RUNTIME_COMMAND_KEYS,
    RUNTIME_SNAPSHOT_KEYS,
    AgentRuntimeControl,
    RuntimeControl,
)
from nanobot.agent.tools.self import MyTool, MyToolConfig
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.security.workspace_access import (
    bind_workspace_scope,
    build_workspace_scope,
    reset_workspace_scope,
)
from nanobot.utils.llm_runtime import LLMRuntime


def _make_loop(
    tmp_path: Path, *, allow_set: bool = False, restricted: bool = False, sandbox: str = "",
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    tools_config = ToolsConfig(
        my=MyToolConfig(allow_set=allow_set), restrict_to_workspace=restricted,
    )
    tools_config.exec.sandbox = sandbox
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        tools_config=tools_config,
        restrict_to_workspace=restricted,
    )


def _my_tool(loop: AgentLoop) -> MyTool:
    tool = loop.tools.get("my")
    assert isinstance(tool, MyTool)
    return tool


def test_agent_loop_assembles_my_tool_with_runtime_control(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    tool = _my_tool(loop)

    assert isinstance(tool._runtime_control, RuntimeControl)
    assert isinstance(tool._runtime_control, AgentRuntimeControl)
    assert tool._runtime_control is not loop


def test_runtime_snapshot_has_exact_allowlist_and_redacts_secrets(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.web_config.search.api_key = "search-secret"
    loop.web_config.proxy = "http://proxy-user:proxy-secret@proxy.example"
    loop.unlisted_secret = "loop-secret"

    snapshot = _my_tool(loop)._runtime_control.snapshot()
    values = snapshot.as_mapping()

    expected_snapshot_keys = frozenset({
        "model",
        "model_preset",
        "model_presets",
        "max_iterations",
        "context_window_tokens",
        "workspace",
        "workspace_sandbox",
        "provider_retry_mode",
        "max_tool_result_chars",
        "tool_names",
        "web_config",
        "exec_config",
    })
    assert RUNTIME_SNAPSHOT_KEYS == expected_snapshot_keys
    assert frozenset(values) == expected_snapshot_keys
    assert RUNTIME_COMMAND_KEYS == frozenset({
        "model",
        "model_preset",
        "max_iterations",
        "context_window_tokens",
        "provider_retry_mode",
        "max_tool_result_chars",
        "workspace",
    })
    assert "provider" not in values
    assert "sessions" not in values
    assert "restrict_to_workspace" not in values
    assert "unlisted_secret" not in values
    rendered = repr(values)
    assert "search-secret" not in rendered
    assert "proxy-secret" not in rendered
    assert "loop-secret" not in rendered
    assert snapshot.web_config["proxy"] == "<configured>"


def test_runtime_snapshot_is_detached_from_mutable_config(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    control = _my_tool(loop)._runtime_control
    snapshot = control.snapshot()
    search = snapshot.web_config["search"]
    assert isinstance(search, dict)

    search["provider"] = "mutated"
    snapshot.exec_config["allow_patterns"] = ["mutated"]
    snapshot.tool_names.append("mutated")

    refreshed = control.snapshot()
    refreshed_search = refreshed.web_config["search"]
    assert isinstance(refreshed_search, dict)
    assert refreshed_search["provider"] == loop.web_config.search.provider
    assert refreshed.exec_config["allow_patterns"] == loop.exec_config.allow_patterns
    assert "mutated" not in refreshed.tool_names


@pytest.mark.asyncio
async def test_unlisted_loop_attributes_cannot_be_read_or_modified(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)
    loop.unlisted_control_plane = "internal-secret"
    original_workspace_root = loop.workspace_scopes.default_workspace
    tool = _my_tool(loop)

    inspected = await tool.execute(action="check", key="unlisted_control_plane")
    modified = await tool.execute(
        action="set",
        key="unlisted_control_plane",
        value="scratch-value",
    )
    nested = await tool.execute(
        action="set",
        key="workspace_scopes.default_workspace",
        value="elsewhere",
    )

    assert "internal-secret" not in inspected
    assert "not found" in inspected
    assert modified == "Set scratchpad.unlisted_control_plane = 'scratch-value'"
    assert loop.unlisted_control_plane == "internal-secret"
    assert "Error" in nested
    assert loop.workspace_scopes.default_workspace == original_workspace_root


@pytest.mark.asyncio
async def test_default_allow_set_and_public_parameter_schema_are_unchanged(
    tmp_path: Path,
) -> None:
    loop = _make_loop(tmp_path)
    tool = _my_tool(loop)

    assert ToolsConfig().my.allow_set is False
    assert tool.parameters == {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["check", "set"],
                "description": "Action to perform",
            },
            "key": {
                "type": "string",
                "description": (
                    "Dot-path for check/set. Examples: 'max_iterations', 'workspace', "
                    "'provider_retry_mode'. Use 'request.channel', 'request.chat_id', or "
                    "'request.sender_id' for current routing metadata. Use 'model_preset' "
                    "to switch named model presets. For check without key, shows all "
                    "config values."
                ),
            },
            "value": {
                "description": (
                    "New value (for set). Type must match target (int for "
                    "max_iterations/context_window_tokens, str for model/model_preset)."
                ),
            },
        },
        "required": ["action"],
    }
    assert "READ-ONLY MODE" in tool.description
    result = await tool.execute(action="set", key="max_iterations", value=80)
    assert result == "Error: set is disabled (tools.my.allow_set is false)"
    assert loop.max_iterations != 80


@pytest.mark.asyncio
async def test_allowlisted_commands_preserve_runtime_side_effects(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)
    tool = _my_tool(loop)

    max_iterations = await tool.execute(
        action="set",
        key="max_iterations",
        value=80,
    )
    retry_mode = await tool.execute(
        action="set",
        key="provider_retry_mode",
        value="persistent",
    )
    scratchpad = await tool.execute(
        action="set",
        key="preference",
        value={"concise": True},
    )

    assert max_iterations == "Set max_iterations = 80 (was 200)"
    assert retry_mode == "Set provider_retry_mode = 'persistent' (was 'standard')"
    assert scratchpad == "Set scratchpad.preference = {'concise': True}"
    assert loop.max_iterations == 80
    assert loop.subagents.max_iterations == 80
    assert loop.provider_retry_mode == "persistent"
    assert tool._runtime_control.snapshot().scratchpad == {
        "preference": {"concise": True},
    }


@pytest.mark.asyncio
async def test_registry_exposes_unchanged_my_tool_actions(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)

    checked = await loop.tools.execute("my", {"action": "check", "key": "model"})
    changed = await loop.tools.execute(
        "my",
        {"action": "set", "key": "max_iterations", "value": 80},
    )

    assert checked == "model: 'test-model'"
    assert changed == "Set max_iterations = 80 (was 200)"
    assert loop.max_iterations == 80


@pytest.mark.asyncio
async def test_workspace_display_command_cannot_change_path_enforcement(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)
    tool = _my_tool(loop)

    result = await tool.execute(action="set", key="workspace", value="elsewhere")

    assert "Set workspace" in result
    assert tool._runtime_control.snapshot().workspace == "elsewhere"
    assert loop.workspace == tmp_path
    assert loop.workspace_scopes.default_workspace == tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "sandbox", "restricted"), [
    ("restricted", "", True),
    ("full", "", False),
    ("full", "seatbelt", True),
])
async def test_workspace_inspection_matches_registered_file_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, sandbox: str, restricted: bool,
) -> None:
    # A configured shell backend is not proof that an external sandbox is running.
    monkeypatch.delenv("NANOBOT_WORKSPACE_SANDBOX_ENFORCED", raising=False)
    monkeypatch.delenv("NANOBOT_SANDBOX_ENFORCED", raising=False)
    agent = tmp_path / "agent"
    project = tmp_path / "project"
    project.mkdir()
    (project / "marker.txt").write_text("project marker", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside marker", encoding="utf-8")
    loop = _make_loop(agent, allow_set=True, restricted=True, sandbox=sandbox)
    tool = _my_tool(loop)
    definitions = json.dumps(loop.tools.get_definitions(), sort_keys=True)
    token = bind_workspace_scope(build_workspace_scope(project, mode))
    try:
        # Legacy display writes must not spoof the effective directory or permission.
        await tool.execute(action="set", key="workspace", value=str(outside.parent))
        status = tool._runtime_control.snapshot().workspace_sandbox
        assert status["workspace_root"] == str(project.resolve())
        assert status["restrict_to_workspace"] is restricted
        assert status["level"] == ("application" if restricted else "off")
        assert status["enforced"] is False
        assert repr(str(project.resolve())) in await tool.execute(action="check", key="workspace_sandbox")
        assert repr(str(project.resolve())) in await tool.execute(action="check")
        assert await tool.execute(action="check", key="workspace_sandbox.restrict_to_workspace") == (
            f"workspace_sandbox.restrict_to_workspace: {restricted!r}"
        )
        for key in ("workspace_sandbox", "workspace_sandbox.restrict_to_workspace"):
            assert "read-only" in await tool.execute(action="set", key=key, value=False)
        assert "not accessible" in await tool.execute(action="check", key="restrict_to_workspace")
        assert "project marker" in await loop.tools.execute("read_file", {"path": "marker.txt"})
        result = await loop.tools.execute("read_file", {"path": str(outside)})
        assert ("outside allowed directory" if restricted else "outside marker") in result
        # The directory and permission enter tool results, not the reusable tool schemas.
        assert json.dumps(loop.tools.get_definitions(), sort_keys=True) == definitions
        status["workspace_root"] = "changed snapshot"
        assert tool._runtime_control.snapshot().workspace_sandbox["workspace_root"] == str(project.resolve())
    finally:
        reset_workspace_scope(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("restricted", [False, True])
async def test_workspace_inspection_uses_instance_default_without_turn(
    tmp_path: Path, restricted: bool,
) -> None:
    loop = _make_loop(tmp_path, restricted=restricted)
    status = _my_tool(loop)._runtime_control.snapshot().workspace_sandbox
    assert status["workspace_root"] == str(tmp_path.resolve())
    assert status["restrict_to_workspace"] is restricted


@pytest.mark.asyncio
async def test_workspace_inspection_is_isolated_between_concurrent_turns(tmp_path: Path) -> None:
    tool = _my_tool(_make_loop(tmp_path))
    ready = asyncio.Event()

    async def inspect(project: Path, mode: str, *, signal: bool) -> dict[str, object]:
        token = bind_workspace_scope(build_workspace_scope(project, mode))
        try:
            if signal:
                ready.set()
            await ready.wait()
            await asyncio.sleep(0)
            result = await tool.execute(action="check", key="workspace_sandbox.workspace_root")
            assert repr(str(project.resolve())) in result
            return tool._runtime_control.snapshot().workspace_sandbox
        finally:
            reset_workspace_scope(token)

    first, second = await asyncio.gather(
        inspect(tmp_path / "first", "restricted", signal=False),
        inspect(tmp_path / "second", "full", signal=True),
    )
    assert first["restrict_to_workspace"] is True
    assert second["restrict_to_workspace"] is False
    assert tool._runtime_control.snapshot().workspace_sandbox["workspace_root"] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_workspace_inspection_reaches_model_from_selected_chat(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "marker.txt").write_text("selected project", encoding="utf-8")
    loop = _make_loop(tmp_path / "agent")
    provider = loop.provider
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id="inspect", name="my", arguments={
                "action": "check", "key": "workspace_sandbox",
            }),
            ToolCallRequest(id="read", name="read_file", arguments={"path": "marker.txt"}),
        ]),
        LLMResponse(content="done", tool_calls=[]),
    ])
    session = loop.sessions.get_or_create("websocket:inspection")
    session.metadata["workspace_scope"] = {
        "project_path": str(project), "access_mode": "restricted",
    }

    response = await loop.process_direct(
        "Check the current directory and read marker.txt",
        channel="websocket", chat_id="inspection", session_key=session.key, ephemeral=True,
    )

    assert response is not None and response.content == "done"
    calls = provider.chat_stream_with_retry.await_args_list
    assert len(calls) == 2
    results = {
        msg["tool_call_id"]: msg["content"] for msg in calls[1].kwargs["messages"]
        if msg["role"] == "tool"
    }
    assert repr(str(project.resolve())) in results["inspect"]
    assert "'restrict_to_workspace': True" in results["inspect"]
    assert "selected project" in results["read"]
    assert calls[0].kwargs["tools"] == calls[1].kwargs["tools"]


@pytest.fixture
def runtime() -> LLMRuntime:
    return LLMRuntime(MagicMock(), "test", GenerationSettings(), 128_000)


@pytest.mark.parametrize("params", [
    {"action": "create"},
    {"action": "create", "task": "  "},
    {"action": "send", "message": "update"},
    {"action": "cancel"},
])
async def test_subagent_rejects_missing_action_inputs(tmp_path, runtime, params):
    loop = _make_loop(tmp_path)
    with request_context(RequestContext("test", "route", session_key="owner", runtime=runtime)):
        result = await loop.tools.execute("subagent", params)
    assert result.startswith("Error:")
    assert loop.subagents.get_running_count() == 0


@pytest.mark.parametrize("single_task", [False, True])
async def test_subagent_check_is_session_scoped(tmp_path, single_task, runtime):
    loop = _make_loop(tmp_path)
    manager = loop.subagents
    # Queued tasks must be scoped before their runner starts.
    await manager.spawn("ALPHA_PRIVATE_TASK", label="ALPHA_LABEL", session_key="owner:a", runtime=runtime)
    await manager.spawn("BETA_PRIVATE_TASK", label="BETA_LABEL", session_key="owner:b", runtime=runtime)
    try:
        for owner, visible, hidden in [("owner:a", "ALPHA", "BETA"), ("owner:b", "BETA", "ALPHA")]:
            with request_context(RequestContext("test", "same-chat", session_key=owner)):
                params = {"action": "check"}
                if single_task:
                    params["task_id"] = next(iter(manager.statuses_for_session(owner)))
                result = await loop.tools.execute("subagent", params)
                assert visible + "_LABEL" in result
                assert visible + "_PRIVATE_TASK" in result
                assert hidden not in result
                assert "queued" in result
                overview = await loop.tools.execute("my", {"action": "check"})
                assert "ALPHA" not in overview and "BETA" not in overview
                assert "not accessible" in await loop.tools.execute("my", {
                    "action": "check", "key": "subagents",
                })
    finally:
        await manager.close()


async def test_subagent_check_rejects_foreign_task(tmp_path, runtime):
    loop = _make_loop(tmp_path)
    manager = loop.subagents
    await manager.spawn("PRIVATE_TASK", session_key="owner:a", runtime=runtime)
    try:
        task_id = next(iter(manager.statuses_for_session("owner:a")))
        with request_context(RequestContext("test", "same-chat", session_key="owner:b")):
            result = await loop.tools.execute("subagent", {"action": "check", "task_id": task_id})
            unknown = await loop.tools.execute("subagent", {"action": "check", "task_id": "unknown"})
            assert result == unknown
            assert result.startswith("Error: task unavailable")
    finally:
        await manager.close()


@pytest.mark.parametrize("session_key", [None, ""])
async def test_subagent_check_without_session_cannot_enumerate_tasks(tmp_path, session_key, runtime):
    loop = _make_loop(tmp_path)
    manager = loop.subagents
    await manager.spawn("PRIVATE_TASK", session_key="owner:a", runtime=runtime)
    try:
        task_id = next(iter(manager.statuses_for_session("owner:a")))
        assert "unavailable" in await loop.tools.execute("subagent", {"action": "check"})
        with request_context(RequestContext("test", "same-chat", session_key=session_key)):
            assert "unavailable" in await loop.tools.execute("subagent", {"action": "check"})
            assert "unavailable" in await loop.tools.execute("subagent", {
                "action": "check", "task_id": task_id,
            })
    finally:
        await manager.close()


async def test_subagent_check_retained_results_and_receipts_are_scoped_and_detached(tmp_path, runtime):
    from nanobot.agent.runner import AgentRunResult

    loop = _make_loop(tmp_path)
    manager = loop.subagents
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(spec):
        entered.set()
        await release.wait()
        return AgentRunResult(messages=[], final_content="PRIVATE_RESULT")

    manager.runner.run = run
    owner = RequestContext("test", "route", session_key="owner:a", runtime=runtime)
    try:
        with request_context(owner):
            await loop.tools.execute("subagent", {"action": "create", "task": "private"})
            await entered.wait()
            task_id = next(iter(manager.statuses_for_session("owner:a")))
            sent = json.loads(await loop.tools.execute("subagent", {
                "action": "send", "task_id": task_id, "message": "pending",
            }))
            release.set()
            await asyncio.gather(*manager._running_tasks.values())
            params = {"action": "check", "task_id": task_id}
            result = json.loads(await loop.tools.execute("subagent", params))
            assert result["state"] == "done"
            assert result["result"] == "PRIVATE_RESULT"
            assert result["receipts"] == {sent["message_id"]: "undelivered"}
            snapshot = manager.check(task_id, "owner:a")
            snapshot.receipts.clear()
            snapshot.result = "tampered"
            assert json.loads(await loop.tools.execute("subagent", params)) == result
            listed = json.loads(await loop.tools.execute("subagent", {"action": "check"}))
            assert listed == {"tasks": [result]}
            with request_context(RequestContext("test", "route", session_key="owner:b")):
                assert "unavailable" in await loop.tools.execute("subagent", params)
                assert json.loads(await loop.tools.execute("subagent", {"action": "check"})) == {"tasks": []}
    finally:
        release.set()
        await manager.close()
