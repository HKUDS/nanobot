"""OAuth support for remote MCP servers.

This module intentionally owns MCP OAuth end to end. Provider OAuth has a
different lifecycle and storage contract, so sharing a higher-level workflow
would couple unrelated extension boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

import httpx
from filelock import AsyncFileLock, BaseAsyncFileLock, FileLock
from loguru import logger
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyHttpUrl, AnyUrl

from nanobot.config.paths import get_data_dir
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

MCP_OAUTH_CALLBACK_PATH = "/auth/mcp/callback"
_STORE_VERSION = 1
_STORE_LOCK_TIMEOUT_S = 15
_REFRESH_LOCK_TIMEOUT_S = 60
_DEFAULT_REDIRECT_URI = f"http://127.0.0.1{MCP_OAUTH_CALLBACK_PATH}"
_CLIENT_URI = AnyHttpUrl("https://github.com/HKUDS/nanobot")
_LOGO_URI = AnyHttpUrl(
    "https://raw.githubusercontent.com/HKUDS/nanobot/main/"
    "webui/public/brand/nanobot_apple_touch.png"
)


class _StoredServer(TypedDict, total=False):
    server_fingerprint: str
    write_lease: str
    tokens: dict[str, Any]
    expires_at: float
    token_issuer: str
    client_info: dict[str, Any]
    oauth_metadata: dict[str, Any]
    oauth_issuer: str
    redirect_uri: str


class _CredentialStore(TypedDict):
    version: int
    servers: dict[str, _StoredServer]
    generations: dict[str, str]


class MCPAuthorizationRequiredError(RuntimeError):
    """Raised when a background MCP connection needs interactive authorization."""


@dataclass(frozen=True)
class MCPOAuthHandlers:
    """Browser callbacks supplied only for a user-initiated OAuth attempt."""

    redirect_uri: str
    redirect_handler: Callable[[str], Awaitable[None]]
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]]
    reset_credentials: bool = False


@dataclass(frozen=True)
class _OAuthSnapshot:
    tokens: OAuthToken | None
    expires_at: float | None
    token_issuer: str | None
    client_info: OAuthClientInformationFull | None
    oauth_metadata: OAuthMetadata | None
    oauth_issuer: str | None


@dataclass(frozen=True)
class _RefreshLease:
    lock: BaseAsyncFileLock
    access_token: str
    refresh_token: str
    token_issuer: str


def _store_path() -> Path:
    return get_data_dir() / "auth" / "mcp.json"


def _server_fingerprint(server_url: str) -> str:
    return hashlib.sha256(server_url.strip().encode("utf-8")).hexdigest()


def _normalize_issuer(value: str) -> str:
    return value.rstrip("/")


def _empty_store() -> _CredentialStore:
    return {"version": _STORE_VERSION, "servers": {}, "generations": {}}


def _stored_server(value: object) -> _StoredServer | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    entry: _StoredServer = {}
    fingerprint = raw.get("server_fingerprint")
    if isinstance(fingerprint, str):
        entry["server_fingerprint"] = fingerprint
    write_lease = raw.get("write_lease")
    if isinstance(write_lease, str) and write_lease:
        entry["write_lease"] = write_lease
    redirect_uri = raw.get("redirect_uri")
    if isinstance(redirect_uri, str):
        entry["redirect_uri"] = redirect_uri
    tokens = raw.get("tokens")
    if isinstance(tokens, dict):
        token_values = cast(dict[object, object], tokens)
        if all(isinstance(key, str) for key in token_values):
            entry["tokens"] = cast(dict[str, Any], token_values)
    expires_at = raw.get("expires_at")
    if (
        isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and math.isfinite(expires_at)
    ):
        entry["expires_at"] = float(expires_at)
    token_issuer = raw.get("token_issuer")
    if isinstance(token_issuer, str) and token_issuer:
        entry["token_issuer"] = token_issuer
    client_info = raw.get("client_info")
    if isinstance(client_info, dict):
        client_values = cast(dict[object, object], client_info)
        if all(isinstance(key, str) for key in client_values):
            entry["client_info"] = cast(dict[str, Any], client_values)
    oauth_metadata = raw.get("oauth_metadata")
    if isinstance(oauth_metadata, dict):
        metadata_values = cast(dict[object, object], oauth_metadata)
        if all(isinstance(key, str) for key in metadata_values):
            entry["oauth_metadata"] = cast(dict[str, Any], metadata_values)
    oauth_issuer = raw.get("oauth_issuer")
    if isinstance(oauth_issuer, str) and oauth_issuer:
        entry["oauth_issuer"] = _normalize_issuer(oauth_issuer)
    return entry


def _read_store_unlocked(path: Path) -> _CredentialStore:
    try:
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return _empty_store()
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read MCP OAuth credentials: {}", type(exc).__name__)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    payload = cast(dict[object, object], raw)
    raw_servers = payload.get("servers")
    if not isinstance(raw_servers, dict):
        return _empty_store()
    servers: dict[str, _StoredServer] = {}
    for name, value in cast(dict[object, object], raw_servers).items():
        entry = _stored_server(value)
        if isinstance(name, str) and entry is not None:
            servers[name] = entry
    generations: dict[str, str] = {}
    raw_generations = payload.get("generations")
    if isinstance(raw_generations, dict):
        for name, value in cast(dict[object, object], raw_generations).items():
            if isinstance(name, str) and isinstance(value, str) and value:
                generations[name] = value
    return {
        "version": _STORE_VERSION,
        "servers": servers,
        "generations": generations,
    }


def _with_store_lock(path: Path) -> FileLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_suffix(".lock")), timeout=_STORE_LOCK_TIMEOUT_S)


def _write_store_unlocked(path: Path, payload: _CredentialStore) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(path.parent, 0o700)
    _write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False))
    with suppress(OSError):
        os.chmod(path, 0o600)


class MCPOAuthStorage:
    """Persistent MCP SDK token storage, isolated by config name and server URL."""

    def __init__(self, server_name: str, server_url: str) -> None:
        self.server_name = server_name
        self.server_fingerprint = _server_fingerprint(server_url)
        self._observed_generation = self._read_generation_sync()
        self._write_lease: str | None = None

    def _read_generation_sync(self) -> str | None:
        path = _store_path()
        if not path.exists():
            return None
        # Writes replace the whole file atomically, so this observes either side
        # of a concurrent deletion without blocking the async connection path.
        return _read_store_unlocked(path)["generations"].get(self.server_name)

    def _generation_is_current(self, payload: _CredentialStore) -> bool:
        return payload["generations"].get(self.server_name) == self._observed_generation

    def _entry_unlocked(self, payload: _CredentialStore) -> _StoredServer | None:
        servers = payload["servers"]
        entry = servers.get(self.server_name)
        if entry is None or entry.get("server_fingerprint") != self.server_fingerprint:
            return None
        return entry

    def _bind_entry_unlocked(
        self,
        payload: _CredentialStore,
        *,
        create: bool,
    ) -> tuple[_StoredServer | None, bool]:
        if not self._generation_is_current(payload):
            return None, False
        entry = self._entry_unlocked(payload)
        if self._write_lease is not None:
            if entry is None or entry.get("write_lease") != self._write_lease:
                return None, False
            return entry, False
        if entry is None:
            if not create:
                return None, False
            self._write_lease = secrets.token_urlsafe(24)
            entry = _StoredServer(
                server_fingerprint=self.server_fingerprint,
                write_lease=self._write_lease,
            )
            payload["servers"][self.server_name] = entry
            return entry, True
        write_lease = entry.get("write_lease")
        changed = not isinstance(write_lease, str) or not write_lease
        if changed:
            write_lease = secrets.token_urlsafe(24)
            entry["write_lease"] = write_lease
        self._write_lease = write_lease
        return entry, changed

    def _read_entry_sync(self) -> _StoredServer | None:
        path = _store_path()
        with _with_store_lock(path):
            payload = _read_store_unlocked(path)
            entry, changed = self._bind_entry_unlocked(payload, create=False)
            if changed:
                _write_store_unlocked(path, payload)
            return entry

    def _update_entry_sync(
        self,
        update: Callable[[_StoredServer], None],
        *,
        create: bool = True,
        claim: bool = False,
    ) -> bool:
        path = _store_path()
        with _with_store_lock(path):
            payload = _read_store_unlocked(path)
            if claim:
                # A browser flow owns subsequent SDK writes until another flow
                # claims the entry or the configured server is removed.
                if not self._generation_is_current(payload):
                    logger.info(
                        "Ignored stale MCP OAuth credential claim for '{}'",
                        self.server_name,
                    )
                    return False
                entry = self._entry_unlocked(payload)
                if entry is None:
                    entry = _StoredServer(server_fingerprint=self.server_fingerprint)
                    payload["servers"][self.server_name] = entry
                self._write_lease = secrets.token_urlsafe(24)
                entry["write_lease"] = self._write_lease
            else:
                entry, _ = self._bind_entry_unlocked(payload, create=create)
                if entry is None:
                    if self._write_lease is not None:
                        logger.info(
                            "Ignored stale MCP OAuth credential update for '{}'",
                            self.server_name,
                        )
                    return False
            update(entry)
            payload["version"] = _STORE_VERSION
            _write_store_unlocked(path, payload)
            return True

    def _snapshot_from_entry(self, entry: _StoredServer | None) -> _OAuthSnapshot:
        tokens: OAuthToken | None = None
        raw_tokens = entry.get("tokens") if entry is not None else None
        if isinstance(raw_tokens, dict):
            try:
                tokens = OAuthToken.model_validate(raw_tokens)
            except (ValueError, TypeError):
                logger.warning("Ignoring invalid MCP OAuth tokens for '{}'", self.server_name)

        expires_at: float | None = None
        raw_expiry = entry.get("expires_at") if entry is not None else None
        if isinstance(raw_expiry, (int, float)) and not isinstance(raw_expiry, bool):
            expires_at = float(raw_expiry)

        token_issuer: str | None = None
        raw_token_issuer = entry.get("token_issuer") if entry is not None else None
        if isinstance(raw_token_issuer, str) and raw_token_issuer:
            token_issuer = raw_token_issuer

        client_info: OAuthClientInformationFull | None = None
        raw_client = entry.get("client_info") if entry is not None else None
        if isinstance(raw_client, dict):
            try:
                client_info = OAuthClientInformationFull.model_validate(raw_client)
            except (ValueError, TypeError):
                logger.warning(
                    "Ignoring invalid MCP OAuth client info for '{}'",
                    self.server_name,
                )

        oauth_metadata: OAuthMetadata | None = None
        raw_metadata = entry.get("oauth_metadata") if entry is not None else None
        if isinstance(raw_metadata, dict):
            try:
                oauth_metadata = OAuthMetadata.model_validate(raw_metadata)
            except (ValueError, TypeError):
                logger.warning(
                    "Ignoring invalid MCP OAuth metadata for '{}'",
                    self.server_name,
                )

        oauth_issuer: str | None = None
        raw_oauth_issuer = entry.get("oauth_issuer") if entry is not None else None
        if isinstance(raw_oauth_issuer, str) and raw_oauth_issuer:
            oauth_issuer = _normalize_issuer(raw_oauth_issuer)

        return _OAuthSnapshot(
            tokens,
            expires_at,
            token_issuer,
            client_info,
            oauth_metadata,
            oauth_issuer,
        )

    async def get_snapshot(self) -> _OAuthSnapshot:
        entry = await asyncio.to_thread(self._read_entry_sync)
        return self._snapshot_from_entry(entry)

    async def get_tokens(self) -> OAuthToken | None:
        return (await self.get_snapshot()).tokens

    @staticmethod
    def _replace_tokens(entry: _StoredServer, tokens: OAuthToken | None) -> None:
        if tokens is None:
            entry.pop("tokens", None)
            entry.pop("expires_at", None)
            entry.pop("token_issuer", None)
        else:
            entry["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
            if tokens.expires_in is None:
                entry.pop("expires_at", None)
            else:
                entry["expires_at"] = time.time() + float(tokens.expires_in)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        def update(entry: _StoredServer) -> None:
            self._replace_tokens(entry, tokens)
            issuer = entry.get("oauth_issuer")
            if isinstance(issuer, str) and issuer:
                entry["token_issuer"] = _normalize_issuer(issuer)
            else:
                entry.pop("token_issuer", None)

        await asyncio.to_thread(self._update_entry_sync, update)

    async def clear_tokens(self) -> None:
        def update(entry: _StoredServer) -> None:
            self._replace_tokens(entry, None)

        await asyncio.to_thread(self._update_entry_sync, update, create=False)

    async def clear_tokens_and_client(self) -> None:
        def update(entry: _StoredServer) -> None:
            self._replace_tokens(entry, None)
            entry.pop("client_info", None)

        await asyncio.to_thread(self._update_entry_sync, update, create=False)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return (await self.get_snapshot()).client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        raw = client_info.model_dump(mode="json", exclude_none=True)

        def update(entry: _StoredServer) -> None:
            entry["client_info"] = raw

        await asyncio.to_thread(self._update_entry_sync, update)

    async def set_oauth_metadata(
        self,
        metadata: OAuthMetadata,
        *,
        issuer: str | None = None,
    ) -> None:
        raw = metadata.model_dump(mode="json", exclude_none=True)
        oauth_issuer = _normalize_issuer(issuer or str(metadata.issuer))

        def update(entry: _StoredServer) -> None:
            entry["oauth_metadata"] = raw
            entry["oauth_issuer"] = oauth_issuer

        await asyncio.to_thread(self._update_entry_sync, update)

    async def clear_oauth_metadata(self) -> None:
        def update(entry: _StoredServer) -> None:
            entry.pop("oauth_metadata", None)
            entry.pop("oauth_issuer", None)

        await asyncio.to_thread(self._update_entry_sync, update, create=False)

    @staticmethod
    def _token_binding(entry: _StoredServer) -> tuple[str, str, str] | None:
        raw = entry.get("tokens")
        if not isinstance(raw, dict):
            return None
        access_token = raw.get("access_token")
        refresh_token = raw.get("refresh_token")
        token_issuer = entry.get("token_issuer")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(refresh_token, str)
            or not refresh_token
            or not isinstance(token_issuer, str)
            or not token_issuer
        ):
            return None
        return access_token, refresh_token, token_issuer

    def refresh_lock(self) -> BaseAsyncFileLock:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(
            f"{self.server_name}\0{self.server_fingerprint}".encode("utf-8")
        ).hexdigest()
        return AsyncFileLock(
            path.with_name(f"mcp-refresh-{identity}.lock"),
            timeout=_REFRESH_LOCK_TIMEOUT_S,
        )

    def _finish_refresh_sync(
        self,
        lease: _RefreshLease,
        tokens: OAuthToken | None,
        *,
        clear_client: bool,
    ) -> bool:
        path = _store_path()
        with _with_store_lock(path):
            payload = _read_store_unlocked(path)
            entry, changed = self._bind_entry_unlocked(payload, create=False)
            if (
                entry is None
                or self._token_binding(entry)
                != (lease.access_token, lease.refresh_token, lease.token_issuer)
            ):
                if changed:
                    _write_store_unlocked(path, payload)
                return False

            self._replace_tokens(entry, tokens)
            if clear_client:
                entry.pop("client_info", None)
            _write_store_unlocked(path, payload)
            return True

    async def finish_refresh(
        self,
        lease: _RefreshLease,
        tokens: OAuthToken | None,
        *,
        clear_client: bool = False,
    ) -> bool:
        return await asyncio.to_thread(
            self._finish_refresh_sync,
            lease,
            tokens,
            clear_client=clear_client,
        )

    async def redirect_uri(self) -> str | None:
        entry = await asyncio.to_thread(self._read_entry_sync)
        value = entry.get("redirect_uri") if entry is not None else None
        return value if isinstance(value, str) and value else None

    async def prepare_redirect_uri(self, redirect_uri: str, *, reset: bool = False) -> None:
        def update(entry: _StoredServer) -> None:
            changed = entry.get("redirect_uri") != redirect_uri
            if reset:
                self._replace_tokens(entry, None)
                entry.pop("client_info", None)
            elif changed:
                # Dynamic registrations bind a client to its redirect URI.
                entry.pop("client_info", None)
            entry["redirect_uri"] = redirect_uri

        claimed = await asyncio.to_thread(self._update_entry_sync, update, claim=True)
        if not claimed:
            raise MCPAuthorizationRequiredError("MCP authorization was cancelled")

    def has_credentials(self) -> bool:
        entry = self._read_entry_sync()
        raw_tokens = entry.get("tokens") if entry is not None else None
        if not isinstance(raw_tokens, dict):
            return False
        tokens = cast(dict[str, object], raw_tokens)
        access_token = tokens.get("access_token")
        return isinstance(access_token, str) and bool(access_token)


class MCPTokenRefreshError(RuntimeError):
    """Raised when a refresh failed without proving that authorization is invalid."""


class _RetryOAuthWithDiscoveredMetadata(BaseException):
    """Restart the SDK flow after discovery without logging a false OAuth failure."""


class _RetryOAuthWithStoredCredentials(BaseException):
    """Restart the SDK flow with credentials refreshed by another provider."""


def _oauth_error_code(response: httpx.Response) -> str | None:
    try:
        payload = cast(object, response.json())
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = cast(dict[object, object], payload).get("error")
    return error if isinstance(error, str) else None


class _RefreshingOAuthClientProvider(OAuthClientProvider):
    """MCP SDK OAuth provider with restart-safe, one-shot token refresh.

    This is a compatibility layer for modelcontextprotocol/python-sdk#3328.
    Its private SDK method contract is pinned by tests and should be removed once
    the upstream fix is available in nanobot's supported MCP version.
    """

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: MCPOAuthStorage,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._nanobot_storage = storage
        self._refresh_attempted = ContextVar("mcp_oauth_refresh_attempted", default=False)
        self._refresh_after_discovery = ContextVar(
            "mcp_oauth_refresh_after_discovery",
            default=False,
        )
        self._refresh_claim = ContextVar[_RefreshLease | None](
            "mcp_oauth_refresh_claim",
            default=None,
        )
        self._token_issuer: str | None = None
        super().__init__(
            server_url,
            client_metadata,
            storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=timeout,
        )

    async def _initialize(self) -> None:
        """Restore enough OAuth state to refresh without an interactive flow."""
        self._apply_snapshot(await self._nanobot_storage.get_snapshot())
        self._initialized = True

    def _apply_snapshot(self, snapshot: _OAuthSnapshot) -> None:
        self.context.current_tokens = snapshot.tokens
        self.context.token_expiry_time = snapshot.expires_at
        self._token_issuer = snapshot.token_issuer
        self.context.client_info = snapshot.client_info
        self.context.oauth_metadata = snapshot.oauth_metadata
        self.context.auth_server_url = snapshot.oauth_issuer

    async def _reload_after_lost_claim(self, lease: _RefreshLease) -> bool:
        snapshot = await self._nanobot_storage.get_snapshot()
        self._apply_snapshot(snapshot)
        tokens = snapshot.tokens
        if tokens is None:
            return False
        if (tokens.access_token, tokens.refresh_token) != (
            lease.access_token,
            lease.refresh_token,
        ):
            return True
        raise MCPTokenRefreshError("MCP OAuth credentials changed while refreshing; retry later")

    async def _release_refresh_claim(self) -> None:
        lease = self._refresh_claim.get()
        if lease is None:
            return
        self._refresh_claim.set(None)
        await lease.lock.release()

    async def _handle_refresh_response(self, response: httpx.Response) -> bool:
        """Persist a rotated token pair while retaining credentials on transient errors."""
        lease = self._refresh_claim.get()
        if lease is None:
            raise MCPTokenRefreshError("MCP OAuth refresh response has no storage lease")

        if response.status_code != 200:
            error = _oauth_error_code(response)
            if error in {"invalid_grant", "invalid_client", "unauthorized_client"}:
                clear_client = error != "invalid_grant"
                cleared = await self._nanobot_storage.finish_refresh(
                    lease,
                    None,
                    clear_client=clear_client,
                )
                await self._release_refresh_claim()
                if not cleared:
                    return await self._reload_after_lost_claim(lease)
                self.context.clear_tokens()
                self._token_issuer = None
                if clear_client:
                    self.context.client_info = None
                return False
            if response.status_code == 404:
                await self._release_refresh_claim()
                await self._nanobot_storage.clear_oauth_metadata()
                self.context.oauth_metadata = None
                self._refresh_attempted.set(False)
                return False
            await self._release_refresh_claim()
            raise MCPTokenRefreshError(
                f"MCP OAuth token refresh failed ({response.status_code}); will retry later"
            )

        try:
            token_response = OAuthToken.model_validate_json(await response.aread())
        except (ValueError, TypeError) as exc:
            await self._release_refresh_claim()
            raise MCPTokenRefreshError("MCP OAuth token refresh returned an invalid response") from exc

        previous = self.context.current_tokens
        updates: dict[str, str] = {}
        if previous is not None:
            if token_response.refresh_token is None and previous.refresh_token is not None:
                updates["refresh_token"] = previous.refresh_token
            if token_response.scope is None and previous.scope is not None:
                updates["scope"] = previous.scope
        if updates:
            token_response = token_response.model_copy(update=updates)

        committed = await self._nanobot_storage.finish_refresh(lease, token_response)
        await self._release_refresh_claim()
        if not committed:
            return await self._reload_after_lost_claim(lease)
        self.context.current_tokens = token_response
        self.context.update_token_expiry(token_response)
        return True

    async def _refresh_token(self) -> httpx.Request:
        tokens = self.context.current_tokens
        if tokens is None or tokens.refresh_token is None:
            return await super()._refresh_token()
        lock = self._nanobot_storage.refresh_lock()
        await lock.acquire()
        try:
            snapshot = await self._nanobot_storage.get_snapshot()
        except BaseException:
            await lock.release()
            raise
        stored_tokens = snapshot.tokens
        if stored_tokens is None or (
            stored_tokens.access_token,
            stored_tokens.refresh_token,
            snapshot.token_issuer,
        ) != (tokens.access_token, tokens.refresh_token, self._token_issuer):
            await lock.release()
            self._apply_snapshot(snapshot)
            raise _RetryOAuthWithStoredCredentials
        metadata = self.context.oauth_metadata
        token_issuer = self._token_issuer
        oauth_issuer = self.context.auth_server_url
        if metadata is None or oauth_issuer is None or token_issuer != _normalize_issuer(oauth_issuer):
            try:
                await self._nanobot_storage.clear_tokens()
            finally:
                await lock.release()
            self.context.clear_tokens()
            self._token_issuer = None
            raise _RetryOAuthWithStoredCredentials
        assert token_issuer is not None
        lease = _RefreshLease(
            lock=lock,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_issuer=token_issuer,
        )
        self._refresh_claim.set(lease)
        self._refresh_attempted.set(True)
        try:
            return await super()._refresh_token()
        except BaseException:
            await self._release_refresh_claim()
            raise

    async def _perform_authorization(self) -> httpx.Request:
        metadata = self.context.oauth_metadata
        oauth_issuer: str | None = None
        if metadata is not None:
            oauth_issuer = _normalize_issuer(self.context.auth_server_url or str(metadata.issuer))
            await self._nanobot_storage.set_oauth_metadata(metadata, issuer=oauth_issuer)
        if (
            self._refresh_after_discovery.get()
            and metadata is not None
            and oauth_issuer == self._token_issuer
        ):
            raise _RetryOAuthWithDiscoveredMetadata
        if self._refresh_after_discovery.get():
            await self._nanobot_storage.clear_tokens_and_client()
            self.context.clear_tokens()
            self.context.client_info = None
            self._token_issuer = None
            raise _RetryOAuthWithStoredCredentials
        return await super()._perform_authorization()

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Let a 401 discover the token endpoint, then restart once to refresh."""
        try:
            for attempt in range(3):
                self._refresh_attempted.set(False)
                self._refresh_after_discovery.set(False)
                try:
                    async with aclosing(super().async_auth_flow(request)) as flow:
                        try:
                            outgoing = await anext(flow)
                        except StopAsyncIteration:
                            return
                        while True:
                            response = yield outgoing
                            if (
                                attempt == 0
                                and str(outgoing.url) == self.context.server_url
                                and response.status_code == 401
                                and not self._refresh_attempted.get()
                                and self.context.can_refresh_token()
                            ):
                                self._refresh_after_discovery.set(True)
                            try:
                                outgoing = await flow.asend(response)
                            except StopAsyncIteration:
                                return
                except _RetryOAuthWithDiscoveredMetadata:
                    # The SDK has now validated discovery metadata. Mark the token
                    # expired so its normal pre-request branch refreshes against the
                    # discovered endpoint instead of guessing {server_origin}/token.
                    self.context.token_expiry_time = time.time() - 1
                    continue
                except _RetryOAuthWithStoredCredentials:
                    continue
                finally:
                    self._refresh_after_discovery.set(False)
            raise AssertionError("MCP OAuth refresh retry did not complete")
        finally:
            await self._release_refresh_claim()


async def _missing_callback() -> tuple[str, str | None]:
    raise MCPAuthorizationRequiredError("MCP server requires browser authorization")


async def create_mcp_oauth_auth(
    server_name: str,
    server_url: str,
    handlers: MCPOAuthHandlers | None = None,
) -> OAuthClientProvider:
    """Build the official MCP SDK OAuth provider for one configured server."""
    storage = MCPOAuthStorage(server_name, server_url)
    if handlers is not None:
        await storage.prepare_redirect_uri(
            handlers.redirect_uri,
            reset=handlers.reset_credentials,
        )
        redirect_uri = handlers.redirect_uri
        redirect_handler = handlers.redirect_handler
        callback_handler = handlers.callback_handler
    else:
        if not await asyncio.to_thread(storage.has_credentials):
            # Do not perform discovery or dynamic registration from a background
            # startup. Interactive OAuth begins only after an explicit user action.
            raise MCPAuthorizationRequiredError("MCP server requires browser authorization")
        redirect_uri = await storage.redirect_uri() or _DEFAULT_REDIRECT_URI

        async def authorization_required(_authorization_url: str) -> None:
            await storage.clear_tokens()
            raise MCPAuthorizationRequiredError("MCP server requires browser authorization")

        redirect_handler = authorization_required
        callback_handler = _missing_callback

    metadata = OAuthClientMetadata(
        redirect_uris=[AnyUrl(redirect_uri)],
        token_endpoint_auth_method="none",
        client_name="nanobot",
        client_uri=_CLIENT_URI,
        logo_uri=_LOGO_URI,
        software_id="https://github.com/HKUDS/nanobot",
    )
    return _RefreshingOAuthClientProvider(
        server_url,
        metadata,
        storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        timeout=300,
    )


def mcp_oauth_has_credentials(server_name: str, server_url: str) -> bool:
    """Return whether this exact configured MCP instance has an access token."""
    return MCPOAuthStorage(server_name, server_url).has_credentials()


def delete_mcp_oauth_credentials(server_name: str) -> bool:
    """Delete credentials for one config name without touching other MCP instances."""
    path = _store_path()
    with _with_store_lock(path):
        payload = _read_store_unlocked(path)
        servers = payload["servers"]
        removed = servers.pop(server_name, None) is not None
        # Rotate even when no entry exists so a flow created before removal cannot
        # claim the name later and resurrect credentials.
        payload["generations"][server_name] = secrets.token_urlsafe(24)
        _write_store_unlocked(path, payload)
        return removed
