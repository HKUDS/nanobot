"""AuthService: user creation, password verification, session lifecycle, audit log.

Single class owns all auth-DB interactions. Callers obtain an instance via the
default factory ``AuthService.default()`` which opens a connection against
``~/.nanobot/auth.db``. Tests pass an explicit ``data_dir``.

Security choices:
  - Passwords hashed with argon2id (time_cost=3, memory_cost=64MB, parallelism=2).
  - Session tokens: 32 random URL-safe bytes; only sha256(token) is persisted.
  - Sliding TTL: ``verify_session`` extends ``expires_at`` on each hit.
  - Every state-changing call writes an ``audit_log`` row (success or failure).
  - Login errors are intentionally generic — no distinction between
    "unknown email" and "wrong password" reaches the caller.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from nanobot.auth.ids import assert_ulid, new_ulid
from nanobot.auth.schema import init_auth_db, open_auth_db

DEFAULT_SESSION_TTL_S = 30 * 24 * 60 * 60  # 30 days
MIN_PASSWORD_LEN = 12

_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


class AuthError(Exception):
    """Generic auth failure; safe to surface to clients."""


class EmailTakenError(AuthError):
    """Raised when create_user is called with a duplicate email."""


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    display_name: str | None
    role: str
    created_at: int
    last_login_at: int | None
    disabled: bool


@dataclass(frozen=True)
class SessionRecord:
    token: str  # raw token — only returned at mint time
    user_id: str
    expires_at: int


def _now() -> int:
    return int(time.time())


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_to_user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        disabled=bool(row["disabled"]),
    )


class AuthService:
    """Synchronous auth operations against the SQLite auth DB."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @classmethod
    def default(cls, data_dir: Path | None = None) -> "AuthService":
        init_auth_db(data_dir)
        return cls(open_auth_db(data_dir))

    def close(self) -> None:
        self._conn.close()

    # ----- user lifecycle ----------------------------------------------------

    def create_user(
        self,
        email: str,
        password: str,
        *,
        display_name: str | None = None,
        role: str = "user",
        ip: str | None = None,
    ) -> UserRecord:
        email_norm = email.strip().lower()
        if not email_norm or "@" not in email_norm:
            raise AuthError("invalid email")
        if len(password) < MIN_PASSWORD_LEN:
            raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        if role not in ("user", "admin"):
            raise AuthError(f"invalid role: {role}")

        user_id = new_ulid()
        pwd_hash = _HASHER.hash(password)
        now = _now()
        try:
            self._conn.execute(
                "INSERT INTO users (id, email, password_hash, display_name, role, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, email_norm, pwd_hash, display_name, role, now),
            )
        except sqlite3.IntegrityError as exc:
            self._audit("signup.fail", target_user_id=None, ip=ip, detail=email_norm)
            raise EmailTakenError("email already registered") from exc
        self._audit("signup", target_user_id=user_id, ip=ip, detail=email_norm)
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> UserRecord:
        assert_ulid(user_id)
        row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise AuthError("user not found")
        return _row_to_user(row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return _row_to_user(row) if row else None

    # ----- password verification --------------------------------------------

    def verify_password(self, email: str, password: str, *, ip: str | None = None) -> UserRecord:
        """Return user on success; raise AuthError on any failure.

        Generic error to avoid leaking whether email is registered.
        """
        user = self.get_user_by_email(email)
        if user is None:
            # Run hash to keep timing roughly constant against enumeration.
            try:
                _HASHER.verify("$argon2id$v=19$m=65536,t=3,p=2$xxxxxxxxxxxxxxxx$" + "x" * 43, password)
            except Exception:
                pass
            self._audit("login.fail", target_user_id=None, ip=ip, detail=email.strip().lower())
            raise AuthError("invalid credentials")
        if user.disabled:
            self._audit("login.fail", target_user_id=user.id, ip=ip, detail="disabled")
            raise AuthError("invalid credentials")
        row = self._conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user.id,)
        ).fetchone()
        try:
            _HASHER.verify(row["password_hash"], password)
        except VerifyMismatchError:
            self._audit("login.fail", target_user_id=user.id, ip=ip, detail="bad_password")
            raise AuthError("invalid credentials") from None
        if _HASHER.check_needs_rehash(row["password_hash"]):
            self._conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (_HASHER.hash(password), user.id),
            )
        self._conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), user.id))
        self._audit("login.ok", target_user_id=user.id, ip=ip)
        return user

    def set_password(self, user_id: str, new_password: str, *, ip: str | None = None) -> None:
        assert_ulid(user_id)
        if len(new_password) < MIN_PASSWORD_LEN:
            raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        pwd_hash = _HASHER.hash(new_password)
        self._conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, user_id))
        # Reset all sessions for this user — force re-login.
        self._conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))
        self._audit("reset", target_user_id=user_id, ip=ip)

    # ----- sessions ----------------------------------------------------------

    def mint_session(
        self,
        user_id: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
        ttl_seconds: int = DEFAULT_SESSION_TTL_S,
    ) -> SessionRecord:
        assert_ulid(user_id)
        token = secrets.token_urlsafe(32)
        now = _now()
        expires = now + ttl_seconds
        self._conn.execute(
            "INSERT INTO web_sessions "
            "(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_hash_token(token), user_id, now, expires, now, user_agent, ip),
        )
        return SessionRecord(token=token, user_id=user_id, expires_at=expires)

    def verify_session(
        self,
        token: str,
        *,
        sliding: bool = True,
        ttl_seconds: int = DEFAULT_SESSION_TTL_S,
    ) -> UserRecord:
        """Return the owning user if token is valid and unexpired; else raise."""
        if not token:
            raise AuthError("missing session token")
        token_hash = _hash_token(token)
        row = self._conn.execute(
            "SELECT s.user_id, s.expires_at FROM web_sessions s WHERE s.token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            raise AuthError("invalid session")
        now = _now()
        if row["expires_at"] <= now:
            self._conn.execute("DELETE FROM web_sessions WHERE token_hash = ?", (token_hash,))
            self._audit("session.expire", target_user_id=row["user_id"])
            raise AuthError("invalid session")
        if sliding:
            self._conn.execute(
                "UPDATE web_sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                (now, now + ttl_seconds, token_hash),
            )
        return self.get_user(row["user_id"])

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        self._conn.execute("DELETE FROM web_sessions WHERE token_hash = ?", (_hash_token(token),))

    def revoke_all_sessions(self, user_id: str) -> int:
        assert_ulid(user_id)
        cur = self._conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount or 0

    def expire_sessions(self) -> int:
        cur = self._conn.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (_now(),))
        return cur.rowcount or 0

    # ----- audit -------------------------------------------------------------

    def _audit(
        self,
        event: str,
        *,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        ip: str | None = None,
        detail: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_log (ts, actor_user_id, event, target_user_id, ip, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), actor_user_id, event, target_user_id, ip, detail),
        )
