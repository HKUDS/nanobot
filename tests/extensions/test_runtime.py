from pathlib import Path

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter
from nanobot.extensions import ExtensionManifest
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionSnapshot,
)
from nanobot.extensions.runtime import ExtensionRuntimeManager


def _candidate(root: Path, extension_id: str = "test.python") -> ExtensionCandidate:
    return ExtensionCandidate(
        ExtensionManifest(
            id=extension_id,
            name="Python extension",
            version="1.0.0",
            entry="extension:register",
        ),
        location=root,
        trusted=True,
    )


def _snapshot(*candidates: ExtensionCandidate) -> ExtensionSnapshot:
    return ExtensionSnapshot(candidates, ())


def _write_extension(root: Path, result: str = "ok") -> None:
    (root / "extension.py").write_text(
        f"""
from nanobot.agent.hook import AgentHook
from nanobot.agent.tools.base import Tool

class ExtensionTool(Tool):
    @property
    def name(self):
        return "extension_echo"

    @property
    def description(self):
        return "Echo from an extension"

    @property
    def parameters(self):
        return {{"type": "object", "properties": {{}}}}

    async def execute(self):
        return "{result}"

async def command(_context):
    return None

def hook_factory(_context):
    return AgentHook()

def register(api):
    api.register_tool(ExtensionTool())
    api.register_command("extension", command)
    api.register_hook_factory(hook_factory)
"""
    )


async def test_python_extension_registers_and_removes_owned_capabilities(
    tmp_path: Path,
) -> None:
    _write_extension(tmp_path)
    tools = ToolRegistry()
    commands = CommandRouter()
    hooks = []
    manager = ExtensionRuntimeManager(
        tools=tools,
        commands=commands,
        hook_factories=hooks,
    )

    result = await manager.activate(_snapshot(_candidate(tmp_path)))

    assert result.diagnostics == ()
    assert tools.owner("extension_echo") == "test.python"
    assert commands.owner("exact", "/extension") == "test.python"
    assert len(hooks) == 1
    assert await tools.get("extension_echo").execute() == "ok"

    await manager.close()

    assert tools.owner("extension_echo") is None
    assert commands.owner("exact", "/extension") is None
    assert hooks == []


async def test_failed_registration_rolls_back_partial_state(tmp_path: Path) -> None:
    (tmp_path / "extension.py").write_text(
        """
from nanobot.agent.tools.base import Tool

class DuplicateTool(Tool):
    name = "duplicate"
    description = "Duplicate"
    parameters = {"type": "object", "properties": {}}
    async def execute(self):
        return "ok"

async def command(_context):
    return None

def register(api):
    api.register_tool(DuplicateTool())
    api.register_command("duplicate", command)
"""
    )
    tools = ToolRegistry()
    commands = CommandRouter()

    async def core_handler(_context):
        return None

    commands.exact("/duplicate", core_handler)
    manager = ExtensionRuntimeManager(
        tools=tools,
        commands=commands,
    )

    result = await manager.activate(_snapshot(_candidate(tmp_path)))

    assert result.extensions == ()
    assert result.diagnostics[0].code == "activation_failed"
    assert tools.get("duplicate") is None
    assert commands.owner("exact", "/duplicate") == "nanobot.core"


async def test_python_extension_reloads_updated_source(tmp_path: Path) -> None:
    tools = ToolRegistry()
    candidate = _candidate(tmp_path)
    _write_extension(tmp_path, "first")
    first = ExtensionRuntimeManager(tools=tools, commands=CommandRouter())

    await first.activate(_snapshot(candidate))
    assert await tools.get("extension_echo").execute() == "first"
    await first.close()

    _write_extension(tmp_path, "later")
    second = ExtensionRuntimeManager(tools=tools, commands=CommandRouter())
    await second.activate(_snapshot(candidate))

    assert await tools.get("extension_echo").execute() == "later"
    await second.close()


async def test_extensions_with_the_same_entry_module_are_isolated(
    tmp_path: Path,
) -> None:
    tools = ToolRegistry()
    manager = ExtensionRuntimeManager(tools=tools, commands=CommandRouter())
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _write_extension(first_root, "first")
    _write_extension(second_root, "second")
    second_source = (second_root / "extension.py").read_text()
    (second_root / "extension.py").write_text(
        second_source
        .replace("extension_echo", "second_echo")
        .replace('register_command("extension"', 'register_command("second"')
    )

    result = await manager.activate(
        _snapshot(
            _candidate(first_root, "test.first"),
            _candidate(second_root, "test.second"),
        )
    )

    assert result.diagnostics == ()
    assert await tools.get("extension_echo").execute() == "first"
    assert await tools.get("second_echo").execute() == "second"
    await manager.close()
