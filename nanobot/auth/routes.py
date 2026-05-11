"""HTTP auth routes for the gateway health-port server.

The gateway speaks raw HTTP/1.0 on its health port (see ``commands.py``).
This module exposes pure ``Request -> Response`` handlers so the wire-level
glue stays trivial and the logic is unit-testable without spinning a
real socket.

Routes (v1):
  POST /auth/login   {email, password}   -> sets ``nanobot_session`` cookie
  POST /auth/logout                       -> clears cookie, revokes session
  GET  /auth/me                           -> returns current user from cookie

A subsequent slice adds ``POST /auth/signup``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from nanobot.auth.ratelimit import RateLimiter
from nanobot.auth.service import AuthError, AuthService, EmailTakenError, UserRecord

SESSION_COOKIE = "nanobot_session"
SESSION_COOKIE_MAX_AGE_S = 30 * 24 * 60 * 60  # 30 days

# Per-endpoint policy: (max_attempts, window_seconds). Tuned for v1 single-instance.
RATE_LIMIT_POLICY: dict[str, tuple[int, float]] = {
    "/auth/login": (5, 60.0),
    "/auth/signup": (3, 60.0),
}


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    remote_ip: str | None = None


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[str] = field(default_factory=list)  # raw Set-Cookie values


def _parse_cookies(header: str | None) -> dict[str, str]:
    """Parse a ``Cookie:`` header value into a flat mapping."""
    if not header:
        return {}
    out: dict[str, str] = {}
    for chunk in header.split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _json_response(status: int, payload: dict[str, Any]) -> Response:
    body = json.dumps(payload).encode("utf-8")
    return Response(
        status=status,
        body=body,
        headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
    )


def _error(status: int, message: str) -> Response:
    return _json_response(status, {"error": message})


def _user_payload(user: UserRecord) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }


def _build_session_cookie(token: str, *, secure: bool) -> str:
    parts = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={SESSION_COOKIE_MAX_AGE_S}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _clear_session_cookie() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def _detect_secure(req: Request) -> bool:
    # Behind a TLS terminator, the proxy sets X-Forwarded-Proto.
    proto = req.headers.get("x-forwarded-proto", "").lower()
    return proto == "https"


def _parse_json_body(req: Request) -> dict[str, Any]:
    if not req.body:
        return {}
    try:
        loaded = json.loads(req.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthError("invalid request body") from exc
    if not isinstance(loaded, dict):
        raise AuthError("invalid request body")
    return loaded


def handle_signup(req: Request, svc: AuthService) -> Response:
    if req.method != "POST":
        return _error(405, "method not allowed")
    try:
        data = _parse_json_body(req)
    except AuthError as exc:
        return _error(400, str(exc))
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    display_name = data.get("display_name")
    if isinstance(display_name, str):
        display_name = display_name.strip() or None
    else:
        display_name = None
    if not email or not password:
        return _error(400, "email and password required")
    try:
        user = svc.create_user(
            email,
            password,
            display_name=display_name,
            ip=req.remote_ip,
        )
    except EmailTakenError:
        return _error(409, "email already registered")
    except AuthError as exc:
        return _error(400, str(exc))
    session = svc.mint_session(
        user.id,
        user_agent=req.headers.get("user-agent"),
        ip=req.remote_ip,
    )
    resp = _json_response(200, {"user": _user_payload(user)})
    resp.cookies.append(_build_session_cookie(session.token, secure=_detect_secure(req)))
    return resp


def handle_login(req: Request, svc: AuthService) -> Response:
    if req.method != "POST":
        return _error(405, "method not allowed")
    try:
        data = _parse_json_body(req)
    except AuthError as exc:
        return _error(400, str(exc))
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return _error(400, "email and password required")
    try:
        user = svc.verify_password(email, password, ip=req.remote_ip)
    except AuthError:
        return _error(401, "invalid credentials")
    session = svc.mint_session(
        user.id,
        user_agent=req.headers.get("user-agent"),
        ip=req.remote_ip,
    )
    resp = _json_response(200, {"user": _user_payload(user)})
    resp.cookies.append(_build_session_cookie(session.token, secure=_detect_secure(req)))
    return resp


def handle_logout(req: Request, svc: AuthService) -> Response:
    if req.method != "POST":
        return _error(405, "method not allowed")
    cookies = _parse_cookies(req.headers.get("cookie"))
    token = cookies.get(SESSION_COOKIE, "")
    svc.revoke_session(token)
    resp = _json_response(200, {"ok": True})
    resp.cookies.append(_clear_session_cookie())
    return resp


def handle_me(req: Request, svc: AuthService) -> Response:
    if req.method != "GET":
        return _error(405, "method not allowed")
    cookies = _parse_cookies(req.headers.get("cookie"))
    token = cookies.get(SESSION_COOKIE, "")
    try:
        user = svc.verify_session(token)
    except AuthError:
        return _error(401, "unauthenticated")
    return _json_response(200, {"user": _user_payload(user)})


_DISPATCH = {
    ("POST", "/auth/signup"): handle_signup,
    ("POST", "/auth/login"): handle_login,
    ("POST", "/auth/logout"): handle_logout,
    ("GET", "/auth/me"): handle_me,
}


def dispatch(
    req: Request,
    svc: AuthService,
    *,
    limiter: RateLimiter | None = None,
) -> Response | None:
    """Return a response for known /auth/* routes, else None.

    When ``limiter`` is provided, requests to rate-limited endpoints are
    counted per (path, remote_ip) and 429 is returned when the policy
    threshold trips.
    """
    if not req.path.startswith("/auth/"):
        return None
    handler = _DISPATCH.get((req.method, req.path))
    if handler is None:
        for method, path in _DISPATCH:
            if path == req.path:
                return _error(405, "method not allowed")
        return _error(404, "not found")
    if limiter is not None and req.path in RATE_LIMIT_POLICY:
        max_attempts, window_s = RATE_LIMIT_POLICY[req.path]
        ip = req.remote_ip or "-"
        ok, retry_after = limiter.try_consume(
            (req.path, ip), max_attempts=max_attempts, window_s=window_s
        )
        if not ok:
            try:
                svc._audit(  # noqa: SLF001 — intentional cross-module audit
                    "ratelimit.trip",
                    target_user_id=None,
                    ip=ip,
                    detail=req.path,
                )
            except Exception:
                pass
            resp = _error(429, "too many requests")
            resp.headers["Retry-After"] = str(retry_after)
            return resp
    return handler(req, svc)
