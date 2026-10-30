"""Render the initial manual install handoff for a verified release candidate.

This is not a channel resolver or an updater. The caller must verify the candidate
bytes first; public availability, migration notes and native acceptance are release
gates, not properties inferred from a manifest.
"""

from __future__ import annotations

import re
import shlex
from typing import Literal

from nanobot.releases import PLATFORMS, ReleaseArtifact, ReleaseManifest

Owner = Literal["uv", "pipx", "pip"]
PLATFORM_LABELS = {
    "darwin-arm64": "macOS 13+ · Apple silicon",
    "darwin-x64": "macOS 13+ · Intel x64",
    "linux-arm64": "Linux · glibc 2.17+ · ARM64",
    "linux-x64": "Linux · glibc 2.17+ · x64",
    "win32-x64": "Windows · x64",
}

# Uses only Python's standard library, so the first preview can be installed before
# the user's nanobot has a channel-aware updater. The downloaded file is retained:
# managers can record its location as the installation source.
VERIFY_AND_INSTALL = '''from pathlib import Path
import hashlib
import subprocess
import sys
wheel = Path(sys.argv[1]).resolve(strict=True)
with wheel.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
if wheel.stat().st_size != int(sys.argv[2]) or digest != sys.argv[3]:
    raise SystemExit("Wheel size or SHA-256 mismatch; no package manager was started.")
command = sys.argv[4:]
if command[0] == "python":
    command[0] = sys.executable
subprocess.run([*command, "nanobot-ai @ " + wheel.as_uri()], check=True)
'''


def install_command(manifest: ReleaseManifest, artifact: ReleaseArtifact, *,
                    owner: Owner, existing: bool) -> list[str]:
    """Verify saved bytes before asking the original owner to install that file."""
    if not artifact.filename.endswith(".whl"):
        raise ValueError("Install instructions require a platform wheel")
    if artifact not in manifest.artifacts:
        raise ValueError("Artifact does not belong to this release")
    if owner == "uv":
        command = ["uv", "tool", "upgrade" if existing else "install", "--no-python-downloads"]
    elif owner == "pipx":
        command = ["pipx", "install", "--skip-maintenance", *(["--upgrade"] if existing else [])]
    elif owner == "pip":
        command = ["python", "-I", "-m", "pip", "install", *(["--upgrade"] if existing else [])]
    else:
        raise ValueError(f"Unsupported installation owner: {owner}")
    return ["python", "-I", "-c", VERIFY_AND_INSTALL, artifact.filename,
            str(artifact.size), artifact.sha256, *command]


def verification_command(owner: Owner, *, windows: bool) -> str:
    """Inspect the persistent environment, never an ephemeral uvx/pipx run cache."""
    if owner == "pip":
        return "python -I -m nanobot --version"
    directory = "uv tool dir" if owner == "uv" else "pipx environment --value PIPX_LOCAL_VENVS"
    if windows:
        return f"& (Join-Path ({directory}) 'nanobot-ai\\Scripts\\python.exe') -I -m nanobot --version"
    return f'"$({directory})/nanobot-ai/bin/python" -I -m nanobot --version'


def render_install_command(command: list[str], *, windows: bool) -> str:
    """Render install_command's Python helper for the target shell."""
    if not windows:
        return shlex.join(command)
    # Windows PowerShell strips embedded quotes from native -c arguments. Feed
    # the fixed ASCII helper on stdin instead; wheel identity remains in argv.
    arguments = " ".join("'" + value.replace("'", "''") + "'" for value in command[4:])
    return f"@'\n{command[3].rstrip()}\n'@ | python -I - {arguments}"


def bootstrap_commands(manifest: ReleaseManifest, manifest_sha256: str) -> tuple[str, str]:
    """Pin the installer to the candidate and the download to verified manifest bytes."""
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("Use the verified release manifest SHA-256")
    base = f"https://raw.githubusercontent.com/HKUDS/nanobot/{manifest.candidate_commit}/scripts"
    unix = f'''(
  installer_dir="$(mktemp -d)" || exit 1
  trap 'rm -f "$installer_dir/install.sh"; rmdir "$installer_dir"' 0
  curl --fail --silent --show-error --location --proto '=https' \\
    '{base}/install.sh' -o "$installer_dir/install.sh" &&
  sh "$installer_dir/install.sh" --release '{manifest.version}' \\
    --manifest-sha256 '{manifest_sha256}'
)'''
    windows = f'''$Installer = Join-Path ([IO.Path]::GetTempPath()) ("nanobot-install-" + [guid]::NewGuid() + ".ps1")
try {{
    Invoke-WebRequest -UseBasicParsing -Uri '{base}/install.ps1' -OutFile $Installer -ErrorAction Stop
    & $Installer -Release '{manifest.version}' -ManifestSha256 '{manifest_sha256}'
    if ($LASTEXITCODE -ne 0) {{ throw "Installation did not complete; review the output above." }}
}} finally {{
    Remove-Item -LiteralPath $Installer -ErrorAction SilentlyContinue
}}'''
    return unix, windows


def render_install_guide(manifest: ReleaseManifest, *, manifest_sha256: str | None = None) -> str:
    release_url = f"https://github.com/HKUDS/nanobot/releases/tag/v{manifest.version}"
    lines = [
        f"# Install nanobot {manifest.version}", "",
        "> Candidate handoff — not publication approval. Use these commands only after",
        "> the maintainer has published and publicly verified this exact release, added",
        "> its changes/migration/recovery notes, and declared its native test coverage.", "",
        f"- Release: [{manifest.version}]({release_url})",
        f"- Source commit: `{manifest.source_commit}`",
        f"- Packaged candidate: `{manifest.candidate_commit}`",
        f"- Python requirement: `{manifest.requires_python}`", "",
        "The wheel contains the built WebUI and matching native TUI. Installing nanobot",
        "itself needs no Bun, Node or Git. Python and third-party dependencies have their",
        "own requirements. Commands pin this one release; they do not subscribe to Preview.", "",
        "## Before installing", "",
        "1. Read this release's changes, known limitations and recovery instructions.",
        "   Prefer a separate environment **and separate data/profile/port** for an early",
        "   preview. A second environment alone does not isolate the default nanobot data.",
        "2. For an existing install, identify its manager, interpreter and supervisor.",
        "   Finish active tasks, stop all affected writers through that supervisor, and",
        "   back up nanobot configuration/sessions and the owner's install metadata.",
        "   Do not install into a running gateway or assume this guide performs a backup.",
        "3. Use automatic platform selection when offered below. For the manual route,",
        "   choose the target computer's platform, then **one** owner/operation.",
        "   Fresh commands are only for a new install; existing commands must target the",
        "   same account and manager home. For pip, activate the intended ordinary venv",
        "   and verify `python` belongs to it; never use system Python or a uv/pipx venv.", "",
        "4. For the manual route, download the linked wheel into a directory you own. Open",
        "   a terminal in that directory. Each command uses Python 3.11+ (`python`) to",
        "   verify the saved file's size and SHA-256 **before** starting the manager.",
        "   For uv/pipx this helper Python does not replace the tool's interpreter.",
        "   Keep the wheel at that path: the manager may record it as the install source.", "",
        "These commands cover a base `nanobot-ai` installation. If you use extras,",
        "pipx constraints/options/suffix/lock, custom wrappers or several installations,",
        "review the recorded",
        "spec and target explicitly instead of copying a base-package command. Preserve",
        "extras, injected packages, Python and index settings. Docker, Desktop, editable",
        "checkouts and system packages use their own deployment instructions.", "",
        "Command versions checked by the installer fixtures: uv 0.11.16 and pipx 1.17.12.",
        "Check your manager's version/help; older versions may not support these flags.",
        "This guide does not upgrade the manager. uv retains existing version constraints;",
        "pipx can skip a pinned/locked package successfully. A zero exit code alone does",
        "not prove the requested version was installed. Do not force/unpin automatically.", "",
    ]
    if manifest_sha256 is not None:
        unix, windows = bootstrap_commands(manifest, manifest_sha256)
        lines += [
            "## Automatic platform selection", "",
            "Run **one** command block on the computer to install or update, after the",
            "checks above. It downloads this candidate's installer, preserves a recognized",
            "existing installation owner and selects that Python environment's wheel.",
            "It verifies the manifest, download size, hash and wheel identity before install.",
            "Python/dependency compatibility is enforced by the manager; this command does",
            "not provide a gateway maintenance window, backup or verified restart.", "",
            "macOS / Linux (Python 3.11+ and curl):", "", "```sh", unix, "```", "",
            "Windows (Python 3.11+ and PowerShell):", "", "```powershell", windows, "```", "",
            "Do not bypass a system script-execution policy. Use your approved installation",
            "route if this script is blocked. These commands target one release, not a",
            "persistent Preview subscription. The downloaded wheel stays in the private",
            "nanobot release cache because the original manager may retain its path.", "",
            "<details>", "<summary>Manual platform and manager commands</summary>", "",
        ]
    lines += [
        "## Select the target platform", "",
        "Use the architecture of the target Python environment, not the browser. No musl",
        "or Windows ARM64 wheel is provided. x64 native TUI builds require SSE4.2.",
        "A platform label is not proof of a native test; consult the release's coverage.", "",
    ]
    for target, platform in PLATFORMS.items():
        artifact = next(item for item in manifest.artifacts
                        if item.filename.endswith(f"-py3-none-{platform}.whl"))
        shell = "powershell" if target == "win32-x64" else "sh"
        lines += [f"### {PLATFORM_LABELS[target]}", "",
                  f"Download: [{artifact.filename}]({manifest.artifact_url(artifact)}) ({artifact.size:,} bytes).",
                  f"SHA-256: `{artifact.sha256}`.", ""]
        owners: tuple[tuple[Owner, str], ...] = (
            ("uv", "uv tool"), ("pipx", "pipx"), ("pip", "pip in an ordinary venv"),
        )
        for owner, title in owners:
            lines += [f"#### {title}", "", "New installation:", "", f"```{shell}",
                      render_install_command(install_command(manifest, artifact, owner=owner, existing=False),
                                             windows=target == "win32-x64"),
                      "```", "", "Existing base-package installation, after stopping and backing up:", "",
                      f"```{shell}",
                      render_install_command(install_command(manifest, artifact, owner=owner, existing=True),
                                             windows=target == "win32-x64"),
                      "```", "", "Verify the version from this owner's persistent environment:", "",
                      f"```{shell}", verification_command(owner, windows=target == "win32-x64"), "```", ""]
    if manifest_sha256 is not None:
        lines += ["</details>", ""]
    lines += [
        "## Verify, restart and recover", "",
        f"The verification command must report `{manifest.version}`. If it reports another",
        "version, stop and inspect the manager result and installation identity. Do not",
        "retry through another manager, run `pipx run`/`uvx`, or clear an intentional pin.", "",
        "After package verification, restart the original gateway with its original",
        "supervisor, profile and arguments. Verify that gateway's actual running version",
        "and readiness, then check that existing sessions can be opened and appended to.",
        "CLI version output is not proof that an already-running service has updated.", "",
        "If download or installation fails, retain the error and backup, and do not start",
        "an unverified environment. Follow the release's owner-specific recovery steps.",
        "Retry this exact candidate only if it is still eligible. Never replace a backup",
        "with partially migrated state. A package downgrade is not a data rollback; stop",
        "all writers and review data compatibility before restoring or downgrading.", "",
        "GitHub-only previews are not discovered by an ordinary index-only `pip --pre`",
        "upgrade. A local wheel may remain in a manager receipt or be a one-time override;",
        "neither means a daily-update subscription has been created.", "",
    ]
    return "\n".join(lines)
