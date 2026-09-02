import os
import subprocess
import sys
from pathlib import Path

from nanobot.cli import entry
from nanobot.cli.entry import _agent_invocation_args, _native_tui_candidate


def test_root_command_routes_to_agent_without_copying_agent_options() -> None:
    assert _agent_invocation_args([]) == []
    assert _agent_invocation_args(["agent", "--theme", "dark"]) == ["--theme", "dark"]
    assert _agent_invocation_args(["--workspace", "./project"]) == [
        "--workspace",
        "./project",
    ]
    assert _agent_invocation_args(["-mhello"]) == ["-mhello"]


def test_root_metadata_and_subcommands_keep_the_root_cli() -> None:
    for args in (
        ["--help"],
        ["--version"],
        ["--install-completion"],
        ["gateway"],
        ["webui"],
    ):
        assert _agent_invocation_args(args) is None


def test_root_shell_completion_keeps_root_subcommands() -> None:
    env = os.environ.copy()
    env.update(
        {
            "_NANOBOT_COMPLETE": "complete_bash",
            "COMP_WORDS": "nanobot ",
            "COMP_CWORD": "1",
        }
    )
    script = (
        "import sys; "
        "from nanobot.cli.entry import main; "
        "sys.argv = ['nanobot']; "
        "main()"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert {"agent", "gateway", "webui"} <= set(result.stdout.splitlines())
    assert "not supported" not in result.stderr


def test_root_alias_dispatches_the_shared_agent_command(monkeypatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(entry.sys, "argv", ["nanobot", "-m", "hello"])
    monkeypatch.setattr(
        entry,
        "set_cli_process_identity",
        lambda args: calls.__setitem__("identity", args),
    )
    monkeypatch.setattr(entry, "_configure_windows_console", lambda: None)
    monkeypatch.setattr(
        entry,
        "_run_agent",
        lambda args, *, prog_name: calls.update(args=args, prog_name=prog_name),
    )

    entry.main()

    assert calls == {
        "identity": ["agent", "-m", "hello"],
        "args": ["-m", "hello"],
        "prog_name": "nanobot",
    }


def test_native_agent_invocations_use_the_lightweight_entrypoint() -> None:
    assert _native_tui_candidate(["agent"])
    assert _native_tui_candidate(["agent", "--session", "websocket:chat"])
    assert _native_tui_candidate(["agent", "--theme=light"])


def test_classic_and_one_shot_agent_invocations_keep_the_full_cli_entrypoint() -> None:
    assert not _native_tui_candidate(["agent", "--classic"])
    assert not _native_tui_candidate(["agent", "-m", "hello"])
    assert not _native_tui_candidate(["agent", "-mhello"])
    assert not _native_tui_candidate(["agent", "--message=hello"])
    assert not _native_tui_candidate(["status"])
