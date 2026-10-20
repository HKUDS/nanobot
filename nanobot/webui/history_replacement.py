"""Rollback/recovery journal for the display side of an owner history replacement.

SQLite generation is the commit decision. The journal is temporary transaction
material, never a backup session or a user-selectable version. Readers and
appenders settle an interrupted replacement before accessing display files.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar
from uuid import uuid4

from filelock import FileLock
from loguru import logger

from nanobot.session.location import SessionLocation
from nanobot.utils.helpers import atomic_write_lines

_P = ParamSpec("_P")
_T = TypeVar("_T")


@lru_cache(maxsize=256)
def _lock(path: Path) -> FileLock:
    return FileLock(str(path), timeout=10)


def _paths(key: str) -> tuple[Path, Path, tuple[Path, ...]]:
    from nanobot.webui.transcript import webui_transcript_path

    root = webui_transcript_path(key).parent
    stem = SessionLocation.safe_key(key)
    return (root / f"{stem}.edit.lock", root / f"{stem}.edit.json", (
        root / f"{stem}.jsonl", root / f"{stem}.segments", root / f"{stem}.json",
    ))


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _restore(stage: Path, paths: tuple[Path, ...]) -> None:
    for index, target in enumerate(paths):
        backup = stage / f"old-{index}"
        if backup.is_dir():
            replacement = stage / f"restore-{index}"
            if replacement.exists():
                _remove(replacement)
            shutil.copytree(backup, replacement)
            _remove(target)
            os.replace(replacement, target)
        elif backup.is_file():
            replacement = stage / f"restore-{index}"
            shutil.copy2(backup, replacement)
            os.replace(replacement, target)
        else:
            _remove(target)


def _finish(journal: Path, stage: Path) -> None:
    journal.unlink(missing_ok=True)
    try:
        shutil.rmtree(stage)
    except OSError:
        logger.warning("Unable to remove completed history-edit transaction files: {}", stage)


def _recover(key: str, journal: Path, paths: tuple[Path, ...]) -> None:
    if not journal.is_file():
        return
    data = json.loads(journal.read_text(encoding="utf-8"))
    stage = journal.parent / data["stage"]
    if stage.parent != journal.parent or not stage.name.startswith(".edit-"):
        raise ValueError("invalid history-edit journal")
    # Read-only and independent of the session owner's connection/transaction.
    with sqlite3.connect(Path(data["database"]).as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        row = db.execute("SELECT generation FROM sessions WHERE key=?", (key,)).fetchone()
    if row and row[0] == data["generation"]:
        # All new files were installed before the SQLite commit.
        _finish(journal, stage)
    else:
        _restore(stage, paths)
        _finish(journal, stage)


@contextmanager
def transcript_access(key: str) -> Iterator[None]:
    lock_path, journal, paths = _paths(key)
    with _lock(lock_path):
        _recover(key, journal, paths)
        yield


def guarded_transcript(function: Callable[Concatenate[str, _P], _T]) -> Callable[Concatenate[str, _P], _T]:
    @wraps(function)
    def guarded(session_key: str, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        with transcript_access(session_key):
            return function(session_key, *args, **kwargs)
    return guarded


@contextmanager
def replace_transcript(
    key: str, rows: list[dict[str, Any]], *, database: Path, generation: str,
) -> Iterator[None]:
    """Install prepared rows; retain rollback material until SQLite settles."""
    from nanobot.webui.transcript import _write_records_to_path

    lock_path, journal, paths = _paths(key)
    with _lock(lock_path):
        _recover(key, journal, paths)
        stage = journal.parent / f".edit-{uuid4().hex}"
        stage.mkdir()
        journal_written = False
        try:
            _write_records_to_path(stage / "new.jsonl", rows)
            for index, path in enumerate(paths):
                if path.is_dir():
                    shutil.copytree(path, stage / f"old-{index}")
                elif path.is_file():
                    shutil.copy2(path, stage / f"old-{index}")
            atomic_write_lines(journal, [json.dumps({
                "stage": stage.name, "database": str(database), "generation": generation,
            })])
            journal_written = True
            os.replace(stage / "new.jsonl", paths[0])
            for path in paths[1:]:
                _remove(path)
            yield
        except BaseException:
            if journal_written:
                _restore(stage, paths)
                _finish(journal, stage)
            else:
                shutil.rmtree(stage)
            raise
        else:
            # A failed cleanup must not turn a committed edit into a rejection.
            try:
                _finish(journal, stage)
            except OSError:
                logger.warning("History-edit journal cleanup deferred: {}", journal)
