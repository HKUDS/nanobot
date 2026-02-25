"""PKCE and authorization helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
from typing import Any


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _decode_base64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _generate_pkce() -> tuple[str, str]:
    verifier = _base64url(os.urandom(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


def _create_state() -> str:
    return _base64url(os.urandom(16))


def _parse_authorization_input(raw: str) -> tuple[str | None, str | None]:
    value = raw.strip()
    if not value:
        return None, None
    try:
        url = urllib.parse.urlparse(value)
        qs = urllib.parse.parse_qs(url.query)
        code = qs.get("code", [None])[0]
        state = qs.get("state", [None])[0]
        if code:
            return code, state
    except Exception:
        pass

    if "#" in value:
        parts = value.split("#", 1)
        return parts[0] or None, parts[1] or None

    if "code=" in value:
        qs = urllib.parse.parse_qs(value)
        return qs.get("code", [None])[0], qs.get("state", [None])[0]

    return value, None


def _decode_account_id(
    access_token: str,
    jwt_claim_path: str | None,
    account_id_claim: str | None,
) -> str | None:
    if not jwt_claim_path or not account_id_claim:
        return None
    parts = access_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT token")
    payload = json.loads(_decode_base64url(parts[1]).decode("utf-8"))
    auth = payload.get(jwt_claim_path) or {}
    account_id = auth.get(account_id_claim)
    if not account_id:
        return None
    return str(account_id)


def _parse_token_payload(payload: dict[str, Any], missing_message: str) -> tuple[str, str, int]:
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access or not refresh or not isinstance(expires_in, int):
        raise RuntimeError(missing_message)
    return access, refresh, expires_in
