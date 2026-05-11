"""Tests for nanobot.auth.service."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from nanobot.auth import (
    AuthError,
    AuthService,
    EmailTakenError,
    init_auth_db,
    is_ulid,
)
from nanobot.auth.schema import get_auth_db_path


@pytest.fixture()
def svc(tmp_path: Path) -> AuthService:
    init_auth_db(tmp_path)
    yield AuthService.default(tmp_path)


def test_create_user_returns_ulid(svc: AuthService) -> None:
    u = svc.create_user("Alice@Example.com", "correct horse battery staple")
    assert is_ulid(u.id)
    assert u.email == "alice@example.com"
    assert u.role == "user"
    assert u.disabled is False


def test_create_user_duplicate_email_raises(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    with pytest.raises(EmailTakenError):
        svc.create_user("A@B.COM", "another password long enough")


def test_create_user_rejects_short_password(svc: AuthService) -> None:
    with pytest.raises(AuthError):
        svc.create_user("a@b.com", "short")


def test_create_user_rejects_bad_email(svc: AuthService) -> None:
    with pytest.raises(AuthError):
        svc.create_user("not-an-email", "correct horse battery staple")


def test_verify_password_success_and_failure(svc: AuthService) -> None:
    pwd = "correct horse battery staple"
    u = svc.create_user("a@b.com", pwd)
    assert svc.verify_password("a@b.com", pwd).id == u.id

    with pytest.raises(AuthError):
        svc.verify_password("a@b.com", "wrong password long enough")

    with pytest.raises(AuthError):
        svc.verify_password("unknown@b.com", pwd)


def test_verify_password_rejects_disabled_user(svc: AuthService, tmp_path: Path) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    conn = sqlite3.connect(get_auth_db_path(tmp_path))
    conn.execute("UPDATE users SET disabled=1 WHERE id=?", (u.id,))
    conn.commit()
    conn.close()
    with pytest.raises(AuthError):
        svc.verify_password("a@b.com", "correct horse battery staple")


def test_mint_and_verify_session(svc: AuthService) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    s = svc.mint_session(u.id, user_agent="UA/1", ip="1.2.3.4")
    assert s.user_id == u.id
    assert s.expires_at > int(time.time())

    verified = svc.verify_session(s.token)
    assert verified.id == u.id


def test_verify_session_rejects_bad_token(svc: AuthService) -> None:
    with pytest.raises(AuthError):
        svc.verify_session("not-a-real-token")
    with pytest.raises(AuthError):
        svc.verify_session("")


def test_revoked_session_rejected(svc: AuthService) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    s = svc.mint_session(u.id)
    svc.revoke_session(s.token)
    with pytest.raises(AuthError):
        svc.verify_session(s.token)


def test_expired_session_rejected(svc: AuthService) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    s = svc.mint_session(u.id, ttl_seconds=1)
    time.sleep(1.2)
    with pytest.raises(AuthError):
        svc.verify_session(s.token)


def test_sliding_ttl_extends(svc: AuthService, tmp_path: Path) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    s = svc.mint_session(u.id, ttl_seconds=10)
    time.sleep(1.1)
    svc.verify_session(s.token, sliding=True, ttl_seconds=10)
    row = sqlite3.connect(get_auth_db_path(tmp_path)).execute(
        "SELECT expires_at FROM web_sessions ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row[0] > s.expires_at


def test_set_password_revokes_existing_sessions(svc: AuthService) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    s = svc.mint_session(u.id)
    svc.set_password(u.id, "new password also long enough")
    with pytest.raises(AuthError):
        svc.verify_session(s.token)
    svc.verify_password("a@b.com", "new password also long enough")


def test_expire_sessions_purges_old_rows(svc: AuthService) -> None:
    u = svc.create_user("a@b.com", "correct horse battery staple")
    svc.mint_session(u.id, ttl_seconds=1)
    time.sleep(1.2)
    assert svc.expire_sessions() >= 1


def test_audit_log_records_events(svc: AuthService, tmp_path: Path) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    try:
        svc.verify_password("a@b.com", "wrong password long enough")
    except AuthError:
        pass
    svc.verify_password("a@b.com", "correct horse battery staple")

    conn = sqlite3.connect(get_auth_db_path(tmp_path))
    events = [r[0] for r in conn.execute("SELECT event FROM audit_log ORDER BY id")]
    assert "signup" in events
    assert "login.fail" in events
    assert "login.ok" in events
