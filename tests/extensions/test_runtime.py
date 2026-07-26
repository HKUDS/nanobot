from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter
from nanobot.config.schema import Config
from nanobot.extensions import (
    DependencyKind,
    ExtensionCandidate,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionRuntime,
    ExtensionRuntimeManager,
    ExtensionScope,
    ExtensionSnapshot,
)


def _snapshot(candidate: ExtensionCandidate) -> ExtensionSnapshot:
    return ExtensionSnapshot((candidate,), (), ())


@pytest.mark.asyncio
async def test_runtime_activation_and_close_are_transactional(tmp_path: Path) -> None:
    (tmp_path / "index.mjs").write_text(
        """
        export default function (pi) {
          pi.registerTool({
            name: "remote_echo",
            description: "Echo",
            parameters: { type: "object", properties: {} },
            execute: async () => ({ content: [{ type: "text", text: "ok" }] })
          });
          pi.registerCommand("remote", {
            description: "Remote command",
            handler: async () => undefined
          });
          pi.on("agent_start", () => undefined);
        }
        """
    )
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.remote",
            name="Remote",
            version="1.0.0",
            runtime=ExtensionRuntime.PI,
            entry="index.mjs",
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    tools = ToolRegistry()
    commands = CommandRouter()
    manager = ExtensionRuntimeManager(
        tools=tools,
        commands=commands,
        config=Config(),
    )

    result = await manager.activate(_snapshot(candidate))

    assert not result.diagnostics
    assert tools.owner("remote_echo") == "test.remote"
    assert commands.owner("exact", "/remote") == "test.remote"
    assert len(result.hook_factories) == 1

    await manager.close()

    assert tools.owner("remote_echo") is None
    assert commands.owner("exact", "/remote") is None


@pytest.mark.asyncio
async def test_runtime_rolls_back_partial_registration(tmp_path: Path) -> None:
    (tmp_path / "index.mjs").write_text(
        """
        export default function (pi) {
          pi.registerTool({
            name: "duplicate",
            description: "Duplicate",
            parameters: {},
            execute: async () => ({ content: [] })
          });
          pi.registerCommand("duplicate", {
            handler: async () => undefined
          });
        }
        """
    )
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.duplicate",
            name="Duplicate",
            version="1.0.0",
            runtime=ExtensionRuntime.PI,
            entry="index.mjs",
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    commands = CommandRouter()

    async def core_handler(_ctx):
        return None

    commands.exact("/duplicate", core_handler)
    manager = ExtensionRuntimeManager(
        tools=ToolRegistry(),
        commands=commands,
        config=Config(),
    )

    result = await manager.activate(_snapshot(candidate))

    assert result.extensions == ()
    assert result.diagnostics[0].code == "activation_failed"
    assert commands.owner("exact", "/duplicate") == "nanobot.core"


@pytest.mark.asyncio
async def test_python_runtime_reloads_updated_source(tmp_path: Path) -> None:
    source = tmp_path / "plugin.py"
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.python",
            name="Python",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entry="plugin:register",
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    tools = ToolRegistry()

    def write_plugin(result: str) -> None:
        source.write_text(
            f"""
from nanobot.agent.tools.base import Tool

class ReloadTool(Tool):
    @property
    def name(self):
        return "reload_test"

    @property
    def description(self):
        return "Reload test"

    @property
    def parameters(self):
        return {{"type": "object", "properties": {{}}}}

    async def execute(self):
        return "{result}"

def register(api):
    api.register_tool(ReloadTool())
"""
        )

    write_plugin("first")
    first = ExtensionRuntimeManager(
        tools=tools,
        commands=CommandRouter(),
        config=Config(),
    )
    first_result = await first.activate(_snapshot(candidate))
    assert first_result.diagnostics == ()
    assert await tools.get("reload_test").execute() == "first"
    await first.close()

    write_plugin("later")
    second = ExtensionRuntimeManager(
        tools=tools,
        commands=CommandRouter(),
        config=Config(),
    )
    second_result = await second.activate(_snapshot(candidate))
    assert second_result.diagnostics == ()
    assert await tools.get("reload_test").execute() == "later"
    await second.close()


@pytest.mark.asyncio
async def test_python_runtime_accepts_single_entries_form(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text(
        """
def register(_api):
    pass
"""
    )
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.python-entries",
            name="Python entries",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entries=("plugin:register",),
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    manager = ExtensionRuntimeManager(
        tools=ToolRegistry(),
        commands=CommandRouter(),
        config=Config(),
    )

    result = await manager.activate(_snapshot(candidate))

    assert result.diagnostics == ()
    await manager.close()


@pytest.mark.asyncio
async def test_python_runtime_rejects_module_outside_package(tmp_path: Path) -> None:
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.collision",
            name="Collision",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entry="json:register",
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    manager = ExtensionRuntimeManager(
        tools=ToolRegistry(),
        commands=CommandRouter(),
        config=Config(),
    )

    result = await manager.activate(_snapshot(candidate))

    assert result.extensions == ()
    assert result.diagnostics[0].code == "activation_failed"
    assert "conflicts with loaded module" in result.diagnostics[0].message


@pytest.mark.asyncio
async def test_python_hook_factory_is_removed_without_clearing_core_hooks(
    tmp_path: Path,
) -> None:
    (tmp_path / "plugin.py").write_text(
        """
from nanobot.agent.hook import AgentHook

def extension_hook(_context):
    return AgentHook()

def register(api):
    api.register_hook_factory(extension_hook)
"""
    )
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.hook",
            name="Hook",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entry="plugin:register",
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )

    def core_hook(_context):
        return None

    hooks = [core_hook]
    manager = ExtensionRuntimeManager(
        tools=ToolRegistry(),
        commands=CommandRouter(),
        config=Config(),
        hook_factories=hooks,
    )

    result = await manager.activate(_snapshot(candidate))

    assert result.diagnostics == ()
    assert len(hooks) == 2
    await manager.close()
    assert hooks == [core_hook]


@pytest.mark.asyncio
async def test_python_runtime_cannot_overwrite_core_tool(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text(
        """
from nanobot.agent.tools.base import Tool

class DuplicateTool(Tool):
    name = "duplicate"
    description = "Duplicate"
    parameters = {"type": "object", "properties": {}}

    async def execute(self):
        return "extension"

def register(api):
    api.register_tool(DuplicateTool())
"""
    )
    candidate = ExtensionCandidate(
        ExtensionManifest(
            id="test.overwrite",
            name="Overwrite",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entry="plugin:register",
        ),
        ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    core_tool = SimpleNamespace(name="duplicate")
    tools = ToolRegistry()
    tools.register(core_tool)
    manager = ExtensionRuntimeManager(
        tools=tools,
        commands=CommandRouter(),
        config=Config(),
    )

    result = await manager.activate(_snapshot(candidate))

    assert result.extensions == ()
    assert result.diagnostics[0].code == "activation_failed"
    assert tools.get("duplicate") is core_tool
    assert tools.owner("duplicate") == "nanobot.core"


@pytest.mark.asyncio
async def test_failed_extension_prevents_dependent_activation(tmp_path: Path) -> None:
    base_root = tmp_path / "base"
    dependent_root = tmp_path / "dependent"
    base_root.mkdir()
    dependent_root.mkdir()
    base = ExtensionCandidate(
        ExtensionManifest(
            id="base",
            name="Base",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entry="missing:register",
        ),
        ExtensionScope.USER,
        location=base_root,
        trusted=True,
    )
    dependent = ExtensionCandidate(
        ExtensionManifest(
            id="dependent",
            name="Dependent",
            version="1.0.0",
            runtime=ExtensionRuntime.DECLARATIVE,
            dependencies=(
                ExtensionDependency(
                    kind=DependencyKind.EXTENSION,
                    name="base",
                ),
            ),
        ),
        ExtensionScope.USER,
        location=dependent_root,
        trusted=True,
    )
    manager = ExtensionRuntimeManager(
        tools=ToolRegistry(),
        commands=CommandRouter(),
        config=Config(),
    )

    result = await manager.activate(ExtensionSnapshot((base, dependent), (), ()))

    assert result.extensions == ()
    assert [item.code for item in result.diagnostics] == [
        "activation_failed",
        "dependency_activation_failed",
    ]
