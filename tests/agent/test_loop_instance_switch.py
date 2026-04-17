from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.instances import RuntimeInstance
from nanobot.config.schema import Config, MCPServerConfig
from nanobot.providers.base import GenerationSettings, LLMResponse


class _FakeMCPTool(Tool):
    @property
    def name(self) -> str:
        return "mcp_notionApi_API-post-search"

    @property
    def description(self) -> str:
        return "Fake notion search tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return "ok"


class _FakeStack:
    async def aclose(self) -> None:
        return None


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=256)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[])
    )
    return provider


def _make_config(workspace: Path) -> Config:
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.model = "test-model"
    config.tools.mcp_servers = {
        "notionApi": MCPServerConfig(command="fake-mcp", enabled_tools=["*"]),
    }
    return config


def _tool_names(definitions: list[dict]) -> list[str]:
    names: list[str] = []
    for definition in definitions:
        function = definition.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return names


@pytest.mark.asyncio
async def test_switch_instance_reconnects_mcp_before_next_message(
    tmp_path: Path, monkeypatch
) -> None:
    base_workspace = tmp_path / "base-workspace"
    local_workspace = tmp_path / "local-workspace"
    base_workspace.mkdir()
    local_workspace.mkdir()
    base_config_path = tmp_path / ".nanobot-research" / "config.json"
    local_config_path = tmp_path / ".nanobot-local" / "config.json"
    base_config_path.parent.mkdir()
    local_config_path.parent.mkdir()
    base_config_path.write_text("{}", encoding="utf-8")
    local_config_path.write_text("{}", encoding="utf-8")

    base_config = _make_config(base_workspace)
    local_config = _make_config(local_workspace)
    provider = _make_provider()
    connect_calls: list[tuple[str, ...]] = []

    async def fake_connect_mcp_servers(mcp_servers, registry) -> dict[str, _FakeStack]:
        connect_calls.append(tuple(sorted(mcp_servers)))
        registry.register(_FakeMCPTool())
        return {"notionApi": _FakeStack()}

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", fake_connect_mcp_servers)
    monkeypatch.setattr(
        "nanobot.agent.loop.find_runtime_instance",
        lambda name: RuntimeInstance(
            name="local",
            config_path=local_config_path,
            aliases=("local", ".nanobot-local", "nanobot-local"),
        )
        if name.lower() == "local"
        else None,
    )
    monkeypatch.setattr(
        "nanobot.agent.loop.discover_runtime_instances",
        lambda: [
            RuntimeInstance(
                name="research",
                config_path=base_config_path,
                aliases=("research", ".nanobot-research", "nanobot-research"),
            ),
            RuntimeInstance(
                name="local",
                config_path=local_config_path,
                aliases=("local", ".nanobot-local", "nanobot-local"),
            ),
        ],
    )
    monkeypatch.setattr("nanobot.agent.loop.get_config_path", lambda: base_config_path)
    monkeypatch.setattr(
        "nanobot.config.loader.load_config",
        lambda path=None: local_config
        if Path(path).resolve(strict=False) == local_config_path.resolve(strict=False)
        else base_config,
    )
    monkeypatch.setattr("nanobot.config.loader.resolve_config_env_vars", lambda config: config)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: provider)
    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=base_config.workspace_path,
        model=base_config.agents.defaults.model,
        mcp_servers=base_config.tools.mcp_servers,
    )

    await loop._connect_mcp()
    assert "mcp_notionApi_API-post-search" in loop.tools.tool_names

    ok, _ = await loop.switch_runtime_instance("local")

    assert ok is True
    assert loop.active_instance_name == "local"
    assert len(connect_calls) == 2
    assert "mcp_notionApi_API-post-search" in loop.tools.tool_names

    provider.chat_with_retry.reset_mock()
    await loop.process_direct(
        "search notion page",
        session_key="weixin:test-chat",
        channel="weixin",
        chat_id="test-chat",
    )

    sent_tools = provider.chat_with_retry.await_args.kwargs["tools"]
    assert "mcp_notionApi_API-post-search" in _tool_names(sent_tools)


@pytest.mark.asyncio
async def test_system_messages_reconnect_mcp_before_llm_request(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _make_provider()
    connect_calls: list[str] = []

    async def fake_connect_mcp_servers(_mcp_servers, registry) -> dict[str, _FakeStack]:
        connect_calls.append("connected")
        registry.register(_FakeMCPTool())
        return {"notionApi": _FakeStack()}

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", fake_connect_mcp_servers)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=workspace,
        model="test-model",
        mcp_servers={"notionApi": MCPServerConfig(command="fake-mcp", enabled_tools=["*"])},
    )

    loop.tools = ToolRegistry()
    loop._register_default_tools()
    loop._mcp_connected = False
    loop._mcp_stacks = {}
    provider.chat_with_retry.reset_mock()

    await loop._process_message(
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="weixin:test-chat",
            content="continue",
        )
    )

    assert connect_calls == ["connected"]
    sent_tools = provider.chat_with_retry.await_args.kwargs["tools"]
    assert "mcp_notionApi_API-post-search" in _tool_names(sent_tools)
