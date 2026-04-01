from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus


def test_agent_loop_allows_reading_runtime_media_dir_when_workspace_restricted(tmp_path, monkeypatch) -> None:
    media_dir = tmp_path / "runtime-media"
    monkeypatch.setattr("nanobot.agent.loop.get_media_dir", lambda channel=None: media_dir)

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path / "workspace",
        restrict_to_workspace=True,
    )

    read_tool = loop.tools.get("read_file")
    assert read_tool is not None
    assert media_dir in read_tool._extra_allowed_dirs


def test_subagent_allows_reading_runtime_media_dir_when_workspace_restricted(tmp_path, monkeypatch) -> None:
    media_dir = tmp_path / "runtime-media"
    monkeypatch.setattr("nanobot.agent.subagent.get_media_dir", lambda channel=None: media_dir)

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    manager = SubagentManager(
        provider=provider,
        workspace=tmp_path / "workspace",
        bus=MessageBus(),
        restrict_to_workspace=True,
    )

    captured: dict[str, object] = {}

    class _FakeRegistry:
        def register(self, tool) -> None:
            if getattr(tool, "name", None) == "read_file":
                captured["tool"] = tool

    monkeypatch.setattr("nanobot.agent.subagent.ToolRegistry", _FakeRegistry)
    monkeypatch.setattr(manager, "_build_subagent_prompt", lambda: "system")

    async def _run() -> None:
        try:
            await manager._run_subagent("task1", "do thing", "label", {"channel": "cli", "chat_id": "direct"})
        except Exception:
            # We only care about tool registration before provider execution.
            pass

    import asyncio
    asyncio.run(_run())

    read_tool = captured.get("tool")
    assert read_tool is not None
    assert media_dir in read_tool._extra_allowed_dirs
