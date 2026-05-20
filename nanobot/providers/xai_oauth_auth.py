"""xAI Grok OAuth credential flow and storage."""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from filelock import FileLock

DEFAULT_XAI_API_BASE = "https://api.x.ai/v1"
DEFAULT_XAI_AUTH_ISSUER = "https://auth.x.ai"
DEFAULT_XAI_DISCOVERY_URL = f"{DEFAULT_XAI_AUTH_ISSUER}/.well-known/openid-configuration"
DEFAULT_XAI_REDIRECT_URI = "http://127.0.0.1:56121/callback"
DEFAULT_XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
DEFAULT_XAI_SCOPE = "openid profile email offline_access grok-cli:access api:access"

_SERVICE_NAME = "nanobot.xai_oauth"
_SECRET_USERNAME = "default"
_TOKEN_SKEW_SECONDS = 60
_LOGIN_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class XaiOAuthEndpoints:
    authorization_endpoint: str
    token_endpoint: str


@dataclass(frozen=True)
class XaiOAuthCredential:
    access_token: str
    refresh_token: str = ""
    expires_at: float | None = None
    account_id: str | None = None
    token_type: str = "Bearer"
    api_base: str = DEFAULT_XAI_API_BASE
    storage: str = "unknown"

    @property
    def is_expiring(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time() + _TOKEN_SKEW_SECONDS


def _nanobot_home() -> Path:
    override = os.environ.get("NANOBOT_HOME")
    if override:
        return Path(override).expanduser()
    from nanobot.config.loader import get_config_path

    return get_config_path().parent


def _auth_dir() -> Path:
    return _nanobot_home() / "auth"


def get_xai_oauth_metadata_path() -> Path:
    """Return the non-secret xAI OAuth metadata path."""
    return _auth_dir() / "xai-oauth.json"


def _lock_path() -> Path:
    return get_xai_oauth_metadata_path().with_suffix(".lock")


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        path.parent.chmod(0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with suppress(OSError):
        tmp.chmod(0o600)
    tmp.replace(path)
    with suppress(OSError):
        path.chmod(0o600)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _keyring_set(tokens: dict[str, Any]) -> bool:
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.set_password(_SERVICE_NAME, _SECRET_USERNAME, json.dumps(tokens))
        return True
    except Exception:
        return False


def _keyring_get() -> dict[str, Any] | None:
    try:
        import keyring  # type: ignore[import-not-found]

        raw = keyring.get_password(_SERVICE_NAME, _SECRET_USERNAME)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _keyring_delete() -> None:
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.delete_password(_SERVICE_NAME, _SECRET_USERNAME)
    except Exception:
        pass


def _token_payload(credential: XaiOAuthCredential) -> dict[str, Any]:
    return {
        "access_token": credential.access_token,
        "refresh_token": credential.refresh_token,
        "expires_at": credential.expires_at,
        "token_type": credential.token_type,
    }


def save_xai_oauth_credential(credential: XaiOAuthCredential) -> XaiOAuthCredential:
    """Persist xAI OAuth tokens, preferring OS keychain storage."""
    with FileLock(str(_lock_path())):
        tokens = _token_payload(credential)
        metadata: dict[str, Any] = {
            "provider": "xai_oauth",
            "api_base": credential.api_base,
            "account_id": credential.account_id,
            "expires_at": credential.expires_at,
            "updated_at": int(time.time()),
        }
        if _keyring_set(tokens):
            metadata["storage"] = "keyring"
        else:
            metadata["storage"] = "file"
            metadata["tokens"] = tokens
        _write_private_json(get_xai_oauth_metadata_path(), metadata)
        return XaiOAuthCredential(
            access_token=credential.access_token,
            refresh_token=credential.refresh_token,
            expires_at=credential.expires_at,
            account_id=credential.account_id,
            token_type=credential.token_type,
            api_base=credential.api_base,
            storage=str(metadata["storage"]),
        )


def load_xai_oauth_credential() -> XaiOAuthCredential | None:
    """Load xAI OAuth credentials from keyring or the private file fallback."""
    path = get_xai_oauth_metadata_path()
    if not path.exists():
        return None
    with FileLock(str(_lock_path())):
        try:
            metadata = _read_json(path)
        except (OSError, json.JSONDecodeError):
            return None

        storage = str(metadata.get("storage") or "file")
        tokens = _keyring_get() if storage == "keyring" else metadata.get("tokens")
        if not isinstance(tokens, dict):
            return None
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            return None

        return XaiOAuthCredential(
            access_token=access_token,
            refresh_token=str(tokens.get("refresh_token") or ""),
            expires_at=_as_float(tokens.get("expires_at") or metadata.get("expires_at")),
            account_id=_as_str(metadata.get("account_id")),
            token_type=str(tokens.get("token_type") or "Bearer"),
            api_base=str(metadata.get("api_base") or DEFAULT_XAI_API_BASE),
            storage=storage,
        )


def delete_xai_oauth_credentials() -> list[Path]:
    """Delete persisted xAI OAuth credentials and return removed local paths."""
    removed: list[Path] = []
    path = get_xai_oauth_metadata_path()
    lock_path = _lock_path()
    with FileLock(str(lock_path)):
        _keyring_delete()
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    return removed


def get_xai_oauth_login_status() -> XaiOAuthCredential | None:
    return load_xai_oauth_credential()


def pkce_challenge(verifier: str) -> str:
    digest = sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _new_pkce_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")


def build_xai_authorization_url(
    endpoints: XaiOAuthEndpoints,
    *,
    verifier: str,
    state: str,
    nonce: str | None = None,
    redirect_uri: str = DEFAULT_XAI_REDIRECT_URI,
) -> str:
    params = {
        "response_type": "code",
        "client_id": DEFAULT_XAI_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": DEFAULT_XAI_SCOPE,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce or secrets.token_urlsafe(16),
        "plan": "generic",
        "referrer": "nanobot",
    }
    return f"{endpoints.authorization_endpoint}?{urlencode(params)}"


def discover_xai_oauth_endpoints() -> XaiOAuthEndpoints:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True, trust_env=True) as client:
            response = client.get(DEFAULT_XAI_DISCOVERY_URL)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        payload = {}

    endpoints = XaiOAuthEndpoints(
        authorization_endpoint=str(
            payload.get("authorization_endpoint")
            or f"{DEFAULT_XAI_AUTH_ISSUER}/authorize"
        ),
        token_endpoint=str(
            payload.get("token_endpoint")
            or f"{DEFAULT_XAI_AUTH_ISSUER}/oauth/token"
        ),
    )
    _validate_xai_endpoint(endpoints.authorization_endpoint, "authorization_endpoint")
    _validate_xai_endpoint(endpoints.token_endpoint, "token_endpoint")
    return endpoints


def _validate_xai_endpoint(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host == "x.ai" or host.endswith(".x.ai")):
        raise RuntimeError(f"Refusing non-xAI OAuth {label}: {url}")


def _parse_callback_value(raw: str) -> tuple[str, str | None]:
    raw = raw.strip()
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        params = parse_qs(parsed.query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [None])[0]
        if not code:
            raise RuntimeError("OAuth callback URL did not contain a code.")
        return code, state
    if raw.startswith("?") or "=" in raw:
        params = parse_qs(raw.lstrip("?"))
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [None])[0]
        if not code:
            raise RuntimeError("OAuth callback query did not contain a code.")
        return code, state
    if raw:
        return raw, None
    raise RuntimeError("No OAuth code provided.")


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    data = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(data.encode("ascii"))
        payload = json.loads(decoded)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _credential_from_token_response(payload: dict[str, Any], previous: XaiOAuthCredential | None = None) -> XaiOAuthCredential:
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise RuntimeError("xAI token response did not include an access token.")

    claims = _decode_jwt_payload(access_token)
    id_claims = _decode_jwt_payload(str(payload.get("id_token") or ""))
    expires_at = _as_float(payload.get("expires_at"))
    if expires_at is None:
        expires_in = _as_float(payload.get("expires_in"))
        expires_at = time.time() + expires_in if expires_in else _as_float(claims.get("exp"))

    account_id = (
        _as_str(id_claims.get("email"))
        or _as_str(id_claims.get("preferred_username"))
        or _as_str(id_claims.get("sub"))
        or _as_str(claims.get("sub"))
        or (previous.account_id if previous else None)
    )
    refresh_token = str(payload.get("refresh_token") or (previous.refresh_token if previous else ""))

    return XaiOAuthCredential(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        account_id=account_id,
        token_type=str(payload.get("token_type") or (previous.token_type if previous else "Bearer")),
        api_base=previous.api_base if previous else DEFAULT_XAI_API_BASE,
    )


def exchange_xai_oauth_code(
    code: str,
    *,
    verifier: str,
    endpoints: XaiOAuthEndpoints | None = None,
    redirect_uri: str = DEFAULT_XAI_REDIRECT_URI,
) -> XaiOAuthCredential:
    endpoints = endpoints or discover_xai_oauth_endpoints()
    challenge = pkce_challenge(verifier)
    with httpx.Client(timeout=30.0, follow_redirects=True, trust_env=True) as client:
        response = client.post(
            endpoints.token_endpoint,
            headers={"Accept": "application/json"},
            data={
                "grant_type": "authorization_code",
                "client_id": DEFAULT_XAI_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"xAI token exchange failed: HTTP {response.status_code}: {response.text[:500]}")
    return _credential_from_token_response(response.json())


def refresh_xai_oauth_credential(credential: XaiOAuthCredential | None = None) -> XaiOAuthCredential:
    credential = credential or load_xai_oauth_credential()
    if not credential or not credential.refresh_token:
        raise RuntimeError("xAI Grok OAuth is not logged in. Run: nanobot provider login xai-oauth")

    endpoints = discover_xai_oauth_endpoints()
    with httpx.Client(timeout=30.0, follow_redirects=True, trust_env=True) as client:
        response = client.post(
            endpoints.token_endpoint,
            headers={"Accept": "application/json"},
            data={
                "grant_type": "refresh_token",
                "client_id": DEFAULT_XAI_CLIENT_ID,
                "refresh_token": credential.refresh_token,
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"xAI token refresh failed: HTTP {response.status_code}: {response.text[:500]}")
    return save_xai_oauth_credential(_credential_from_token_response(response.json(), previous=credential))


def resolve_xai_oauth_credential(*, force_refresh: bool = False) -> XaiOAuthCredential:
    credential = load_xai_oauth_credential()
    if not credential:
        raise RuntimeError("xAI Grok OAuth is not logged in. Run: nanobot provider login xai-oauth")
    if force_refresh or credential.is_expiring:
        credential = refresh_xai_oauth_credential(credential)
    return credential


def login_xai_oauth_interactive(
    print_fn: Callable[[str], None] | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    open_browser: bool = True,
    manual_paste: bool = False,
    timeout_seconds: int = _LOGIN_TIMEOUT_SECONDS,
) -> XaiOAuthCredential:
    """Run browser PKCE login and persist xAI OAuth credentials."""
    printer = print_fn or print
    prompt = prompt_fn or input
    endpoints = discover_xai_oauth_endpoints()
    verifier = _new_pkce_verifier()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    authorize_url = build_xai_authorization_url(
        endpoints,
        verifier=verifier,
        state=state,
        nonce=nonce,
    )

    callback = _LoopbackCallback()
    server_started = False if manual_paste else callback.start()
    printer(f"Open: {authorize_url}")
    if open_browser:
        with suppress(Exception):
            webbrowser.open(authorize_url)

    result: dict[str, str] | None = None
    if manual_paste:
        printer("Paste the callback URL or xAI fallback code after authorization.")
    elif server_started:
        try:
            result = callback.wait(timeout_seconds)
        finally:
            callback.stop()
    else:
        printer("Loopback port 56121 is unavailable; paste the callback URL or xAI fallback code.")

    if result:
        code = result.get("code") or ""
        returned_state = result.get("state")
    else:
        pasted = prompt("Paste callback URL or fallback code")
        code, returned_state = _parse_callback_value(pasted)

    if not code:
        raise RuntimeError("OAuth login did not return a code.")
    if returned_state and returned_state != state:
        raise RuntimeError("OAuth state mismatch. Please retry login.")

    credential = exchange_xai_oauth_code(code, verifier=verifier, endpoints=endpoints)
    return save_xai_oauth_credential(credential)


class _LoopbackCallback:
    def __init__(self) -> None:
        self._event = Event()
        self._result: dict[str, str] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> bool:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                code = (params.get("code") or [""])[0]
                state = (params.get("state") or [""])[0]
                if parsed.path != "/callback" or not code:
                    self.send_response(404)
                    self.end_headers()
                    return
                owner._result = {"code": code, "state": state}
                owner._event.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body>nanobot xAI OAuth complete. You may close this tab.</body></html>")

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        class Server(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        try:
            self._server = Server(("127.0.0.1", 56121), Handler)
        except OSError:
            return False
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout_seconds: int) -> dict[str, str] | None:
        if self._event.wait(timeout_seconds):
            return dict(self._result)
        return None

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=1)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
