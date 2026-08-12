"""OAuth support for remote MCP servers.

This module intentionally owns MCP OAuth end to end. Provider OAuth has a
different lifecycle and storage contract, so sharing a higher-level workflow
would couple unrelated extension boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

from filelock import FileLock
from loguru import logger
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl

from nanobot.config.paths import get_data_dir
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

MCP_OAUTH_CALLBACK_PATH = "/auth/mcp/callback"
_STORE_VERSION = 1
_STORE_LOCK_TIMEOUT_S = 15
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
    client_info: dict[str, Any]
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


def _store_path() -> Path:
    return get_data_dir() / "auth" / "mcp.json"


def _server_fingerprint(server_url: str) -> str:
    return hashlib.sha256(server_url.strip().encode("utf-8")).hexdigest()


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
    client_info = raw.get("client_info")
    if isinstance(client_info, dict):
        client_values = cast(dict[object, object], client_info)
        if all(isinstance(key, str) for key in client_values):
            entry["client_info"] = cast(dict[str, Any], client_values)
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

    async def get_tokens(self) -> OAuthToken | None:
        entry = await asyncio.to_thread(self._read_entry_sync)
        raw = entry.get("tokens") if entry is not None else None
        if not isinstance(raw, dict):
            return None
        try:
            return OAuthToken.model_validate(raw)
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid MCP OAuth tokens for '{}'", self.server_name)
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        raw = tokens.model_dump(mode="json", exclude_none=True)

        def update(entry: _StoredServer) -> None:
            entry["tokens"] = raw

        await asyncio.to_thread(self._update_entry_sync, update)

    async def clear_tokens(self) -> None:
        def update(entry: _StoredServer) -> None:
            entry.pop("tokens", None)

        await asyncio.to_thread(self._update_entry_sync, update, create=False)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        entry = await asyncio.to_thread(self._read_entry_sync)
        raw = entry.get("client_info") if entry is not None else None
        if not isinstance(raw, dict):
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid MCP OAuth client info for '{}'", self.server_name)
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        raw = client_info.model_dump(mode="json", exclude_none=True)

        def update(entry: _StoredServer) -> None:
            entry["client_info"] = raw

        await asyncio.to_thread(self._update_entry_sync, update)

    async def redirect_uri(self) -> str | None:
        entry = await asyncio.to_thread(self._read_entry_sync)
        value = entry.get("redirect_uri") if entry is not None else None
        return value if isinstance(value, str) and value else None

    async def prepare_redirect_uri(self, redirect_uri: str, *, reset: bool = False) -> None:
        def update(entry: _StoredServer) -> None:
            changed = entry.get("redirect_uri") != redirect_uri
            if reset:
                entry.pop("tokens", None)
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
    return OAuthClientProvider(
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
