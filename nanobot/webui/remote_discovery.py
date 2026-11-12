"""Locate remote nanobot configurations without reading credentials or using sudo.

Only the selected account's config and named nanobot systemd units are inspected.
An alternate service account is returned as a choice, never silently impersonated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nanobot.webui.remote_ssh import RemoteError, RemoteProfile, run_check

_LOCATE = r'''
import getpass, json, os, pathlib, re, shlex, socket, stat, subprocess, sys
try:
    import pwd
except ImportError:
    pwd = None

candidates = []
incomplete = False
current_user = pwd.getpwuid(os.getuid()).pw_name if pwd else getpass.getuser()

def add(path, user="", service=""):
    global incomplete
    if len(candidates) >= 8:
        incomplete = True
        return
    try:
        path = pathlib.Path(path).expanduser()
        if not path.is_absolute():
            return
        exists = stat.S_ISREG(path.stat().st_mode)
    except PermissionError:
        # A declared service config can be offered even when the SSH account
        # cannot stat it. The later explicit choice still needs sudo permission.
        exists = bool(service)
    except (OSError, ValueError):
        return
    user = "" if user == current_user else user
    item = {"config_path": str(path), "runtime_user": user, "service": service}
    if exists and not any(x["config_path"] == item["config_path"] and x["runtime_user"] == user for x in candidates):
        candidates.append(item)

add(sys.argv[1])

def systemctl(*args):
    result = subprocess.run(["systemctl", *args, "--no-pager"],
                            capture_output=True, text=True, timeout=2)
    if result.returncode:
        raise OSError("systemctl unavailable")
    return result.stdout

try:
    units = [line.split()[0] for line in systemctl("list-units", "--all", "--plain", "--no-legend", "nanobot*.service").splitlines() if line.split()]
    units = [name for name in units if re.fullmatch(r"nanobot[a-zA-Z0-9_.@-]*\.service", name)]
    incomplete = len(units) > 8
    if units and pwd:
        records = systemctl("show", *units[:8], "--property=Id,User,ExecStart,WorkingDirectory")
        for block in records.strip().split("\n\n"):
            fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            service = fields.get("Id", "")
            if service not in units[:8]:
                continue
            user = fields.get("User") or "root"
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", user):
                continue
            try:
                home = pathlib.Path(pwd.getpwnam(user).pw_dir)
                tokens = shlex.split(fields.get("ExecStart", ""))
            except (KeyError, ValueError):
                incomplete = True
                continue
            config = None
            for index, token in enumerate(tokens):
                if token.startswith("--config="):
                    config = token.split("=", 1)[1]
                    break
                if token in {"--config", "-c"} and index + 1 < len(tokens):
                    config = tokens[index + 1]
                    break
            if config and ("$" in config or "%" in config):
                incomplete = True
                continue
            if config:
                if config.startswith("~/"):
                    path = home / config[2:]
                elif pathlib.Path(config).is_absolute():
                    path = pathlib.Path(config)
                else:
                    path = pathlib.Path(fields.get("WorkingDirectory") or str(home)) / config
            else:
                path = home / ".nanobot/config.json"
            add(path, user, service)
except (OSError, subprocess.TimeoutExpired):
    incomplete = True

print("\n\x1eNANOBOT_REMOTE:" + json.dumps({"hostname": socket.gethostname(), "candidates": candidates, "incomplete": incomplete}))
'''


class RemoteLocation(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    config_path: str = Field(min_length=1, max_length=2048)
    runtime_user: str = Field(default="", max_length=64, pattern=r"^([a-zA-Z_][a-zA-Z0-9_-]*)?$")
    service: str = Field(default="", max_length=256, pattern=r"^([a-zA-Z0-9_.@-]+\.service)?$")

    @field_validator("config_path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return RemoteProfile.safe_path(value)


class RemoteInspection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    hostname: str = Field(min_length=1, max_length=253)
    candidates: list[RemoteLocation] = Field(max_length=8)
    incomplete: bool


async def inspect(profile: RemoteProfile, known_hosts: Path | None = None) -> dict[str, Any]:
    # Inspection is always performed as the SSH login, even when an old profile
    # has a service account. Discovery must not implicitly escalate privileges.
    result = await run_check(profile.model_copy(update={"runtime_user": ""}), _LOCATE, known_hosts)
    try:
        return RemoteInspection.model_validate(result).model_dump()
    except ValidationError:
        raise RemoteError("probe_failed") from None
