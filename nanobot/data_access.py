"""Account-scoped leases for named nanobot stores shared by Python installations.

Runtimes share leases; backup/install maintenance requires exclusive access. Two
lease namespaces cover overlapping store roots in both directions. This coordinates
participating runtimes, not older versions, other accounts, external databases or
arbitrary project files.
Each process must acquire its own lease; a parent's exit must not unlock a pip child.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Generator, Iterable
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import UUID

from nanobot.installation_lock import FileLease, InstallationBusyError, file_access
from nanobot.utils.atomic_file import atomic_write_lines, read_atomic_bytes

_DATA_STORES = (
    "sessions", "webui", "media", "auth", "pairing.json", "cron", "delivery",
    "llm_usage.sqlite3", "llm_usage.sqlite3-wal", "llm_usage.sqlite3-shm",
    "whatsapp-auth", "weixin", "matrix-store", "linear", "mochat", "cli-apps/installed.json",
)
_WORKSPACE_STORES = (
    ".nanobot", "memory", "skills", "sessions", "cron", "triggers",
    "AGENTS.md", "TOOLS.md", "SOUL.md", "USER.md", "HEARTBEAT.md",
)
_MAX_RESERVATION_BYTES = 16 * 1024 * 1024


def _stored_roots(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError("Invalid data maintenance scope")
    values = cast(list[object], raw)
    if not 1 <= len(values) <= 40_000 or any(
        not isinstance(root, str) or len(root) > 4096 or "\0" in root or not Path(root).is_absolute()
        for root in values
    ):
        raise ValueError("Invalid data maintenance scope")
    return tuple(cast(list[str], values))


def _covered(requested: tuple[str, ...], reserved: tuple[str, ...]) -> bool:
    allowed = set(map(Path, reserved))
    return all(any(parent in allowed for parent in (path, *path.parents)) for path in map(Path, requested))


@dataclass(frozen=True)
class _Reservation:
    job_id: str
    roots: tuple[str, ...]
    grants: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        encoded = json.dumps({
            "schema_version": 1, "job_id": self.job_id, "roots": self.roots,
            "grants": {participant: {"token_sha256": digest, "roots": scope}
                       for participant, (digest, scope) in self.grants.items()},
        })
        if len(encoded.encode("utf-8")) + 1 > _MAX_RESERVATION_BYTES:
            raise ValueError("Data maintenance reservation is too large")
        atomic_write_lines(path, [encoded])
        path.chmod(0o600)


def _reservation(path: Path) -> _Reservation | None:
    """Read a bounded, atomically replaced reservation; corruption never means idle."""
    if path.is_symlink():
        raise ValueError("Invalid data maintenance reservation")
    try:
        encoded = read_atomic_bytes(path, max_bytes=_MAX_RESERVATION_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(encoded) > _MAX_RESERVATION_BYTES:
        raise ValueError("Data maintenance reservation is too large")
    raw: object = json.loads(encoded)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Invalid data maintenance reservation")
    record = cast(dict[str, object], raw)
    owner, roots = record.get("job_id"), record.get("roots")
    if (record.get("schema_version") != 1 or not isinstance(owner, str)
            or str(UUID(owner)) != owner):
        raise ValueError("Invalid data maintenance reservation")
    scope = _stored_roots(roots)
    raw_grants = record.get("grants", {})
    if not isinstance(raw_grants, dict):
        raise ValueError("Invalid maintenance startup grants")
    grant_values = cast(dict[object, object], raw_grants)
    if len(grant_values) > 1024:
        raise ValueError("Invalid maintenance startup grants")
    grants: dict[str, tuple[str, tuple[str, ...]]] = {}
    for participant, raw_grant in grant_values.items():
        if not isinstance(participant, str) or not re.fullmatch(r"[0-9a-f]{64}", participant) or not isinstance(raw_grant, dict):
            raise ValueError("Invalid maintenance startup participant")
        grant = cast(dict[str, object], raw_grant)
        digest = grant.get("token_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid maintenance startup grant")
        granted_scope = _stored_roots(grant.get("roots"))
        if not _covered(granted_scope, scope):
            raise ValueError("Maintenance startup scope exceeds the reserved data")
        grants[participant] = digest, granted_scope
    return _Reservation(owner, scope, grants)


@dataclass(frozen=True)
class DataStartupGrant:
    """Process-local bearer for one reviewed participant, not task admission.

    The lifecycle owner must pass it only to the intended verified startup and
    keep agent/tool/scheduler admission closed. This coordinates cooperating
    runtimes; it is not an OS security boundary against the same account.
    """

    job_id: str
    participant: str
    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if (str(UUID(self.job_id)) != self.job_id or not re.fullmatch(r"[0-9a-f]{64}", self.participant)
                or not re.fullmatch(r"[0-9a-f]{64}", self.token)):
            raise ValueError("Invalid maintenance startup grant")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.token.encode()).hexdigest()


@dataclass(frozen=True)
class DataLease:
    """Reservation operations are valid only inside the owning data_access context."""

    roots: tuple[str, ...]
    reservation_path: Path
    job_id: str | None
    exclusive: bool
    _files: tuple[FileLease, ...] = field(default=(), repr=False, compare=False)

    @contextmanager
    def inherit_for_exec(self) -> Generator[None]:
        """Retain all store leases in a dedicated POSIX installer's exec handoff."""
        with ExitStack() as stack:
            for lease in self._files:
                stack.enter_context(lease.inherit_for_exec())
            yield

    def reserve(self) -> None:
        """Keep participating writers out through handoff, crash and repair."""
        if self.job_id is None or not self.exclusive:
            raise ValueError("Only an update job may reserve data maintenance")
        # Starting another package mutation revokes every old startup grant.
        _Reservation(self.job_id, self.roots).save(self.reservation_path)

    def grant_startup(self, participant: str, paths: Iterable[str | Path]) -> DataStartupGrant:
        """Authorize one runtime during a shared, job-owned post-install handoff.

        Must be called inside data_access(paths, job_id=...) after installation
        verification. No exclusive data locks are held while the child starts.
        A live participant retains its own OS lease and cannot be reauthorized.
        """
        if self.job_id is None or self.exclusive:
            raise ValueError("Startup grants require a shared maintenance handoff")
        grant = DataStartupGrant(self.job_id, participant, os.urandom(32).hex())
        scope = _canonical_roots(paths)
        if not scope or not _covered(scope, self.roots):
            raise ValueError("Startup grant exceeds the reviewed data scope")
        current = _reservation(self.reservation_path)
        if current is None or (current.job_id, current.roots) != (self.job_id, self.roots):
            raise ValueError("Data maintenance belongs to a different job or scope")
        if participant not in current.grants and len(current.grants) >= 1024:
            raise ValueError("Too many maintenance startup participants")
        try:
            with file_access(self.reservation_path.parent / f"startup-{participant}.lock", exclusive=True):
                current.grants[participant] = grant.digest, scope
                current.save(self.reservation_path)
        except BlockingIOError as exc:
            raise InstallationBusyError("This maintenance startup participant is still running") from exc
        return grant

    def release_reservation(self) -> None:
        """Clear only this job's reservation after verification or safe cancellation."""
        if self.job_id is None:
            raise ValueError("Only an update job may release data maintenance")
        current = _reservation(self.reservation_path)
        if current is None:
            return
        if (current.job_id, current.roots) != (self.job_id, self.roots):
            raise ValueError("Data maintenance belongs to a different job or scope")
        # Atomic replacement also flushes the directory; a crash cannot lose an
        # unsynced unlink and resurrect an apparently cleared reservation.
        atomic_write_lines(self.reservation_path, ["null"])

    def grant_profile_startup(self, participant: str, *, home: Path, data_dir: Path,
                              config: Path, workspace: Path) -> DataStartupGrant:
        """Honor a protocol-1 handoff without granting its new lazy store early."""
        paths = profile_data_paths(home=home, data_dir=data_dir, config=config, workspace=workspace)
        delivery = (data_dir / "delivery").absolute()
        if not _covered(_canonical_roots((delivery,)), self.roots):
            paths = tuple(path for path in paths if path != delivery)
        # Every other store must still be covered by the immutable reservation.
        # profile_data_access holds the deferred store's ordinary lease, and the
        # runtime admission gate keeps its lazy owner inactive until activation.
        return self.grant_startup(participant, paths)


def _canonical_roots(paths: Iterable[str | Path]) -> tuple[str, ...]:
    roots: set[str] = set()
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            raise ValueError("Data stores must use absolute paths")
        roots.add(str(path.resolve()).casefold())
    return tuple(sorted(roots))


def profile_data_paths(*, home: Path, data_dir: Path, config: Path, workspace: Path) -> tuple[Path, ...]:
    """One store inventory for runtime leases and scoped update backups.

    Keep store symlinks visible here: backup must reject them, not silently expand
    its read scope. Lease identity alone resolves aliases so runtimes cannot race.
    CLI/config workspace paths may be relative; bind them to this runtime's cwd
    without following symlinks before passing the inventory to strict leases.
    """
    return tuple(path.absolute() for path in (
        config, home / "history" / "cli_history", home / "sessions",
        *(data_dir / name for name in _DATA_STORES),
        *(workspace / name for name in _WORKSPACE_STORES),
    ))


@contextmanager
def profile_data_access(*, home: Path, data_dir: Path, config: Path, workspace: Path,
                        grant: DataStartupGrant | None = None) -> Generator[None]:
    """Lease current stores without expanding an older updater's startup grant.

    Protocol 1 predates the delivery store. That owner is lazy and cannot open
    its database until runtime admission opens. Under an exact legacy grant,
    lease delivery normally, separately from protected initialization. No data
    migration or delivery write is permitted before activation. New updaters
    include it in the ordinary full backup/reservation scope.
    """
    paths = profile_data_paths(home=home, data_dir=data_dir, config=config, workspace=workspace)
    delivery = (data_dir / "delivery").absolute()
    legacy = tuple(path for path in paths if path != delivery)
    if grant is not None:
        pending = _reservation(Path.home() / ".nanobot/updates/data-locks/maintenance.json")
        if (pending is not None and pending.job_id == grant.job_id
                and pending.grants.get(grant.participant) == (grant.digest, _canonical_roots(legacy))):
            with data_access(legacy, grant=grant), data_access((delivery,)):
                yield
            return
    with data_access(paths, grant=grant):
        yield


def finish_data_handoff(paths: Iterable[str | Path], *, job_id: str) -> None:
    """Finish cleanup of a durably verified handoff, including after a crash.

    Unlike starting a handoff this can find its reservation already cleared.
    Caller must have persisted verified runtime success. The owner lock and
    exact job/scope check prevent clearing another maintenance reservation;
    running children keep their own data leases throughout this cleanup.
    """
    roots = _canonical_roots(paths)
    if not roots or str(UUID(job_id)) != job_id:
        raise ValueError("Data handoff completion requires its original identity and scope")
    directory = Path.home() / ".nanobot" / "updates" / "data-locks"
    with file_access(directory / "maintenance.lock", exclusive=True):
        DataLease(roots, directory / "maintenance.json", job_id, False).release_reservation()


def require_no_pending_data_update() -> None:
    """Reject a known unfinished transaction before stopping another gateway.

    This is an early check, not a maintenance grant. The worker must still obtain
    exclusive installation/data leases and validate the reservation after shutdown.
    """
    directory = Path.home() / ".nanobot" / "updates" / "data-locks"
    try:
        with file_access(directory / "maintenance.lock", exclusive=True):
            if _reservation(directory / "maintenance.json") is not None:
                raise InstallationBusyError("Another data update is unfinished; recover it before stopping this gateway")
    except BlockingIOError as exc:
        raise InstallationBusyError("Another data update is active; this gateway was not stopped") from exc


@contextmanager
def data_access(paths: Iterable[str | Path], *, updating: bool = False,
                job_id: str | None = None, grant: DataStartupGrant | None = None) -> Generator[DataLease]:
    """Refuse overlapping live writers/maintenance without waiting or killing them.

    Writers claim roots in one namespace and ancestors in the other; maintenance
    does the reverse, exclusively. Neither a parent nor a child store can bypass
    the other's lease. Disjoint runtime data stays available; maintenance jobs in
    this account serialize deliberately rather than require a live lock registry.
    Leases are nonblocking, ordered and released together after partial failure.
    An exclusive job may reserve its roots across process handoff. Only that same
    job and exact scope can resume maintenance; a crash does not lift the fence.

    After verifying package files, the owner may use shared access with job_id to
    grant restricted child startup. The owner retains the maintenance lock, while
    each granted child holds its own shared data and exclusive participant leases.
    Only the owner releases the reservation after runtime verification; context
    exit never clears it. A grant permits data initialization, not normal work.
    """
    canonical = _canonical_roots(paths)
    roots = set(map(Path, canonical))
    if job_id is not None and (not roots or str(UUID(job_id)) != job_id):
        raise ValueError("Data maintenance requires a canonical job identity")
    if grant is not None and (updating or job_id is not None):
        raise ValueError("A startup participant cannot act as the maintenance owner")
    leases: set[tuple[str, str]] = set()
    for path in roots:
        requested, ancestors = (path,), (path, *path.parents)
        for namespace, items in (
            ("writers", requested if updating else ancestors),
            ("maintenance", ancestors if updating else requested),
        ):
            for item in items:
                # Conservatively merge case aliases, including on macOS volumes
                # where normcase alone does not normalize path identity.
                leases.add((namespace, str(item).casefold()))
    directory = Path.home() / ".nanobot" / "updates" / "data-locks"
    with ExitStack() as stack:
        held: list[FileLease] = []
        try:
            if updating or job_id is not None:
                # One reservation per account, including Windows stores on
                # different drives that have no shared filesystem ancestor.
                held.append(stack.enter_context(file_access(directory / "maintenance.lock", exclusive=True)))
            if grant is not None:
                held.append(stack.enter_context(file_access(directory / f"startup-{grant.participant}.lock", exclusive=True)))
            for namespace, key in sorted(leases):
                name = hashlib.sha256(os.fsencode(key)).hexdigest()
                held.append(stack.enter_context(file_access(directory / f"{namespace}-{name}.lock", exclusive=updating)))
        except BlockingIOError as exc:
            raise InstallationBusyError(
                "Nanobot data is in use by another runtime or update. Stop its writers "
                "before retrying; no data lease was granted."
            ) from exc
        path = directory / "maintenance.json"
        pending = _reservation(path)
        if pending is None and (grant is not None or (job_id is not None and not updating)):
            raise InstallationBusyError("Data maintenance handoff is no longer reserved")
        if pending is not None:
            owner, reserved = pending.job_id, pending.roots
            if updating or job_id is not None:
                if (job_id, canonical) != (owner, reserved):
                    raise InstallationBusyError("Data maintenance belongs to an unfinished update; resume that job first")
            elif grant is not None:
                if grant.job_id != owner or pending.grants.get(grant.participant) != (grant.digest, canonical):
                    raise InstallationBusyError("Startup grant does not match this participant's reserved data scope")
            else:
                requested = set(map(Path, canonical))
                ancestors = {parent for root in requested for parent in (root, *root.parents)}
                if any(root in ancestors or any(parent in requested for parent in root.parents)
                       for root in map(Path, reserved)):
                    raise InstallationBusyError("Nanobot data is reserved by an unfinished update; check its saved job before restarting")
        yield DataLease(canonical, path, job_id, updating, tuple(held))
