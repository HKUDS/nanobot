"""Tests for nanobot.auth.routes — request/response level."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.auth.routes import (
    SESSION_COOKIE,
    Request,
    Response,
    dispatch,
)
from nanobot.auth.service import AuthService


@pytest.fixture()
def svc(tmp_path: Path) -> AuthService:
    yield AuthService.default(tmp_path)


def _post(path: str, body: dict, *, cookie: str | None = None) -> Request:
    headers = {"content-type": "application/json"}
    if cookie is not None:
        headers["cookie"] = cookie
    return Request(
        method="POST", path=path, headers=headers,
        body=json.dumps(body).encode("utf-8"), remote_ip="127.0.0.1",
    )


def _get(path: str, *, cookie: str | None = None) -> Request:
    headers = {}
    if cookie is not None:
        headers["cookie"] = cookie
    return Request(
        method="GET", path=path, headers=headers, body=b"", remote_ip="127.0.0.1",
    )


def _cookie_from_response(resp: Response) -> str:
    assert resp.cookies, "expected Set-Cookie on response"
    raw = resp.cookies[0]
    token = raw.split(";", 1)[0]  # "nanobot_session=<token>"
    return token


def test_login_success_sets_cookie(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    resp = dispatch(_post("/auth/login", {"email": "a@b.com", "password": "correct horse battery staple"}), svc)
    assert resp.status == 200
    payload = json.loads(resp.body)
    assert payload["user"]["email"] == "a@b.com"
    cookie = _cookie_from_response(resp)
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    flags = "; ".join(resp.cookies[0].split(";")[1:]).lower()
    assert "httponly" in flags
    assert "samesite=lax" in flags
    assert "path=/" in flags


def test_login_bad_password_returns_401(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    resp = dispatch(_post("/auth/login", {"email": "a@b.com", "password": "wrong password long enough"}), svc)
    assert resp.status == 401
    assert not resp.cookies


def test_login_unknown_email_returns_401(svc: AuthService) -> None:
    resp = dispatch(_post("/auth/login", {"email": "nobody@b.com", "password": "any pwd long enough"}), svc)
    assert resp.status == 401


def test_login_missing_fields_returns_400(svc: AuthService) -> None:
    resp = dispatch(_post("/auth/login", {"email": ""}), svc)
    assert resp.status == 400


def test_login_secure_flag_when_https(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    req = _post("/auth/login", {"email": "a@b.com", "password": "correct horse battery staple"})
    req = Request(
        method=req.method, path=req.path,
        headers={**req.headers, "x-forwarded-proto": "https"},
        body=req.body, remote_ip=req.remote_ip,
    )
    resp = dispatch(req, svc)
    assert resp.status == 200
    assert "Secure" in resp.cookies[0]


def test_me_returns_user_when_authed(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    login = dispatch(_post("/auth/login", {"email": "a@b.com", "password": "correct horse battery staple"}), svc)
    cookie = _cookie_from_response(login)
    resp = dispatch(_get("/auth/me", cookie=cookie), svc)
    assert resp.status == 200
    assert json.loads(resp.body)["user"]["email"] == "a@b.com"


def test_me_returns_401_without_cookie(svc: AuthService) -> None:
    resp = dispatch(_get("/auth/me"), svc)
    assert resp.status == 401


def test_me_returns_401_with_bad_cookie(svc: AuthService) -> None:
    resp = dispatch(_get("/auth/me", cookie=f"{SESSION_COOKIE}=garbage"), svc)
    assert resp.status == 401


def test_logout_clears_cookie_and_revokes_session(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    login = dispatch(_post("/auth/login", {"email": "a@b.com", "password": "correct horse battery staple"}), svc)
    cookie = _cookie_from_response(login)

    resp = dispatch(_post("/auth/logout", {}, cookie=cookie), svc)
    assert resp.status == 200
    assert any("Max-Age=0" in c for c in resp.cookies)

    me = dispatch(_get("/auth/me", cookie=cookie), svc)
    assert me.status == 401


def test_unknown_auth_path_returns_404(svc: AuthService) -> None:
    resp = dispatch(_post("/auth/does-not-exist", {}), svc)
    assert resp.status == 404


def test_wrong_method_on_known_route_returns_405(svc: AuthService) -> None:
    resp = dispatch(_get("/auth/login"), svc)
    assert resp.status == 405


def test_non_auth_path_returns_none(svc: AuthService) -> None:
    resp = dispatch(_get("/health"), svc)
    assert resp is None


def test_malformed_json_returns_400(svc: AuthService) -> None:
    req = Request(
        method="POST", path="/auth/login",
        headers={"content-type": "application/json"},
        body=b"{not-json", remote_ip="127.0.0.1",
    )
    resp = dispatch(req, svc)
    assert resp.status == 400


def test_login_generic_error_does_not_distinguish_unknown_vs_wrong(svc: AuthService) -> None:
    svc.create_user("a@b.com", "correct horse battery staple")
    bad_pwd = dispatch(_post("/auth/login", {"email": "a@b.com", "password": "wrong password long enough"}), svc)
    unknown = dispatch(_post("/auth/login", {"email": "nobody@b.com", "password": "any password long enough"}), svc)
    assert bad_pwd.status == unknown.status == 401
    assert json.loads(bad_pwd.body) == json.loads(unknown.body)
