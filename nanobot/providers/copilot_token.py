"""GitHub Copilot token management with OAuth device flow and caching."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


# Constants
CLIENT_ID = "Iv1.b507a08c87ecfe98"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_COPILOT_API_BASE_URL = "https://api.individual.githubcopilot.com"
CACHE_DIR = Path.home() / ".nanobot" / "credentials"
CACHE_FILE = CACHE_DIR / "copilot-token.json"


@dataclass
class CopilotTokenCache:
    """Cached Copilot token data."""
    token: str
    expires_at: int
    updated_at: int

    def is_usable(self, buffer_seconds: int = 300) -> bool:
        """Check if token is still valid (with buffer before expiry)."""
        return self.expires_at - time.time() > buffer_seconds


class CopilotTokenManager:
    """
    Manages GitHub OAuth flow and Copilot token lifecycle.

    Usage:
        # First-time setup (interactive)
        manager = CopilotTokenManager()
        github_token = await manager.authenticate()
        # Save github_token for future use

        # Using cached GitHub token
        manager = CopilotTokenManager(github_token="ghu_...")
        copilot_token, api_base = await manager.get_copilot_token()
    """

    def __init__(
        self,
        github_token: str | None = None,
        cache_path: Path | None = None,
        user_agent: str = "GitHubCopilotChat/0.26.7",
        editor_version: str = "vscode/1.96.2",
    ):
        """
        Initialize token manager.

        Args:
            github_token: Long-lived GitHub OAuth token (ghu_...). If provided,
                         skips device auth and uses this token directly.
            cache_path: Path to store Copilot token cache. Defaults to ~/.nanobot/credentials/copilot-token.json
            user_agent: User-Agent header for API requests
            editor_version: Editor-Version header for API requests
        """
        self.github_token = github_token
        self.cache_path = cache_path or CACHE_FILE
        self.user_agent = user_agent
        self.editor_version = editor_version
        self._cache: CopilotTokenCache | None = None

    def _load_cache(self) -> CopilotTokenCache | None:
        """Load cached token from disk. Supports both camelCase and snake_case formats."""
        if self._cache is not None:
            return self._cache

        try:
            if self.cache_path.exists():
                data = json.loads(self.cache_path.read_text())
                # Support both openclaw format (expiresAt) and our format (expires_at)
                expires_at = data.get("expires_at") or data.get("expiresAt")
                updated_at = data.get("updated_at") or data.get("updatedAt") or expires_at
                token = data["token"]
                self._cache = CopilotTokenCache(
                    token=token,
                    expires_at=int(expires_at),
                    updated_at=int(updated_at),
                )
                return self._cache
        except (json.JSONDecodeError, KeyError, IOError, ValueError, TypeError):
            pass

        return None

    def _save_cache(self, token: str, expires_at: int) -> None:
        """Save token to cache."""
        self._cache = CopilotTokenCache(
            token=token,
            expires_at=expires_at,
            updated_at=int(time.time()),
        )
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({
            "token": token,
            "expires_at": expires_at,
            "updated_at": self._cache.updated_at,
        }, indent=2))

    @staticmethod
    def derive_api_base_url(token: str) -> str:
        """
        Extract API base URL from Copilot token.

        Copilot tokens contain a 'proxy-ep' field that specifies the endpoint.
        """
        match = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token, re.IGNORECASE)
        if not match:
            return DEFAULT_COPILOT_API_BASE_URL

        proxy_ep = match.group(1)
        # Convert proxy.xxx to api.xxx
        host = proxy_ep
        if host.startswith("https://"):
            host = host[8:]
        elif host.startswith("http://"):
            host = host[7:]

        host = re.sub(r"^proxy\.", "api.", host, flags=re.IGNORECASE)
        return f"https://{host}"

    async def _request_device_code(self, client: httpx.AsyncClient) -> dict[str, Any]:
        """Request device code for GitHub OAuth."""
        response = await client.post(
            DEVICE_CODE_URL,
            data={
                "client_id": CLIENT_ID,
                "scope": "read:user repo read:org",
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()

    async def _poll_for_token(
        self,
        client: httpx.AsyncClient,
        device_code: str,
        interval: int,
        expires_at: float,
    ) -> str:
        """Poll GitHub OAuth endpoint until user authorization completes."""
        while time.time() < expires_at:
            response = await client.post(
                ACCESS_TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )

            data = response.json()

            if "access_token" in data:
                return data["access_token"]

            error = data.get("error")
            if error == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            elif error == "expired_token":
                raise RuntimeError("Device code expired. Please restart authentication.")
            elif error:
                raise RuntimeError(f"OAuth error: {error}")

        raise RuntimeError("Authentication timed out. Please try again.")

    async def authenticate(self) -> str:
        """
        Perform GitHub OAuth device flow to get a GitHub token.

        Returns:
            GitHub OAuth token (ghu_...) that should be saved for future use.

        Raises:
            RuntimeError: If authentication fails
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Request device code
            device_data = await self._request_device_code(client)

            print(f"\n{'='*60}")
            print("GitHub Copilot Authentication Required")
            print(f"{'='*60}")
            print(f"\n1. Visit: {device_data['verification_uri']}")
            print(f"2. Enter code: {device_data['user_code']}")
            print(f"\nWaiting for authorization... (Press Ctrl+C to cancel)")
            print(f"{'='*60}\n")

            # Step 2: Poll for access token
            interval = device_data["interval"]
            expires_in = device_data["expires_in"]
            expires_at = time.time() + expires_in

            github_token = await self._poll_for_token(
                client,
                device_data["device_code"],
                interval,
                expires_at,
            )

            print("\n✓ Authentication successful!")
            print(f"  GitHub Token: {github_token[:20]}...")
            print(f"  Save this token for future use.\n")

            self.github_token = github_token
            return github_token

    async def get_copilot_token(self) -> tuple[str, str]:
        """
        Get valid Copilot API token and base URL.

        This method:
        1. Checks cache for valid token (works without GitHub token)
        2. If cache is invalid/missing, exchanges GitHub token for Copilot token
        3. Returns token and derived API base URL

        Returns:
            Tuple of (copilot_token, api_base_url)

        Raises:
            RuntimeError: If cache is invalid AND GitHub token is not set, or exchange fails
        """
        # Check cache first (works without GitHub token)
        cache = self._load_cache()
        if cache and cache.is_usable():
            api_base = self.derive_api_base_url(cache.token)
            return cache.token, api_base

        # Cache invalid/missing - need GitHub token to refresh
        if not self.github_token:
            raise RuntimeError(
                "Copilot token cache is invalid or expired. "
                "GitHub token is required to refresh. "
                "Provide github_token constructor arg or call authenticate() first."
            )

        # Fetch new token
        # Important: Use proper User-Agent to avoid "approved clients" error
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                COPILOT_TOKEN_URL,
                headers={
                    "Authorization": f"token {self.github_token}",  # GitHub uses 'token' prefix
                    "Accept": "application/json",
                    "User-Agent": "GitHubCopilot/1.0.0",  # Required to avoid "approved clients" error
                },
            )

            if response.status_code == 401:
                raise RuntimeError(
                    "GitHub token is invalid or expired. "
                    "Please re-authenticate with authenticate()."
                )
            if response.status_code == 403:
                raise RuntimeError(
                    "GitHub token does not have Copilot access. "
                    "Make sure your GitHub account has an active Copilot subscription."
                )
            response.raise_for_status()

            data = response.json()
            token = data["token"]

            # Handle expires_at - GitHub may return seconds or milliseconds
            expires_at = data["expires_at"]
            if expires_at < 10000000000:  # Seconds
                expires_at = expires_at * 1000

            # Cache the token
            self._save_cache(token, expires_at)

            api_base = self.derive_api_base_url(token)
            return token, api_base

    async def invalidate_cache(self) -> None:
        """Invalidate cached token, forcing refresh on next request."""
        self._cache = None
        if self.cache_path.exists():
            self.cache_path.unlink()

    def get_cached_token(self) -> tuple[str, str] | None:
        """
        Get cached token if still valid (synchronous).

        Returns:
            Tuple of (token, api_base_url) if cached and valid, None otherwise.
        """
        cache = self._load_cache()
        if cache and cache.is_usable():
            api_base = self.derive_api_base_url(cache.token)
            return cache.token, api_base
        return None


async def main() -> None:
    """CLI for GitHub OAuth authentication."""
    import argparse

    parser = argparse.ArgumentParser(description="GitHub Copilot Authentication")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test existing cached token",
    )
    args = parser.parse_args()

    manager = CopilotTokenManager()

    if args.test:
        cached = manager.get_cached_token()
        if cached:
            token, api_base = cached
            print("✓ Cached token is valid")
            print(f"  API Base: {api_base}")
            print(f"  Token: {token[:50]}...")
        else:
            print("✗ No valid cached token found")
            print("  Run without --test to authenticate")
    else:
        github_token = await manager.authenticate()
        # Test the token exchange
        copilot_token, api_base = await manager.get_copilot_token()
        print(f"✓ Copilot token obtained")
        print(f"  API Base: {api_base}")
        print(f"  Token: {copilot_token[:50]}...")


if __name__ == "__main__":
    asyncio.run(main())
