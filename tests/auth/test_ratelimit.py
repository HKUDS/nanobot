"""Slice B2 — rate limit on /auth/login + /auth/signup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.auth.ratelimit import RateLimiter
from nanobot.auth.routes import Request, dispatch
from nanobot.auth.service import AuthService


@pytest.fixture()
def svc(tmp_path: Path) -> AuthService:
    yield AuthService.default(tmp_path)


def _login(ip: str = "1.2.3.4") -> Request:
    return Request(
        method="POST",
        path="/auth/login",
        headers={"content-type": "application/json"},
        body=json.dumps({"email": "a@b.com", "password": "wrong password long enough"}).encode(),
        remote_ip=ip,
    )


def _signup(seq: int, ip: str = "1.2.3.4") -> Request:
    return Request(
        method="POST",
        path="/auth/signup",
        headers={"content-type": "application/json"},
        body=json.dumps(
            {"email": f"u{seq}@example.com", "password": "correct horse battery staple"}
        ).encode(),
        remote_ip=ip,
    )


def test_login_rate_limit_kicks_in_after_5_attempts(svc: AuthService) -> None:
    clock = [1000.0]
    limiter = RateLimiter(now=lambda: clock[0])
    statuses = [dispatch(_login(), svc, limiter=limiter).status for _ in range(6)]
    assert statuses == [401, 401, 401, 401, 401, 429]


def test_signup_rate_limit_kicks_in_after_3_attempts(svc: AuthService) -> None:
    clock = [2000.0]
    limiter = RateLimiter(now=lambda: clock[0])
    # First three should be allowed (and create users); 4th 429.
    r1 = dispatch(_signup(1), svc, limiter=limiter)
    r2 = dispatch(_signup(2), svc, limiter=limiter)
    r3 = dispatch(_signup(3), svc, limiter=limiter)
    r4 = dispatch(_signup(4), svc, limiter=limiter)
    assert r1.status == 200
    assert r2.status == 200
    assert r3.status == 200
    assert r4.status == 429


def test_rate_limit_response_has_retry_after_header(svc: AuthService) -> None:
    clock = [3000.0]
    limiter = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        dispatch(_login(), svc, limiter=limiter)
    blocked = dispatch(_login(), svc, limiter=limiter)
    assert blocked.status == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1


def test_rate_limit_clears_after_window_expires(svc: AuthService) -> None:
    clock = [4000.0]
    limiter = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        dispatch(_login(), svc, limiter=limiter)
    assert dispatch(_login(), svc, limiter=limiter).status == 429
    # Advance past the 60s window.
    clock[0] += 61.0
    assert dispatch(_login(), svc, limiter=limiter).status == 401


def test_rate_limit_per_ip(svc: AuthService) -> None:
    clock = [5000.0]
    limiter = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        dispatch(_login(ip="1.1.1.1"), svc, limiter=limiter)
    # IP 1 is over the limit.
    assert dispatch(_login(ip="1.1.1.1"), svc, limiter=limiter).status == 429
    # IP 2 is fresh.
    assert dispatch(_login(ip="2.2.2.2"), svc, limiter=limiter).status == 401


def test_no_limiter_means_no_throttling(svc: AuthService) -> None:
    """If no limiter is passed (e.g. tests, CLI), behaviour is unrestricted."""
    for _ in range(20):
        resp = dispatch(_login(), svc)
        assert resp.status == 401


def test_ratelimit_audit_row_written(svc: AuthService, tmp_path: Path) -> None:
    import sqlite3

    from nanobot.auth.schema import get_auth_db_path

    clock = [6000.0]
    limiter = RateLimiter(now=lambda: clock[0])
    for _ in range(6):
        dispatch(_login(), svc, limiter=limiter)
    events = [
        r[0]
        for r in sqlite3.connect(get_auth_db_path(tmp_path)).execute(
            "SELECT event FROM audit_log"
        )
    ]
    assert "ratelimit.trip" in events
