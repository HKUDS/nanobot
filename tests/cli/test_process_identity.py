from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.cli.process_identity import named_executable, set_cli_process_identity


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["agent"], "nanobot-agent"),
        (["gateway", "--background"], "nanobot-gateway"),
        (["webui"], "nanobot-webui"),
        (["status"], "nanobot"),
        ([], "nanobot"),
    ],
)
def test_cli_process_identity_uses_product_and_role(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    expected: str,
) -> None:
    titles: list[str] = []
    monkeypatch.setattr("nanobot.cli.process_identity.os.name", "posix")
    monkeypatch.setattr("nanobot.cli.process_identity.setproctitle", titles.append)

    set_cli_process_identity(args)

    assert titles == [expected]


def test_cli_process_identity_keeps_windows_launcher_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titles: list[str] = []
    monkeypatch.setattr("nanobot.cli.process_identity.os.name", "nt")
    monkeypatch.setattr("nanobot.cli.process_identity.setproctitle", titles.append)

    set_cli_process_identity(["agent"])

    assert titles == []


def test_named_executable_creates_stable_role_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bun"
    executable.write_text("runtime", encoding="utf-8")
    monkeypatch.setattr("nanobot.cli.process_identity.os.name", "posix")

    first = Path(
        named_executable(executable.as_posix(), name="nanobot-tui", directory=tmp_path / "run")
    )
    second = Path(
        named_executable(executable.as_posix(), name="nanobot-tui", directory=tmp_path / "run")
    )

    assert first == second
    assert first.name == "nanobot-tui"
    assert first.is_symlink()
    assert first.resolve() == executable


def test_named_executable_uses_original_on_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("nanobot.cli.process_identity.os.name", "nt")

    assert (
        named_executable("bun.exe", name="nanobot-tui", directory=tmp_path / "run")
        == "bun.exe"
    )
