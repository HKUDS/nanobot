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


@pytest.mark.parametrize("target", ["ro", "media"])
@pytest.mark.parametrize("ancestor", ["tree", "tree/branch"])
async def test_native_readonly_ancestor_cannot_be_renamed(layout, target, ancestor):
    workspace = layout["workspace"]
    protected = workspace / "tree" / "branch" / "readonly"
    protected.mkdir(parents=True)
    sentinel = protected / "sentinel"
    sentinel.write_text("synthetic-readonly")
    layout[target] = protected
    moved_sentinel = Path("shifted") / protected.relative_to(workspace / ancestor) / "sentinel"

    result = await run_script(
        layout,
        f"mv {ancestor} shifted && printf changed > {shlex.quote(str(moved_sentinel))}",
    )

    assert "Operation not permitted" in result
    assert sentinel.read_text() == "synthetic-readonly"
    assert not (workspace / "shifted").exists()


async def test_native_readonly_ancestor_keeps_other_children_writable(layout):
    workspace = layout["workspace"]
    protected = workspace / "tree" / "readonly"
    protected.mkdir(parents=True)
    layout["ro"] = protected

    result = await run_script(
        layout,
        "mkdir tree/sibling && printf writable > tree/sibling/file && "
        "mv tree/sibling tree/renamed && rm tree/renamed/file && rmdir tree/renamed",
    )

    assert result == "\nExit code: 0"
    assert protected.is_dir()
    assert not (workspace / "tree" / "renamed").exists()


@pytest.mark.parametrize("override", ["root", "parent", "child"])
async def test_native_rw_override_preserves_readonly_ancestor_policy(layout, override):
    workspace = layout["workspace"]
    protected = workspace / "tree" / "readonly"
    writable = protected / "cache"
    writable.mkdir(parents=True)
    layout["ro"] = protected
    layout["rw"] = {"root": protected, "parent": protected.parent, "child": writable}[override]

    result = await run_script(layout, "printf writable > tree/readonly/cache/file")
    assert result == "\nExit code: 0"
    assert (writable / "file").read_text() == "writable"

    result = await run_script(layout, "mv tree shifted")
    if override == "child":
        assert "Operation not permitted" in result
        assert protected.is_dir()
    else:
        assert result == "\nExit code: 0"
        assert (workspace / "shifted" / "readonly" / "cache" / "file").read_text() == "writable"


@pytest.mark.parametrize("cwd_kind", ["missing", "file"])
@pytest.mark.parametrize("separator", ["; ", "\n", " || "])
async def test_native_failed_cwd_does_not_execute_shell_list(layout, cwd_kind, separator):
    workspace = layout["workspace"]
    cwd = workspace / "unusable"
    if cwd_kind == "file":
        cwd.write_text("not-a-directory")
    tool = ExecTool(working_dir=str(workspace), sandbox="seatbelt")

    result = str(await tool.execute(
        command=f"printf first > first{separator}printf second > second",
        working_dir=str(cwd), timeout=5,
    ))

    assert "cd:" in result
    assert not result.endswith("Exit code: 0")
    assert not (workspace / "first").exists()
    assert not (workspace / "second").exists()


async def test_native_nested_cwd_runs_complete_shell_list(layout):
    workspace = layout["workspace"]
    cwd = workspace / "nested 'directory"
    cwd.mkdir()
    tool = ExecTool(working_dir=str(workspace), sandbox="seatbelt")

    result = str(await tool.execute(
        command="printf first > first; printf second > second",
        working_dir=str(cwd), timeout=5,
    ))

    assert result == "\nExit code: 0"
    assert (cwd / "first").read_text() == "first"
    assert (cwd / "second").read_text() == "second"
    assert not (workspace / "second").exists()


@pytest.mark.parametrize("override", ["root", "parent"])
async def test_native_rw_override_respects_volume_case_sensitivity(layout, override):
    workspace = layout["workspace"]
    protected = workspace / "Tree" / "ReadOnly"
    protected.mkdir(parents=True)
    sentinel = protected / "sentinel"
    sentinel.write_text("synthetic-readonly")
    alias = workspace / "tree" / "readonly"
    alias.mkdir(parents=True, exist_ok=True)
    same_directory = alias.samefile(protected)
    layout["ro"] = protected
    layout["rw"] = alias if override == "root" else alias.parent

    result = await run_script(layout, "printf writable > tree/readonly/other")
    assert result == "\nExit code: 0"
    result = await run_script(layout, "mv Tree shifted")

    if same_directory:
        assert result == "\nExit code: 0"
        assert (workspace / "shifted" / "ReadOnly" / "other").read_text() == "writable"
    else:
        # On a case-sensitive volume the distinct RW directory must not remove
        # protection from Tree/ReadOnly, even though its spelling differs only by case.
        assert "Operation not permitted" in result
        assert sentinel.read_text() == "synthetic-readonly"
