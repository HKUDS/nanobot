"""Slice D1 — `nanobot user …` CLI subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.auth import AuthService
from nanobot.cli.user import user_app


@pytest.fixture()
def isolate_data_dir(monkeypatch, tmp_path: Path) -> Path:
    """Redirect AuthService.default() to a temp data dir."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return tmp_path


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_list_empty(runner: CliRunner, isolate_data_dir: Path) -> None:
    result = runner.invoke(user_app, ["list"])
    assert result.exit_code == 0
    assert "No users." in result.output


def test_create_and_list_user(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    pwds = iter(["correct horse battery staple", "correct horse battery staple"])
    monkeypatch.setattr("nanobot.cli.user.getpass.getpass", lambda *_: next(pwds))
    result = runner.invoke(user_app, ["create", "alice@x.com", "--display-name", "Alice"])
    assert result.exit_code == 0, result.output
    assert "Created" in result.output
    assert "alice@x.com" in result.output

    listing = runner.invoke(user_app, ["list"])
    # Rich truncates email columns in narrow test consoles, so match a stable prefix.
    assert "alice@x" in listing.output
    assert "Alice" in listing.output


def test_create_rejects_short_password(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    pwds = iter(["short", "short"])
    monkeypatch.setattr("nanobot.cli.user.getpass.getpass", lambda *_: next(pwds))
    result = runner.invoke(user_app, ["create", "alice@x.com"])
    assert result.exit_code == 1


def test_create_rejects_password_mismatch(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    pwds = iter(["correct horse battery staple", "different one entirely"])
    monkeypatch.setattr("nanobot.cli.user.getpass.getpass", lambda *_: next(pwds))
    result = runner.invoke(user_app, ["create", "alice@x.com"])
    assert result.exit_code == 1
    assert "do not match" in result.output.lower()


def test_create_duplicate_email(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "nanobot.cli.user.getpass.getpass", lambda *_: "correct horse battery staple"
    )
    assert runner.invoke(user_app, ["create", "alice@x.com"]).exit_code == 0
    second = runner.invoke(user_app, ["create", "alice@x.com"])
    assert second.exit_code == 1
    assert "already registered" in second.output


def test_promote_then_demote(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "nanobot.cli.user.getpass.getpass", lambda *_: "correct horse battery staple"
    )
    runner.invoke(user_app, ["create", "alice@x.com"])

    p = runner.invoke(user_app, ["promote", "alice@x.com"])
    assert p.exit_code == 0, p.output
    svc = AuthService.default(isolate_data_dir)
    try:
        assert svc.get_user_by_email("alice@x.com").role == "admin"
    finally:
        svc.close()

    d = runner.invoke(user_app, ["demote", "alice@x.com"])
    assert d.exit_code == 0
    svc = AuthService.default(isolate_data_dir)
    try:
        assert svc.get_user_by_email("alice@x.com").role == "user"
    finally:
        svc.close()


def test_reset_password_revokes_sessions(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "nanobot.cli.user.getpass.getpass", lambda *_: "correct horse battery staple"
    )
    runner.invoke(user_app, ["create", "alice@x.com"])

    svc = AuthService.default(isolate_data_dir)
    try:
        alice = svc.get_user_by_email("alice@x.com")
        live = svc.mint_session(alice.id)
    finally:
        svc.close()

    new_pwds = iter(["new strong password 1234", "new strong password 1234"])
    monkeypatch.setattr("nanobot.cli.user.getpass.getpass", lambda *_: next(new_pwds))
    r = runner.invoke(user_app, ["reset-password", "alice@x.com"])
    assert r.exit_code == 0

    svc = AuthService.default(isolate_data_dir)
    try:
        # The old session must no longer verify.
        from nanobot.auth import AuthError

        with pytest.raises(AuthError):
            svc.verify_session(live.token)
        # New password works.
        svc.verify_password("alice@x.com", "new strong password 1234")
    finally:
        svc.close()


def test_delete_with_yes_flag(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "nanobot.cli.user.getpass.getpass", lambda *_: "correct horse battery staple"
    )
    runner.invoke(user_app, ["create", "alice@x.com"])
    r = runner.invoke(user_app, ["delete", "alice@x.com", "--yes"])
    assert r.exit_code == 0
    assert "Deleted" in r.output

    svc = AuthService.default(isolate_data_dir)
    try:
        assert svc.get_user_by_email("alice@x.com") is None
    finally:
        svc.close()


def test_disable_blocks_login(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "nanobot.cli.user.getpass.getpass", lambda *_: "correct horse battery staple"
    )
    runner.invoke(user_app, ["create", "alice@x.com"])

    svc = AuthService.default(isolate_data_dir)
    try:
        svc.verify_password("alice@x.com", "correct horse battery staple")
    finally:
        svc.close()

    r = runner.invoke(user_app, ["disable", "alice@x.com"])
    assert r.exit_code == 0

    svc = AuthService.default(isolate_data_dir)
    try:
        from nanobot.auth import AuthError

        with pytest.raises(AuthError):
            svc.verify_password("alice@x.com", "correct horse battery staple")
    finally:
        svc.close()

    # Re-enable.
    r = runner.invoke(user_app, ["disable", "alice@x.com", "--off"])
    assert r.exit_code == 0
    svc = AuthService.default(isolate_data_dir)
    try:
        svc.verify_password("alice@x.com", "correct horse battery staple")
    finally:
        svc.close()


def test_unknown_user_errors_cleanly(
    runner: CliRunner, isolate_data_dir: Path
) -> None:
    result = runner.invoke(user_app, ["promote", "ghost@nowhere"])
    assert result.exit_code == 1
    assert "No user matches" in result.output


def test_resolve_by_user_id(
    runner: CliRunner, isolate_data_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "nanobot.cli.user.getpass.getpass", lambda *_: "correct horse battery staple"
    )
    runner.invoke(user_app, ["create", "alice@x.com"])
    svc = AuthService.default(isolate_data_dir)
    try:
        uid = svc.get_user_by_email("alice@x.com").id
    finally:
        svc.close()

    r = runner.invoke(user_app, ["promote", uid])
    assert r.exit_code == 0
