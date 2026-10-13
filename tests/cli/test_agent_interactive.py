from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import (
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_message_for_event,
)
from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


@pytest.mark.parametrize("streamed", [False, True])
def test_interactive_agent_routes_a_complete_user_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    streamed: bool,
) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    seen: dict[str, object] = {}
    renderers: list[object] = []

    class _Renderer:
        def __init__(self, **_kwargs: object) -> None:
            self.streamed = False
            self.header_printed = False
            self.deltas: list[str] = []
            self.ends: list[bool] = []
            self.closed = 0
            renderers.append(self)

        async def on_delta(self, content: str) -> None:
            self.streamed = True
            self.deltas.append(content)

        async def on_end(self, *, resuming: bool = False) -> None:
            self.ends.append(resuming)

        async def close(self) -> None:
            self.closed += 1

        def stop_for_input(self) -> None:
            return None

    class _AgentLoop:
        channels_config = None

        @classmethod
        def from_config(cls, _config, bus, **_kwargs):
            instance = cls(bus)
            seen["loop"] = instance
            return instance

        def __init__(self, bus) -> None:
            self.bus = bus
            self.stopped = asyncio.Event()
            self.aclose_calls = 0

        async def run(self) -> None:
            message = await self.bus.consume_inbound()
            seen["inbound"] = message
            if streamed:
                for event in (
                    StreamDeltaEvent(content="hello "),
                    StreamDeltaEvent(content="world"),
                    StreamEndEvent(),
                    StreamedResponseEvent(),
                ):
                    await self.bus.publish_outbound(
                        outbound_message_for_event(
                            channel=message.channel,
                            chat_id=message.chat_id,
                            event=event,
                            content="hello world" if isinstance(event, StreamedResponseEvent) else None,
                        )
                    )
            else:
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=message.channel,
                        chat_id=message.chat_id,
                        content="hello world",
                    )
                )
            await self.stopped.wait()

        def stop(self) -> None:
            self.stopped.set()

        async def aclose(self) -> None:
            self.aclose_calls += 1

    read_input = AsyncMock(side_effect=["hello nanobot", "exit"])
    print_response = MagicMock()
    monkeypatch.setattr("nanobot.cli.agent._load_runtime_config", lambda *_args: config)
    monkeypatch.setattr("nanobot.cli.agent.sync_workspace_templates", lambda *_args: None)
    monkeypatch.setattr("nanobot.cli.agent.is_default_workspace", lambda *_args: False)
    monkeypatch.setattr("nanobot.cli.agent._set_nanobot_logs", lambda *_args: None)
    monkeypatch.setattr("nanobot.cli.agent._model_display", lambda *_args: ("test-model", ""))
    monkeypatch.setattr("nanobot.cli.agent.consume_restart_notice_from_env", lambda: None)
    monkeypatch.setattr("nanobot.cli.agent.AgentLoop", _AgentLoop)
    monkeypatch.setattr("nanobot.cli.agent.StreamRenderer", _Renderer)
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda *_args: object())
    monkeypatch.setattr(
        "nanobot.providers.image_generation.image_gen_provider_configs",
        lambda *_args: [],
    )
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda *_args: object())
    monkeypatch.setattr("nanobot.cli.agent.signal.signal", lambda *_args: None)
    monkeypatch.setattr("nanobot.cli.terminal._init_prompt_session", lambda: None)
    monkeypatch.setattr("nanobot.cli.terminal._flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("nanobot.cli.terminal._restore_terminal", lambda: None)
    monkeypatch.setattr("nanobot.cli.terminal._read_interactive_input_async", read_input)
    monkeypatch.setattr("nanobot.cli.terminal._print_agent_response", print_response)

    result = runner.invoke(app, ["agent", "--classic", "--session", "cli:journey"])

    assert result.exit_code == 0, result.output
    inbound = seen["inbound"]
    assert isinstance(inbound, InboundMessage)
    assert (inbound.channel, inbound.chat_id, inbound.content) == (
        "cli",
        "journey",
        "hello nanobot",
    )
    assert inbound.metadata == {"_wants_stream": True}
    loop = seen["loop"]
    assert isinstance(loop, _AgentLoop)
    assert loop.aclose_calls == 1
    assert len(renderers) == 1
    renderer = renderers[0]
    assert isinstance(renderer, _Renderer)
    if streamed:
        assert renderer.deltas == ["hello ", "world"]
        assert renderer.ends == [False]
        assert renderer.closed == 0
        print_response.assert_not_called()
    else:
        assert renderer.deltas == []
        assert renderer.closed == 1
        print_response.assert_called_once_with(
            "hello world",
            render_markdown=True,
            metadata={},
        )
