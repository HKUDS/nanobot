import pytest
from prompt_toolkit.document import Document
from rich.console import Console

from nanobot.cli import commands as cli_commands
from nanobot.cli.tui.activity import format_activity_rows
from nanobot.cli.tui.app import should_use_tui
from nanobot.cli.tui.commands import SlashCommandCompleter, command_palette_text
from nanobot.cli.tui.render import render_startup
from nanobot.cli.tui.state import CliTuiState


def test_format_activity_rows_formats_tool_and_file_events() -> None:
    rows = format_activity_rows(
        {
            "_tool_events": [
                {
                    "phase": "start",
                    "name": "exec",
                    "arguments": {"command": "pytest tests/test_example.py", "cwd": "/tmp/project"},
                },
                {
                    "phase": "end",
                    "name": "read_file",
                    "arguments": {"path": "README.md"},
                    "result": {"summary": "read 12 lines"},
                },
            ],
            "_file_edit_events": [
                {"phase": "end", "path": "nanobot/a.py", "added": 3, "deleted": 1},
            ],
        }
    )

    assert rows == [
        "[bright_black]●[/bright_black] [bold]Running[/bold] pytest tests/test_example.py",
        "[green]●[/green] [bold]Read[/bold] README.md\n"
        "  [dim]└ read 12 lines[/dim]",
        "[green]●[/green] [bold]Edited[/bold] nanobot/a.py\n"
        "  [dim]└ +3 -1[/dim]",
    ]


def test_format_activity_rows_skips_start_events_when_requested() -> None:
    rows = format_activity_rows(
        {
            "_tool_events": [
                {"phase": "start", "name": "exec", "arguments": {"command": "ls"}},
                {
                    "phase": "end",
                    "name": "read_file",
                    "arguments": {"path": "README.md"},
                    "result": {"summary": "read 12 lines"},
                },
            ],
            "_file_edit_events": [
                {"phase": "start", "path": "nanobot/a.py"},
                {"phase": "end", "path": "nanobot/a.py", "added": 3, "deleted": 1},
            ],
        },
        include_start=False,
    )

    assert rows == [
        "[green]●[/green] [bold]Read[/bold] README.md\n  [dim]└ read 12 lines[/dim]",
        "[green]●[/green] [bold]Edited[/bold] nanobot/a.py\n  [dim]└ +3 -1[/dim]",
    ]


def test_format_activity_rows_summarizes_list_dir_results() -> None:
    rows = format_activity_rows(
        {
            "_tool_events": [
                {
                    "phase": "end",
                    "name": "list_dir",
                    "arguments": {"path": "."},
                    "result": (
                        "📄 .gitignore\n"
                        "📄 AGENTS.md\n"
                        "📁 nanobot\n"
                        "📁 tests\n"
                        "📄 pyproject.toml\n"
                    ),
                },
            ],
        }
    )

    assert rows == [
        "[green]●[/green] [bold]Explored[/bold] .\n"
        "  [dim]└ 5 entries[/dim]\n"
        "  [dim]└ .gitignore, AGENTS.md, nanobot, tests, +1 more[/dim]",
    ]


def test_should_use_tui_respects_flags(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    assert should_use_tui(classic=False, no_tui=False) is True
    assert should_use_tui(classic=True, no_tui=False) is False
    assert should_use_tui(classic=False, no_tui=True) is False


def test_command_palette_text_is_terminal_integrated() -> None:
    idle = command_palette_text("")
    palette = command_palette_text("/")
    framed_palette = command_palette_text("/", width=80)

    assert "/new" in palette
    assert "New chat" not in idle
    assert "commands" in idle
    assert "shortcuts" not in idle
    assert "\n" in palette
    assert framed_palette.startswith("─" * 8)
    assert "/new" in framed_palette


def test_slash_command_completer_filters_commands() -> None:
    completions = list(
        SlashCommandCompleter().get_completions(
            Document("/d", cursor_position=2),
            None,
        )
    )
    texts = [completion.text for completion in completions]

    assert "/dream" in texts
    assert "/dream-log" in texts
    assert "/diff" in texts
    assert "/new" not in texts
    assert all(completion.start_position == -2 for completion in completions)


def test_render_startup_omits_cat_logo(tmp_path) -> None:
    console = Console(record=True, force_terminal=False)

    render_startup(
        console,
        CliTuiState(
            model="test-model",
            preset="primary",
            workspace=tmp_path,
            access_mode="restricted",
            session_id="cli:direct",
        ),
    )

    out = console.export_text()
    assert "nanobot v" in out
    assert "test-model" in out
    assert "🐈" not in out
    assert "_ __" not in out


@pytest.mark.asyncio
async def test_stream_mcp_startup_log_prints_plain_log_lines(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "mcp.log"
    log_path.write_text("[TOOLS] Configuration loaded\n", encoding="utf-8")
    done = cli_commands.asyncio.Event()
    done.set()
    console = Console(record=True, force_terminal=False)
    monkeypatch.setattr(cli_commands, "console", console)

    await cli_commands._stream_mcp_startup_log(log_path, done)

    assert "[TOOLS] Configuration loaded" in console.export_text()
