"""Bounded, explicit checks of saved shell sandbox settings, without a model."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import TypedDict

from nanobot.agent.tools.shell_config import ExecToolConfig
from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import resolve_config_env_vars
from nanobot.execution import processes
from nanobot.execution.sandbox import build_sandbox_argv
from nanobot.security.sandbox_launcher import (
    SandboxLauncherError,
    resolve_sandbox_launcher,
    supported_sandbox_backend,
)

_PROBE_TIMEOUT_S = 5


class SandboxCheck(TypedDict):
    state: str
    reason: str
    launcher: str | None
    revision: str
    supported_backend: str | None


def sandbox_settings_status(config: ExecToolConfig, workspace: Path) -> SandboxCheck:
    return _prepare_settings(config, workspace)[1]


def _prepare_settings(config: ExecToolConfig, workspace: Path) -> tuple[ExecToolConfig, SandboxCheck]:
    backend = supported_sandbox_backend()
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
    elif config.sandbox != backend:
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
    return config, result


async def check_sandbox(config: ExecToolConfig, workspace: Path) -> SandboxCheck:
    config, result = await asyncio.to_thread(_prepare_settings, config, workspace)
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
        try:
            argv = build_sandbox_argv(
                config.sandbox, script, str(project), str(project),
                launcher=config.sandbox_launcher,
                sandbox_ro_binds=config.sandbox_ro_binds,
                sandbox_rw_binds=config.sandbox_rw_binds,
            )
            result["launcher"] = argv[0]
        except SandboxLauncherError as exc:
            result.update(state="unavailable", reason=exc.reason)
            return result
        tree: processes.ProcessTree | None = None
        try:
            tree = await processes.spawn_process_tree(
                argv, str(project), {"PATH": os.defpath, "HOME": str(project)}, capture_output=False,
            )
            code = await asyncio.wait_for(tree.process.wait(), timeout=_PROBE_TIMEOUT_S)
            success = code == 0 and (project / "inside").read_text() == "checked" and canary.read_text() == "unchanged"
            result.update(state="passed" if success else "unavailable", reason="" if success else "probe_failed")
        except TimeoutError:
            result.update(state="unavailable", reason="probe_timeout")
        except OSError:
            result.update(state="unavailable", reason="probe_failed")
        finally:
            if tree is not None:
                if tree.process.returncode is None:
                    await tree.terminate()
                else:
                    tree.finish()
        return result
