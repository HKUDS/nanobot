from pathlib import Path

import pytest

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter
from nanobot.config.schema import Config
from nanobot.extensions import (
    ExtensionCandidate,
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
