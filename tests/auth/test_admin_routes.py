"""Slice D2/D3 — /admin/users routes + role gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.auth.routes import (
    SESSION_COOKIE,
    Request,
    dispatch,
)
from nanobot.auth.service import AuthService


@pytest.fixture()
def svc(tmp_path: Path) -> AuthService:
    yield AuthService.default(tmp_path)


def _admin_cookie(svc: AuthService) -> str:
    """Create an admin user and return the auth cookie string."""
    u = svc.create_user("admin@nanobot", "correct horse battery staple", role="admin")
    s = svc.mint_session(u.id)
    return f"{SESSION_COOKIE}={s.token}"


def _user_cookie(svc: AuthService, email: str = "regular@nanobot") -> str:
    u = svc.create_user(email, "correct horse battery staple")
    s = svc.mint_session(u.id)
    return f"{SESSION_COOKIE}={s.token}"


def _req(method: str, path: str, *, cookie: str | None = None, body: dict | None = None) -> Request:
    headers = {"content-type": "application/json"}
    if cookie:
        headers["cookie"] = cookie
    return Request(
        method=method,
        path=path,
        headers=headers,
        body=json.dumps(body).encode() if body is not None else b"",
        remote_ip="127.0.0.1",
    )


def test_admin_list_requires_admin(svc: AuthService) -> None:
    # Unauth: 401.
    r = dispatch(_req("GET", "/admin/users"), svc)
    assert r.status == 401
    # Regular user: 403.
    r = dispatch(_req("GET", "/admin/users", cookie=_user_cookie(svc)), svc)
    assert r.status == 403


def test_admin_list_returns_users(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    svc.create_user("a@x", "correct horse battery staple")
    svc.create_user("b@x", "correct horse battery staple")
    r = dispatch(_req("GET", "/admin/users", cookie=cookie), svc)
    assert r.status == 200
    payload = json.loads(r.body)
    emails = {u["email"] for u in payload["users"]}
    assert {"a@x", "b@x", "admin@nanobot"} <= emails


def test_admin_set_role_promotes(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    target = svc.create_user("plain@x", "correct horse battery staple")
    r = dispatch(
        _req("POST", f"/admin/users/{target.id}/role", cookie=cookie, body={"role": "admin"}),
        svc,
    )
    assert r.status == 200
    assert svc.get_user(target.id).role == "admin"


def test_admin_set_role_rejects_bad_value(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    target = svc.create_user("plain@x", "correct horse battery staple")
    r = dispatch(
        _req("POST", f"/admin/users/{target.id}/role", cookie=cookie, body={"role": "tsar"}),
        svc,
    )
    assert r.status == 400


def test_admin_set_role_requires_admin(svc: AuthService) -> None:
    target = svc.create_user("plain@x", "correct horse battery staple")
    r = dispatch(
        _req("POST", f"/admin/users/{target.id}/role", cookie=_user_cookie(svc), body={"role": "admin"}),
        svc,
    )
    assert r.status == 403


def test_admin_set_disabled_disables_and_revokes(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    target = svc.create_user("plain@x", "correct horse battery staple")
    live = svc.mint_session(target.id)
    r = dispatch(
        _req("POST", f"/admin/users/{target.id}/disabled", cookie=cookie, body={"disabled": True}),
        svc,
    )
    assert r.status == 200
    assert svc.get_user(target.id).disabled is True
    # Their existing session must no longer verify.
    from nanobot.auth import AuthError

    with pytest.raises(AuthError):
        svc.verify_session(live.token)


def test_admin_set_disabled_invalid_body(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    target = svc.create_user("plain@x", "correct horse battery staple")
    r = dispatch(
        _req("POST", f"/admin/users/{target.id}/disabled", cookie=cookie, body={"disabled": "yes"}),
        svc,
    )
    assert r.status == 400


def test_admin_delete_removes_user(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    target = svc.create_user("doomed@x", "correct horse battery staple")
    r = dispatch(_req("DELETE", f"/admin/users/{target.id}", cookie=cookie), svc)
    assert r.status == 200
    assert svc.get_user_by_email("doomed@x") is None


def test_admin_cannot_self_delete(svc: AuthService) -> None:
    u = svc.create_user("admin@x", "correct horse battery staple", role="admin")
    s = svc.mint_session(u.id)
    cookie = f"{SESSION_COOKIE}={s.token}"
    r = dispatch(_req("DELETE", f"/admin/users/{u.id}", cookie=cookie), svc)
    assert r.status == 400


def test_admin_unknown_user_returns_404(svc: AuthService) -> None:
    cookie = _admin_cookie(svc)
    # Syntactically valid ULID, but no row.
    fake = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"
    r = dispatch(_req("DELETE", f"/admin/users/{fake}", cookie=cookie), svc)
    assert r.status == 404


def test_admin_role_change_writes_audit_row(svc: AuthService, tmp_path: Path) -> None:
    import sqlite3

    from nanobot.auth.schema import get_auth_db_path

    cookie = _admin_cookie(svc)
    target = svc.create_user("plain@x", "correct horse battery staple")
    dispatch(
        _req("POST", f"/admin/users/{target.id}/role", cookie=cookie, body={"role": "admin"}),
        svc,
    )
    events = [
        r[0]
        for r in sqlite3.connect(get_auth_db_path(tmp_path)).execute(
            "SELECT event FROM audit_log"
        )
    ]
    assert "promote" in events


def test_admin_disabled_admin_blocked(svc: AuthService) -> None:
    """A disabled admin can't perform admin actions even with a valid session."""
    admin = svc.create_user("admin@x", "correct horse battery staple", role="admin")
    s = svc.mint_session(admin.id)
    # Manually flip disabled (simulate another admin disabling them).
    svc._conn.execute("UPDATE users SET disabled = 1 WHERE id = ?", (admin.id,))
    cookie = f"{SESSION_COOKIE}={s.token}"
    r = dispatch(_req("GET", "/admin/users", cookie=cookie), svc)
    assert r.status == 403
