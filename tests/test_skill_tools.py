"""Tests for skill-provided custom tools (Step 14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.base import ToolResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_skill(
    skill_dir: Path,
    name: str,
    *,
    skill_md: str = "---\ndescription: test skill\n---\n# Test",
    tools_py: str | None = None,
) -> Path:
    """Create a minimal skill directory under *skill_dir*."""
    d = skill_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md, encoding="utf-8")
    if tools_py is not None:
        (d / "tools.py").write_text(tools_py, encoding="utf-8")
    return d


SIMPLE_TOOLS_PY = '''\
"""Custom tools for the demo skill."""

from nanobot.agent.tools.base import Tool, ToolResult
from typing import Any


class PingTool(Tool):
    """Answers with pong."""

    readonly = True

    @property
    def name(self) -> str:
        return "ping"

    @property
    def description(self) -> str:
        return "Responds with pong."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("pong")


class EchoTool(Tool):
    """Echoes the input text."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes back the given text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(kwargs.get("text", ""))
'''


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiscoverTools:
    """Test SkillsLoader.discover_tools()."""

    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture()
    def loader(self, workspace: Path) -> SkillsLoader:
        return SkillsLoader(workspace, builtin_skills_dir=workspace / "_builtin")

    def test_no_skills_returns_empty(self, loader: SkillsLoader) -> None:
        assert loader.discover_tools() == []

    def test_skill_without_tools_py(self, workspace: Path, loader: SkillsLoader) -> None:
        _make_skill(workspace / "skills", "plain-skill")
        assert loader.discover_tools() == []

    def test_discovers_tools_from_workspace_skill(
        self, workspace: Path, loader: SkillsLoader
    ) -> None:
        _make_skill(workspace / "skills", "demo", tools_py=SIMPLE_TOOLS_PY)
        tools = loader.discover_tools()
        names = {t.name for t in tools}
        assert "ping" in names
        assert "echo" in names
        assert len(tools) == 2

    def test_discovers_tools_from_builtin_skill(self, workspace: Path) -> None:
        builtin_dir = workspace / "_builtin"
        _make_skill(builtin_dir, "builtin-demo", tools_py=SIMPLE_TOOLS_PY)
        loader = SkillsLoader(workspace, builtin_skills_dir=builtin_dir)
        tools = loader.discover_tools()
        assert len(tools) == 2

    def test_workspace_skill_takes_priority(self, workspace: Path) -> None:
        """If both workspace and builtin have the same skill, workspace wins."""
        builtin_dir = workspace / "_builtin"
        # Builtin with one tool
        _make_skill(
            builtin_dir,
            "demo",
            tools_py="""\
from nanobot.agent.tools.base import Tool, ToolResult
from typing import Any

class BuiltinOnly(Tool):
    @property
    def name(self): return "builtin_only"
    @property
    def description(self): return "builtin"
    @property
    def parameters(self): return {"type": "object", "properties": {}}
    async def execute(self, **kw): return ToolResult.ok("builtin")
""",
        )
        # Workspace overrides with a different tool
        _make_skill(workspace / "skills", "demo", tools_py=SIMPLE_TOOLS_PY)
        loader = SkillsLoader(workspace, builtin_skills_dir=builtin_dir)
        tools = loader.discover_tools(["demo"])
        names = {t.name for t in tools}
        # Should get workspace tools, not builtin
        assert "ping" in names
        assert "builtin_only" not in names

    def test_filter_by_skill_names(self, workspace: Path, loader: SkillsLoader) -> None:
        _make_skill(workspace / "skills", "alpha", tools_py=SIMPLE_TOOLS_PY)
        _make_skill(workspace / "skills", "beta")  # no tools.py
        tools = loader.discover_tools(["alpha"])
        assert len(tools) == 2
        tools = loader.discover_tools(["beta"])
        assert len(tools) == 0

    def test_abstract_classes_not_instantiated(self, workspace: Path, loader: SkillsLoader) -> None:
        """Abstract Tool subclasses (missing implementations) are skipped."""
        _make_skill(
            workspace / "skills",
            "abstract-skill",
            tools_py='''\
from nanobot.agent.tools.base import Tool
from typing import Any

class IncompleteTool(Tool):
    """This tool lacks required abstract implementations."""
    @property
    def name(self): return "incomplete"
    # Missing description, parameters, execute
''',
        )
        tools = loader.discover_tools(["abstract-skill"])
        assert len(tools) == 0

    def test_private_classes_ignored(self, workspace: Path, loader: SkillsLoader) -> None:
        _make_skill(
            workspace / "skills",
            "private-skill",
            tools_py="""\
from nanobot.agent.tools.base import Tool, ToolResult
from typing import Any

class _HelperTool(Tool):
    @property
    def name(self): return "_helper"
    @property
    def description(self): return "helper"
    @property
    def parameters(self): return {"type": "object", "properties": {}}
    async def execute(self, **kw): return ToolResult.ok("hidden")
""",
        )
        tools = loader.discover_tools(["private-skill"])
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_discovered_tool_executes(self, workspace: Path, loader: SkillsLoader) -> None:
        _make_skill(workspace / "skills", "exec-test", tools_py=SIMPLE_TOOLS_PY)
        tools = loader.discover_tools(["exec-test"])
        ping = next(t for t in tools if t.name == "ping")
        result = await ping.execute()
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.output == "pong"

    def test_broken_module_does_not_crash(self, workspace: Path, loader: SkillsLoader) -> None:
        """A skill with a syntax error in tools.py shouldn't crash the loader."""
        _make_skill(workspace / "skills", "broken", tools_py="this is not valid python !!!")
        tools = loader.discover_tools(["broken"])
        assert tools == []

    def test_tool_requiring_constructor_args_skipped(
        self, workspace: Path, loader: SkillsLoader
    ) -> None:
        """Tools that require constructor args can't be auto-instantiated."""
        _make_skill(
            workspace / "skills",
            "needs-args",
            tools_py="""\
from nanobot.agent.tools.base import Tool, ToolResult
from typing import Any

class NeedsArgsTool(Tool):
    def __init__(self, api_key: str):
        self.api_key = api_key
    @property
    def name(self): return "needs_args"
    @property
    def description(self): return "needs args"
    @property
    def parameters(self): return {"type": "object", "properties": {}}
    async def execute(self, **kw): return ToolResult.ok(self.api_key)
""",
        )
        tools = loader.discover_tools(["needs-args"])
        assert len(tools) == 0


class TestFindSkillToolsPy:
    """Test the _find_skill_tools_py helper."""

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        loader = SkillsLoader(tmp_path)
        _make_skill(tmp_path / "skills", "notools")
        assert loader._find_skill_tools_py("notools") is None

    def test_finds_workspace_tools(self, tmp_path: Path) -> None:
        loader = SkillsLoader(tmp_path)
        _make_skill(tmp_path / "skills", "with-tools", tools_py="# tools")
        path = loader._find_skill_tools_py("with-tools")
        assert path is not None
        assert path.name == "tools.py"
        assert "skills/with-tools" in str(path)

    def test_finds_builtin_tools(self, tmp_path: Path) -> None:
        builtin = tmp_path / "_builtin"
        loader = SkillsLoader(tmp_path, builtin_skills_dir=builtin)
        _make_skill(builtin, "bi-skill", tools_py="# builtin tools")
        path = loader._find_skill_tools_py("bi-skill")
        assert path is not None
        assert "_builtin" in str(path)
