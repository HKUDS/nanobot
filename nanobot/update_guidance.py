"""Read-only, installation-bound instructions; never an alternative executor."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from packaging.version import Version

from nanobot.installation_receipt import RECEIPT_NAME
from nanobot.releases import ReleaseRecord

if TYPE_CHECKING:
    from nanobot.update_plan import InstallationSnapshot

Method = Literal["managed", "uv", "pipx", "pip", "source", "container", "system"]


def installation_method(installation: InstallationSnapshot) -> Method:
    if installation.owner == "venv":
        return "managed" if RECEIPT_NAME in installation.records else "pip"
    return installation.owner


def shell_command(arguments: list[str], *, windows: bool, environment: tuple[str, str] | None = None) -> str:
    """Bind a manager root without changing the user's persistent shell settings."""
    if not windows:
        return shlex.join(["env", "=".join(environment), *arguments] if environment else arguments)
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
    command = "& " + " ".join(quote(value) for value in arguments)
    if environment:
        name, value = environment
        command = (f"& {{ $nanobotPrevious = $env:{name}\n"
                   f"  try {{ $env:{name} = {quote(value)}; {command} }}\n"
                   f"  finally {{ $env:{name} = $nanobotPrevious }}\n}}")
    return command


class UpdateGuide(ReleaseRecord):
    method: Method
    host: str
    environment: str
    shell: Literal["sh", "powershell"]
    inspect_command: str | None = None
    update_command: str | None = None
    verify_command: str | None = None
    reason: Literal["registry", "preview", "policy", "extras", "manager", "source", "container", "system", "review", "restart"]


def update_guide(installation: InstallationSnapshot, target_version: str, *,
                 extras: list[str] | None, current: bool = True) -> UpdateGuide:
    """Only offer commands whose owner and environment have been identified.

    uv retains recorded constraints and settings. Generic pipx upgrades are only
    offered without recorded constraints or pip options. Neither promises our feed's
    exact target; the UI explains this and requires checking the running version.
    """
    method = installation_method(installation)
    windows = os.name == "nt"
    guide = UpdateGuide(method=method, host=platform.node(), environment=installation.environment,
                        shell="powershell" if windows else "sh", reason="review")
    if not current or Version(target_version) < Version(installation.installed_version) or any(ord(char) < 32 for value in (installation.python, installation.environment,
                                                     installation.running_package) for char in value):
        return guide
    guide = guide.model_copy(update={"verify_command": shell_command([installation.python, "-I", "-m", "nanobot", "--version"], windows=windows)})
    if Version(target_version) == Version(installation.installed_version) and method != "container":
        return guide.model_copy(update={"reason": "restart"})
    if method == "container":
        # Container paths/hostname are not the deployment host or service name.
        return guide.model_copy(update={"reason": "container", "verify_command": None})
    elif method == "source":
        root = str(Path(installation.running_package).parent.parent)
        return guide.model_copy(update={"reason": "source", "inspect_command": shell_command(["git", "-C", root, "status", "--short", "--branch"], windows=windows)})
    elif method == "system":
        return guide.model_copy(update={"reason": "system"})
    elif method in {"uv", "pipx"}:
        directory = Path(installation.environment)
        manager = shutil.which(method)
        policy = installation.manager
        if not manager or (method == "uv" and directory.name != "nanobot-ai") or (method == "pipx" and (directory.parent.name != "venvs" or not directory.name.startswith("nanobot-ai"))):
            return guide.model_copy(update={"reason": "manager"})
        root = ("UV_TOOL_DIR", str(directory.parent)) if method == "uv" else ("PIPX_HOME", str(directory.parent.parent))
        prefix = [manager, "tool"] if method == "uv" else [manager]
        guide = guide.model_copy(update={"inspect_command": shell_command([*prefix, "list"], windows=windows, environment=root)})
        if policy is None or policy.source != "registry" or policy.restriction(target_version):
            return guide.model_copy(update={"reason": "policy"})
        elif Version(target_version).is_prerelease:
            return guide.model_copy(update={"reason": "preview"})
        else:
            return guide.model_copy(update={"reason": "registry", "update_command": shell_command([*prefix, "upgrade", directory.name], windows=windows, environment=root)})
    elif Version(target_version).is_prerelease:
        return guide.model_copy(update={"reason": "preview"})
    elif extras is None:
        # A venv populated with `uv pip` need not contain pip itself. Inspect
        # metadata with the standard library, without guessing its original extras.
        inspect = [installation.python, "-I", "-c",
                   "import importlib.metadata,sys; d=importlib.metadata.distribution(sys.argv[1]); "
                   "print(d.metadata[sys.argv[2]], d.version); print(d.locate_file(sys.argv[3]))",
                   "nanobot-ai", "Name", "."]
        return guide.model_copy(update={"reason": "extras", "inspect_command": shell_command(inspect, windows=windows)})
    else:
        requirement = "nanobot-ai" + (f"[{','.join(extras)}]" if extras else "") + f"=={target_version}"
        return guide.model_copy(update={"reason": "registry", "update_command": shell_command([installation.python, "-I", "-m", "pip", "install", "--upgrade", requirement], windows=windows)})
