from pathlib import Path

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter
from nanobot.config.schema import Config
from nanobot.extensions.host import ExtensionHost
from nanobot.extensions.runtime import ExtensionRuntimeManager


class _Agent:
    def __init__(self) -> None:
        self.tools = ToolRegistry()
        self.commands = CommandRouter()
        self._hook_factories = []


async def test_host_reloads_and_closes_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    agent = _Agent()
    config = Config()
    activated: list[object] = []
    closed: list[object] = []

    async def activate(self, snapshot):
        activated.append(snapshot)
        return type(
            "Result",
            (),
            {"extensions": (), "hook_factories": (), "diagnostics": ()},
        )()

    async def close(self):
        closed.append(self)

    monkeypatch.setattr(ExtensionRuntimeManager, "activate", activate)
    monkeypatch.setattr(ExtensionRuntimeManager, "close", close)

    host = ExtensionHost(agent, lambda: config, user_root=tmp_path)
    first = await host.reload()
    second = await host.reload()
    await host.close()

    assert host.snapshot is None
    assert first.catalog.snapshot.extensions
    assert second.catalog.snapshot.extensions
    assert len(activated) == 2
    assert len(closed) == 2
