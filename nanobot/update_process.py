"""Process-owned leases and protected startup for frozen updater children.

Copied into the frozen worker; keep this module standard-library only. Commands
come from the preparer's implementation, never from a client or release record.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from nanobot.installation_lock import (
    InstallationBusyError,
    file_access,
    installation_access,
    installation_state_dir,
)
from nanobot.utils.atomic_file import atomic_write_lines, io_path

# This stack belongs only to the single-use frozen child. Do not close it on a
# function return/SystemExit: pip/site atexit cleanup must still hold the leases.
# Module teardown and process exit release them after Python's exit callbacks.
child_leases = ExitStack()


def initialize_runtime(python: str, environment: str) -> None:
    """Initialize the target's site only after the caller acquired its own leases."""
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError("An update child must start with isolated, deferred site initialization")
    if Path(sys.executable).absolute() != Path(python).absolute():
        raise ValueError("Update child is using a different Python interpreter")
    import site

    site.main()
    if Path(sys.prefix).resolve() != Path(environment).resolve():
        raise ValueError("Update child is using a different installation")


_INSPECTION_BOOTSTRAP = """
import json, sys, types
from contextlib import ExitStack
from pathlib import Path
request = json.load(sys.stdin)
atomic = types.ModuleType('_nanobot_inspection_atomic')
sys.modules[atomic.__name__] = atomic
exec(compile(request['atomic'], '<inspection atomic I/O>', 'exec'), atomic.__dict__)
locking = types.ModuleType('_nanobot_inspection_lock')
sys.modules[locking.__name__] = locking
exec(compile(request['locking'], '<inspection leases>', 'exec'), locking.__dict__)
leases = ExitStack()
try:
    leases.enter_context(locking.installation_access(environment=request['environment'],
                                                   allow_incomplete=request['allow_incomplete']))
except locking.InstallationBusyError:
    raise SystemExit(11) from None
exec(compile(request['startup'], '<inspection startup>', 'exec'))
initialize_runtime(request['python'], request['environment'])
sys.argv = ['-c', *request['arguments']]
exec(compile(request['probe'], '<installation inspection>', 'exec'), {'__name__': '__main__'})
"""


def inspect_python_environment(python: str, environment: str, probe: str, *,
                               arguments: tuple[str, ...] = (), timeout: int = 15,
                               allow_incomplete: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a first-party read probe with child-owned startup/exit protection.

    Planning has no staged worker yet. Freeze the existing stdlib lease and
    startup implementations while holding the parent lease, then pass them over
    stdin to an isolated child. No mutable package code runs before its lease;
    the global child stack survives probe return and atexit after caller loss.
    This is not an installer or a command interface for clients/release records.
    """
    import inspect

    with installation_access(environment=environment, allow_incomplete=allow_incomplete):
        # Lease acquisition needs the same frozen I/O helper as the worker. The
        # child must not import either helper from the target before its lease.
        atomic_module = io_path.__module__
        locking = inspect.getsource(sys.modules[installation_access.__module__]).replace(
            f"from {atomic_module} import io_path", "from _nanobot_inspection_atomic import io_path",
        )
        request = json.dumps(dict(
            atomic=inspect.getsource(sys.modules[atomic_module]), locking=locking,
            startup=inspect.getsource(initialize_runtime), python=python, environment=environment,
            probe=probe, arguments=arguments, allow_incomplete=allow_incomplete,
        ))
        result = subprocess.run([python, "-I", "-S", "-c", _INSPECTION_BOOTSTRAP], input=request,
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode == 11:
            raise InstallationBusyError("This installation is being updated; try checking again when it finishes")
        return result


@dataclass(frozen=True)
class PreparationProcess:
    directory: Path
    environment: str
    generation: str
    active: bool = True

    @classmethod
    def create(cls, directory: Path, environment: str) -> PreparationProcess:
        """Called with the parent and native preparation leases held."""
        result = cls(directory.resolve(), str(Path(environment).resolve()), uuid4().hex)
        result._save(active=True)
        return result

    @classmethod
    def load(cls, directory: Path) -> PreparationProcess:
        path = directory / "preparation.json"
        if path.is_symlink():
            raise ValueError("Invalid preparation identity")
        with path.open("rb") as stream:
            value = json.loads(stream.read(16_385))
        if not isinstance(value, dict):
            raise ValueError("Invalid preparation identity")
        record = cast(dict[str, object], value)
        if (type(record.get("active")) is not bool or not isinstance(record.get("environment"), str)
                or not isinstance(record.get("generation"), str)):
            raise ValueError("Invalid preparation identity")
        environment, generation = cast(str, record["environment"]), cast(str, record["generation"])
        if (UUID(generation).hex != generation or not Path(environment).is_absolute()
                or directory != installation_state_dir(environment).resolve() / "jobs" / str(UUID(directory.name))):
            raise ValueError("Preparation belongs to another installation")
        return cls(directory, environment, generation, cast(bool, record["active"]))

    def _save(self, *, active: bool) -> None:
        path = self.directory / "preparation.json"
        atomic_write_lines(path, [json.dumps(dict(environment=self.environment,
                                                generation=self.generation, active=active))])
        path.chmod(0o600)

    def close(self) -> None:
        """Revoke late children only after the actual native command has exited."""
        self._save(active=False)

    def run(self, executable: str, arguments: list[str], *, kind: Literal["python", "native"] = "python",
            timeout: int = 900, env: dict[str, str] | None = None,
            cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        # Python commands run in their intended interpreter. Native uv uses the
        # base interpreter only to acquire leases, then replaces that same PID.
        base: object = getattr(sys, "_base_executable")
        if not isinstance(base, str):
            raise ValueError("Preparation needs a known base Python")
        bootstrap = executable if kind == "python" else base
        request = json.dumps(dict(generation=self.generation, kind=kind,
                                  executable=executable, arguments=arguments))
        # -S prevents site/.pth code in the mutable environment from running
        # before this child has acquired its own leases.
        return subprocess.run([bootstrap, "-I", "-S", str(self.directory / "worker.pyz"),
                               "--prepare-native", str(self.directory)], input=request,
                              capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)


def run_preparation_child(directory: Path) -> None:
    """Acquire our own leases before reading mutable packages or staging files."""
    encoded = sys.stdin.read(1024 * 1024 + 1)
    if len(encoded) > 1024 * 1024:
        raise ValueError("Preparation command exceeds its size limit")
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("Invalid preparation command")
    request = cast(dict[str, object], value)
    kind, executable, arguments = request.get("kind"), request.get("executable"), request.get("arguments")
    if (not isinstance(kind, str) or kind not in {"python", "native"} or not isinstance(executable, str)
            or not Path(executable).is_absolute() or not isinstance(arguments, list)
            or not arguments):
        raise ValueError("Invalid preparation command")
    if not all(isinstance(item, str) for item in cast(list[object], arguments)):
        raise ValueError("Invalid preparation arguments")
    args = cast(list[str], arguments)
    identity = PreparationProcess.load(directory)
    native = child_leases.enter_context(file_access(
        installation_state_dir(identity.environment) / "prepare-native.lock", exclusive=True))
    installation = child_leases.enter_context(installation_access(environment=identity.environment))
    # Recovery/retry holds native.lock while revoking the generation. Check
    # again inside the lease: a delayed child cannot use a replacement job.
    if (not identity.active or PreparationProcess.load(directory) != identity
            or request.get("generation") != identity.generation):
        raise ValueError("The preparation generation changed")
    if kind == "native":
        if os.name != "posix":
            raise ValueError("Native preparation needs a verified exec handoff on this platform")
        with native.inherit_for_exec(), installation.inherit_for_exec():
            os.execve(executable, [executable, *args], os.environ)
    if len(args) < 2 or not (args[:1] == ["-c"] or args[:2] == ["-m", "pip"]):
        raise ValueError("Unsupported preparation command")
    # Use the same Python path on POSIX and Windows; byte-range leases cannot
    # transfer through exec on Windows. Site startup and atexit stay protected.
    sys.argv = ["pip" if args[0] == "-m" else "-c", *args[2:]]
    # uv also probes its disposable prepared venv. The job's leases protect
    # both that staging area and the live installation; they are not necessarily
    # the environment whose Python this particular probe is running.
    initialize_runtime(executable, str(Path(executable).parent.parent))
    if args[0] == "-m":
        runpy.run_module("pip", run_name="__main__")
    else:
        exec(compile(args[1], "<update preparation probe>", "exec"), {"__name__": "__main__"})
