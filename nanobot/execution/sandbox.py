"""Sandbox backends for shell command execution.

To add a backend, match the callable signature of _bwrap and _seatbelt and
register it in _BACKENDS below.
"""

import os
import shlex
from pathlib import Path
from typing import Iterable

from nanobot.config.paths import get_media_dir
from nanobot.security.sandbox_launcher import resolve_sandbox_launcher


def _normalize_bind_paths(
    paths: Iterable[str],
    *,
    workspace: Path,
) -> list[str]:
    binds: dict[str, None] = {}
    for raw in paths:
        value = str(raw).strip()
        if not value:
            continue
        path = Path(os.path.expandvars(value)).expanduser()
        if not path.is_absolute():
            continue
        resolved_path = path.resolve(strict=False)
        # A later bind of the workspace or an ancestor could cover the
        # tmpfs that hides the config directory.
        if workspace.is_relative_to(resolved_path):
            continue
        binds[str(resolved_path)] = None
    return list(binds)


def _bwrap(
    command: str,
    ws: Path,
    sandbox_cwd: str,
    *,
    media: Path,
    ro_binds: list[str],
    rw_binds: list[str],
) -> list[str]:
    optional = [
        "/bin",
        "/lib",
        "/lib64",
        "/etc/alternatives",
        "/etc/ssl/certs",
        "/etc/pki/tls/certs",
        "/etc/pki/ca-trust",
        "/etc/crypto-policies",
        "/etc/resolv.conf",
        "/etc/ld.so.cache",
    ]

    args = [
        "--new-session", "--die-with-parent", "--setenv", "HOME", str(ws),
        "--ro-bind", "/usr", "/usr",
    ]
    for p in optional:
        args += ["--ro-bind-try", p, p]
    args += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", str(ws.parent),
        "--dir", str(ws),
        "--bind", str(ws), str(ws),
        "--ro-bind-try", str(media), str(media),
    ]
    for p in ro_binds:
        args += ["--ro-bind-try", p, p]
    for p in rw_binds:
        args += ["--bind-try", p, p]
    args += ["--chdir", sandbox_cwd, "--", "sh", "-c", command]
    return args


# System code and certificates needed by command-line tools. Do not grant
# /var, /tmp, /Library or /etc wholesale: those contain host application data,
# not an isolated scratch filesystem as in bwrap. Seatbelt matches real paths.
_SEATBELT_SYSTEM_READ_SUBPATHS = (
    "/usr",
    "/bin",
    "/sbin",
    "/dev",
    "/System",
    "/Library/Developer/CommandLineTools",
    "/private/etc/ssl",
    "/private/var/db/dyld",
    "/private/var/db/timezone",
)

_SEATBELT_SYSTEM_READ_LITERALS = (
    "/private/etc/hosts",
    "/private/etc/services",
    "/private/etc/protocols",
    "/private/etc/gitconfig",
    "/etc/gitconfig",
    "/private/var/run/resolv.conf",
    "/private/var/select/sh",
    "/private/var/select/developer_dir",
    "/private/var/db/xcode_select_link",
    "/var/select/developer_dir",
    "/var/db/xcode_select_link",
)

# Ancestors that must stay searchable but are not covered by any allowed
# subpath.  Resolving "/private/var/..." stats "/private", and
# (subpath "/private/var") does not cover its own parent.
_SEATBELT_TRAVERSABLE_LITERALS = ("/private",)


def _seatbelt_ancestors(*paths: Path) -> list[str]:
    """Collect every ancestor directory of *paths*, closest first.

    Seatbelt checks each path component while resolving, so a sandbox that
    allows a deep directory but not its ancestors fails with ENOTDIR on every
    command.  Only ``file-read-metadata`` is granted for these: the directories
    stay searchable, but listing or reading them is still denied.
    """
    return list(dict.fromkeys(str(ancestor) for path in paths for ancestor in path.parents))


def _seatbelt_is_within(path: Path, root: Path) -> bool:
    """Match existing path aliases without lowercasing case-sensitive volumes."""
    if path.is_relative_to(root):
        return True
    for ancestor in (path, *path.parents):
        try:
            if ancestor.samefile(root):
                return True
        except OSError:
            # Missing/inaccessible paths retain conservative lexical matching.
            continue
    return False


def _sbpl_quote(path: str) -> str:
    """Render *path* as an SBPL string literal.

    SBPL uses C-style string escaping, so a backslash or a double quote in a
    path would otherwise terminate the literal early and change the meaning of
    every rule that follows it.
    """
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _seatbelt(
    command: str,
    ws: Path,
    sandbox_cwd: str,
    *,
    media: Path,
    ro_binds: list[str],
    rw_binds: list[str],
) -> list[str]:
    """Wrap command in a macOS Seatbelt sandbox (requires sandbox-exec(1)).

    The workspace is read-write and media is read-only. The workspace's parent
    (the config directory in the default layout) is denied. Host temporary and
    application-data directories are not shared; TMPDIR and HOME use the
    workspace instead. Additional tool installations need explicit read binds.

    Seatbelt has no mount namespace, so masking the parent is expressed as a
    deny rule placed *before* the workspace allow — the last matching rule
    wins, which re-exposes the workspace subtree while the rest of the parent
    stays denied.  Unlike ``bwrap``, a denied parent still appears in directory
    listings; only its contents are inaccessible.

    Network access is left unrestricted, matching ``bwrap`` (which does not pass
    ``--unshare-net``).
    """
    def subpaths(paths: Iterable[str]) -> str:
        return " ".join(f"(subpath {_sbpl_quote(p)})" for p in paths)

    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow mach*)",
        "(allow ipc*)",
        "(allow network*)",
        # sh(1) reads the root directory while resolving a path, and
        # (subpath "/usr") does not cover "/" itself.  Without this rule the
        # shell aborts during startup.
        '(allow file-read* (literal "/"))',
        f"(allow file-read* {subpaths(_SEATBELT_SYSTEM_READ_SUBPATHS)})",
        "(allow file-read* "
        + " ".join(f"(literal {_sbpl_quote(p)})" for p in _SEATBELT_SYSTEM_READ_LITERALS)
        + ")",
        '(allow file-write* (literal "/dev/null") (literal "/dev/zero"))',
    ]

    # Mask the config directory.  The workspace allow below re-exposes the
    # workspace subtree, because the last matching rule wins.
    parent = ws.parent
    if parent != ws and str(parent) != "/":
        rules.append(f"(deny file-read* file-write* (subpath {_sbpl_quote(str(parent))}))")

    # Keep every ancestor of an allowed path searchable, including the masked
    # parent: metadata only, so it cannot be listed or read.
    traversable = _seatbelt_ancestors(
        ws, media, *(Path(p) for p in ro_binds), *(Path(p) for p in rw_binds),
        *(Path(p) for p in _SEATBELT_SYSTEM_READ_SUBPATHS),
        *(Path(p) for p in _SEATBELT_SYSTEM_READ_LITERALS),
    )
    literals = [
        *(p for p in _SEATBELT_TRAVERSABLE_LITERALS if p not in traversable),
        *traversable,
    ]
    rules.append(
        "(allow file-read-metadata "
        + " ".join(f"(literal {_sbpl_quote(p)})" for p in literals)
        + ")"
    )

    rules.append(f"(allow file-read* file-write* (subpath {_sbpl_quote(str(ws))}))")
    rules.append(f"(allow file-read* (subpath {_sbpl_quote(str(media))}))")
    rules.append(f"(deny file-write* (subpath {_sbpl_quote(str(media))}))")

    for p in ro_binds:
        rules.append(f"(allow file-read* (subpath {_sbpl_quote(p)}))")
        # A read allow does not revoke a broader write grant (e.g. workspace).
        rules.append(f"(deny file-write* (subpath {_sbpl_quote(p)}))")
    for p in rw_binds:
        rules.append(f"(allow file-read* file-write* (subpath {_sbpl_quote(p)}))")

    # Path-based read-only rules do not follow a renamed ancestor. Keep those
    # directory entries fixed without denying writes to their other children.
    # A RW bind covering the entire RO root intentionally overrides protection;
    # a writable descendant must not unlock the rest of the read-only tree.
    writable_roots = [Path(p) for p in rw_binds]
    protected_roots = [
        root for root in (media, *(Path(p) for p in ro_binds))
        if not any(_seatbelt_is_within(root, writable) for writable in writable_roots)
    ]
    ancestors = _seatbelt_ancestors(*protected_roots)
    if ancestors:
        rules.append(
            "(deny file-write-unlink "
            + " ".join(f"(literal {_sbpl_quote(p)})" for p in ancestors)
            + ")"
        )

    # sandbox-exec(1) has no --chdir. Exit on failure before evaluating any of
    # the submitted shell list; `cd ... && a; b` would still execute b on failure.
    return [
        "-p",
        "\n".join(rules),
        "/usr/bin/env",
        f"HOME={ws}",
        f"TMPDIR={ws}",
        "sh",
        "-c",
        f"cd {shlex.quote(sandbox_cwd)} || exit\n{command}",
    ]


_BACKENDS = {"bwrap": _bwrap, "seatbelt": _seatbelt}


def build_sandbox_argv(
    sandbox: str,
    command: str,
    workspace: str,
    cwd: str,
    *,
    launcher: str = "",
    sandbox_ro_binds: Iterable[str] | None = None,
    sandbox_rw_binds: Iterable[str] | None = None,
) -> list[str]:
    """Build the sandbox argv with an independently resolved host launcher."""
    backend = _BACKENDS.get(sandbox)
    if backend is None:
        raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")
    ws = Path(workspace).resolve()
    media = get_media_dir().resolve()
    requested_cwd = Path(cwd).resolve()
    sandbox_cwd = str(requested_cwd if requested_cwd.is_relative_to(ws) else ws)

    rw_binds = tuple(sandbox_rw_binds or ())
    args = backend(
        command, ws, sandbox_cwd, media=media,
        ro_binds=_normalize_bind_paths(sandbox_ro_binds or (), workspace=ws),
        rw_binds=_normalize_bind_paths(rw_binds, workspace=ws),
    )
    executable = resolve_sandbox_launcher(
        sandbox, launcher, writable_roots=(Path(workspace), *map(Path, rw_binds)),
    )
    return [executable, *args]
