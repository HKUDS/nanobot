"""Sandbox backends for shell command execution.

To add a new backend, implement a function with the signature:
    _wrap_<name>(command: str, workspace: str, cwd: str) -> str
and register it in _BACKENDS below.
"""

import shlex
from pathlib import Path

from nanobot.config.paths import get_media_dir

_BWRAP_USERNS_ERROR_PATTERNS = (
    "operation not permitted",
    "permission denied",
    "creating new namespace failed",
    "namespace setup failed",
    "clone3",
    "clone",
    "unshare",
    "user namespace",
)


def _read_sysctl(name: str) -> str | None:
    path = Path("/proc/sys") / Path(name.replace(".", "/"))
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def bwrap_userns_failure_hint(stderr: str) -> str | None:
    """Return an actionable hint for common bwrap user namespace failures."""
    lower = stderr.lower()
    if not any(pattern in lower for pattern in _BWRAP_USERNS_ERROR_PATTERNS):
        return None

    details: list[str] = []
    unprivileged = _read_sysctl("kernel.unprivileged_userns_clone")
    if unprivileged == "0":
        details.append("kernel.unprivileged_userns_clone=0")

    max_namespaces = _read_sysctl("user.max_user_namespaces")
    if max_namespaces == "0":
        details.append("user.max_user_namespaces=0")

    apparmor_userns = _read_sysctl("kernel.apparmor_restrict_unprivileged_userns")
    if apparmor_userns == "1":
        details.append("kernel.apparmor_restrict_unprivileged_userns=1")

    suffix = f" Detected: {', '.join(details)}." if details else ""
    return (
        "Bubblewrap sandbox failed while creating Linux namespaces. This is common on "
        "Ubuntu 24.04+ when AppArmor restricts unprivileged user namespaces, or when "
        "the host/container disables user namespaces."
        f"{suffix} See docs/configuration.md#bubblewrap-on-ubuntu-2404 for the "
        "AppArmor profile and container capability requirements."
    )


def _bwrap(command: str, workspace: str, cwd: str) -> str:
    """Wrap command in a bubblewrap sandbox (requires bwrap in container).

    Only the workspace is bind-mounted read-write; its parent dir (which holds
    config.json) is hidden behind a fresh tmpfs.  The media directory is
    bind-mounted read-only so exec commands can read uploaded attachments.
    """
    ws = Path(workspace).resolve()
    media = get_media_dir().resolve()

    try:
        sandbox_cwd = str(ws / Path(cwd).resolve().relative_to(ws))
    except ValueError:
        sandbox_cwd = str(ws)

    required  = ["/usr"]
    optional  = ["/bin", "/lib", "/lib64", "/etc/alternatives",
                 "/etc/ssl/certs", "/etc/resolv.conf", "/etc/ld.so.cache"]

    args = ["bwrap", "--new-session", "--die-with-parent"]
    for p in required:
        args += ["--ro-bind", p, p]
    for p in optional:
        args += ["--ro-bind-try", p, p]
    args += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", str(ws.parent),        # mask config dir
        "--dir", str(ws),                 # recreate workspace mount point
        "--bind", str(ws), str(ws),
        "--ro-bind-try", str(media), str(media),  # read-only access to media
        "--chdir", sandbox_cwd,
        "--", "sh", "-c", command,
    ]
    return shlex.join(args)


_BACKENDS = {"bwrap": _bwrap}


def wrap_command(sandbox: str, command: str, workspace: str, cwd: str) -> str:
    """Wrap *command* using the named sandbox backend."""
    if backend := _BACKENDS.get(sandbox):
        return backend(command, workspace, cwd)
    raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")
