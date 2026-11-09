import os
import subprocess
import sys
from pathlib import Path

import pytest

from nanobot.cli import entry
from nanobot.cli.entry import _agent_invocation_args, _native_tui_candidate
from nanobot.installation_lock import InstallationBusyError, installation_access, installation_id


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
        ["--home", "./instance", "onboard"],
        ["--home=./instance", "webui"],
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
    monkeypatch.setattr(entry, "configure_windows_console", lambda: None)
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


def test_desktop_handled_bare_invocation_does_not_start_python(monkeypatch) -> None:
    from nanobot.cli import desktop_target

    monkeypatch.setattr(entry.sys, "argv", ["nanobot"])
    monkeypatch.setattr(entry, "set_cli_process_identity", lambda _args: None)
    monkeypatch.setattr(entry, "configure_windows_console", lambda: None)
    monkeypatch.setattr(desktop_target, "dispatch_bare_desktop_target", lambda _args: 0)
    monkeypatch.setattr(
        entry,
        "_run_agent",
        lambda *_args, **_kwargs: pytest.fail("Python agent must not start"),
    )

    entry.main()


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


def test_entry_refuses_dispatch_during_update(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "environment"))
    monkeypatch.setattr(sys, "argv", ["nanobot", "gateway"])
    monkeypatch.setattr(entry, "_dispatch", lambda: pytest.fail("Runtime dispatched during update"))
    with installation_access(updating=True):
        with pytest.raises(SystemExit) as result:
            entry.main()
    assert result.value.code == 1
    assert "being updated" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["update"], ["--home", "/test", "update"], ["--home=/test", "update"]])
def test_update_command_can_reach_its_own_lease_and_recovery(tmp_path, monkeypatch, args):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "environment"))
    monkeypatch.setattr(sys, "argv", ["nanobot", *args])
    called = []
    monkeypatch.setattr(entry, "_dispatch", lambda: called.append(True))
    with installation_access(updating=True):
        entry.main()
    assert called == [True]


@pytest.mark.parametrize("args", [["update", "--job", "saved-id"],
                                 ["--home=/test", "update", "--job=saved-id", "--retry-handoff"]])
def test_saved_update_recovery_owns_runtime_before_application_imports(tmp_path, monkeypatch, args):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "environment"))
    monkeypatch.setattr(sys, "argv", ["nanobot", *args])
    entered = []

    def dispatch():
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True):
                pytest.fail("Recovery imported without a runtime lease")
        entered.append(True)

    monkeypatch.setattr(entry, "_dispatch", dispatch)
    entry.main()
    assert entered == [True]
    with installation_access(updating=True):
        with pytest.raises(SystemExit):
            entry.main()
    assert entered == [True]


@pytest.mark.parametrize("action,allowed", [("stop", True), ("status", True), ("logs", True), ("restart", False)])
def test_interrupted_installation_keeps_stop_commands_usable(tmp_path, monkeypatch, action, allowed):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "environment"))
    pending = tmp_path / ".nanobot/run" / f"update-{installation_id()[:16]}.pending"
    pending.parent.mkdir(parents=True)
    pending.write_text("incomplete")
    monkeypatch.setattr(sys, "argv", ["nanobot", "--home", str(tmp_path / "profile"), "gateway", action])
    called = []
    monkeypatch.setattr(entry, "_dispatch", lambda: called.append(True))
    if allowed:
        entry.main()
        assert called == [True]
    else:
        with pytest.raises(SystemExit):
            entry.main()
        assert not called
