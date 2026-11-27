"""Google AI Ultra Desktop OAuth. Only the token endpoint uses DPoP; model calls use Bearer."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import stat
import tempfile
import threading
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlencode

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nanobot.config.paths import get_config_path
from nanobot.utils.atomic_file import read_atomic_bytes, replace_atomic

_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_QUOTA = "https://www.googleapis.com/auth/generative-language.peruserquota"
_CALLBACK = "/oauth2callback"
_CALLBACK_TIMEOUT = 600
_CLIENT_ID = "NANOBOT_GOOGLE_AI_PLAN_CLIENT_ID"
_CLIENT_SECRET = "NANOBOT_GOOGLE_AI_PLAN_CLIENT_SECRET"
_REAUTH = "No usable Google AI Ultra plan login. Sign in again."


class GoogleAIPlanOAuthError(RuntimeError):
    """Sign-in or refresh failed; the message can be shown to the user."""


class _Tokens(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    access_token: str = Field(min_length=1, repr=False)
    refresh_token: str | None = Field(default=None, min_length=1, repr=False)
    expires_in: int = Field(default=3599, gt=0)
    scope: str = ""
    id_token: str | None = Field(default=None, repr=False)


class _Credential(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    client_id: str
    access: str = Field(min_length=1, repr=False)
    refresh: str = Field(min_length=1, repr=False)
    expires: int
    private_scalar: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    nonce: str | None = Field(default=None, repr=False)


def _desktop_client() -> dict[str, str]:
    client_id = os.environ.get(_CLIENT_ID, "").strip()
    secret = os.environ.get(_CLIENT_SECRET, "").strip()
    if not client_id or not secret:
        raise GoogleAIPlanOAuthError(
            f"Set {_CLIENT_ID} and {_CLIENT_SECRET} for your approved Google Desktop app."
        )
    return {"client_id": client_id, "client_secret": secret}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _digest(value: str) -> str:
    return _b64(hashlib.sha256(value.encode()).digest())


def _proof(key: ec.EllipticCurvePrivateKey, jti: str, nonce: str | None, iat: int | None) -> str:
    point = key.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "x": _b64(point.x.to_bytes(32, "big")),
           "y": _b64(point.y.to_bytes(32, "big"))}
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk}
    claims = {"jti": jti, "htm": "POST", "htu": _TOKEN, "iat": int(time.time()) if iat is None else iat}
    if nonce is not None:
        claims["nonce"] = nonce
    signing_input = ".".join(_b64(json.dumps(part).encode()) for part in (header, claims))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def _token_grant(
    form: dict[str, str], key: ec.EllipticCurvePrivateKey, proxy: str | None, nonce: str | None = None,
) -> tuple[_Tokens, str | None]:
    # The single-use code must be hashed for jti. Never retry its exchange.
    code = form.get("code")
    iat = None
    retried_nonce = False
    try:
        with httpx.Client(proxy=proxy, timeout=30, trust_env=False, follow_redirects=False) as client:
            while True:
                proof = _proof(key, _digest(code) if code else secrets.token_urlsafe(24), nonce, iat)
                response = client.post(_TOKEN, data=form, headers={"DPoP": proof, "Accept": "application/json"})
                next_nonce = response.headers.get("DPoP-Nonce")
                if response.status_code == 200:
                    return _Tokens.model_validate_json(response.content), next_nonce or nonce
                payload = response.json()
                error = cast(dict[str, object], payload).get("error") if isinstance(payload, dict) else None
                if not code and response.status_code in (400, 401):
                    if error == "use_dpop_nonce" and next_nonce and next_nonce != nonce and not retried_nonce:
                        nonce, retried_nonce = next_nonce, True
                        continue
                    if error == "invalid_dpop_proof" and iat is None and response.headers.get("Date"):
                        iat = int(parsedate_to_datetime(response.headers["Date"]).timestamp())
                        continue
                if not code and error in ("invalid_grant", "unauthorized_client"):
                    raise GoogleAIPlanOAuthError(_REAUTH)
                raise GoogleAIPlanOAuthError(f"Google token request failed (HTTP {response.status_code}).")
    except (ValueError, OverflowError, httpx.HTTPError, httpx.InvalidURL):
        # Never include callback queries, HTTP response bodies, proxy URLs, or validation inputs.
        raise GoogleAIPlanOAuthError("Google token request failed. Check the connection and try again.") from None


class _IdClaims(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    iss: str
    aud: str
    exp: int
    nonce: str


def _validate_id_token(token: str | None, nonce: str, client_id: str) -> None:
    # OIDC Core 3.1.3.7: only for an ID token received directly from the fixed token endpoint over TLS.
    try:
        _, payload, _ = (token or "").split(".")
        claims = _IdClaims.model_validate_json(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if (claims.iss in ("accounts.google.com", "https://accounts.google.com") and claims.aud == client_id
                and claims.exp > time.time() - 60 and claims.nonce == nonce):
            return
    except ValueError:
        pass
    raise GoogleAIPlanOAuthError("Google sign-in returned an invalid ID token.")


def _authorize(on_url: Callable[[str], None], params: dict[str, str]) -> tuple[str, str]:
    result: queue.Queue[str | None] = queue.Queue(maxsize=1)
    state = params["state"].encode()

    class Handler(BaseHTTPRequestHandler):
        timeout = 3

        def log_message(self, format: str, *args: object) -> None:
            pass  # HTTP request lines contain the authorization code.

        def do_GET(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            if path != _CALLBACK or self.headers.get_all("Host") != [authority]:
                self.send_error(404)
                return
            try:
                values = parse_qs(query, keep_blank_values=True, max_num_fields=32)
            except ValueError:
                self.send_error(400)
                return
            states = values.get("state", [])
            if len(states) != 1 or not secrets.compare_digest(states[0].encode(), state):
                self.send_error(400)
                return  # Unrelated callbacks must not cancel the real sign-in.
            codes = values.get("code", [])
            code = codes[0] if len(codes) == 1 and codes[0] and "error" not in values else None
            try:
                result.put_nowait(code)
            except queue.Full:
                self.send_error(409)
                return
            self.send_response(200 if code else 400)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Return to nanobot for the sign-in result. You can close this tab.")

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        authority = f"127.0.0.1:{server.server_port}"
        redirect = f"http://{authority}{_CALLBACK}"
        url = f"{_AUTHORIZE}?{urlencode({**params, 'redirect_uri': redirect})}"
        worker = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + _CALLBACK_TIMEOUT
            on_url(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            code = result.get(timeout=remaining)
            if not code:
                raise GoogleAIPlanOAuthError("Google sign-in was denied or returned no code.")
            return code, redirect
        except queue.Empty:
            raise GoogleAIPlanOAuthError("Google sign-in timed out. Start a new sign-in.") from None
        finally:
            server.shutdown()
            worker.join()


def _storage_path(*, create: bool = False) -> Path:
    path = get_config_path().parent / "auth" / "google-ai-plan.json"
    directory = path.parent
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return path
    if not stat.S_ISDIR(info.st_mode) or (os.name == "posix" and (
        info.st_uid != os.getuid() or info.st_mode & 0o022
    )):
        raise GoogleAIPlanOAuthError("Google credential directory is not private.")
    if create and os.name == "posix" and info.st_mode & 0o077:
        directory.chmod(0o700)
    return path


def _lock(path: Path) -> FileLock:
    return FileLock(path.with_suffix(".lock"), mode=0o600, timeout=100)


def _load(path: Path) -> _Credential:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or (os.name == "posix" and (
            info.st_uid != os.getuid() or info.st_mode & 0o077
        )):
            raise GoogleAIPlanOAuthError("Google credential file is not private.")
        return _Credential.model_validate_json(read_atomic_bytes(path, max_bytes=128 * 1024))
    except (FileNotFoundError, ValidationError):
        raise GoogleAIPlanOAuthError(_REAUTH) from None


def _save(path: Path, credential: _Credential) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".google-ai-plan-")  # 0600 before any data is written
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(credential.model_dump_json().encode())
            stream.flush()
            os.fsync(stream.fileno())
        replace_atomic(Path(name), path)
    finally:
        Path(name).unlink(missing_ok=True)


def login_google_ai_plan(*, on_url: Callable[[str], None], proxy: str | None = None) -> None:
    """Pass the consent URL to the CLI and save a validated login for the active profile."""
    client = _desktop_client()
    path = _storage_path(create=True)
    verifier, state, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    key = ec.generate_private_key(ec.SECP256R1())
    code, redirect_uri = _authorize(on_url, {
        "client_id": client["client_id"], "response_type": "code", "scope": f"openid email profile {_QUOTA}",
        "code_challenge": _digest(verifier), "code_challenge_method": "S256", "state": state, "nonce": nonce,
    })
    tokens, _ = _token_grant({**client, "grant_type": "authorization_code", "code": code,
                              "code_verifier": verifier, "redirect_uri": redirect_uri}, key, proxy)
    if not tokens.refresh_token:
        raise GoogleAIPlanOAuthError("Google sign-in returned no refresh token.")
    if _QUOTA not in tokens.scope.split():
        raise GoogleAIPlanOAuthError("Google did not grant access to the Google AI Ultra plan.")
    _validate_id_token(tokens.id_token, nonce, client["client_id"])
    credential = _Credential(client_id=client["client_id"], access=tokens.access_token, refresh=tokens.refresh_token,
                             expires=int(time.time()) + tokens.expires_in,
                             private_scalar=key.private_numbers().private_value.to_bytes(32, "big").hex())
    with _lock(path):
        _save(path, credential)


def get_google_ai_plan_token(*, proxy: str | None = None) -> str:
    """Return a bearer access token, refreshing within five minutes of expiry."""
    path = _storage_path()
    if not path.parent.exists():
        raise GoogleAIPlanOAuthError(_REAUTH)
    with _lock(path):
        credential = _load(path)
        if credential.expires > time.time() + 300:
            return credential.access
        client = _desktop_client()
        if client["client_id"] != credential.client_id:
            raise GoogleAIPlanOAuthError("The Google Desktop client changed. Sign in again.")
        try:
            key = ec.derive_private_key(int(credential.private_scalar, 16), ec.SECP256R1())
        except ValueError:
            raise GoogleAIPlanOAuthError(_REAUTH) from None
        tokens, nonce = _token_grant({**client, "grant_type": "refresh_token", "refresh_token": credential.refresh},
                                     key, proxy, credential.nonce)
        credential.access = tokens.access_token
        credential.refresh = tokens.refresh_token or credential.refresh
        credential.expires = int(time.time()) + tokens.expires_in
        credential.nonce = nonce
        _save(path, credential)
        return credential.access


def has_google_ai_plan_login() -> bool:
    """Local presence check only: does not refresh, contact Google, or require a client secret."""
    try:
        _load(_storage_path())
        return True
    except (GoogleAIPlanOAuthError, OSError):
        return False


def logout_google_ai_plan() -> bool:
    """Forget this profile's tokens and DPoP key without remotely revoking the grant."""
    path = _storage_path()
    if not path.parent.exists():
        return False
    with _lock(path):
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True
