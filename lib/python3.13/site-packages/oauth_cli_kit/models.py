"""OAuth data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OAuthProviderConfig:
    """Configuration for an OAuth 2.0 provider."""

    client_id: str
    authorize_url: str
    token_url: str
    redirect_uri: str
    scope: str
    jwt_claim_path: str | None = None
    account_id_claim: str | None = None
    default_originator: str = "oauth-cli-kit"
    token_filename: str = "oauth.json"


@dataclass
class OAuthToken:
    """OAuth token data structure."""

    access: str
    refresh: str
    expires: int
    account_id: str | None = None


# Backward-compatible alias for earlier Codex naming.
CodexToken = OAuthToken
