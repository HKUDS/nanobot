"""Reject unconverted display-history backups before sessions become writable."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

from nanobot.session.location import SessionLocation

if TYPE_CHECKING:
    from nanobot.session.sqlite_store import SqliteSessionStore

_IMPORT_MARKER = "webui_history_import_v1"
_CHECKED_MARKER = "webui_history_checked_v1"


def _children(directory: Path, *, missing_ok: bool = False) -> list[Path]:
    try:
        return sorted(directory.iterdir())
    except FileNotFoundError:
        if missing_ok:
            return []
        raise RuntimeError(f"Cannot inspect legacy WebUI history directory: {directory}") from None
    except OSError as exc:
        raise RuntimeError(f"Cannot inspect legacy WebUI history directory: {directory}") from exc


def _has_legacy_content(path: Path) -> bool:
    # 0.4.0 skipped empty files without recording per-chat import ownership.
    state = path.lstat()
    return not stat.S_ISREG(state.st_mode) or state.st_size > 0


def _source_identity(directory: Path, path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Legacy WebUI history must be a regular file: {path}")
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        after = os.fstat(source.fileno())
    if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or not os.path.samestat(after, path.stat())):
        raise RuntimeError(f"Legacy WebUI history changed while checking: {path}")
    return [str(path.relative_to(directory)), digest]


def check_history_upgrade(store: SqliteSessionStore, directory: Path) -> None:
    """Check the instance before writes without interpreting or importing old records."""
    if directory.is_symlink():
        raise RuntimeError(f"WebUI history directory must not be a symlink: {directory}")
    sources: dict[str, list[Path]] = {}
    for path in _children(directory, missing_ok=True):
        if path.match("*.jsonl") and _has_legacy_content(path):
            sources.setdefault(path.stem, []).append(path)
        elif path.match("*.segments"):
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError(f"Legacy WebUI segments must be a directory: {path}")
            for segment in _children(path):
                if segment.match("[0-9][0-9][0-9][0-9][0-9][0-9].jsonl") and _has_legacy_content(segment):
                    sources.setdefault(path.stem, []).append(segment)
    if not sources:
        return

    namespace = store.path.parent
    with store.transaction() as db:
        imported = db.execute("SELECT value FROM storage_meta WHERE key=?", (_IMPORT_MARKER,)).fetchone()
        if imported is not None and imported[0] != "complete":
            raise RuntimeError(f"Invalid legacy WebUI import marker in {store.path}; restore a valid backup.")
        # 0.4.0 could complete this namespace while skipping a source owned by
        # another workspace. Only per-chat receipts prove a source was imported here.
        local_imports: set[str] = {
            SessionLocation.safe_key(str(row[0])[len(_IMPORT_MARKER) + 1:])
            for row in db.execute(
                "SELECT key FROM storage_meta WHERE key LIKE ? AND value='complete'", (_IMPORT_MARKER + ":%",),
            )
        } if imported is not None else set()
        sources = {stem: paths for stem, paths in sources.items() if stem not in local_imports}
        if not sources:
            return

        owners: dict[str, set[tuple[Path, str]]] = {}
        for database in namespace.parent.glob("*/sessions.sqlite3"):
            if database.parent == namespace:
                continue
            if database.is_symlink() or database.parent.is_symlink():
                raise RuntimeError(f"session namespace must not be a symlink: {database}")
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as foreign:
                # A rejected pre-0.4 upgrade can leave an empty, rolled-back database.
                if (foreign.execute("PRAGMA user_version").fetchone()[0] == 0
                        and foreign.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None):
                    continue
                for row in foreign.execute(
                    "SELECT key FROM storage_meta WHERE key LIKE ? AND value='complete'", (_IMPORT_MARKER + ":%",),
                ):
                    key = str(row[0])[len(_IMPORT_MARKER) + 1:]
                    owners.setdefault(SessionLocation.safe_key(key), set()).add((database, key))

        evidence: dict[str, object] = {}
        for stem, paths in sources.items():
            matches = owners.get(stem, set())
            if len(matches) != 1:
                _require_040(paths[0])
            database, key = next(iter(matches))
            evidence[stem] = {
                "owner": database.parent.name, "key": key,
                "files": [_source_identity(directory, path) for path in paths],
            }
        checked = db.execute("SELECT value FROM storage_meta WHERE key=?", (_CHECKED_MARKER,)).fetchone()
        try:
            raw_previous: object = json.loads(checked[0]) if checked is not None else {}
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid legacy WebUI history check marker in {store.path}.") from exc
        if not isinstance(raw_previous, dict):
            raise RuntimeError(f"Invalid legacy WebUI history check marker in {store.path}.")
        previous = cast(dict[str, object], raw_previous)
        local_stems = {SessionLocation.safe_key(str(row[0])) for row in db.execute("SELECT key FROM sessions")}
        for stem, paths in sources.items():
            if previous.get(stem) != evidence[stem] and stem in local_stems:
                _require_040(paths[0])
        # Remember content digests and foreign receipts, not history records.
        # Unchanged foreign backups stay valid even after a new local chat uses the same key.
        encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        db.execute("INSERT INTO storage_meta (key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_CHECKED_MARKER, encoded))


def _require_040(source: Path) -> NoReturn:
    raise RuntimeError(
        f"Legacy WebUI history requires nanobot 0.4.0: {source}. "
        "Start the 0.4.0 gateway with the same config and the workspace that owns this history "
        "to finish migration before upgrading; resolve any ownership conflict first. "
        "Existing history files have not been changed."
    )
