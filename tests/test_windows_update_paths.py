import stat
import sys
from pathlib import Path

import pytest

from nanobot.installation_lock import file_access
from nanobot.update_worker import read_record, write_record
from nanobot.utils.atomic_file import (
    _open_snapshot,
    atomic_write_lines,
    atomic_write_text,
    io_path,
    read_atomic_bytes,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows filesystem semantics")


def record_path(root: Path, length: int) -> Path:
    # Only fixture setup/inspection uses the extended namespace. Every product
    # operation below receives an ordinary absolute path, including at 280 chars.
    root = Path(str(root).removeprefix("\\\\?\\"))
    padding = length - len(str(root)) - len("\\status.json") - 1
    assert 0 < padding < 255
    path = root / ("d" * padding) / "status.json"
    assert path.is_absolute() and len(str(path)) == length
    return path


def fixture_path(path: Path) -> Path:
    return Path("\\\\?\\" + str(path))


@pytest.mark.parametrize("length", [228, 280], ids=["long-sibling", "long-target"])
@pytest.mark.parametrize("kind", ["text", "lines"])
def test_atomic_io(tmp_path: Path, length: int, kind: str) -> None:
    target = record_path(tmp_path, length)
    sibling = target.with_name(f".{target.name}.{'0' * 32}.tmp")
    assert len(str(sibling)) == length + 38 > 260
    if kind == "lines":
        fixture_path(target.parent).mkdir(parents=True)

    def write(text: str) -> None:
        if kind == "text":
            atomic_write_text(target, text)
        else:
            atomic_write_lines(target, [text])

    suffix = b"" if kind == "text" else b"\n"
    write("old")
    with _open_snapshot(target) as previous:
        write("new")
        assert previous.read() == b"old" + suffix
        assert read_atomic_bytes(target) == b"new" + suffix
    assert read_atomic_bytes(target, max_bytes=2) == b"ne"
    assert list(fixture_path(target.parent).glob("*.tmp")) == []


@pytest.mark.parametrize("length", [228, 280], ids=["long-sibling", "long-target"])
def test_update_record(tmp_path: Path, length: int) -> None:
    target = record_path(tmp_path, length)
    fixture_path(target.parent).mkdir(parents=True)
    write_record(target, {"state": "ready"})
    assert read_record(target) == {"state": "ready"}
    with _open_snapshot(target) as previous:
        write_record(target, {"state": "stopping"})
        assert previous.read() == b'{"state":"ready"}\n'
        assert read_record(target) == {"state": "stopping"}


@pytest.mark.parametrize("kind", ["text", "lines"])
def test_readonly_record_keeps_old_value(tmp_path: Path, kind: str) -> None:
    target = record_path(tmp_path, 228)
    fixture_path(target.parent).mkdir(parents=True)
    fixture_path(target).write_bytes(b"kept\n")
    target.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            if kind == "text":
                atomic_write_text(target, "new\n")
            else:
                atomic_write_lines(target, ["new"])
        assert read_atomic_bytes(target) == b"kept\n"
        assert list(fixture_path(target.parent).glob("*.tmp")) == []
    finally:
        target.chmod(stat.S_IWRITE)


def test_long_file_lease(tmp_path: Path) -> None:
    target = record_path(tmp_path, 280).with_suffix(".lock")
    with file_access(target, exclusive=False):
        with file_access(target, exclusive=False):
            with pytest.raises(BlockingIOError):
                with file_access(target, exclusive=True):
                    pytest.fail("An updater acquired a live runtime's lease")
    with file_access(target, exclusive=True):
        with pytest.raises(BlockingIOError):
            with file_access(target, exclusive=False):
                pytest.fail("A runtime entered an updating installation")
    with file_access(target, exclusive=False):
        pass


def test_io_path_spelling(tmp_path: Path) -> None:
    ordinary = tmp_path / "nested" / ".." / "status.json"
    extended = fixture_path(tmp_path / "status.json")
    assert io_path(ordinary) == extended
    assert io_path(extended) == extended
    assert io_path(Path(r"\\server\share\updates\status.json")) == Path(
        r"\\?\UNC\server\share\updates\status.json"
    )


def test_relative_atomic_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    target = Path("relative state") / "status.json"
    atomic_write_text(target, "old")
    with _open_snapshot(target) as previous:
        atomic_write_text(target, "new")
        assert previous.read() == b"old"
        assert read_atomic_bytes(target) == b"new"
