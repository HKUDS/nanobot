"""Credential-bearing browser URLs must not enter a macOS command line."""

import ctypes
import subprocess
from unittest.mock import MagicMock

import pytest

from nanobot.cli import desktop_target, webui_support


@pytest.fixture
def macos_url_services(monkeypatch):
    foundation = MagicMock()
    services = MagicMock()
    foundation.CFURLCreateWithBytes.return_value = 123
    services.LSOpenCFURLRef.return_value = 0

    def load(path):
        if path == "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation":
            return foundation
        assert path == "/System/Library/Frameworks/CoreServices.framework/CoreServices"
        return services

    monkeypatch.setattr(ctypes, "CDLL", load)
    monkeypatch.setattr(webui_support.sys, "platform", "darwin")
    monkeypatch.setenv("BROWSER", "unsafe-browser %s")
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_kw: pytest.fail("URL reached subprocess")
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_a, **_kw: pytest.fail("URL reached process argv")
    )
    monkeypatch.setattr(
        webui_support.webbrowser, "open", lambda *_a, **_kw: pytest.fail("unsafe browser fallback")
    )
    return foundation, services


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/",
    "http://127.0.0.1:8765/#/?bootstrapSecret=synthetic-only",
    "http://localhost:5173/#/?bootstrapSecret=quote%22%27%24%28%29%26",
    "http://[::1]:8765/#/中文?bootstrapSecret=synthetic-only",
])
def test_macos_uses_os_url_events_without_process_arguments(macos_url_services, capsys, url):
    foundation, services = macos_url_services
    assert webui_support._launch_browser(url) is True
    encoded = url.encode("utf-8")
    foundation.CFURLCreateWithBytes.assert_called_once_with(
        None, encoded, len(encoded), 0x08000100, None
    )
    services.LSOpenCFURLRef.assert_called_once_with(123, None)
    foundation.CFRelease.assert_called_once_with(123)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure", ["load", "symbol", "create", "open", "exception", "encoding"])
def test_macos_browser_failures_never_fall_back_or_log_url(
    macos_url_services, monkeypatch, capsys, failure,
):
    foundation, services = macos_url_services
    url = "http://localhost/#/?bootstrapSecret=synthetic-only"
    if failure in {"load", "symbol"}:
        error_type = OSError if failure == "load" else AttributeError
        monkeypatch.setattr(ctypes, "CDLL", MagicMock(side_effect=error_type(url)))
    elif failure == "create":
        foundation.CFURLCreateWithBytes.return_value = None
    elif failure == "open":
        services.LSOpenCFURLRef.return_value = -50
    elif failure == "exception":
        services.LSOpenCFURLRef.side_effect = OSError(url)
    else:
        url += "\ud800"
    assert webui_support._launch_browser(url) is False
    assert capsys.readouterr() == ("", "")
    if failure in {"open", "exception"}:
        foundation.CFRelease.assert_called_once_with(123)
    else:
        foundation.CFRelease.assert_not_called()


@pytest.mark.parametrize("launch_status, exit_code", [(0, 0), (-50, 3)])
def test_desktop_handoff_uses_the_protected_shared_launcher(
    macos_url_services, monkeypatch, capsys, launch_status, exit_code,
):
    foundation, services = macos_url_services
    services.LSOpenCFURLRef.return_value = launch_status
    url = "http://localhost:8765/#/?bootstrapSecret=synthetic-only"
    calls = []

    class Target:
        def request(self, operation):
            calls.append(operation)
            return desktop_target.DesktopReply(
                "ready", frozenset({"webui"}), url if operation == "webui" else None,
            )

    monkeypatch.setattr(desktop_target, "_interactive_shell", lambda: True)
    monkeypatch.setattr(desktop_target, "discover_desktop_target", Target)
    monkeypatch.setattr(desktop_target, "_choose_target", lambda _: "desktop")
    assert desktop_target.dispatch_bare_desktop_target(["webui"]) == exit_code
    assert calls == ["status", "webui"]
    assert foundation.CFURLCreateWithBytes.call_args.args[1] == url.encode()
    output = capsys.readouterr()
    assert "synthetic-only" not in output.out + output.err
    assert "Using current Python" not in output.out
