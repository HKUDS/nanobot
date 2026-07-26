from pathlib import Path

import pytest

from nanobot.extensions.compatibility import CompatibleExtension
from nanobot.extensions.node_host import NodeSidecar


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


@pytest.mark.asyncio
async def test_pi_extension_loads_tools_commands_and_events(tmp_path: Path) -> None:
    entry = _write(
        tmp_path / "pi-extension.mjs",
        """
        export default function (pi) {
          pi.registerTool({
            name: "pi_echo",
            label: "Echo",
            description: "Echo input",
            parameters: {
              type: "object",
              properties: { text: { type: "string" } },
              required: ["text"]
            },
            async execute(_id, params) {
              return { content: [{ type: "text", text: `pi:${params.text}` }] };
            }
          });
          pi.registerCommand("hello", {
            description: "Say hello",
            async handler(args, ctx) { ctx.ui.notify(`hello:${args}`); }
          });
          pi.on("agent_start", (event) => {
            if (!event.messages) throw new Error("missing messages");
          });
        }
        """,
    )
    host = NodeSidecar()
    try:
        result = await host.load(
            runtime="pi",
            entries=(entry,),
            root=tmp_path,
            extension_id="test.pi",
            name="Pi test",
            version="1.0.0",
            workspace=tmp_path,
        )
        extension = CompatibleExtension(
            host=host,
            runtime="pi",
            owner="test.pi",
            result=result,
        )
        assert [(item.kind, item.name) for item in result.registrations] == [
            ("tool", "pi_echo"),
            ("command", "hello"),
            ("hook", "agent_start"),
        ]
        assert await extension.tools[0].execute(text="ok") == "pi:ok"
        assert extension.hook is not None
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_openclaw_definition_loads_and_invokes_tool(tmp_path: Path) -> None:
    entry = _write(
        tmp_path / "openclaw-plugin.cjs",
        """
        module.exports = {
          id: "test.openclaw",
          register(api) {
            api.registerTool({
              name: "claw_echo",
              description: "Echo input",
              parameters: {
                type: "object",
                properties: { text: { type: "string" } },
                required: ["text"]
              },
              async execute(_id, params) {
                return { content: [{ type: "text", text: `claw:${params.text}` }] };
              }
            });
            api.registerCommand({
              name: "status",
              description: "Show status",
              handler: async () => ({ text: "ready" })
            });
            api.on("agent_end", () => undefined);
          }
        };
        """,
    )
    host = NodeSidecar()
    try:
        result = await host.load(
            runtime="openclaw",
            entries=(entry,),
            root=tmp_path,
            extension_id="test.openclaw",
            name="OpenClaw test",
            version="1.0.0",
            workspace=tmp_path,
        )
        extension = CompatibleExtension(
            host=host,
            runtime="openclaw",
            owner="test.openclaw",
            result=result,
        )
        assert await extension.tools[0].execute(text="ok") == "claw:ok"
        assert {item.name for item in result.registrations} == {
            "claw_echo",
            "status",
            "agent_end",
        }
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_pi_package_loads_every_declared_entry(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "first.mjs",
        """
        export default function (pi) {
          pi.registerCommand("first", { handler: async () => "first" });
        }
        """,
    )
    second = _write(
        tmp_path / "second.mjs",
        """
        export default function (pi) {
          pi.registerCommand("second", { handler: async () => "second" });
        }
        """,
    )
    host = NodeSidecar()
    try:
        result = await host.load(
            runtime="pi",
            entries=(first, second),
            root=tmp_path,
            extension_id="test.multi",
            name="Pi multi-entry test",
            version="1.0.0",
            workspace=tmp_path,
        )
        assert {
            item.name for item in result.registrations if item.kind == "command"
        } == {"first", "second"}
    finally:
        await host.close()
