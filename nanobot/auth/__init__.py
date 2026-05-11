"""Authentication and per-user identity for nanobot multi-tenant mode."""

from nanobot.auth.context import UserContext
from nanobot.auth.ids import assert_ulid, is_ulid, new_ulid
from nanobot.auth.schema import AUTH_DB_FILENAME, init_auth_db, open_auth_db
from nanobot.auth.service import (
    AuthError,
    AuthService,
    EmailTakenError,
    SessionRecord,
    UserRecord,
)

__all__ = [
    "AUTH_DB_FILENAME",
    "AuthError",
    "AuthService",
    "EmailTakenError",
    "SessionRecord",
    "UserContext",
    "UserRecord",
    "assert_ulid",
    "init_auth_db",
    "is_ulid",
    "new_ulid",
    "open_auth_db",
]
