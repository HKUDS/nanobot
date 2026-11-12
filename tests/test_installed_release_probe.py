"""Protect the real release probe from accepting an incomplete built frontend."""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_installed_release import (
    _wait_for_closed_listeners,
    gateway_probe,
    host_environment,
    webui_assets,
)


def test_probe_waits_for_listener_teardown_after_redirector_exit(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        # A still-live listener cannot count as cleaned up.
        with pytest.raises(ValueError, match="listener remained reachable"):
            _wait_for_closed_listeners((port,), timeout=0)
        # Model the kernel completing teardown after the first observation.
        monkeypatch.setattr("scripts.verify_installed_release.time.sleep", lambda _: listener.close())
        _wait_for_closed_listeners((port,))


def test_isolation_retains_windows_cpu_identity_without_developer_paths():
    environment = {"SYSTEMROOT": r"C:\Windows", "PROCESSOR_ARCHITECTURE": "AMD64",
                   "PROCESSOR_ARCHITEW6432": "AMD64", "PATH": r"C:\dev\bun",
                   "PYTHONPATH": r"C:\checkout", "NANOBOT_TUI_BIN": r"C:\old\tui.exe"}
    expected = {key: environment[key] for key in (
        "SYSTEMROOT", "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432",
    )}
    assert host_environment(environment) == expected
    # The installer and installed-package probe apply this boundary separately.
    assert host_environment(host_environment(environment)) == expected


@pytest.fixture
def frontend(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("entry.js", "lazy.js", "style.css"):
        (assets / name).write_text("compiled content", encoding="utf-8")
    manifest = {
        "index.html": {"file": "assets/entry.js", "css": ["assets/style.css"],
                       "dynamicImports": ["settings"]},
        "settings": {"file": "assets/lazy.js", "imports": ["index.html"]},
    }
    (tmp_path / "index.html").write_text('<script src="/assets/entry.js"></script>')
    (tmp_path / "asset-manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_manifest_covers_lazy_assets_not_only_initial_html(frontend):
    assert webui_assets(frontend) == {"assets/entry.js", "assets/lazy.js", "assets/style.css"}
    (frontend / "assets/lazy.js").unlink()
    with pytest.raises(ValueError, match="Missing or empty.*lazy.js"):
        webui_assets(frontend)


def test_missing_import_record_fails_even_if_entrypoint_exists(frontend):
    path = frontend / "asset-manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["settings"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Missing WebUI manifest dependency"):
        webui_assets(frontend)


def test_stale_html_cannot_pass_against_an_unrelated_manifest(frontend):
    (frontend / "index.html").write_text('<script src="/assets/old.js"></script>')
    with pytest.raises(ValueError, match="HTML entrypoints"):
        webui_assets(frontend)


@pytest.mark.parametrize("options", [[], ["--gateway"]])
def test_probe_requires_isolated_python_before_importing_source(tmp_path, options):
    script = Path(__file__).resolve().parents[1] / "scripts/verify_installed_release.py"
    report = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, str(script), "--version", "0.3.6.dev1", "--commit", "a" * 40,
         "--report", str(report), *options], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "python -I" in result.stderr
    assert not report.exists()


def test_gateway_probe_reports_failed_cli_start_and_reaps_its_child(tmp_path, monkeypatch, capsys):
    popen = subprocess.Popen
    children = []

    def failed_cli(command, **kwargs):
        # A missing runtime dependency makes the installed CLI exit before binding.
        child = popen([command[0], "-I", "-c",
                       "print('candidate startup failed'); raise SystemExit(7)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", failed_cli)
    with pytest.raises(ValueError, match="exited before readiness: 7"):
        gateway_probe("0.3.6.dev1", tmp_path / "gateway")
    assert len(children) == 1 and children[0].poll() == 7
    assert "candidate startup failed" in capsys.readouterr().err
