"""Subprocess wrappers around gh + ssh-keygen for fleet provisioning.

Each function returns plain data; raises ``ProvisionError`` on failure with a
clean message. Designed to be unit-testable by patching ``_run``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProvisionError(RuntimeError):
    """Wraps a subprocess failure with a clean message."""


@dataclass
class CreatedRepo:
    full_name: str          # e.g. "phelps-sg/agent-peewee"
    ssh_url: str            # e.g. "git@github.com:phelps-sg/agent-peewee.git"


@dataclass
class Keypair:
    private_key_path: Path
    public_key_path: Path
    public_key: str


@dataclass
class DeployKey:
    id: int
    title: str


def check_gh_auth() -> None:
    """Raise ProvisionError if `gh` is not installed or not authenticated."""
    try:
        _run(["gh", "auth", "status"])
    except FileNotFoundError as e:
        raise ProvisionError("gh CLI not found on PATH") from e
    except subprocess.CalledProcessError as e:
        raise ProvisionError(f"gh is not authenticated:\n{e.stderr or e.stdout}") from e


def create_repo(org: str, name: str, *, description: str = "", private: bool = True) -> CreatedRepo:
    """Create a GitHub repo via ``gh repo create``."""
    full = f"{org}/{name}"
    args = ["gh", "repo", "create", full, "--private" if private else "--public"]
    if description:
        args += ["--description", description]
    _run(args)
    ssh_url = f"git@github.com:{full}.git"
    return CreatedRepo(full_name=full, ssh_url=ssh_url)


def archive_repo(full_name: str) -> None:
    """Archive (not delete) a repo via ``gh repo archive --yes``."""
    _run(["gh", "repo", "archive", full_name, "--yes"])


def generate_keypair(key_dir: Path, *, comment: str) -> Keypair:
    """ssh-keygen an ed25519 keypair with no passphrase into ``key_dir``."""
    key_dir = Path(key_dir).expanduser()
    key_dir.mkdir(parents=True, exist_ok=True)
    private = key_dir / "id"
    public = key_dir / "id.pub"
    if private.exists() or public.exists():
        raise ProvisionError(f"keypair already exists in {key_dir}")
    _run([
        "ssh-keygen", "-t", "ed25519", "-N", "", "-C", comment,
        "-f", str(private),
    ])
    private.chmod(0o600)
    pub_text = public.read_text().strip()
    return Keypair(private_key_path=private, public_key_path=public, public_key=pub_text)


def add_deploy_key(full_name: str, public_key: str, *, title: str, read_only: bool = False) -> DeployKey:
    """Register a public key as a deploy key with the given access level."""
    args = [
        "gh", "api", f"repos/{full_name}/keys",
        "--method", "POST",
        "-f", f"title={title}",
        "-f", f"key={public_key}",
        "-F", f"read_only={'true' if read_only else 'false'}",
    ]
    out = _run(args)
    try:
        body = json.loads(out)
        return DeployKey(id=int(body["id"]), title=body.get("title", title))
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise ProvisionError(f"unexpected gh response: {out!r}") from e


def remove_deploy_key(full_name: str, key_id: int) -> None:
    _run([
        "gh", "api", f"repos/{full_name}/keys/{key_id}",
        "--method", "DELETE",
    ])


def list_deploy_keys(full_name: str) -> list[dict]:
    out = _run(["gh", "api", f"repos/{full_name}/keys"])
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ProvisionError(f"unexpected gh response: {out!r}") from e


def _run(args: list[str]) -> str:
    """Synchronous subprocess. Raises ProvisionError on non-zero exit."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise
    if proc.returncode != 0:
        raise ProvisionError(
            f"{' '.join(args)} exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc.stdout
