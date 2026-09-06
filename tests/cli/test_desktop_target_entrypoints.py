"""The picker covers retained launchers without intercepting explicit commands."""

import pytest
from typer.testing import CliRunner

from nanobot.cli import commands, desktop_target, entry


@pytest.mark.parametrize("args", [[], ["webui"]])
def test_retained_launcher_attaches_without_starting_python(monkeypatch, args):
    seen = []

    def dispatch(raw):
        seen.append(raw)
        return 0

    monkeypatch.setattr(desktop_target, "dispatch_bare_desktop_target", dispatch)
    monkeypatch.setattr(entry, "_run_agent", lambda *_a, **_kw: pytest.fail("agent started"))
    # Callback exits before webui can inspect/load config or start its runtime.
    monkeypatch.setattr(
        "nanobot.cli.webui._resolve_webui_config_path",
        lambda *_a, **_kw: pytest.fail("Python WebUI started"),
    )
    result = CliRunner().invoke(commands.app, args)
    assert result.exit_code == 0, result.output
    assert seen == [args]


@pytest.mark.parametrize("args", [["agent", "--help"], ["--help"], ["--version"],
                                  ["webui", "--no-open"], ["webui", "--port", "8765"]])
def test_retained_launcher_explicit_commands_never_discover(monkeypatch, args):
    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(
        desktop_target, "discover_desktop_target", lambda: pytest.fail("explicit discovery")
    )
    class PythonWebuiReachedError(Exception):
        pass

    def stop_webui(*_args, **_kwargs):
        raise PythonWebuiReachedError

    monkeypatch.setattr("nanobot.cli.webui._resolve_webui_config_path", stop_webui)
    result = CliRunner().invoke(commands.app, args)
    if args[0] == "webui":
        assert isinstance(result.exception, PythonWebuiReachedError), result.output
    else:
        assert result.exit_code == 0, result.output


def test_modern_webui_invocation_prompts_once(monkeypatch):
    calls = []

    def dispatch(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(desktop_target, "dispatch_bare_desktop_target", dispatch)
    monkeypatch.setattr(entry.sys, "argv", ["nanobot", "webui"])
    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 0
    assert calls == [["webui"]]
