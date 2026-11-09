"""Descriptor-based reads for paths already resolved under workspace policy."""

import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class NotRegularFileError(OSError):
    """The opened resource is not a regular file."""


@contextmanager
def open_regular_file(resolved_path: Path) -> Generator[tuple[BinaryIO, int]]:
    """Own one descriptor for the entire read and report its initial size.

    Callers must resolve the path under the current access policy first.
    Where supported, refuse a swapped-in final symlink and avoid waiting on
    a swapped-in FIFO. This does not protect ancestor path components.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(resolved_path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise NotRegularFileError
        yield stream, opened.st_size
