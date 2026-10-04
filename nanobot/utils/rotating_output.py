"""Bounded text output for detached nanobot processes."""

from __future__ import annotations

import io
import os
import shutil
import sys
import threading
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

BACKGROUND_LOG_PATH_ENV = "_NANOBOT_BACKGROUND_LOG_PATH"
BACKGROUND_LOG_MAX_BYTES_ENV = "_NANOBOT_BACKGROUND_LOG_MAX_BYTES"
BACKGROUND_LOG_BACKUP_COUNT_ENV = "_NANOBOT_BACKGROUND_LOG_BACKUP_COUNT"

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5


class RotatingTextOutput(io.TextIOBase):
    """A UTF-8 text stream that keeps each retained file within its size cap."""

    def __init__(self, path: Path, *, max_bytes: int, backup_count: int) -> None:
        super().__init__()
        self._path = path
        self._max_bytes = max(1, max_bytes)
        self._backup_count = max(0, backup_count)
        self._handle: BinaryIO | None = None
        self._size = 0
        self._lock = threading.RLock()

    @property
    def encoding(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        return "utf-8"

    @property
    def errors(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        return "replace"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        with self._lock:
            self._ensure_open()
            assert self._handle is not None
            return self._handle.fileno()

    def write(self, text: str) -> int:
        if not text:
            return 0
        data = text.encode(self.encoding, errors=self.errors)
        with self._lock:
            self._ensure_open()
            if len(data) <= self._max_bytes:
                if self._size and self._size + len(data) > self._max_bytes:
                    self._rotate()
                    self._ensure_open()
                self._append(data)
                return len(text)

            if self._size:
                size_before = self._size
                self._rotate()
                if self._size >= size_before:
                    self._ensure_open()
                    self._append(data)
                    return len(text)
            offset = 0
            while offset < len(data):
                self._ensure_open()
                capacity = self._max_bytes - self._size
                if capacity <= 0:
                    size_before = self._size
                    self._rotate()
                    if self._size >= size_before:
                        self._ensure_open()
                        self._append(data[offset:])
                        break
                    continue

                chunk_size = self._utf8_chunk_size(data, offset, capacity)
                if chunk_size == 0 and self._size:
                    self._rotate()
                    continue
                # A configured cap smaller than one UTF-8 code point cannot
                # satisfy both constraints. Keep the byte cap in that degenerate
                # case; normal caps split only at code-point boundaries.
                chunk_size = chunk_size or min(capacity, len(data) - offset)
                chunk = data[offset : offset + chunk_size]
                self._append(chunk)
                offset += chunk_size
                if offset < len(data):
                    size_before = self._size
                    self._rotate()
                    if self._size >= size_before:
                        self._ensure_open()
                        self._append(data[offset:])
                        break
        return len(text)

    @staticmethod
    def _utf8_chunk_size(data: bytes, offset: int, capacity: int) -> int:
        """Return the largest prefix within capacity that ends on a UTF-8 boundary."""
        end = min(len(data), offset + capacity)
        if end == len(data):
            return end - offset
        while end > offset and data[end] & 0xC0 == 0x80:
            end -= 1
        return end - offset

    def _append(self, data: bytes) -> None:
        assert self._handle is not None
        self._handle.write(data)
        self._handle.flush()
        self._size += len(data)

    def flush(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            super().close()

    def _ensure_open(self) -> None:
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        size = self._path.stat().st_size if self._path.exists() else 0
        if size >= self._max_bytes:
            self._rotate()
            size = self._path.stat().st_size if self._path.exists() else 0
        self._handle = self._path.open("ab")
        self._size = size

    def _rotate(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None

        if self._backup_count == 0:
            try:
                self._path.unlink(missing_ok=True)
                self._size = 0
            except OSError:
                self._size = self._path.stat().st_size if self._path.exists() else 0
            return

        try:
            oldest = self._backup_path(self._backup_count)
            oldest.unlink(missing_ok=True)
            for index in range(self._backup_count - 1, 0, -1):
                source = self._backup_path(index)
                if source.exists():
                    source.replace(self._backup_path(index + 1))
            if self._path.exists():
                try:
                    self._path.replace(self._backup_path(1))
                except PermissionError:
                    # A Windows ``gateway logs --follow`` reader can prevent rename.
                    # Copy and truncate preserves both retention and the live stream.
                    shutil.copyfile(self._path, self._backup_path(1))
                    self._path.open("wb").close()
            self._size = 0
        except OSError:
            # Logging must remain available even when rotation is temporarily blocked.
            self._size = self._path.stat().st_size if self._path.exists() else 0

    def _backup_path(self, index: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{index}")


def _positive_int(value: str | None, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(value or ""))
    except ValueError:
        return default


def configure_background_output_from_env() -> RotatingTextOutput | None:
    """Replace inherited output handles when launched by ``ManagedProcessRuntime``."""
    raw_path = os.environ.pop(BACKGROUND_LOG_PATH_ENV, "")
    if not raw_path:
        return None
    max_bytes = _positive_int(
        os.environ.pop(BACKGROUND_LOG_MAX_BYTES_ENV, None),
        DEFAULT_MAX_BYTES,
        minimum=1,
    )
    backup_count = _positive_int(
        os.environ.pop(BACKGROUND_LOG_BACKUP_COUNT_ENV, None),
        DEFAULT_BACKUP_COUNT,
        minimum=0,
    )
    stream = RotatingTextOutput(
        Path(raw_path),
        max_bytes=max_bytes,
        backup_count=backup_count,
    )

    replaced = {id(output): output for output in (sys.stdout, sys.stderr)}
    sys.stdout = stream
    sys.stderr = stream
    sys.__stdout__ = stream
    sys.__stderr__ = stream
    for output in replaced.values():
        with suppress(Exception):
            output.flush()
        with suppress(Exception):
            output.close()
    return stream
