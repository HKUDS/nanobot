"""Minimal HTTP client for AgentHiFive Vault API.

Handles approval polling and approval-bound replay execution.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .auth import AgentTokenManager
from .types import (
    AgentAuthConfig,
    AgentHiFiveAuthConfig,
    VaultBlockedResult,
    VaultExecuteResult,
)

logger = logging.getLogger(__name__)


def _resolve_download_dir() -> Path:
    from nanobot.config.paths import get_media_dir

    env_dir = os.environ.get("AGENTHIFIVE_DOWNLOAD_DIR", "").strip()
    if env_dir:
        path = Path(env_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    return get_media_dir("agenthifive")


def _sanitize_filename(filename: str) -> str:
    cleaned = Path(filename).name.strip().replace("\x00", "_")
    for char in '<>:"/\\|?*':
        cleaned = cleaned.replace(char, "_")
    cleaned = " ".join(cleaned.split())[:240]
    return cleaned or f"download-{time.time_ns()}"


def _resolve_filename(
    url: str,
    content_disposition: str | None,
    filename_hint: str | None = None,
) -> str:
    if filename_hint:
        return _sanitize_filename(filename_hint)

    if content_disposition:
        match = re.search(r'filename\*?\s*=\s*(?:UTF-8\'\'|")?([^";]+)', content_disposition, re.I)
        if match:
            value = match.group(1).replace('"', "").replace("'", "")
            try:
                return _sanitize_filename(unquote(value))
            except Exception:
                return _sanitize_filename(value)

    try:
        candidate = Path(urlparse(url).path).name
        if candidate:
            return _sanitize_filename(candidate)
    except Exception:
        pass

    return f"download-{time.time_ns()}"


class ReplayResult:
    """Result of an approval replay execution."""

    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self.body = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_fingerprint_mismatch(self) -> bool:
        return self.status_code == 403 and "payload does not match" in self.body.get("error", "")


class VaultClient:
    """Lightweight client for AgentHiFive approval and replay operations."""

    def __init__(self, base_url: str, auth: AgentHiFiveAuthConfig, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self._token_manager = (
            AgentTokenManager(
                base_url=self.base_url,
                agent_id=auth.agent_id,
                private_key=auth.private_key,
                token_audience=auth.token_audience,
                timeout=timeout,
            )
            if isinstance(auth, AgentAuthConfig)
            else None
        )

    async def start(self) -> None:
        """Warm auth on startup so early failures surface immediately."""
        if self._token_manager:
            await self._token_manager.get_token()

    async def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        if self._token_manager:
            token = await self._token_manager.get_token(force_refresh=force_refresh)
        else:
            token = self.auth.token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=await self._headers(),
                json=json_body,
            )

            if response.status_code == 401 and self._token_manager:
                logger.info("AgentHiFive token expired or rejected — refreshing and retrying")
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=await self._headers(force_refresh=True),
                    json=json_body,
                )

        return response

    async def poll_approval(self, approval_id: str) -> dict[str, Any]:
        """Check the status of a pending approval.

        Returns the approval object with at least a 'status' field:
        'pending', 'approved', 'denied', 'expired', 'consumed'.
        """
        resp = await self._request("GET", f"/v1/approvals/{approval_id}")
        if resp.status_code == 404:
            return {"status": "not_found"}
        resp.raise_for_status()
        data = resp.json()
        return data.get("approval", data)

    async def list_connections(self) -> list[dict[str, Any]]:
        """Return the active connections visible to the current agent."""
        resp = await self._request("GET", "/v1/connections")
        resp.raise_for_status()
        data = resp.json()
        connections = data.get("connections", data)
        return connections if isinstance(connections, list) else []

    async def execute(self, payload: dict[str, Any]) -> VaultExecuteResult:
        """Execute a provider request through POST /v1/vault/execute."""
        resp = await self._request("POST", "/v1/vault/execute", json_body=payload)

        if resp.status_code == 401:
            return VaultExecuteResult(
                status_code=401,
                headers={},
                body=None,
                audit_id="",
                blocked=VaultBlockedResult(
                    reason="Vault authentication failed — the agent's access token is invalid or expired.",
                    policy="vault-auth",
                    hint=(
                        "Reconnect the AgentHiFive integration with a fresh bootstrap secret "
                        "or valid bearer token."
                    ),
                ),
            )

        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400 and "application/json" not in content_type:
            preview = (resp.text or "")[:120].replace("\n", " ")
            return VaultExecuteResult(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                body=None,
                audit_id="",
                blocked=VaultBlockedResult(
                    reason=f"Vault returned HTTP {resp.status_code}: {preview or resp.reason_phrase}",
                    policy="vault-http",
                ),
            )

        try:
            result = resp.json()
        except ValueError:
            result = {}

        blocked = result.get("blocked")
        if blocked:
            return VaultExecuteResult(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                body=None,
                audit_id=str(result.get("auditId", "")),
                blocked=VaultBlockedResult(
                    reason=str(result.get("reason", "Blocked by policy")),
                    policy=str(result.get("policy", "unknown")),
                    hint=str(result.get("hint")) if result.get("hint") else None,
                ),
            )

        if resp.status_code == 202 and result.get("approvalRequired"):
            return VaultExecuteResult(
                status_code=202,
                headers=dict(resp.headers),
                body=None,
                audit_id=str(result.get("auditId", "")),
                blocked=VaultBlockedResult(
                    reason=str(result.get("hint", "This request requires human approval.")),
                    policy="step-up-approval",
                    hint=str(result.get("hint")) if result.get("hint") else None,
                    approval_request_id=(
                        str(result.get("approvalRequestId"))
                        if result.get("approvalRequestId")
                        else None
                    ),
                ),
            )

        if resp.status_code == 403:
            return VaultExecuteResult(
                status_code=403,
                headers=dict(resp.headers),
                body=None,
                audit_id=str(result.get("auditId", "")),
                blocked=VaultBlockedResult(
                    reason=str(result.get("error", "Denied by policy")),
                    policy="vault-policy",
                    hint=str(result.get("hint")) if result.get("hint") else None,
                ),
            )

        return VaultExecuteResult(
            status_code=int(result.get("status", resp.status_code)),
            headers=result.get("headers", {}) if isinstance(result.get("headers"), dict) else {},
            body=result.get("body"),
            audit_id=str(result.get("auditId", "")),
        )

    async def execute_replay(
        self,
        original_payload: dict[str, Any],
        approval_id: str,
        *,
        filename_hint: str | None = None,
    ) -> ReplayResult:
        """Re-submit the exact original request with approvalId for replay.

        The vault validates the request fingerprint matches the approved request.
        Returns a ReplayResult with status_code and body for explicit error handling.
        """
        payload = {**original_payload, "approvalId": approval_id}
        logger.info(
            "Replaying approved request: approval=%s method=%s url=%s",
            approval_id,
            payload.get("method"),
            payload.get("url"),
        )
        resp = await self._request("POST", "/v1/vault/execute", json_body=payload)
        if payload.get("download"):
            if 200 <= resp.status_code < 300:
                data = resp.content
                if not data:
                    return ReplayResult(
                        status_code=resp.status_code,
                        body={
                            "status": resp.status_code,
                            "error": "Download returned empty response",
                        },
                    )

                content_type = resp.headers.get("content-type", "application/octet-stream")
                filename = _resolve_filename(
                    str(payload.get("url", "")),
                    resp.headers.get("content-disposition"),
                    filename_hint=filename_hint,
                )
                download_dir = _resolve_download_dir()
                path = download_dir / filename
                path.write_bytes(data)
                return ReplayResult(
                    status_code=resp.status_code,
                    body={
                        "status": resp.status_code,
                        "success": True,
                        "path": str(path),
                        "filename": filename,
                        "contentType": content_type,
                        "sizeBytes": len(data),
                    },
                )

            try:
                body = resp.json()
            except ValueError:
                body = {"error": resp.text or f"Vault returned HTTP {resp.status_code}"}
            if isinstance(body, dict):
                body.setdefault("status", resp.status_code)
            return ReplayResult(status_code=resp.status_code, body=body)

        return ReplayResult(status_code=resp.status_code, body=resp.json())
