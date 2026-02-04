"""Authentication types for nanobot."""

from datetime import datetime
from typing import Any, Literal, Union
from pydantic import BaseModel


class BaseCredentials(BaseModel):
    """Base credentials class."""
    type: str
    provider: str
    email: str | None = None


class ApiKeyCredentials(BaseCredentials):
    """API key credentials."""
    type: Literal["api_key"] = "api_key"
    key: str


class TokenCredentials(BaseCredentials):
    """Token credentials with optional expiration."""
    type: Literal["token"] = "token"
    token: str
    expires: int | None = None  # Timestamp in milliseconds


class OAuthCredentials(BaseCredentials):
    """OAuth credentials with refresh support."""
    type: Literal["oauth"] = "oauth"
    access: str
    refresh: str
    expires: int  # Timestamp in milliseconds
    client_id: str | None = None


# Union type for all credential types
Credentials = Union[ApiKeyCredentials, TokenCredentials, OAuthCredentials]


class AuthProfile(BaseModel):
    """Authentication profile containing credentials and usage stats."""
    credentials: Credentials
    last_used: int | None = None
    cooldown_until: int = 0
    error_count: int = 0


class AuthStore(BaseModel):
    """Authentication store containing all profiles."""
    version: int = 1
    profiles: dict[str, AuthProfile] = {}


class RefreshResult(BaseModel):
    """Result of token refresh operation."""
    api_key: str
    new_credentials: OAuthCredentials
    expires_at: datetime