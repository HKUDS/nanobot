"""Bounded, explicit checks of saved shell sandbox settings, without a model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import signal
import tempfile
from pathlib import Path
from typing import TypedDict

from nanobot.agent.tools.sandbox import wrap_command
from nanobot.agent.tools.sandbox_launcher import (
    SandboxLauncherError,
    resolve_sandbox_launcher,
    sandbox_platform,
)
from nanobot.agent.tools.shell_config import ExecToolConfig

_PROBE_TIMEOUT_S = 5


class SandboxCheck(TypedDict):
    state: str
    reason: str
    launcher: str | None
    revision: str
    supported_backend: str | None


def sandbox_settings_status(config: ExecToolConfig, workspace: Path) -> SandboxCheck:
    import sys

    backend = "bwrap" if sys.platform.startswith("linux") else "seatbelt" if sys.platform == "darwin" else None
    revision = hashlib.sha256(json.dumps(
        {"config": config.model_dump(), "workspace": str(workspace)}, sort_keys=True,
    ).encode()).hexdigest()
    result: SandboxCheck = {
        "state": "unchecked", "reason": "", "launcher": None,
        "revision": revision, "supported_backend": backend,
    }
    if not config.enable:
        result["state"] = "disabled"
    elif not config.sandbox:
        result["state"] = "off"
    elif sandbox_platform(config.sandbox) == "unsupported":
        result.update(state="unsupported", reason="platform_unsupported")
    else:
        try:
            result["launcher"] = resolve_sandbox_launcher(
                config.sandbox, config.sandbox_launcher,
                writable_roots=(workspace, *map(Path, config.sandbox_rw_binds)),
            )
        except SandboxLauncherError as exc:
            result.update(state="unavailable", reason=exc.reason)
    return result


async def check_sandbox(config: ExecToolConfig, workspace: Path) -> SandboxCheck:
    result = await asyncio.to_thread(sandbox_settings_status, config, workspace)
    if result["state"] != "unchecked":
        return result
    # Use synthetic files only. Never run startup/login profiles or an arbitrary
    # user-provided test command. This is a basic probe, not a full security audit.
    with tempfile.TemporaryDirectory(prefix="nanobot-sandbox-check-") as directory:
        root = Path(directory).resolve()
        project = root / "workspace"
        project.mkdir()
        canary = root / "outside"
        canary.write_text("unchanged")
        script = (
            "printf checked > inside && "
            f"! test -r {shlex.quote(str(canary))} && "
            f"! (printf changed > {shlex.quote(str(canary))})"
        )
        argv = shlex.split(wrap_command(
            config.sandbox, script, str(project), str(project),
            sandbox_ro_binds=config.sandbox_ro_binds,
            sandbox_rw_binds=config.sandbox_rw_binds,
        ))
        # Same resolver and wrapper as ExecTool. Recheck against the probe root.
        try:
            argv[0] = resolve_sandbox_launcher(
                config.sandbox, config.sandbox_launcher,
                writable_roots=(project, *map(Path, config.sandbox_rw_binds)),
            )
            result["launcher"] = argv[0]
        except SandboxLauncherError as exc:
            result.update(state="unavailable", reason=exc.reason)
            return result
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=str(project), env={"PATH": os.defpath, "HOME": str(project)},
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            )
            await asyncio.wait_for(process.wait(), timeout=_PROBE_TIMEOUT_S)
            success = process.returncode == 0 and (project / "inside").read_text() == "checked" and canary.read_text() == "unchanged"
            result.update(state="passed" if success else "unavailable", reason="" if success else "probe_failed")
        except TimeoutError:
            result.update(state="unavailable", reason="probe_timeout")
        except OSError:
            result.update(state="unavailable", reason="probe_failed")
        finally:
            if process is not None and process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        return result
