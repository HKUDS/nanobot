"""Unit tests for register_default_tools (extracted from AgentLoop, LAN-213)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.tool_setup import register_default_tools
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.result_cache import ToolResultCache
from nanobot.config.schema import AgentRoleConfig, ExecToolConfig


class FakeSkillsLoader:
    """Stub that returns no skill tools by default."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        self._tools = tools or []

    def discover_tools(self, skill_names: list[str] | None = None) -> list[Any]:
        return self._tools


async def _noop_publish(**kwargs: Any) -> None:
    pass


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "memory").mkdir()
    (tmp_path / "sessions" / "_placeholder").mkdir(parents=True)
    return tmp_path


def _register(
    workspace: Path,
    *,
    role_config: AgentRoleConfig | None = None,
    delegation_enabled: bool = True,
    cron_service: Any = None,
    skills_loader: Any = None,
) -> ToolExecutor:
    registry = ToolRegistry()
    tools = ToolExecutor(registry)
    register_default_tools(
        tools=tools,
        role_config=role_config,
        workspace=workspace,
        restrict_to_workspace=False,
        shell_mode="denylist",
        vision_model=None,
        exec_config=ExecToolConfig(timeout=30),
        brave_api_key=None,
        publish_outbound=_noop_publish,
        cron_service=cron_service,
        delegation_enabled=delegation_enabled,
        missions=Mock(),
        result_cache=Mock(spec=ToolResultCache),
        skills_enabled=bool(skills_loader),
        skills_loader=skills_loader or FakeSkillsLoader(),
    )
    return tools


class TestRegisterDefaultTools:
    def test_default_tools_registered(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace)
        names = tools._registry.tool_names
        # Spot-check core tools are present
        for expected in (
            "read_file",
            "write_file",
            "edit_file",
            "list_dir",
            "exec",
            "web_search",
            "web_fetch",
            "message",
            "feedback",
            "check_email",
        ):
            assert expected in names, f"Missing expected tool: {expected}"

    def test_delegation_tools_present_when_enabled(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, delegation_enabled=True)
        names = tools._registry.tool_names
        for expected in (
            "delegate",
            "delegate_parallel",
            "mission_start",
            "mission_status",
            "mission_list",
            "mission_cancel",
        ):
            assert expected in names, f"Missing delegation tool: {expected}"

    def test_expected_tool_count(self, tmp_workspace: Path) -> None:
        """Regression guard: total tool count from auditing tool_setup.py."""
        tools = _register(tmp_workspace)
        # Count derived from manual audit of tool_setup.py at commit 7470a43:
        # filesystem(4) + spreadsheet(1) + pptx_read(1) + pptx_analyze(1) +
        # exec(1) + web_search(1) + web_fetch(1) + message(1) + feedback(1) +
        # email(1) + delegation(6) + scratchpad(2) + cache_get_slice(1) +
        # excel_get_rows(1) + excel_find(1) + pptx_get_slide(1) +
        # query_data(1) + describe_data(1) = 27
        # (no cron — cron_service=None)
        count = len(tools._registry)
        assert count == 27, f"Expected 27 tools, got {count}: {sorted(tools._registry.tool_names)}"

    def test_allowed_tools_whitelist(self, tmp_workspace: Path) -> None:
        role = AgentRoleConfig(
            name="restricted", description="", allowed_tools=["exec", "read_file"]
        )
        tools = _register(tmp_workspace, role_config=role)
        names = set(tools._registry.tool_names)
        assert names == {"exec", "read_file"}

    def test_denied_tools_blacklist(self, tmp_workspace: Path) -> None:
        role = AgentRoleConfig(name="safe", description="", denied_tools=["exec"])
        tools = _register(tmp_workspace, role_config=role)
        names = tools._registry.tool_names
        assert "exec" not in names
        assert "read_file" in names

    def test_delegation_disabled_skips_tools(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, delegation_enabled=False)
        names = tools._registry.tool_names
        for absent in (
            "delegate",
            "delegate_parallel",
            "mission_start",
            "mission_status",
            "mission_list",
            "mission_cancel",
        ):
            assert absent not in names, f"Should not register: {absent}"

    def test_no_cron_service_skips_cron(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, cron_service=None)
        assert "cron" not in tools._registry.tool_names

    def test_cron_registered_when_service_provided(self, tmp_workspace: Path) -> None:
        tools = _register(tmp_workspace, cron_service=Mock())
        assert "cron" in tools._registry.tool_names

    def test_skills_tools_discovered(self, tmp_workspace: Path) -> None:
        from nanobot.agent.tools.base import Tool, ToolResult

        class FakeSkillTool(Tool):
            @property
            def name(self) -> str:
                return "fake_skill_tool"

            @property
            def description(self) -> str:
                return "A skill-provided tool"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("ok")

        loader = FakeSkillsLoader(tools=[FakeSkillTool()])
        tools = _register(tmp_workspace, skills_loader=loader)
        assert "fake_skill_tool" in tools._registry.tool_names
