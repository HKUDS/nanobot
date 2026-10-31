import os
import subprocess
import sys
from pathlib import Path

import pytest

from nanobot.utils.rotating_output import (
    BACKGROUND_LOG_BACKUP_COUNT_ENV,
    BACKGROUND_LOG_MAX_BYTES_ENV,
    BACKGROUND_LOG_PATH_ENV,
    RotatingTextOutput,
)


def test_rotating_output_enforces_size_and_backup_count(tmp_path: Path) -> None:
    log_path = tmp_path / "gateway.log"
    output = RotatingTextOutput(log_path, max_bytes=8, backup_count=2)

    output.write("12345678")
    output.write("new")
    output.write("abcdefgh")
    output.close()

    assert log_path.read_text(encoding="utf-8") == "abcdefgh"
    assert (tmp_path / "gateway.log.1").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "gateway.log.2").read_text(encoding="utf-8") == "12345678"
    assert not (tmp_path / "gateway.log.3").exists()


def test_rotating_output_rotates_oversized_existing_file_before_append(tmp_path: Path) -> None:
    log_path = tmp_path / "gateway.log"
    log_path.write_text("existing output", encoding="utf-8")
    output = RotatingTextOutput(log_path, max_bytes=8, backup_count=1)

    output.write("fresh")
    output.close()

    assert log_path.read_text(encoding="utf-8") == "fresh"
    assert (tmp_path / "gateway.log.1").read_text(encoding="utf-8") == "existing output"


@pytest.mark.parametrize("initial_text", ["", "kept"])
@pytest.mark.parametrize("operation", ["write", "empty_write", "fileno"])
def test_closed_output_does_not_reopen_log(
    tmp_path: Path, initial_text: str, operation: str
) -> None:
    log_path = tmp_path / "gateway.log"
    with RotatingTextOutput(log_path, max_bytes=8, backup_count=1) as output:
        output.write(initial_text)

    try:
        with pytest.raises(ValueError, match="closed"):
            if operation == "fileno":
                output.fileno()
            else:
                output.write("" if operation == "empty_write" else "after close")

        assert output.closed
        assert log_path.exists() == bool(initial_text)
        if initial_text:
            assert log_path.read_text(encoding="utf-8") == initial_text
        assert not (tmp_path / "gateway.log.1").exists()
    finally:
        output.close()


def test_rotating_output_splits_one_oversized_write_at_utf8_boundaries(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "gateway.log"
    output = RotatingTextOutput(log_path, max_bytes=8, backup_count=2)
    text = "A世界BC🙂DEF界G"

    assert output.write(text) == len(text)
    output.close()

    paths = [tmp_path / "gateway.log.2", tmp_path / "gateway.log.1", log_path]
    assert all(path.stat().st_size <= 8 for path in paths)
    assert "".join(path.read_text(encoding="utf-8") for path in paths) == text


def test_rotating_output_keeps_writing_when_rotation_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_path = tmp_path / "gateway.log"
    output = RotatingTextOutput(log_path, max_bytes=8, backup_count=1)
    output.write("12345678")
    original_replace = Path.replace

    def block_active_log_rotation(path: Path, target: Path) -> Path:
        if path == log_path:
            raise OSError("rotation blocked")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", block_active_log_rotation)

    assert output.write("oversized output") == len("oversized output")
    output.close()

    assert log_path.read_text(encoding="utf-8") == "12345678oversized output"


def test_rotating_output_falls_back_when_active_log_cannot_be_renamed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_path = tmp_path / "gateway.log"
    log_path.write_text("existing", encoding="utf-8")
    original_replace = Path.replace

    def fail_active_log_rename(path: Path, target: Path) -> Path:
        if path == log_path:
            raise PermissionError("file is being followed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_active_log_rename)
    output = RotatingTextOutput(log_path, max_bytes=8, backup_count=1)

    output.write("fresh")
    output.close()

    assert log_path.read_text(encoding="utf-8") == "fresh"
    assert (tmp_path / "gateway.log.1").read_text(encoding="utf-8") == "existing"


def test_background_output_environment_redirects_stdout_and_stderr(tmp_path: Path) -> None:
    log_path = tmp_path / "gateway.log"
    env = os.environ.copy()
    env[BACKGROUND_LOG_PATH_ENV] = str(log_path)
    env[BACKGROUND_LOG_MAX_BYTES_ENV] = "1024"
    env[BACKGROUND_LOG_BACKUP_COUNT_ENV] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from nanobot.utils.rotating_output import "
                "configure_background_output_from_env; "
                "configure_background_output_from_env(); "
                "print('stdout line'); "
                "print('stderr line', file=__import__('sys').stderr)"
            ),
        ],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "stdout line",
        "stderr line",
    ]
