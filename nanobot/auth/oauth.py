"""Claude OAuth token refresh manager following OpenClaw pattern."""

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
import aiohttp
from aiofiles import os as aio_os
from filelock import FileLock
from loguru import logger
from pydantic import ValidationError

from .types import AuthProfile, AuthStore, OAuthCredentials, RefreshResult


class ClaudeOAuthManager:
    """
    Claude OAuth token manager with automatic refresh.

    Follows OpenClaw patterns:
    - File-based storage with locking
    - 5-minute safety margin
    - Lazy refresh (on-demand)
    - Fallback to main profile
    """

    # 5 minute safety margin (in milliseconds)
    SAFETY_MARGIN_MS = 5 * 60 * 1000

    # OAuth endpoints
    TOKEN_ENDPOINT = "https://console.anthropic.com/v1/oauth/token"
    CLIENT_ID = "client_id_from_anthropic"  # Need to get this from Anthropic

    def __init__(self, auth_dir: str | None = None):
        """
        Initialize OAuth manager.

        Args:
            auth_dir: Directory for auth storage. Defaults to ~/.nanobot/auth
        """
        self.auth_dir = Path(auth_dir or Path.home() / ".nanobot" / "auth")
        self.auth_file = self.auth_dir / "oauth.json"
        self.lock_file = self.auth_dir / "oauth.lock"

        # Ensure auth directory exists with secure permissions
        self.auth_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    async def get_api_key_for_profile(
        self,
        profile_id: str,
        fallback_to_main: bool = True,
    ) -> str | None:
        """
        Get API key for profile, refreshing if necessary.

        Args:
            profile_id: Profile identifier (e.g., "anthropic:default")
            fallback_to_main: Whether to fallback to main profile if this fails

        Returns:
            API key string or None if unavailable
        """
        try:
            # Try to get fresh credentials
            result = await self._refresh_if_needed(profile_id)
            if result:
                return result.api_key

            # Fallback to main profile if enabled
            if fallback_to_main and profile_id != "anthropic:main":
                logger.info(f"Falling back to main profile for {profile_id}")
                return await self.get_api_key_for_profile("anthropic:main", fallback_to_main=False)

            return None

        except Exception as e:
            logger.error(f"Failed to get API key for {profile_id}: {e}")
            return None

    async def _refresh_if_needed(self, profile_id: str) -> RefreshResult | None:
        """
        Refresh token if needed with file locking.

        Args:
            profile_id: Profile to refresh

        Returns:
            RefreshResult or None if failed
        """
        # Acquire file lock to prevent race conditions
        lock = FileLock(str(self.lock_file), timeout=30)

        try:
            with lock:
                # Load current auth store
                store = await self._load_auth_store()
                profile = store.profiles.get(profile_id)

                if not profile:
                    logger.warning(f"Profile not found: {profile_id}")
                    return None

                creds = profile.credentials
                if not isinstance(creds, OAuthCredentials):
                    logger.warning(f"Profile {profile_id} is not OAuth")
                    return None

                # Check if still valid (with safety margin)
                now_ms = int(time.time() * 1000)
                if now_ms < (creds.expires - self.SAFETY_MARGIN_MS):
                    # Still valid, return existing token
                    return RefreshResult(
                        api_key=creds.access,
                        new_credentials=creds,
                        expires_at=datetime.fromtimestamp(creds.expires / 1000),
                    )

                # Need to refresh
                logger.info(f"Refreshing OAuth token for {profile_id}")
                new_creds = await self._perform_refresh(creds)

                if not new_creds:
                    logger.error(f"Failed to refresh token for {profile_id}")
                    return None

                # Update store with new credentials
                profile.credentials = new_creds
                profile.last_used = now_ms
                profile.error_count = 0
                store.profiles[profile_id] = profile

                await self._save_auth_store(store)

                logger.info(f"Successfully refreshed token for {profile_id}")
                return RefreshResult(
                    api_key=new_creds.access,
                    new_credentials=new_creds,
                    expires_at=datetime.fromtimestamp(new_creds.expires / 1000),
                )

        except Exception as e:
            logger.error(f"Error refreshing token for {profile_id}: {e}")
            return None

    async def _perform_refresh(self, creds: OAuthCredentials) -> OAuthCredentials | None:
        """
        Perform the actual OAuth refresh request.

        Args:
            creds: Current OAuth credentials

        Returns:
            New OAuth credentials or None if failed
        """
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.CLIENT_ID,
            "refresh_token": creds.refresh,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.TOKEN_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"OAuth refresh failed: {response.status} - {error_text}")
                        return None

                    data = await response.json()

                    # Extract tokens with safety margin
                    access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)  # Default 1 hour
                    new_refresh_token = data.get("refresh_token", creds.refresh)

                    if not access_token:
                        logger.error("No access token in refresh response")
                        return None

                    # Calculate expiration with safety margin
                    now_ms = int(time.time() * 1000)
                    expires_ms = now_ms + (expires_in * 1000) - self.SAFETY_MARGIN_MS

                    return OAuthCredentials(
                        type="oauth",
                        provider=creds.provider,
                        access=access_token,
                        refresh=new_refresh_token,
                        expires=expires_ms,
                        client_id=creds.client_id,
                        email=creds.email,
                    )

        except Exception as e:
            logger.error(f"OAuth refresh request failed: {e}")
            return None

    async def _load_auth_store(self) -> AuthStore:
        """Load authentication store from file."""
        if not self.auth_file.exists():
            return AuthStore()

        try:
            async with aiofiles.open(self.auth_file, "r") as f:
                content = await f.read()
                data = json.loads(content)
                return AuthStore.model_validate(data)
        except (json.JSONDecodeError, ValidationError, FileNotFoundError) as e:
            logger.warning(f"Failed to load auth store: {e}")
            return AuthStore()

    async def _save_auth_store(self, store: AuthStore) -> None:
        """Save authentication store to file with secure permissions."""
        try:
            # Write to temp file first, then atomic move
            temp_file = self.auth_file.with_suffix(".tmp")

            async with aiofiles.open(temp_file, "w") as f:
                content = store.model_dump_json(indent=2)
                await f.write(content)

            # Set secure permissions before moving
            await aio_os.chmod(temp_file, 0o600)

            # Atomic move
            await aio_os.rename(temp_file, self.auth_file)

        except Exception as e:
            logger.error(f"Failed to save auth store: {e}")
            # Clean up temp file if it exists
            if temp_file.exists():
                await aio_os.unlink(temp_file)

    async def add_oauth_credentials(
        self,
        profile_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        email: str | None = None,
        provider: str = "anthropic",
    ) -> None:
        """
        Add new OAuth credentials to store.

        Args:
            profile_id: Profile identifier
            access_token: Current access token
            refresh_token: Refresh token
            expires_in: Expiration time in seconds
            email: Optional user email
            provider: Provider name
        """
        now_ms = int(time.time() * 1000)
        expires_ms = now_ms + (expires_in * 1000) - self.SAFETY_MARGIN_MS

        creds = OAuthCredentials(
            type="oauth",
            provider=provider,
            access=access_token,
            refresh=refresh_token,
            expires=expires_ms,
            client_id=self.CLIENT_ID,
            email=email,
        )

        lock = FileLock(str(self.lock_file), timeout=30)

        try:
            with lock:
                store = await self._load_auth_store()

                profile = AuthProfile(
                    credentials=creds,
                    last_used=now_ms,
                    cooldown_until=0,
                    error_count=0,
                )

                store.profiles[profile_id] = profile
                await self._save_auth_store(store)

                logger.info(f"Added OAuth credentials for {profile_id}")

        except Exception as e:
            logger.error(f"Failed to add OAuth credentials: {e}")

    async def list_profiles(self) -> dict[str, dict[str, Any]]:
        """List all authentication profiles with status."""
        store = await self._load_auth_store()
        result = {}

        now_ms = int(time.time() * 1000)

        for profile_id, profile in store.profiles.items():
            creds = profile.credentials

            if isinstance(creds, OAuthCredentials):
                is_valid = now_ms < (creds.expires - self.SAFETY_MARGIN_MS)
                expires_at = datetime.fromtimestamp(creds.expires / 1000)

                result[profile_id] = {
                    "type": "oauth",
                    "provider": creds.provider,
                    "email": creds.email,
                    "valid": is_valid,
                    "expires_at": expires_at.isoformat(),
                    "last_used": profile.last_used,
                    "error_count": profile.error_count,
                }
            else:
                result[profile_id] = {
                    "type": creds.type,
                    "provider": creds.provider,
                    "email": creds.email,
                }

        return result

    async def remove_profile(self, profile_id: str) -> bool:
        """Remove authentication profile."""
        lock = FileLock(str(self.lock_file), timeout=30)

        try:
            with lock:
                store = await self._load_auth_store()

                if profile_id in store.profiles:
                    del store.profiles[profile_id]
                    await self._save_auth_store(store)
                    logger.info(f"Removed profile {profile_id}")
                    return True
                else:
                    logger.warning(f"Profile {profile_id} not found")
                    return False

        except Exception as e:
            logger.error(f"Failed to remove profile: {e}")
            return False