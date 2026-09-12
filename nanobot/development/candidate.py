"""Copy-based source snapshots and real, fail-closed Linux test isolation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

from nanobot.development.models import CheckResult

_IGNORED = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules", ".venv"}
_MAX_FILE = 2_000_000
_MAX_TREE = 120_000_000
_MAX_LOG = 2_000_000


def contained(root: Path, relative: str) -> Path:
    requested = Path(relative)
    if not relative or requested.is_absolute() or any(part in {"..", ".git"} for part in requested.parts):
        raise ValueError("a relative source path without parent traversal is required")
    target = root / requested
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("source path escapes the candidate")
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError("candidate symlinks are not supported")
        current = current.parent
    return target


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    size = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(item for item in dirs if item not in _IGNORED)
        for name in [*dirs, *names]:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("candidate symlinks are not supported")
        for name in sorted(names):
            path = Path(directory) / name
            if name.endswith(".pyc"):
                continue
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE:
                raise ValueError("candidate contains a special or oversized file")
            size += info.st_size
            if size > _MAX_TREE or len(files) >= 20_000:
                raise ValueError("candidate exceeds the source snapshot limit")
            files.append(path)
    return sorted(files)


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in source_files(root):
        record = [path.relative_to(root).as_posix(), bool(path.stat().st_mode & 0o111),
                  hashlib.sha256(path.read_bytes()).hexdigest()]
        digest.update(json.dumps(record, ensure_ascii=False).encode() + b"\n")
    return digest.hexdigest()


def protected_path(relative: str) -> bool:
    path = Path(relative)
    return ("tests" in path.parts or path.name == "conftest.py"
            or path.name in {"pyproject.toml", "pytest.ini", "setup.cfg", "package.json", "bun.lock", "bun.lockb"}
            or path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
            or path.name.startswith(("vitest.config.", "vite.config.", "tsconfig")))


def copy_source(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for path in source_files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)


def snapshot(repository: Path, destination: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repository), *args], check=True,
                              capture_output=True, text=True, timeout=30).stdout

    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("commit or preserve working changes before starting isolated development")
    base = git("rev-parse", "HEAD").strip()
    names = git("ls-files", "-z").split("\0")
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in filter(None, names):
        path = contained(repository, name)
        if not path.is_file():
            raise ValueError("submodules and special source entries need an explicit build adapter")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
    fingerprint(destination)
    if git("rev-parse", "HEAD").strip() != base or git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("repository changed while creating the baseline")
    return base


class Candidate:
    def __init__(self, source: Path, baseline: Path, dependencies: list[str],
                 source_dependencies: dict[str, Path] | None = None) -> None:
        self.source = source.resolve()
        self.baseline = baseline.resolve()
        self.dependencies = [Path(item).expanduser().absolute() for item in dependencies]
        self.source_dependencies = source_dependencies or {}

    def read(self, relative: str) -> str:
        path = contained(self.source, relative)
        if path.stat().st_size > _MAX_FILE:
            raise ValueError("source file is too large")
        return path.read_text(encoding="utf-8")

    def write(self, relative: str, content: str) -> None:
        path = contained(self.source, relative)
        if len(content.encode()) > _MAX_FILE:
            raise ValueError("source file is too large")
        if any(part in _IGNORED for part in Path(relative).parts):
            raise ValueError("dependency and runtime directories are not editable")
        if protected_path(relative) and (self.baseline / relative).exists():
            raise ValueError("existing acceptance tests and test configuration are frozen")
        if path.name == "conftest.py":
            raise ValueError("test harness hooks cannot be changed by a candidate")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def verify_frozen(self) -> None:
        for path in source_files(self.baseline):
            relative = path.relative_to(self.baseline).as_posix()
            if protected_path(relative):
                target = contained(self.source, relative)
                if not target.is_file() or target.read_bytes() != path.read_bytes():
                    raise ValueError(f"frozen acceptance file changed: {relative}")

    def argv(self, command: list[str]) -> list[str]:
        executable = shutil.which("bwrap")
        if not executable:
            raise ValueError("isolated development requires bubblewrap on Linux")
        if not command or any(not arg or "\x00" in arg for arg in command):
            raise ValueError("a non-empty check argv is required")
        args = [executable, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
                "--cap-drop", "ALL"]
        for directory in ("/usr", "/bin", "/lib", "/lib64"):
            if Path(directory).exists():
                args.extend(["--ro-bind", directory, directory])
        args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                     "--dir", "/home", "--dir", "/home/builder"])
        for dependency in self.dependencies:
            # Only operator-specified dependency paths are exposed, never home/config wholesale.
            if not dependency.exists() or dependency in {Path("/"), Path("/root"), Path.home()}:
                raise ValueError("missing or overbroad read-only development dependency")
            if self.source.is_relative_to(dependency) or self.baseline.is_relative_to(dependency):
                raise ValueError("dependency mount overlaps development state")
            args.extend(["--ro-bind", str(dependency), str(dependency)])
        args.extend(["--bind", str(self.source), "/work"])
        for relative, dependency in self.source_dependencies.items():
            contained(self.source, relative)
            if Path(relative).name != "node_modules" or not dependency.is_dir():
                raise ValueError("missing source dependency directory")
            args.extend(["--ro-bind", str(dependency), "/work/" + relative])
        for path in source_files(self.baseline):
            relative = path.relative_to(self.baseline).as_posix()
            if protected_path(relative):
                args.extend(["--ro-bind", str(path), "/work/" + relative])
        args.extend(["--setenv", "HOME", "/home/builder", "--setenv", "PATH", "/usr/bin:/bin",
                     "--setenv", "PYTHONPATH", "/work", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                     "--setenv", "CI", "1", "--setenv", "LANG", "C.UTF-8", "--chdir", "/work", "--"])
        return [*args, *command]

    async def check(self, command: list[str], log: Path, timeout: int) -> CheckResult:
        self.verify_frozen()
        before = fingerprint(self.source)
        argv = self.argv(command)
        started = time.monotonic()
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        assert process.stdout is not None
        output = bytearray()
        try:
            async with asyncio.timeout(timeout):
                while chunk := await process.stdout.read(8192):
                    output.extend(chunk)
                    if len(output) > _MAX_LOG:
                        raise ValueError("check output exceeded its limit")
                code = await process.wait()
        except BaseException:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            raise
        finally:
            log.write_bytes(bytes(output[:_MAX_LOG]))
            log.chmod(0o600)
        self.verify_frozen()
        if fingerprint(self.source) != before:
            raise ValueError("check modified source files; verification is invalid")
        return CheckResult(command=command, exit_code=code, elapsed_seconds=time.monotonic() - started,
                           log_file=str(log), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                           source_sha256=before)
