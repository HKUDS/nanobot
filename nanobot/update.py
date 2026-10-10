"""Update the current installation from PyPI or an editable source checkout."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import urllib.request
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from importlib.metadata import MetadataPathFinder, PackageNotFoundError, distribution
from pathlib import Path
from typing import TypedDict

from filelock import FileLock, Timeout
from packaging.version import Version

from nanobot import __version__
from nanobot.bun import bun_environment, ensure_bun

_SOURCE_URL = "https://github.com/HKUDS/nanobot.git"


class UpdateError(RuntimeError):
    """An update cannot proceed or did not finish successfully."""

    def __init__(self, message: str, *, needs_repair: bool = False) -> None:
        super().__init__(message)
        self.needs_repair = needs_repair


class UpdateResult(TypedDict):
    version: str
    source: str
    requires_restart: bool


def _run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"Could not run {Path(command[0]).name}: {exc}") from exc
    return result


def _checked(command: list[str], *, cwd: Path | None = None) -> str:
    result = _run(command, cwd=cwd)
    if result.returncode:
        raise UpdateError((result.stderr or result.stdout).strip()[-4000:])
    return result.stdout.strip()


def source_checkout() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    if (root / "pyproject.toml").is_file() and (root / "tui/package.json").is_file():
        return root
    return None


def latest_release() -> str:
    """Read the current stable PyPI release; network failures are not 'up to date'."""
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/nanobot-ai/json", timeout=15) as response:
            payload = json.loads(response.read(4 * 1024 * 1024))
        version = payload["info"]["version"]
        if not isinstance(version, str) or not version:
            raise ValueError("missing release version")
        parsed = Version(version)
        if parsed.is_prerelease or parsed.is_devrelease:
            raise ValueError("PyPI returned a prerelease")
        return str(parsed)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError(f"Could not check PyPI: {exc}") from exc


def _installation_key() -> str:
    return hashlib.sha256(os.fsencode(Path(sys.prefix).resolve())).hexdigest()[:16]


def update_blocked_reason(*, dev: bool = False) -> str:
    """Do not replace files owned by another deployment or package manager."""
    if Path("/.dockerenv").exists() or os.environ.get("RENDER") == "true":
        return "This installation is deployed in a container. Rebuild and redeploy its image."
    prefix = Path(sys.prefix)
    if (prefix / "uv-receipt.toml").exists():
        return "Use `uv tool upgrade nanobot-ai` in the gateway's account to preserve its uv tool settings."
    if (prefix / "pipx_metadata.json").exists():
        return "Use `pipx upgrade nanobot-ai` in the gateway's account to preserve its pipx settings."
    if sys.prefix == sys.base_prefix:
        return "Use the installer or package manager that owns this Python installation. In-app updates require a virtual environment."
    if not dev and source_checkout() is not None:
        return (
            "This gateway runs from source. Use the source update option to keep its checkout. "
            "To switch to a release, stop nanobot, install it in a separate environment, "
            "and launch it outside the checkout."
        )
    return ""


def _journal_path() -> Path:
    return Path.home() / ".nanobot" / "run" / f"update-{_installation_key()}.pending"


def incomplete_update() -> bool:
    """A marker survives failure or process termination after mutation begins."""
    return _journal_path().exists()


def _mark_installing() -> None:
    path = _journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as marker:
        marker.write("Installation may be incomplete. Stop nanobot and retry the update.\n")
        marker.flush()
        os.fsync(marker.fileno())


def _verify_installation(expected: str, source: str) -> None:
    # Match normal `python -m nanobot` restart resolution as well as isolated
    # installed-package resolution. A version from dist-info alone can hide a
    # checkout shadowing the installed wheel through cwd or PYTHONPATH.
    probe = (
        "import json, nanobot; from pathlib import Path; "
        "print(json.dumps([nanobot.__version__, str(Path(nanobot.__file__).resolve())]))"
    )
    installed = json.loads(_checked([sys.executable, "-I", "-c", probe]))
    restarted = json.loads(_checked([sys.executable, "-c", probe]))
    if installed[0] != expected:
        raise UpdateError(f"Installed version is {installed[0]}, expected {expected}. Check the installation environment.")
    if installed != restarted:
        raise UpdateError(
            "The restart would load a different nanobot package. Stop nanobot and restart "
            "outside the source checkout, without a source directory in PYTHONPATH."
        )
    if source != "pypi" and Path(installed[1]).parent != Path(source) / "nanobot":
        raise UpdateError("The interpreter does not load the updated source checkout. Check the editable installation.")


def _prepare_source(
    output: Callable[[str], None], *, before_change: Callable[[], None] = lambda: None,
) -> Path:
    git = shutil.which("git")
    if not git:
        raise UpdateError("Source updates require Git. Install Git and retry, or use a release update.")
    root = source_checkout()
    if root is None:
        root = Path.home() / ".nanobot" / "src" / _installation_key()
        root.parent.mkdir(parents=True, exist_ok=True)
        if not root.exists():
            output("Downloading nanobot source…")
            with tempfile.TemporaryDirectory(prefix=".clone-", dir=root.parent) as temporary:
                candidate = Path(temporary) / "nanobot"
                _checked([git, "clone", "--depth", "1", "--branch", "main", _SOURCE_URL, str(candidate)])
                candidate.rename(root)
    if not (root / ".git").exists():
        raise UpdateError(f"{root} is not a Git checkout. Update its sources manually.")
    if _checked([git, "status", "--porcelain"], cwd=root):
        raise UpdateError(f"Source checkout has local changes: {root}. Commit or move them before updating.")
    branch = _checked([git, "branch", "--show-current"], cwd=root)
    if not branch:
        raise UpdateError("Source checkout has a detached HEAD. Select a branch before updating.")
    remote_result = _run([git, "config", f"branch.{branch}.remote"], cwd=root)
    remote = remote_result.stdout.strip()
    if remote_result.returncode or not remote:
        raise UpdateError("The source branch has no upstream. Configure its upstream before updating.")
    output(f"Updating source branch {branch}…")
    _checked([git, "fetch", "--", remote], cwd=root)
    if _run([git, "merge-base", "--is-ancestor", "HEAD", "@{upstream}"], cwd=root).returncode:
        raise UpdateError("The source branch cannot fast-forward to its upstream. Reconcile it manually.")
    before_change()
    _checked([git, "merge", "--ff-only", "@{upstream}"], cwd=root)
    return root


def _install(arguments: list[str], *, upgrade: bool = False) -> None:
    from nanobot.optional_features import install_packages

    with _release_windows_launchers():
        result = install_packages(arguments, "nanobot update", upgrade=upgrade, runner=_run)
        if not result.ok:
            raise UpdateError(f"Package installation failed: {result.output[-4000:]}")


@contextmanager
def _release_windows_launchers() -> Generator[None]:
    """Windows permits renaming running launchers, but pip cannot overwrite them."""
    moved: list[tuple[Path, Path]] = []
    try:
        if sys.platform == "win32":
            import gc

            # Metadata discovery can keep the launcher's embedded ZIP open on Windows.
            importlib.invalidate_caches()
            MetadataPathFinder().invalidate_caches()
            gc.collect()
            scripts = Path(sysconfig.get_path("scripts"))
            for name in ("nanobot.exe", "nanobot-desktop-tui.exe"):
                launcher = scripts / name
                backup = scripts / f".{name}.update-backup"
                try:
                    if backup.is_file() and not launcher.exists():
                        backup.rename(launcher)
                    else:
                        backup.unlink(missing_ok=True)
                except PermissionError as exc:
                    raise UpdateError("Restart running nanobot processes before updating again.") from exc
                if launcher.is_file():
                    try:
                        launcher.rename(backup)
                    except PermissionError as exc:
                        raise UpdateError(
                            "Stop other nanobot processes and retry with `python -m nanobot update`."
                        ) from exc
                    moved.append((launcher, backup))
        yield
    finally:
        for launcher, backup in reversed(moved):
            if not launcher.exists():
                backup.rename(launcher)
            else:
                # An old gateway/console may still hold this file; the next update cleans it.
                with suppress(PermissionError):
                    backup.unlink(missing_ok=True)


def _is_editable() -> bool:
    try:
        raw = distribution("nanobot-ai").read_text("direct_url.json")
        return bool(raw and json.loads(raw).get("dir_info", {}).get("editable"))
    except (PackageNotFoundError, ValueError):
        return False


def update_installation(
    *, dev: bool = False, allow_downgrade: bool = False, output: Callable[[str], None] = print,
) -> UpdateResult:
    """Update application files and verify their version in a fresh interpreter."""
    reason = update_blocked_reason(dev=dev)
    if reason:
        raise UpdateError(reason)
    lock_dir = Path.home() / ".nanobot" / "run"
    lock_dir.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(lock_dir / f"update-{_installation_key()}.lock"), timeout=0):
            if dev:
                bun = ensure_bun(output=output)
                root = _prepare_source(output, before_change=_mark_installing)
                output("Preparing TUI dependencies…")
                with bun_environment(bun) as env:
                    result = _run([bun, "install", "--frozen-lockfile"], cwd=root / "tui", env=env)
                if result.returncode:
                    raise UpdateError(f"TUI dependencies failed: {(result.stderr or result.stdout)[-4000:]}")
                output("Building WebUI…")
                from nanobot.webui.build import build_webui_bundle

                build_webui_bundle(
                    source_dir=root / "webui", dist_dir=root / "nanobot/web/dist",
                    runner=bun, output=output,
                )
                output("Synchronizing Python dependencies…")
                _install(["--editable", str(root)])
                expected = str(tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
                source = str(root)
            else:
                expected = latest_release()
                if Version(expected) < Version(__version__) and not allow_downgrade:
                    raise UpdateError(
                        f"Installed {__version__} is newer than stable {expected}. "
                        "No files changed. Back up your data before an intentional downgrade, "
                        "then run `nanobot update --allow-downgrade`."
                    )
                target = f"nanobot-ai=={expected}"
                editable = _is_editable()
                if Version(expected) == Version(__version__) and not editable and not incomplete_update():
                    _verify_installation(expected, "pypi")
                    return {"version": expected, "source": "pypi", "requires_restart": False}
                output(f"Installing nanobot {expected} from PyPI…")
                _mark_installing()
                _install([target], upgrade=True)
                if editable and _is_editable():
                    # Pip can keep a same-version editable distribution. Dependencies were
                    # resolved above; replace only the application in this case.
                    _install(["--force-reinstall", "--no-deps", target])
                source = "pypi"
            output("Verifying the installed version…")
            _verify_installation(expected, source)
            _journal_path().unlink()
            return {"version": expected, "source": source, "requires_restart": True}
    except Timeout as exc:
        raise UpdateError("Another nanobot update is already running in this environment.") from exc
    except Exception as exc:
        if incomplete_update():
            raise UpdateError(
                f"{exc}\nInstallation may be incomplete. Stop nanobot and retry the same update "
                "from its Python environment before restarting. No automatic rollback was performed.",
                needs_repair=True,
            ) from exc
        raise
