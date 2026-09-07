"""Exercise the kernel policy, not merely the presence of SBPL text.

Linux/Windows CI retain the portable generation tests in test_sandbox.py.
These native tests use only isolated fixtures and a loopback HTTP service.
"""

import shlex
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from nanobot.agent.tools.shell import ExecTool

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("sandbox-exec") is None,
    reason="requires native macOS Seatbelt",
)


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    # A separate host /tmp root must not inherit the workspace-parent deny.
    with tempfile.TemporaryDirectory(prefix="nanobot-seatbelt-peer-", dir="/tmp") as peer:
        paths = {
            "workspace": root / 'project with "quotes',
            "config": root / "config.json",
            "media": root / "media",
            "peer": Path(peer).resolve(),
        }
        paths["workspace"].mkdir()
        paths["media"].mkdir()
        paths["config"].write_text("synthetic-config")
        paths["ro"] = paths["workspace"] / "readonly"
        paths["ro"].mkdir()
        paths["rw"] = paths["peer"] / "cache"
        paths["rw"].mkdir()
        for name in ("workspace", "media", "peer", "ro", "rw"):
            (paths[name] / "sentinel").write_text("synthetic-data")
        paths["link"] = paths["workspace"] / "outside-link"
        paths["link"].symlink_to(paths["peer"], target_is_directory=True)
        monkeypatch.setattr("nanobot.agent.tools.sandbox.get_media_dir", lambda: paths["media"])
        yield paths


async def run_script(paths, script):
    workspace = paths["workspace"]
    (workspace / "probe.sh").write_text(script)
    tool = ExecTool(
        working_dir=str(workspace), sandbox="seatbelt",
        sandbox_ro_binds=[str(paths["ro"])], sandbox_rw_binds=[str(paths["rw"])],
    )
    # Scripts are legitimate exec input; the kernel must enforce their effects.
    return str(await tool.execute(command="sh probe.sh", timeout=5))


@pytest.mark.parametrize("target", ["workspace", "media", "ro", "rw"])
async def test_native_allowed_reads(layout, target):
    result = await run_script(layout, f"cat {shlex.quote(str(layout[target] / 'sentinel'))}")
    assert result == "synthetic-data\n\nExit code: 0"


@pytest.mark.parametrize("target", ["config", "peer", "link"])
async def test_native_outside_reads_denied(layout, target):
    path = layout[target] if target == "config" else layout[target] / "sentinel"
    result = await run_script(layout, f"cat {shlex.quote(str(path))}")
    assert "Operation not permitted" in result
    assert "synthetic-" not in result


@pytest.mark.parametrize("target", ["workspace", "rw"])
async def test_native_explicit_writes_allowed(layout, target):
    path = layout[target] / "sentinel"
    result = await run_script(layout, f"printf changed > {shlex.quote(str(path))}")
    assert result == "\nExit code: 0"
    assert path.read_text() == "changed"


@pytest.mark.parametrize("target", ["config", "peer", "link", "ro", "media"])
async def test_native_other_writes_denied(layout, target):
    path = layout[target] if target == "config" else layout[target] / "sentinel"
    before = path.read_text()
    result = await run_script(layout, f"printf changed > {shlex.quote(str(path))}")
    assert "Operation not permitted" in result
    assert path.read_text() == before


async def test_native_scratch_and_home_stay_in_workspace(layout):
    # Apple mktemp with no template prefers confstr's host temp directory even
    # when TMPDIR is set. Use an explicit template; do not expose host scratch.
    result = await run_script(
        layout, 'printf "%s\\n" "$HOME"; mktemp "$TMPDIR/probe.XXXXXX" && printf ok > /dev/null',
    )
    assert "STDERR" not in result
    assert result.endswith("Exit code: 0")
    assert all(line.startswith(str(layout["workspace"])) for line in result.splitlines()[:2])


async def test_native_system_git_starts(layout):
    result = await run_script(layout, "git --version")
    assert "git version " in result
    assert result.endswith("Exit code: 0")


async def test_native_launcher_cannot_be_shadowed_by_project_path(layout):
    workspace = layout["workspace"]
    impostor = workspace / "sandbox-exec"
    impostor.write_text("#!/bin/sh\nprintf shadowed-launcher")
    impostor.chmod(0o700)
    tool = ExecTool(
        working_dir=str(workspace), sandbox="seatbelt", path_prepend=str(workspace),
    )
    result = str(await tool.execute(command="printf real-sandbox", timeout=5))
    assert result == "real-sandbox\n\nExit code: 0"


async def test_native_network_remains_available(layout):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"network-ok")

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = await run_script(
                layout, f"curl --noproxy '*' --max-time 2 -sS http://127.0.0.1:{server.server_port}",
            )
            assert result == "network-ok\n\nExit code: 0"
        finally:
            server.shutdown()
            thread.join(timeout=3)
