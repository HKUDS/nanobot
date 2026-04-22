"""Subprocess-tree cleanup tests for ExecTool (MIT-162).

The exec tool used to leak subprocess trees when a tool call ended: on
timeout, cancel, or even success the Python-level ``proc.kill()`` only
signalled the immediate child (``bash -l -c ...``), leaving grandchildren
reparented to init/PID 1 and running until they felt like it. A real
session watched a ``sudo nmap ... | head`` tree live 94 minutes past the
tool call that spawned it.

These tests exercise the fix:

  1. ``start_new_session=True`` on Unix so the child gets its own PGID,
  2. SIGKILL on the whole PGID (skipping SIGTERM, which ``sudo`` swallows),
  3. cleanup runs in ``finally`` so it fires on every exit path.

Each test tags the command it runs with a unique marker (``exec -a
mit162_<uuid> sleep 30``) so scanning ``/proc`` can't be confused by
leaks from previous test runs on the same host — we only care about the
child we just launched. ``exec -a NAME`` rewrites ``argv[0]`` of the
``sleep`` process, which shows up directly in ``/proc/<pid>/cmdline``.

All tests are Unix-only; Windows doesn't have POSIX process groups and
uses a different cleanup path.
"""

import asyncio
import os
import signal
import sys
import time
import uuid

import pytest

from nanobot.agent.tools.shell import ExecTool

# Skip on Windows (no POSIX process groups) *and* on POSIX platforms without
# a Linux-style /proc filesystem (macOS/BSD). The real-subprocess tests locate
# their grandchildren by scanning /proc/<pid>/cmdline; there's no portable
# equivalent we can rely on without shelling out to pgrep, which the exec
# prescreen may itself filter. The production fix (start_new_session + killpg)
# is exercised generically via the mocked _kill_process tests below, so the
# /proc-dependent cases just add Linux-side defense in depth.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not os.path.isdir("/proc"),
    reason=(
        "Process-group cleanup tests require a Linux-style /proc filesystem; "
        "Windows has no POSIX process groups and macOS/BSD lack /proc."
    ),
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_marker(tag: str) -> str:
    # `exec -a` requires a token that's a valid argv[0] — no spaces, no
    # hyphens that could trip up shell parsing, keep it identifier-safe.
    return f"mit162_{tag}_{uuid.uuid4().hex}"


def _sleep_cmd(marker: str, seconds: int = 30) -> str:
    """A shell command that spawns `sleep` with ``argv[0]`` == *marker*.

    This is how the test locates *its own* sleep grandchild: scan /proc for
    the exact marker instead of the generic "sleep 30" string that other
    tests (or leftover leaks) would also match.
    """
    return f"exec -a {marker} sleep {seconds}"


def _find_pid_by_marker(marker: str) -> int | None:
    """Return the PID of a process whose ``argv[0]`` equals *marker*, else None."""
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                raw = f.read()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if not raw:
            continue
        argv0 = raw.split(b"\x00", 1)[0].decode(errors="replace")
        if argv0 == marker:
            return int(entry)
    return None


def _wait_for_pid_to_appear(marker: str, timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = _find_pid_by_marker(marker)
        if pid is not None:
            return pid
        time.sleep(0.02)
    return None


def _wait_for_pid_to_exit(pid: int, timeout: float) -> bool:
    """True if *pid* is no longer alive within *timeout* seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # Process exists but we can't signal it — treat as still alive
            # and keep polling; if it ever goes away we'll see ESRCH.
            pass
        time.sleep(0.02)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


# ---------------------------------------------------------------------------
# spawn flag
# ---------------------------------------------------------------------------

class TestSpawnSessionFlag:
    """``start_new_session=True`` is the foundation of the whole fix."""

    @pytest.mark.asyncio
    async def test_unix_spawn_uses_new_session(self):
        """On Unix the child must be placed in its own session/PGID."""
        from unittest.mock import AsyncMock, patch

        with (
            patch("nanobot.agent.tools.shell._IS_WINDOWS", False),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_exec.return_value = AsyncMock()
            await ExecTool._spawn("echo hi", "/tmp", {"HOME": "/tmp"})

        kwargs = mock_exec.call_args.kwargs
        assert kwargs.get("start_new_session") is True, (
            "spawn must request a new session so killpg can target the whole tree"
        )


# ---------------------------------------------------------------------------
# real-subprocess cleanup tests
# ---------------------------------------------------------------------------

class TestTimeoutKillsTree:
    """On timeout the entire subprocess tree must be gone."""

    @pytest.mark.asyncio
    async def test_timeout_kills_sleeping_child(self):
        """A sleep that times out at 1s must not survive past the call."""
        marker = _make_marker("timeout")
        tool = ExecTool(timeout=1)

        task = asyncio.create_task(tool.execute(command=_sleep_cmd(marker)))

        pid = await asyncio.get_event_loop().run_in_executor(
            None, _wait_for_pid_to_appear, marker, 2.0
        )
        assert pid is not None, (
            f"could not locate the sleep child for marker {marker}; "
            "test harness failed to observe the process before cleanup"
        )

        result = await task
        assert "timed out" in result.lower()

        gone = _wait_for_pid_to_exit(pid, timeout=3.0)
        assert gone, f"sleep child (pid {pid}) outlived the timed-out exec call"


class TestCancelKillsTree:
    """When the enclosing task is cancelled mid-exec, cleanup still runs."""

    @pytest.mark.asyncio
    async def test_cancel_kills_sleeping_child(self):
        marker = _make_marker("cancel")
        tool = ExecTool(timeout=30)
        task = asyncio.create_task(tool.execute(command=_sleep_cmd(marker)))

        # Wait for the grandchild to actually exist before we pull the rug.
        pid = await asyncio.get_event_loop().run_in_executor(
            None, _wait_for_pid_to_appear, marker, 2.0
        )
        assert pid is not None, (
            "test harness failed to see the sleep child before cancellation"
        )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        gone = _wait_for_pid_to_exit(pid, timeout=3.0)
        assert gone, f"sleep child (pid {pid}) outlived the cancelled exec call"


class TestSigtermTrappedChildIsSigkilled:
    """The sudo-style case: a child that ignores SIGTERM must still die."""

    @pytest.mark.asyncio
    async def test_sigterm_ignoring_child_is_killed(self, tmp_path):
        marker = _make_marker("trap")
        # A bash script that ignores SIGTERM/INT/HUP and holds a sleep child
        # open via `wait`. The only way out is SIGKILL on the process group.
        # The sleep is launched in a subshell so we can rewrite its argv[0]
        # (the marker) — that's what lets the test locate it on /proc.
        script = tmp_path / "stubborn.sh"
        script.write_text(
            "#!/usr/bin/env bash\n"
            # trap '' TERM INT HUP = install an empty handler for each
            # signal (``trap -`` would *reset* to default and let them kill).
            "trap '' TERM INT HUP\n"
            f"(exec -a {marker} sleep 30) &\n"
            "wait $!\n"
        )
        script.chmod(0o755)

        tool = ExecTool(timeout=1)
        task = asyncio.create_task(tool.execute(command=str(script)))

        pid = await asyncio.get_event_loop().run_in_executor(
            None, _wait_for_pid_to_appear, marker, 2.0
        )
        assert pid is not None, (
            "test harness failed to see the sleep grandchild before cleanup"
        )

        start = time.monotonic()
        result = await task
        elapsed = time.monotonic() - start

        assert "timed out" in result.lower()
        # _kill_process has a 5s budget to reap; anything longer hints at a
        # SIGTERM-only kill stuck waiting on a trap-ignoring process.
        assert elapsed < 10, f"cleanup took {elapsed:.1f}s — SIGTERM likely used"

        gone = _wait_for_pid_to_exit(pid, timeout=3.0)
        assert gone, (
            f"sleep grandchild (pid {pid}) beneath the SIGTERM-trapping "
            f"parent survived cleanup"
        )


# ---------------------------------------------------------------------------
# _kill_process unit tests
# ---------------------------------------------------------------------------

class TestKillProcessHandlesMissingGroup:
    """If the group already exited, killpg's ProcessLookupError must not bubble."""

    @pytest.mark.asyncio
    async def test_process_lookup_error_is_swallowed(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        fake_proc = MagicMock()
        fake_proc.pid = 999999  # almost certainly dead / unused
        fake_proc.returncode = None
        fake_proc.kill = MagicMock(side_effect=ProcessLookupError)
        fake_proc.wait = AsyncMock(return_value=0)

        def boom_getpgid(_pid):
            raise ProcessLookupError

        monkeypatch.setattr(os, "getpgid", boom_getpgid)

        # Must not raise — a dead group is a no-op, not an error.
        await ExecTool._kill_process(fake_proc)

    @pytest.mark.asyncio
    async def test_killpg_is_sigkill_not_sigterm(self, monkeypatch):
        """The fix skips SIGTERM; sudo/trap-installed children need SIGKILL."""
        from unittest.mock import AsyncMock, MagicMock

        recorded = []

        def fake_getpgid(pid):
            return pid  # same-as-pid is fine for bookkeeping

        def fake_killpg(pgid, sig):
            recorded.append((pgid, sig))

        monkeypatch.setattr(os, "getpgid", fake_getpgid)
        monkeypatch.setattr(os, "killpg", fake_killpg)

        fake_proc = MagicMock()
        fake_proc.pid = 12345
        fake_proc.returncode = None
        fake_proc.kill = MagicMock()
        fake_proc.wait = AsyncMock(return_value=0)

        await ExecTool._kill_process(fake_proc)

        assert recorded, "killpg must be invoked on the pgid"
        (pgid, sig) = recorded[0]
        assert sig == signal.SIGKILL, (
            f"process-group kill must use SIGKILL (got {sig!r}); "
            "SIGTERM is silently swallowed by sudo/trap-installed children"
        )
