"""Auth parsing and token management for AgentHiFive integration."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import jwt
from jwt.algorithms import ECAlgorithm

from .types import (
    AgentAuthConfig,
    AgentHiFiveRuntimeConfig,
    BearerAuthConfig,
)

logger = logging.getLogger(__name__)


class AgentHiFiveConfigError(ValueError):
    """Raised when the AgentHiFive integration config is incomplete or invalid."""


def _parse_jwk_text(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise AgentHiFiveConfigError("AgentHiFive private key is empty")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            return json.loads(decoded)
        except Exception as exc:  # pragma: no cover - defensive parsing branch
            raise AgentHiFiveConfigError(
                "AgentHiFive private key is not valid JSON/base64 JWK"
            ) from exc


def _load_private_key(env: dict[str, str]) -> dict[str, Any] | None:
    key_path = env.get("AGENTHIFIVE_PRIVATE_KEY_PATH", "").strip()
    if key_path:
        path = Path(key_path).expanduser()
        if not path.exists():
            raise AgentHiFiveConfigError(f"AgentHiFive private key path not found: {path}")
        return _parse_jwk_text(path.read_text(encoding="utf-8"))

    key_inline = env.get("AGENTHIFIVE_PRIVATE_KEY", "").strip()
    if key_inline:
        return _parse_jwk_text(key_inline)

    return None


def build_runtime_config_from_mcp_server(server_config: Any) -> AgentHiFiveRuntimeConfig:
    """Build adapter runtime config from the shared MCP server config block."""
    env = dict(getattr(server_config, "env", {}) or {})
    base_url = env.get("AGENTHIFIVE_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise AgentHiFiveConfigError(
            "AgentHiFive MCP config is missing AGENTHIFIVE_BASE_URL",
        )

    bearer_token = env.get("AGENTHIFIVE_BEARER_TOKEN", "").strip()
    if bearer_token:
        auth = BearerAuthConfig(mode="bearer", token=bearer_token)
    else:
        agent_id = env.get("AGENTHIFIVE_AGENT_ID", "").strip()
        private_key = _load_private_key(env)
        if not agent_id or not private_key:
            raise AgentHiFiveConfigError(
                "AgentHiFive auth required: set AGENTHIFIVE_BEARER_TOKEN, or "
                "(AGENTHIFIVE_PRIVATE_KEY_PATH or AGENTHIFIVE_PRIVATE_KEY) + AGENTHIFIVE_AGENT_ID",
            )
        token_audience = env.get("AGENTHIFIVE_TOKEN_AUDIENCE", "").strip() or None
        auth = AgentAuthConfig(
            mode="agent",
            agent_id=agent_id,
            private_key=private_key,
            token_audience=token_audience,
        )

    poll_interval_ms = env.get("AGENTHIFIVE_POLL_INTERVAL_MS", "").strip()
    timeout_ms = env.get("AGENTHIFIVE_HTTP_TIMEOUT_MS", "").strip()

    return AgentHiFiveRuntimeConfig(
        base_url=base_url,
        auth=auth,
        poll_interval=(float(poll_interval_ms) / 1000.0) if poll_interval_ms else 5.0,
        timeout=(float(timeout_ms) / 1000.0) if timeout_ms else 10.0,
    )


class AgentTokenManager:
    """Mint and cache short-lived AgentHiFive access tokens in memory."""

    def __init__(
        self,
        *,
        base_url: str,
        agent_id: str,
        private_key: dict[str, Any],
        token_audience: str | None = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.private_key = private_key
        self.token_audience = (token_audience or self.base_url).rstrip("/")
        self.timeout = timeout
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self._signing_key = ECAlgorithm.from_jwk(json.dumps(private_key))

    async def get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        async with self._lock:
            if not force_refresh and self._access_token and time.time() < self._expires_at - 60:
                return self._access_token

            access_token, expires_in = await self._exchange_token()
            self._access_token = access_token
            self._expires_at = time.time() + expires_in
            return access_token

    async def _exchange_token(self) -> tuple[str, int]:
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": self.agent_id,
                "sub": self.agent_id,
                "aud": self.token_audience,
                "iat": now,
                "exp": now + 30,
                "jti": str(uuid.uuid4()),
            },
            self._signing_key,
            algorithm="ES256",
        )

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.post(
                f"{self.base_url}/v1/agents/token",
                json={
                    "grant_type": "client_assertion",
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": assertion,
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )

        if not response.is_success:
            text = response.text
            raise RuntimeError(f"AgentHiFive token exchange failed: {response.status_code} {text}")

        data = response.json()
        return data["access_token"], int(data["expires_in"])
