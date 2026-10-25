"""Discover named SSH targets without running SSH, shell hooks, or contacting hosts.

This is a bounded name index, not an SSH configuration evaluator. OpenSSH still
resolves User, Port, IdentityFile, ProxyJump and Match at connection time.
"""

from __future__ import annotations

import glob
import os
import re
import shlex
import stat
from pathlib import Path
from typing import TypedDict

from nanobot.webui.remote_ssh import RemoteError


class SSHHost(TypedDict):
    host: str
    source: str
    ssh_config: str


class SSHDiscovery(TypedDict):
    hosts: list[SSHHost]
    files: list[str]
    incomplete: bool


def discover_hosts(config_file: str = "") -> SSHDiscovery:
    """Read literal Host names, including Include files, with no side effects.

    Wildcard/negated Host patterns are not destinations. Conditional includes
    may contribute suggestions; those are not claims that a host is reachable.
    Only names and source paths are returned, never arbitrary config contents.
    """
    if len(config_file) > 2048 or any(ord(char) < 32 for char in config_file):
        raise RemoteError("invalid_profile")
    home = Path.home()
    user_ssh = home / ".ssh"
    system_ssh = (Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "ssh"
                  if os.name == "nt" else Path("/etc/ssh"))
    roots = [(Path(config_file).expanduser(), user_ssh)] if config_file else [
        (user_ssh / "config", user_ssh), (system_ssh / "ssh_config", system_ssh),
    ]
    result: SSHDiscovery = {"hosts": [], "files": [], "incomplete": False}
    visited: set[Path] = set()
    names: set[str] = set()
    bytes_read = 0

    def visit(path: Path, base: Path, *, required: bool = False) -> None:
        nonlocal bytes_read
        try:
            path = path.resolve()
            if path in visited:
                return
            if len(visited) >= 64 or bytes_read >= 1_048_576:
                result["incomplete"] = True
                return
            visited.add(path)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 262_144:
                raise ValueError
            # Bound reads too, even if the file grows after stat().
            with path.open("rb") as stream:
                content = stream.read(min(262_145, 1_048_577 - bytes_read))
            bytes_read += len(content)
            if len(content) > 262_144 or bytes_read > 1_048_576:
                raise ValueError
            lines = content.decode("utf-8").splitlines()
        except FileNotFoundError:
            if required:
                raise RemoteError("local_file_not_found") from None
            return
        except (OSError, ValueError, RuntimeError):
            if required:
                raise RemoteError("ssh_config_unreadable") from None
            result["incomplete"] = True
            return
        result["files"].append(str(path))
        for line in lines:
            match = re.match(r"^\s*(Host|Include)(?:\s*=\s*|\s+)(.*)$", line, re.I)
            if not match:
                continue
            try:
                values = shlex.split(match[2], comments=True)
            except ValueError:
                result["incomplete"] = True
                continue
            if match[1].lower() == "host":
                for name in values:
                    if (len(name) > 253 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:@-]*", name)
                            or name.casefold() in names):
                        continue
                    if len(result["hosts"]) >= 200:
                        result["incomplete"] = True
                        return
                    names.add(name.casefold())
                    result["hosts"].append({"host": name, "source": str(path),
                                            "ssh_config": str(roots[0][0].expanduser()) if config_file else ""})
            else:
                for pattern in values:
                    # Tokens/environment-dependent paths cannot be resolved without
                    # a target. Leave them to SSH; never invoke `ssh -G` on page load
                    # because Match exec can execute arbitrary local commands.
                    if "$" in pattern or "%" in pattern:
                        result["incomplete"] = True
                        continue
                    expanded = Path(pattern).expanduser()
                    if not expanded.is_absolute():
                        expanded = base / expanded
                    matches = glob.iglob(str(expanded))
                    paths: list[str] = []
                    for candidate in matches:
                        if len(paths) >= 64:
                            result["incomplete"] = True
                            break
                        paths.append(candidate)
                    for candidate in sorted(paths):
                        visit(Path(candidate), base)

    for root, base in roots:
        visit(root, base, required=bool(config_file))
    return result
