import os
import subprocess
import sys
from pathlib import Path

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
