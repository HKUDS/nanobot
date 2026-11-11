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
from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import resolve_config_env_vars

_PROBE_TIMEOUT_S = 5


class SandboxCheck(TypedDict):
    state: str
    reason: str
    launcher: str | None
    revision: str
    supported_backend: str | None


def sandbox_settings_status(config: ExecToolConfig, workspace: Path) -> SandboxCheck:
    return _prepare_settings(config, workspace)[2]


def _prepare_settings(config: ExecToolConfig, workspace: Path) -> tuple[ExecToolConfig, Path, SandboxCheck]:
    import sys

    backend = "bwrap" if sys.platform.startswith("linux") else "seatbelt" if sys.platform == "darwin" else None
    missing_env = False
    try:
        config = resolve_config_env_vars(config)
        workspace = Path(resolve_config_env_vars(str(workspace))).expanduser()
    except ConfigLoadError:
        missing_env = True
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
    elif missing_env:
        result.update(state="unavailable", reason="path_unavailable")
    else:
        try:
            result["launcher"] = resolve_sandbox_launcher(
                config.sandbox, config.sandbox_launcher,
                writable_roots=(workspace, *map(Path, config.sandbox_rw_binds)),
            )
        except SandboxLauncherError as exc:
            result.update(state="unavailable", reason=exc.reason)
    return config, workspace, result


async def check_sandbox(config: ExecToolConfig, workspace: Path) -> SandboxCheck:
    config, workspace, result = await asyncio.to_thread(_prepare_settings, config, workspace)
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
            # bwrap may allow writing a new file in its private tmpfs at the
            # same path. What must stay unchanged is the host-side canary.
            f"(printf changed > {shlex.quote(str(canary))} || true)"
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
