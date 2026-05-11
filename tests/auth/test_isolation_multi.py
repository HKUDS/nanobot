"""Slice B4 — full HTTP→AuthService→FS isolation across two users.

Drives the auth dispatcher directly (no socket) so the test is hermetic and
fast. Stops short of spawning a real gateway server; that round-trip is
already exercised by the manual smoke logged in A5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.auth.context import UserContext
from nanobot.auth.routes import SESSION_COOKIE, Request, dispatch
from nanobot.auth.service import AuthService
from nanobot.session.manager import SessionManager


@pytest.fixture()
def isolate_data_dir(monkeypatch, tmp_path: Path) -> Path:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return tmp_path


@pytest.fixture()
def svc(isolate_data_dir: Path) -> AuthService:
    yield AuthService.default(isolate_data_dir)


def _post(path: str, body: dict, *, cookie: str | None = None) -> Request:
    headers = {"content-type": "application/json"}
    if cookie:
        headers["cookie"] = cookie
    return Request(
        method="POST",
        path=path,
        headers=headers,
        body=json.dumps(body).encode("utf-8"),
        remote_ip="127.0.0.1",
    )


def _get(path: str, *, cookie: str | None = None) -> Request:
    headers = {}
    if cookie:
        headers["cookie"] = cookie
    return Request(
        method="GET", path=path, headers=headers, body=b"", remote_ip="127.0.0.1"
    )


def _cookie(resp) -> str:
    return resp.cookies[0].split(";", 1)[0]


def _user_id_from_response(resp) -> str:
    return json.loads(resp.body)["user"]["id"]


def _send_session_message(workspace: Path, user_id: str, key: str, body: str) -> Path:
    """Mimic what the agent loop does at the SessionManager boundary."""
    ctx = UserContext(user_id=user_id)
    sm = SessionManager(workspace, user_ctx=ctx)
    session = sm.get_or_create(key)
    session.add_message("user", body)
    sm.save(session)
    return sm._get_session_path(key)  # noqa: SLF001 — test introspection


def test_two_users_signup_login_no_state_overlap(
    svc: AuthService, isolate_data_dir: Path
) -> None:
    workspace = isolate_data_dir / "workspace"
    workspace.mkdir()

    # Alice signs up via /auth/signup.
    alice_resp = dispatch(
        _post("/auth/signup", {"email": "alice@example.com", "password": "correct horse battery staple"}),
        svc,
    )
    assert alice_resp.status == 200
    alice_cookie = _cookie(alice_resp)
    alice_id = _user_id_from_response(alice_resp)

    # Bob signs up.
    bob_resp = dispatch(
        _post("/auth/signup", {"email": "bob@example.com", "password": "correct horse battery staple"}),
        svc,
    )
    assert bob_resp.status == 200
    bob_cookie = _cookie(bob_resp)
    bob_id = _user_id_from_response(bob_resp)

    assert alice_id != bob_id

    # Both sessions resolve their own user via /auth/me.
    alice_me = dispatch(_get("/auth/me", cookie=alice_cookie), svc)
    bob_me = dispatch(_get("/auth/me", cookie=bob_cookie), svc)
    assert json.loads(alice_me.body)["user"]["email"] == "alice@example.com"
    assert json.loads(bob_me.body)["user"]["email"] == "bob@example.com"

    # Alice's cookie does NOT resolve to Bob's user.
    assert json.loads(alice_me.body)["user"]["id"] == alice_id
    assert json.loads(bob_me.body)["user"]["id"] == bob_id

    # On the agent side, the two users write to disjoint session dirs.
    alice_path = _send_session_message(
        workspace, alice_id, "websocket:web-1", "alice writes here"
    )
    bob_path = _send_session_message(
        workspace, bob_id, "websocket:web-1", "bob writes here"
    )

    assert alice_path != bob_path
    assert "alice" in alice_path.read_text()
    assert "bob" in bob_path.read_text()
    assert "alice" not in bob_path.read_text()
    assert "bob" not in alice_path.read_text()


def test_alice_cookie_cannot_impersonate_bob(svc: AuthService) -> None:
    alice = dispatch(
        _post("/auth/signup", {"email": "alice2@x.com", "password": "correct horse battery staple"}),
        svc,
    )
    dispatch(
        _post("/auth/signup", {"email": "bob2@x.com", "password": "correct horse battery staple"}),
        svc,
    )
    alice_id = _user_id_from_response(alice)
    me = dispatch(_get("/auth/me", cookie=_cookie(alice)), svc)
    assert json.loads(me.body)["user"]["id"] == alice_id


def test_signed_out_user_cannot_use_revoked_cookie(svc: AuthService) -> None:
    s = dispatch(
        _post("/auth/signup", {"email": "logout@x.com", "password": "correct horse battery staple"}),
        svc,
    )
    cookie = _cookie(s)
    dispatch(_post("/auth/logout", {}, cookie=cookie), svc)
    me = dispatch(_get("/auth/me", cookie=cookie), svc)
    assert me.status == 401


def test_concurrent_session_dirs_disjoint_on_disk(
    svc: AuthService, isolate_data_dir: Path
) -> None:
    """After two users sign up, their per-user directories under
    ``users/<uid>/sessions`` are physically separate trees."""
    workspace = isolate_data_dir / "workspace"
    workspace.mkdir()

    ids = []
    for email in ("u1@x.com", "u2@x.com"):
        r = dispatch(
            _post("/auth/signup", {"email": email, "password": "correct horse battery staple"}),
            svc,
        )
        ids.append(_user_id_from_response(r))
        # Materialize a session for each.
        _send_session_message(workspace, ids[-1], "websocket:k", f"hi from {email}")

    a_dir = isolate_data_dir / "users" / ids[0] / "sessions"
    b_dir = isolate_data_dir / "users" / ids[1] / "sessions"
    assert a_dir.is_dir() and b_dir.is_dir()
    assert a_dir != b_dir
    assert {p.name for p in a_dir.iterdir()} == {p.name for p in b_dir.iterdir()}
    # Same filename, disjoint trees: peeking inside proves no cross-leak.
    assert a_dir.iterdir().__next__().read_text() != b_dir.iterdir().__next__().read_text()


def test_cookie_strings_are_not_reused_between_users(svc: AuthService) -> None:
    """Two independent signups must produce distinct opaque tokens."""
    a = dispatch(_post("/auth/signup", {"email": "a@token.com", "password": "correct horse battery staple"}), svc)
    b = dispatch(_post("/auth/signup", {"email": "b@token.com", "password": "correct horse battery staple"}), svc)
    a_tok = _cookie(a).split("=", 1)[1]
    b_tok = _cookie(b).split("=", 1)[1]
    assert a_tok != b_tok
    assert len(a_tok) >= 32  # urlsafe-b64(32 bytes) → ≥43 chars
    assert SESSION_COOKIE in a.cookies[0]
