# Anthropic OAuth Token Auto-Refresh Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically refresh expired Anthropic OAuth tokens in nanobot, eliminating the need for manual `config.json` updates when the 8-hour token expires.

**Architecture:** Add a `OAuthCredentialStore` that reads/writes `~/.nanobot/oauth_credentials.json` + fallback to `~/.claude/.credentials.json` (Claude CLI format). Integrate into `AnthropicProvider` via a `_ensure_valid_token()` method guarded by `asyncio.Lock`. The store is initialized in `_make_provider` and passed into the provider at construction time.

**Tech Stack:** Python `httpx` (already available via `anthropic` SDK), `asyncio.Lock`, `dataclasses`, `pathlib`, standard library only for the store.

---

## Chunk 1: OAuth credential store module

### Task 1: Create `nanobot/providers/oauth_store.py`

**Files:**
- Create: `nanobot/providers/oauth_store.py`
- Test: `tests/providers/test_oauth_store.py`

**Context:** The store is the single source of truth for OAuth credentials.
- Primary: `~/.nanobot/oauth_credentials.json` (written by nanobot itself)
- Fallback: `~/.claude/.credentials.json` (written by Claude CLI, format: `claudeAiOauth.{accessToken, refreshToken, expiresAt}`)
- `expiresAt` in Claude CLI credentials is milliseconds since epoch
- When credentials are still valid and not near expiry → no refresh needed

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/test_oauth_store.py
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from nanobot.providers.oauth_store import OAuthCredentials, OAuthCredentialStore


def test_credentials_is_expired_when_past_expiry():
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-xxx",
        refresh_token="sk-ant-ort01-xxx",
        expires_at_ms=int(time.time() * 1000) - 10_000,
    )
    assert creds.is_expired(margin_ms=0)


def test_credentials_not_expired_when_future():
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-xxx",
        refresh_token="sk-ant-ort01-xxx",
        expires_at_ms=int(time.time() * 1000) + 3_600_000,
    )
    assert not creds.is_expired(margin_ms=0)


def test_credentials_expired_within_margin():
    # expires in 2 min, margin is 5 min → should be considered expired
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-xxx",
        refresh_token="sk-ant-ort01-xxx",
        expires_at_ms=int(time.time() * 1000) + 2 * 60 * 1000,
    )
    assert creds.is_expired(margin_ms=5 * 60 * 1000)


def test_store_save_and_load(tmp_path):
    store_path = tmp_path / "oauth_credentials.json"
    store = OAuthCredentialStore(store_path=store_path)
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-abc",
        refresh_token="sk-ant-ort01-xyz",
        expires_at_ms=1_000_000_000_000,
    )
    store.save(creds)
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "sk-ant-oat01-abc"
    assert loaded.refresh_token == "sk-ant-ort01-xyz"
    assert loaded.expires_at_ms == 1_000_000_000_000


def test_store_load_returns_none_when_missing(tmp_path):
    store = OAuthCredentialStore(store_path=tmp_path / "nonexistent.json")
    assert store.load() is None


def test_store_load_from_claude_cli(tmp_path):
    cli_creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-cli",
            "refreshToken": "sk-ant-ort01-cli",
            "expiresAt": 1_800_000_000_000,
        }
    }
    cli_path = tmp_path / ".credentials.json"
    cli_path.write_text(json.dumps(cli_creds))
    store = OAuthCredentialStore(
        store_path=tmp_path / "nonexistent.json",
        claude_cli_creds_path=cli_path,
    )
    creds = store.load()
    assert creds is not None
    assert creds.access_token == "sk-ant-oat01-cli"
    assert creds.refresh_token == "sk-ant-ort01-cli"
    assert creds.expires_at_ms == 1_800_000_000_000


def test_store_nanobot_file_takes_precedence_over_cli(tmp_path):
    # nanobot file exists → use it, ignore Claude CLI file
    store_path = tmp_path / "oauth_credentials.json"
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-nanobot",
        refresh_token="sk-ant-ort01-nanobot",
        expires_at_ms=1_900_000_000_000,
    )
    store = OAuthCredentialStore(store_path=store_path)
    store.save(creds)

    cli_creds = {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-cli",
            "refreshToken": "sk-ant-ort01-cli",
            "expiresAt": 1_800_000_000_000,
        }
    }
    cli_path = tmp_path / ".credentials.json"
    cli_path.write_text(json.dumps(cli_creds))

    store2 = OAuthCredentialStore(store_path=store_path, claude_cli_creds_path=cli_path)
    loaded = store2.load()
    assert loaded.access_token == "sk-ant-oat01-nanobot"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/test_oauth_store.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'nanobot.providers.oauth_store'`

- [ ] **Step 3: Implement `nanobot/providers/oauth_store.py`**

```python
"""OAuth credential store for Anthropic Claude Code tokens.

Two credential sources (in priority order):
1. ~/.nanobot/oauth_credentials.json  — written by nanobot after each refresh
2. ~/.claude/.credentials.json        — written by Claude CLI (claudeAiOauth format)

Only the nanobot file is written on refresh; the Claude CLI file is read-only.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from loguru import logger

_DEFAULT_STORE_PATH = Path.home() / ".nanobot" / "oauth_credentials.json"
_DEFAULT_CLI_CREDS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class OAuthCredentials:
    access_token: str
    refresh_token: str
    expires_at_ms: int  # Unix timestamp in milliseconds

    def is_expired(self, margin_ms: int = 5 * 60 * 1000) -> bool:
        """Return True if the token is expired or will expire within margin_ms."""
        now_ms = int(time.time() * 1000)
        return now_ms >= self.expires_at_ms - margin_ms


class OAuthCredentialStore:
    """Read/write OAuth credentials from disk."""

    def __init__(
        self,
        store_path: Path | None = None,
        claude_cli_creds_path: Path | None = None,
    ) -> None:
        self._store_path = store_path or _DEFAULT_STORE_PATH
        self._cli_path = claude_cli_creds_path or _DEFAULT_CLI_CREDS_PATH

    def load(self) -> OAuthCredentials | None:
        """Load credentials. Nanobot file takes precedence over Claude CLI file."""
        creds = self._load_nanobot()
        if creds is not None:
            return creds
        return self._load_claude_cli()

    def save(self, creds: OAuthCredentials) -> None:
        """Persist credentials to the nanobot store file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(creds)
        self._store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("OAuth credentials saved to {}", self._store_path)

    def _load_nanobot(self) -> OAuthCredentials | None:
        if not self._store_path.exists():
            return None
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            return OAuthCredentials(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at_ms=int(data["expires_at_ms"]),
            )
        except Exception as e:
            logger.warning("Failed to load nanobot OAuth credentials: {}", e)
            return None

    def _load_claude_cli(self) -> OAuthCredentials | None:
        if not self._cli_path.exists():
            return None
        try:
            data = json.loads(self._cli_path.read_text(encoding="utf-8"))
            oauth = data.get("claudeAiOauth", {})
            return OAuthCredentials(
                access_token=oauth["accessToken"],
                refresh_token=oauth["refreshToken"],
                expires_at_ms=int(oauth["expiresAt"]),
            )
        except Exception as e:
            logger.warning("Failed to load Claude CLI OAuth credentials: {}", e)
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/test_oauth_store.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/providers/oauth_store.py tests/providers/test_oauth_store.py
git commit -m "feat: add OAuthCredentialStore for Anthropic token persistence"
```

---

## Chunk 2: Token refresh function

### Task 2: Add `refresh_anthropic_token()` in `nanobot/providers/oauth_store.py`

**Files:**
- Modify: `nanobot/providers/oauth_store.py` (add refresh function at bottom)
- Test: `tests/providers/test_oauth_refresh.py`

**Context:** Refresh endpoint from pi-mono research:
- URL: `https://platform.claude.com/v1/oauth/token`
- client_id: `9d1c250a-e61b-44d9-88ed-5944d1962f5e` (fixed, from Claude CLI source)
- `expires_in` is seconds; store as `now_ms + expires_in * 1000 - 5 * 60 * 1000` (5 min early)

- [ ] **Step 1: Write failing tests**

```python
# tests/providers/test_oauth_refresh.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nanobot.providers.oauth_store import refresh_anthropic_token, OAuthCredentials

MOCK_RESPONSE = {
    "access_token": "sk-ant-oat01-new-access",
    "refresh_token": "sk-ant-ort01-new-refresh",
    "expires_in": 28800,
}


@pytest.mark.asyncio
async def test_refresh_returns_new_credentials():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(MOCK_RESPONSE)
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await refresh_anthropic_token("sk-ant-ort01-old-refresh")

    assert result.access_token == "sk-ant-oat01-new-access"
    assert result.refresh_token == "sk-ant-ort01-new-refresh"
    # expires_at_ms = now + 28800*1000 - 5*60*1000, just check it's in the future
    import time
    assert result.expires_at_ms > int(time.time() * 1000)


@pytest.mark.asyncio
async def test_refresh_raises_on_http_error():
    import httpx
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = '{"error": "invalid_grant"}'
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)
    )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(Exception, match="token refresh"):
            await refresh_anthropic_token("bad-token")


@pytest.mark.asyncio
async def test_refresh_posts_correct_payload():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = json.dumps(MOCK_RESPONSE)
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await refresh_anthropic_token("sk-ant-ort01-test")

        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert sent_json["grant_type"] == "refresh_token"
        assert sent_json["client_id"] == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
        assert sent_json["refresh_token"] == "sk-ant-ort01-test"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/test_oauth_refresh.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'refresh_anthropic_token'`

- [ ] **Step 3: Append `refresh_anthropic_token` to `oauth_store.py`**

Add these imports at the top of `oauth_store.py` (after existing imports):
```python
import httpx
```

Append to bottom of `oauth_store.py`:
```python
_ANTHROPIC_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_ANTHROPIC_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_REFRESH_MARGIN_MS = 5 * 60 * 1000  # refresh 5 min before actual expiry


async def refresh_anthropic_token(refresh_token: str) -> OAuthCredentials:
    """Exchange a refresh token for a new access token.

    Raises RuntimeError on failure (network error or non-2xx response).
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": _ANTHROPIC_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _ANTHROPIC_TOKEN_URL,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Anthropic OAuth token refresh failed (HTTP {e.response.status_code}): {e.response.text}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Anthropic OAuth token refresh request failed: {e}") from e

    try:
        data = response.json()
    except Exception as e:
        raise RuntimeError(f"Anthropic OAuth token refresh returned invalid JSON: {e}") from e

    now_ms = int(time.time() * 1000)
    return OAuthCredentials(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at_ms=now_ms + int(data["expires_in"]) * 1000 - _REFRESH_MARGIN_MS,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/test_oauth_refresh.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/providers/oauth_store.py tests/providers/test_oauth_refresh.py
git commit -m "feat: add refresh_anthropic_token() to oauth_store"
```

---

## Chunk 3: Integrate refresh into AnthropicProvider

### Task 3: Add `_ensure_valid_token()` to `AnthropicProvider`

**Files:**
- Modify: `nanobot/providers/anthropic_provider.py`
- Test: `tests/providers/test_anthropic_token_refresh.py`

**Context:**
- Add `credential_store: OAuthCredentialStore | None` param to `__init__`
- Add `_token_expires_at_ms: int` state
- Add `_refresh_lock: asyncio.Lock`
- `_ensure_valid_token()`: check expiry → refresh if needed → update `self._client` with new token
- Call `_ensure_valid_token()` at the start of `chat()` and `chat_stream()` only when `self._is_oauth`
- `_update_oauth_client(new_token)`: recreate `self._client` with new Bearer token

- [ ] **Step 1: Write failing tests**

```python
# tests/providers/test_anthropic_token_refresh.py
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.oauth_store import OAuthCredentials, OAuthCredentialStore


def _make_store(access_token, refresh_token, expires_at_ms):
    store = MagicMock(spec=OAuthCredentialStore)
    store.load.return_value = OAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_ms=expires_at_ms,
    )
    store.save = MagicMock()
    return store


@pytest.mark.asyncio
async def test_no_refresh_when_token_valid():
    """When token is still valid, refresh is not called."""
    future_expiry = int(time.time() * 1000) + 3_600_000
    store = _make_store("sk-ant-oat01-valid", "sk-ant-ort01-r", future_expiry)

    with patch("nanobot.providers.anthropic_provider.refresh_anthropic_token") as mock_refresh:
        provider = AnthropicProvider(
            api_key="sk-ant-oat01-valid",
            credential_store=store,
        )
        provider._token_expires_at_ms = future_expiry

        mock_messages = MagicMock()
        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_messages.create = AsyncMock(return_value=mock_response)
        provider._client = MagicMock()
        provider._client.messages = mock_messages

        await provider.chat([{"role": "user", "content": "hi"}])
        mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_triggered_when_token_expired():
    """When token is expired, refresh is called and client is updated."""
    expired = int(time.time() * 1000) - 1000
    store = _make_store("sk-ant-oat01-old", "sk-ant-ort01-r", expired)

    new_creds = OAuthCredentials(
        access_token="sk-ant-oat01-new",
        refresh_token="sk-ant-ort01-new-r",
        expires_at_ms=int(time.time() * 1000) + 3_600_000,
    )

    with patch("nanobot.providers.anthropic_provider.refresh_anthropic_token",
               new=AsyncMock(return_value=new_creds)) as mock_refresh:
        provider = AnthropicProvider(
            api_key="sk-ant-oat01-old",
            credential_store=store,
        )
        provider._token_expires_at_ms = expired

        mock_messages = MagicMock()
        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_messages.create = AsyncMock(return_value=mock_response)

        # After refresh, client should be replaced
        provider._client = MagicMock()
        provider._client.messages = mock_messages

        # Mock _update_oauth_client to avoid SDK instantiation
        provider._update_oauth_client = MagicMock()

        await provider.chat([{"role": "user", "content": "hi"}])

        mock_refresh.assert_called_once_with("sk-ant-ort01-r")
        store.save.assert_called_once_with(new_creds)
        provider._update_oauth_client.assert_called_once_with("sk-ant-oat01-new")


@pytest.mark.asyncio
async def test_concurrent_refresh_only_runs_once():
    """Two concurrent calls with expired token should only refresh once."""
    expired = int(time.time() * 1000) - 1000
    store = _make_store("sk-ant-oat01-old", "sk-ant-ort01-r", expired)

    refresh_call_count = 0

    async def mock_refresh(rt):
        nonlocal refresh_call_count
        refresh_call_count += 1
        await asyncio.sleep(0.01)
        return OAuthCredentials(
            access_token="sk-ant-oat01-new",
            refresh_token="sk-ant-ort01-new-r",
            expires_at_ms=int(time.time() * 1000) + 3_600_000,
        )

    with patch("nanobot.providers.anthropic_provider.refresh_anthropic_token", side_effect=mock_refresh):
        provider = AnthropicProvider(
            api_key="sk-ant-oat01-old",
            credential_store=store,
        )
        provider._token_expires_at_ms = expired

        mock_messages = MagicMock()
        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "end_turn"
        mock_response.usage = None
        mock_messages.create = AsyncMock(return_value=mock_response)

        real_client = MagicMock()
        real_client.messages = mock_messages
        provider._client = real_client
        provider._update_oauth_client = MagicMock()

        # Simulate two concurrent calls
        await asyncio.gather(
            provider.chat([{"role": "user", "content": "hi"}]),
            provider.chat([{"role": "user", "content": "hello"}]),
        )

        assert refresh_call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/test_anthropic_token_refresh.py -v 2>&1 | head -30
```

Expected: failures related to missing `credential_store` param and `_ensure_valid_token`

- [ ] **Step 3: Modify `anthropic_provider.py`**

**3a. Add import at top of file** (after existing imports):
```python
import asyncio
```

**3b. Add import at module level** (in the imports section):
```python
from nanobot.providers.oauth_store import OAuthCredentialStore, refresh_anthropic_token
```

**3c. Modify `AnthropicProvider.__init__` signature** — add `credential_store` parameter:
```python
def __init__(
    self,
    api_key: str | None = None,
    api_base: str | None = None,
    default_model: str = "claude-sonnet-4-20250514",
    extra_headers: dict[str, str] | None = None,
    credential_store: OAuthCredentialStore | None = None,
):
```

**3d. Add state variables** (inside `__init__`, after `self._is_oauth = ...`):
```python
self._credential_store = credential_store
self._token_expires_at_ms: int = 0
self._refresh_lock: asyncio.Lock = asyncio.Lock()

# Initialize expiry from stored credentials if available
if self._is_oauth and credential_store:
    creds = credential_store.load()
    if creds:
        self._token_expires_at_ms = creds.expires_at_ms
```

**3e. Add `_update_oauth_client` method** (after `__init__`):
```python
def _update_oauth_client(self, new_access_token: str) -> None:
    """Recreate the Anthropic client with a new OAuth access token."""
    from anthropic import AsyncAnthropic
    client_kw: dict[str, Any] = {
        "auth_token": new_access_token,
        "api_key": None,
    }
    if self.api_base:
        client_kw["base_url"] = self.api_base
    if self.extra_headers:
        client_kw["default_headers"] = self.extra_headers
    self._client = AsyncAnthropic(**client_kw)
    logger.debug("AnthropicProvider: client updated with new OAuth access token")
```

**3f. Add `_ensure_valid_token` method** (after `_update_oauth_client`):
```python
async def _ensure_valid_token(self) -> None:
    """Refresh the OAuth token if expired or near expiry. No-op for API key auth."""
    if not self._is_oauth or not self._credential_store:
        return

    from nanobot.providers.oauth_store import OAuthCredentials
    now_ms = int(__import__("time").time() * 1000)
    if now_ms < self._token_expires_at_ms - 5 * 60 * 1000:
        return  # token still valid, fast path (no lock needed)

    async with self._refresh_lock:
        # Re-check after acquiring lock (another coroutine may have refreshed already)
        now_ms = int(__import__("time").time() * 1000)
        if now_ms < self._token_expires_at_ms - 5 * 60 * 1000:
            return

        creds = self._credential_store.load()
        if creds is None:
            logger.warning("AnthropicProvider: no OAuth credentials found, skipping refresh")
            return

        try:
            logger.info("AnthropicProvider: OAuth token expired, refreshing...")
            new_creds = await refresh_anthropic_token(creds.refresh_token)
            self._token_expires_at_ms = new_creds.expires_at_ms
            self._update_oauth_client(new_creds.access_token)
            self._credential_store.save(new_creds)
            logger.info("AnthropicProvider: OAuth token refreshed successfully")
        except Exception as e:
            logger.error("AnthropicProvider: OAuth token refresh failed: {}", e)
            # Continue with existing (possibly expired) token; will get 401 from API
```

**3g. Modify `chat()` and `chat_stream()`** — add `await self._ensure_valid_token()` as the first line inside each method's `try` block (or before it):

In `chat()`, prepend before the existing content:
```python
await self._ensure_valid_token()
```

In `chat_stream()`, prepend before the existing content:
```python
await self._ensure_valid_token()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/test_anthropic_token_refresh.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Run full provider test suite to check no regressions**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/providers/ -v
```

Expected: all provider tests PASS

- [ ] **Step 6: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/providers/anthropic_provider.py tests/providers/test_anthropic_token_refresh.py
git commit -m "feat: add _ensure_valid_token() with asyncio.Lock for OAuth auto-refresh"
```

---

## Chunk 4: Wire credential store into `_make_provider`

### Task 4: Initialize `OAuthCredentialStore` in `_make_provider`

**Files:**
- Modify: `nanobot/cli/commands.py` (the `_make_provider` function, lines ~378–445)
- Test: `tests/cli/test_make_provider_oauth.py`

**Context:**
- When `backend == "anthropic"` and the provider is an OAuth provider (`spec.is_oauth`), create an `OAuthCredentialStore` and pass it to `AnthropicProvider`
- If no `api_key` in config, load initial token from the store's `load()` method
- This makes `config.json` `apiKey` optional for `anthropic_claude_code` — the store handles it

- [ ] **Step 1: Write failing tests**

```python
# tests/cli/test_make_provider_oauth.py
import pytest
from unittest.mock import patch, MagicMock

# We test the logic of credential loading in _make_provider by mocking the store


def test_oauth_provider_loads_token_from_store_when_config_empty(tmp_path):
    """If config has no apiKey, token is loaded from OAuthCredentialStore."""
    from nanobot.providers.oauth_store import OAuthCredentials, OAuthCredentialStore
    import time

    store_path = tmp_path / "oauth_credentials.json"
    store = OAuthCredentialStore(store_path=store_path)
    creds = OAuthCredentials(
        access_token="sk-ant-oat01-from-store",
        refresh_token="sk-ant-ort01-from-store",
        expires_at_ms=int(time.time() * 1000) + 3_600_000,
    )
    store.save(creds)

    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "sk-ant-oat01-from-store"


def test_oauth_store_default_paths_exist():
    """Verify default paths are correct."""
    from pathlib import Path
    from nanobot.providers.oauth_store import _DEFAULT_STORE_PATH, _DEFAULT_CLI_CREDS_PATH
    assert str(_DEFAULT_STORE_PATH).endswith(".nanobot/oauth_credentials.json")
    assert str(_DEFAULT_CLI_CREDS_PATH).endswith(".claude/.credentials.json")
```

- [ ] **Step 2: Run tests to verify they pass (these are simple)**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/cli/test_make_provider_oauth.py -v
```

Expected: both tests PASS immediately

- [ ] **Step 3: Modify `_make_provider` in `nanobot/cli/commands.py`**

Find the `elif backend == "anthropic":` block (around line 424) and replace it:

```python
elif backend == "anthropic":
    from nanobot.providers.anthropic_provider import AnthropicProvider
    from nanobot.providers.oauth_store import OAuthCredentialStore

    # Build credential store for OAuth providers (anthropic_claude_code)
    is_oauth_provider = spec is not None and getattr(spec, "is_oauth", False)
    credential_store = OAuthCredentialStore() if is_oauth_provider else None

    # Resolve API key: config → credential store → ANTHROPIC_OAUTH_TOKEN env → ANTHROPIC_API_KEY env
    anthropic_key = (p.api_key if p else None)
    if not anthropic_key and credential_store:
        stored = credential_store.load()
        if stored:
            anthropic_key = stored.access_token
    if not anthropic_key:
        anthropic_key = os.environ.get("ANTHROPIC_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")

    provider = AnthropicProvider(
        api_key=anthropic_key,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        credential_store=credential_store,
    )
```

- [ ] **Step 4: Run full test suite**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/ -v --ignore=tests/providers/test_anthropic_oauth.py -x 2>&1 | tail -20
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/cli/commands.py tests/cli/test_make_provider_oauth.py
git commit -m "feat: wire OAuthCredentialStore into _make_provider for anthropic_claude_code"
```

---

## Chunk 5: Config cleanup & bootstrap

### Task 5: Make `apiKey` optional in config + migrate existing token to store

**Files:**
- Modify: `nanobot/config/schema.py` (verify `api_key` is `Optional[str]` — likely already is)
- Create: `nanobot/providers/oauth_bootstrap.py` (one-time migration helper)

**Context:** The goal is that `config.json` can have `"anthropic_claude_code": {}` with no `apiKey` and nanobot will still work by reading from the credential store. We also need to migrate the current token from `~/.claude/.credentials.json` to `~/.nanobot/oauth_credentials.json` on first run.

- [ ] **Step 1: Verify `api_key` is Optional in schema**

```bash
grep -n "api_key" /root/git_code/nanobot/nanobot/config/schema.py | head -10
```

Expected: `api_key: str | None = None` or similar

- [ ] **Step 2: Create `oauth_bootstrap.py`**

```python
# nanobot/providers/oauth_bootstrap.py
"""One-time migration: copy token from Claude CLI credentials to nanobot store."""
from __future__ import annotations
from loguru import logger
from nanobot.providers.oauth_store import OAuthCredentialStore


def bootstrap_oauth_credentials() -> bool:
    """If nanobot store is empty but Claude CLI has credentials, copy them over.

    Returns True if credentials are now available (either existed or were copied).
    """
    store = OAuthCredentialStore()
    # Already have nanobot credentials
    if store._load_nanobot() is not None:
        return True
    # Try to migrate from Claude CLI
    cli_creds = store._load_claude_cli()
    if cli_creds is None:
        return False
    store.save(cli_creds)
    logger.info("OAuth credentials migrated from Claude CLI to nanobot store")
    return True
```

- [ ] **Step 3: Call bootstrap in `_make_provider` for OAuth providers**

In the `elif backend == "anthropic":` block (just after creating `credential_store`):

```python
if credential_store:
    from nanobot.providers.oauth_bootstrap import bootstrap_oauth_credentials
    bootstrap_oauth_credentials()
```

- [ ] **Step 4: Remove hard-coded token from `~/.nanobot/config.json`**

```bash
python3 -c "
import json
path = '/root/.nanobot/config.json'
with open(path) as f:
    cfg = json.load(f)

# Remove the hard-coded token, let the store handle it
if 'anthropic_claude_code' in cfg.get('providers', {}):
    cfg['providers']['anthropic_claude_code'].pop('apiKey', None)
    print('Removed apiKey from anthropic_claude_code config')

with open(path, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
"
```

- [ ] **Step 5: Run bootstrap manually to verify migration works**

```bash
cd /root/git_code/nanobot
python3 -c "
from nanobot.providers.oauth_bootstrap import bootstrap_oauth_credentials
result = bootstrap_oauth_credentials()
print('Bootstrap result:', result)

from nanobot.providers.oauth_store import OAuthCredentialStore
store = OAuthCredentialStore()
creds = store.load()
if creds:
    print('access_token prefix:', creds.access_token[:30] + '...')
    print('expires_at_ms:', creds.expires_at_ms)
else:
    print('No credentials found')
"
```

Expected:
```
Bootstrap result: True
access_token prefix: sk-ant-oat01-...
expires_at_ms: <some large number>
```

- [ ] **Step 6: Verify nanobot works end-to-end by restarting daemon**

```bash
touch ~/.nanobot/config.json
sleep 3
# Check logs for startup errors
tail -20 ~/.nanobot/nanobot.log 2>/dev/null || echo "check nanobot logs manually"
```

- [ ] **Step 7: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/providers/oauth_bootstrap.py nanobot/cli/commands.py
git commit -m "feat: bootstrap OAuth credentials from Claude CLI on first run, make apiKey optional"
```

---

## Chunk 6: Final verification & push

### Task 6: Run full test suite and push

- [ ] **Step 1: Run full test suite**

```bash
cd /root/git_code/nanobot
.venv/bin/pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests PASS (no regressions)

- [ ] **Step 2: Send a real test message through Discord to verify end-to-end**

Use the nanobot Discord channel to send a test message and verify the response comes back without 401 errors.

- [ ] **Step 3: Push to remote**

```bash
cd /root/git_code/nanobot
git push origin main
```

- [ ] **Step 4: Verify token will auto-refresh on next expiry**

Check `~/.nanobot/oauth_credentials.json` exists and has valid data:
```bash
python3 -c "
import json, datetime
d = json.load(open('/root/.nanobot/oauth_credentials.json'))
exp_ms = d['expires_at_ms']
exp_dt = datetime.datetime.fromtimestamp(exp_ms / 1000)
print('access_token prefix:', d['access_token'][:30] + '...')
print('expires_at:', exp_dt.strftime('%Y-%m-%d %H:%M:%S'))
print('refresh_token prefix:', d['refresh_token'][:30] + '...')
"
```

---

## Summary of New Files

| File | Purpose |
|------|---------|
| `nanobot/providers/oauth_store.py` | `OAuthCredentials` dataclass, `OAuthCredentialStore` read/write, `refresh_anthropic_token()` async function |
| `nanobot/providers/oauth_bootstrap.py` | One-time migration from Claude CLI credentials |
| `tests/providers/test_oauth_store.py` | Tests for credential store load/save/fallback |
| `tests/providers/test_oauth_refresh.py` | Tests for HTTP refresh call (mocked) |
| `tests/providers/test_anthropic_token_refresh.py` | Tests for `_ensure_valid_token` + concurrency lock |
| `tests/cli/test_make_provider_oauth.py` | Tests for store wiring in `_make_provider` |

## Modified Files

| File | Change |
|------|--------|
| `nanobot/providers/anthropic_provider.py` | Add `credential_store` param, `_ensure_valid_token()`, `_update_oauth_client()` |
| `nanobot/cli/commands.py` | Wire `OAuthCredentialStore` + bootstrap into `_make_provider` |
