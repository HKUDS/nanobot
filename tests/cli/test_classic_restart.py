"""Classic restart delivery, cleanup and canonical entrypoint handoff."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import typer

from nanobot.agent.loop import AgentLoop
from nanobot.cli import entry
from nanobot.config.schema import Config
from nanobot.session.manager import Session
from nanobot.session.state import SessionState
from nanobot.utils.restart import RestartController, RestartTicket, consume_restart_notice_from_env


@pytest.fixture
def classic_runtime(tmp_path, monkeypatch):
    cli_agent = importlib.import_module("nanobot.cli.agent")
    events = []
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.gateway.restart_mode = "spawn"
    home = tmp_path / "instance"
    config_path = home / "config.json"
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    sessions = MagicMock()
    sessions.state = MagicMock(spec=SessionState)
    sessions.state.get = AsyncMock(side_effect=lambda key: Session(key))
    sessions.state.peek.return_value = None
    sessions.state.peek_header.return_value = None
    subagents = MagicMock(close=AsyncMock())
    monkeypatch.setattr("nanobot.agent.loop.ContextBuilder", MagicMock())
    monkeypatch.setattr("nanobot.agent.loop.SessionManager", lambda *_args: sessions)
    monkeypatch.setattr("nanobot.agent.loop.SubagentManager", lambda **_kwargs: subagents)
    controllers = []

    class RecordingRestart(RestartController):
        def __init__(self):
            super().__init__()
            controllers.append(self)

        def request(self):
            ticket = super().request()
            assert ticket is not None
            events.append("requested")

            def commit():
                events.append("committed")
                ticket.commit()

            return RestartTicket(commit)

    monkeypatch.setattr("nanobot.utils.restart.RestartController", RecordingRestart)

    def from_config(_config, bus, **kwargs):
        loop = AgentLoop(bus, provider, config.workspace_path, restart_request=kwargs["restart_request"])
        close = loop.aclose

        async def aclose():
            await close()
            events.append("agent closed")

        loop.aclose = aclose
        return loop

    monkeypatch.setattr(cli_agent, "AgentLoop", SimpleNamespace(from_config=from_config))
    monkeypatch.setattr(cli_agent, "_load_runtime_config", lambda *_args: config)
    monkeypatch.setattr(cli_agent, "sync_workspace_templates", lambda *_args: None)
    monkeypatch.setattr(cli_agent, "is_default_workspace", lambda *_args: False)
    monkeypatch.setattr(cli_agent, "_set_nanobot_logs", lambda *_args: None)
    monkeypatch.setattr(cli_agent, "_model_display", lambda *_args: ("test-model", ""))
    monkeypatch.setattr(cli_agent, "consume_restart_notice_from_env", lambda: None)
    monkeypatch.setattr(cli_agent, "sys", SimpleNamespace(stdout=SimpleNamespace(flush=lambda: events.append("flushed"))))
    monkeypatch.setattr("nanobot.providers.factory.make_provider", lambda *_args: provider)
    monkeypatch.setattr("nanobot.agent.tools.image_generation.register_image_generation_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda *_args: object())

    async def close_mcp():
        events.append("MCP closed")

    mcp = SimpleNamespace(connect=AsyncMock(), aclose=AsyncMock(side_effect=close_mcp))
    monkeypatch.setattr("nanobot.agent.tools.mcp.MCPProvider.from_config", lambda *_args: mcp)
    renderer = SimpleNamespace(streamed=False, header_printed=False, close=AsyncMock(),
                               on_delta=AsyncMock(), on_end=AsyncMock(), stop_for_input=lambda: None)
    monkeypatch.setattr(cli_agent, "StreamRenderer", lambda **_kwargs: renderer)
    monkeypatch.setattr("nanobot.cli.terminal._init_prompt_session", lambda: None)
    monkeypatch.setattr("nanobot.cli.terminal._flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("nanobot.cli.terminal._restore_terminal", lambda: events.append("terminal restored"))
    monkeypatch.setattr(cli_agent.signal, "signal", lambda *_args: cli_agent.signal.SIG_DFL)
    read_input = AsyncMock(side_effect=["/restart", AssertionError("Restart must not read another prompt")])
    monkeypatch.setattr("nanobot.cli.terminal._read_interactive_input_async", read_input)

    def print_response(content, **_kwargs):
        assert not controllers[0].committed
        assert content == "Restarting..."
        events.append("printed")

    monkeypatch.setattr("nanobot.cli.terminal._print_agent_response", print_response)
    monkeypatch.setattr("nanobot.config.home.get_home_path", lambda: home)
    monkeypatch.setattr("nanobot.config.home.get_selected_home_path", lambda: home)
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: home)

    @contextmanager
    def lease(name):
        events.append(name + " acquired")
        try:
            yield
        finally:
            events.append(name + " released")

    monkeypatch.setattr(entry, "installation_access", lambda **_kwargs: lease("installation"))
    monkeypatch.setattr("nanobot.data_access.data_access", lambda *_args: lease("data"))
    replacements = []

    def replace(argv, **kwargs):
        events.append("replacement")
        replacements.append((argv, kwargs))

    monkeypatch.setattr("nanobot.utils.restart.replace_process", replace)
    for key in ("NANOBOT_RESTART_NOTIFY_CHANNEL", "NANOBOT_RESTART_NOTIFY_CHAT_ID",
                "NANOBOT_RESTART_NOTIFY_METADATA", "NANOBOT_RESTART_STARTED_AT"):
        monkeypatch.delenv(key, raising=False)
    return SimpleNamespace(agent=cli_agent.agent, events=events, config=config, home=home,
                           config_path=config_path, replacements=replacements,
                           read_input=read_input, controllers=controllers)


@pytest.mark.parametrize("interactive", [False, True])
def test_classic_restart_flushes_reply_and_cleans_up_before_canonical_relaunch(
    classic_runtime, monkeypatch, interactive,
):
    runtime = classic_runtime
    args = ["--classic", "--session", "cli:journey", "--no-markdown", "--logs",
            "--config", str(runtime.config_path), "--workspace", str(runtime.config.workspace_path)]
    if not interactive:
        args += ["--message", "/restart"]
    app = typer.Typer(add_completion=False)
    app.command()(runtime.agent)
    command = typer.main.get_command(app)
    monkeypatch.setattr(entry.sys, "argv", ["nanobot", "agent", *args])
    monkeypatch.setattr(entry, "_dispatch", lambda: command.main(args=args, standalone_mode=False))

    entry.main()

    events = runtime.events
    assert events.index("requested") < events.index("printed") < events.index("flushed") < events.index("committed")
    assert events.index("committed") < events.index("agent closed") < events.index("MCP closed")
    assert events.index("MCP closed") < events.index("data released") < events.index("installation released") < events.index("replacement")
    if interactive:
        assert events.index("MCP closed") < events.index("terminal restored") < events.index("data released")
        runtime.read_input.assert_awaited_once()
    else:
        runtime.read_input.assert_not_awaited()
    assert runtime.controllers[0].committed
    assert len(runtime.replacements) == 1
    argv, options = runtime.replacements[0]
    assert argv == [entry.sys.executable, "-m", "nanobot", "--home", str(runtime.home),
                    "agent", "--classic", "--session", "cli:journey", "--no-markdown", "--logs",
                    "--config", str(runtime.config_path), "--workspace", str(runtime.config.workspace_path)]
    assert options == {"mode": "spawn", "cwd": Path.cwd()}
    notice = consume_restart_notice_from_env()
    assert notice is not None
    assert (notice.channel, notice.chat_id) == ("cli", "journey")


def test_classic_output_failure_cleans_up_without_committing_or_relaunching(classic_runtime, monkeypatch):
    runtime = classic_runtime

    def fail_print(*_args, **_kwargs):
        raise BrokenPipeError("output was closed")

    monkeypatch.setattr("nanobot.cli.terminal._print_agent_response", fail_print)
    with pytest.raises(BrokenPipeError):
        runtime.agent(message="/restart", session_id="cli:journey", workspace=None,
                      config=None, markdown=False, logs=False, classic=True, theme="auto")

    assert "requested" in runtime.events
    assert not runtime.controllers[0].committed
    assert runtime.events[-3:] == ["agent closed", "MCP closed", "data released"]
    assert runtime.replacements == []
