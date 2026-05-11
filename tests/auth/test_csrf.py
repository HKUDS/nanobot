"""Slice E2 — double-submit CSRF on state-changing /auth/* and /admin/* routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.auth.routes import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    Request,
    dispatch,
)
from nanobot.auth.service import AuthService


@pytest.fixture()
def svc(tmp_path: Path) -> AuthService:
    yield AuthService.default(tmp_path)


def _get(path: str, *, cookie: str = "") -> Request:
    headers = {}
    if cookie:
        headers["cookie"] = cookie
    return Request(method="GET", path=path, headers=headers, body=b"", remote_ip="1.1.1.1")


def _post(
    path: str, body: dict, *, cookie: str = "", csrf_header: str | None = None
) -> Request:
    headers = {"content-type": "application/json"}
    if cookie:
        headers["cookie"] = cookie
    if csrf_header is not None:
        headers[CSRF_HEADER] = csrf_header
    return Request(
        method="POST",
        path=path,
        headers=headers,
        body=json.dumps(body).encode(),
        remote_ip="1.1.1.1",
    )


def _csrf_from_response(resp) -> str | None:
    for raw in resp.cookies:
        if raw.startswith(CSRF_COOKIE + "="):
            return raw.split("=", 1)[1].split(";", 1)[0]
    return None


def test_get_response_issues_csrf_cookie(svc: AuthService) -> None:
    resp = dispatch(_get("/auth/me"), svc, require_csrf=True)
    assert resp.status == 401
    token = _csrf_from_response(resp)
    assert token is not None
    assert len(token) >= 32


def test_post_without_csrf_header_rejected(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    resp = dispatch(
        _post("/auth/login", {"email": "a@b.com", "password": "correct horse battery staple"}),
        svc,
        require_csrf=True,
    )
    assert resp.status == 403
    payload = json.loads(resp.body)
    assert "csrf" in payload["error"].lower()


def test_post_with_matching_csrf_header_accepted(svc: AuthService) -> None:
    # Step 1: GET issues a CSRF cookie.
    bootstrap = dispatch(_get("/auth/me"), svc, require_csrf=True)
    csrf = _csrf_from_response(bootstrap)
    assert csrf

    svc.create_user("a@b.com", "correct horse battery staple")
    cookie_header = f"{CSRF_COOKIE}={csrf}"
    resp = dispatch(
        _post(
            "/auth/login",
            {"email": "a@b.com", "password": "correct horse battery staple"},
            cookie=cookie_header,
            csrf_header=csrf,
        ),
        svc,
        require_csrf=True,
    )
    assert resp.status == 200


def test_post_with_mismatched_csrf_rejected(svc: AuthService) -> None:
    bootstrap = dispatch(_get("/auth/me"), svc, require_csrf=True)
    csrf = _csrf_from_response(bootstrap)
    cookie_header = f"{CSRF_COOKIE}={csrf}"
    svc.create_user("a@b.com", "correct horse battery staple")
    resp = dispatch(
        _post(
            "/auth/login",
            {"email": "a@b.com", "password": "correct horse battery staple"},
            cookie=cookie_header,
            csrf_header="not-the-same-token",
        ),
        svc,
        require_csrf=True,
    )
    assert resp.status == 403


def test_admin_post_requires_csrf(svc: AuthService) -> None:
    admin = svc.create_user("admin@x", "correct horse battery staple", role="admin")
    s = svc.mint_session(admin.id)
    target = svc.create_user("u@x", "correct horse battery staple")
    cookie = f"{SESSION_COOKIE}={s.token}"

    # Without CSRF header → 403.
    r = dispatch(
        _post(
            f"/admin/users/{target.id}/role",
            {"role": "admin"},
            cookie=cookie,
        ),
        svc,
        require_csrf=True,
    )
    assert r.status == 403

    # With CSRF cookie+header → 200.
    csrf = "test-csrf-token-123456"
    r = dispatch(
        _post(
            f"/admin/users/{target.id}/role",
            {"role": "admin"},
            cookie=f"{cookie}; {CSRF_COOKIE}={csrf}",
            csrf_header=csrf,
        ),
        svc,
        require_csrf=True,
    )
    assert r.status == 200


def test_get_admin_does_not_require_csrf(svc: AuthService) -> None:
    """Read-only admin requests don't need CSRF; only state-changing ones do."""
    admin = svc.create_user("admin@x", "correct horse battery staple", role="admin")
    s = svc.mint_session(admin.id)
    cookie = f"{SESSION_COOKIE}={s.token}"
    r = dispatch(_get("/admin/users", cookie=cookie), svc, require_csrf=True)
    assert r.status == 200


def test_default_dispatch_does_not_require_csrf(svc: AuthService) -> None:
    """Existing tests / scripts that don't pass require_csrf=True still work."""
    svc.create_user("a@b.com", "correct horse battery staple")
    r = dispatch(
        _post("/auth/login", {"email": "a@b.com", "password": "correct horse battery staple"}),
        svc,
    )
    assert r.status == 200


def test_existing_csrf_cookie_not_rotated(svc: AuthService) -> None:
    """Subsequent requests with a CSRF cookie do not get a new one minted."""
    bootstrap = dispatch(_get("/auth/me"), svc, require_csrf=True)
    csrf = _csrf_from_response(bootstrap)
    second = dispatch(
        _get("/auth/me", cookie=f"{CSRF_COOKIE}={csrf}"),
        svc,
        require_csrf=True,
    )
    # No new CSRF cookie issued because client already had one.
    assert _csrf_from_response(second) is None
