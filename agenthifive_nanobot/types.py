"""Shared types for the AgentHiFive nanobot adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class PendingApproval:
    """A vault execute request that returned 202 and is awaiting approval."""

    approval_request_id: str
    original_payload: dict[str, Any]
    download_filename: str | None = None
    session_key: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    sender_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "approvalRequestId": self.approval_request_id,
            "originalPayload": self.original_payload,
            "downloadFilename": self.download_filename,
            "sessionKey": self.session_key,
            "channel": self.channel,
            "chatId": self.chat_id,
            "senderId": self.sender_id,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PendingApproval:
        return cls(
            approval_request_id=d["approvalRequestId"],
            original_payload=d["originalPayload"],
            download_filename=d.get("downloadFilename"),
            session_key=d.get("sessionKey"),
            channel=d.get("channel"),
            chat_id=d.get("chatId"),
            sender_id=d.get("senderId"),
            created_at=d.get("createdAt", ""),
        )


@dataclass
class ApprovalResult:
    """The outcome of a resolved approval."""

    approval_request_id: str
    status: str  # "approved", "denied", "expired"
    execution_result: dict[str, Any] | None = None  # vault execute response on success
    error: str | None = None  # error message on failure


@dataclass
class AgentAuthConfig:
    """Long-lived agent auth material used to mint short-lived access tokens."""

    mode: Literal["agent"]
    agent_id: str
    private_key: dict[str, Any]
    token_audience: str | None = None


@dataclass
class BearerAuthConfig:
    """Static bearer-token auth for manual testing / override scenarios."""

    mode: Literal["bearer"]
    token: str


AgentHiFiveAuthConfig = AgentAuthConfig | BearerAuthConfig


@dataclass
class AgentHiFiveRuntimeConfig:
    """Resolved runtime config shared by MCP and the nanobot-side adapter."""

    base_url: str
    auth: AgentHiFiveAuthConfig
    poll_interval: float = 5.0
    timeout: float = 10.0


@dataclass
class VaultBlockedResult:
    """Policy/auth block details returned by the vault proxy."""

    reason: str
    policy: str
    hint: str | None = None
    approval_request_id: str | None = None


@dataclass
class VaultExecuteResult:
    """Normalized result from a vault execute request."""

    status_code: int
    headers: dict[str, Any]
    body: Any
    audit_id: str
    blocked: VaultBlockedResult | None = None
