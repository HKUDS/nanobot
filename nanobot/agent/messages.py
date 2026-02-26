"""Structured message model for the dual-layer architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class MessageType(str, Enum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ARTIFACT = "artifact"
    USER_ATTACHMENT = "user_attachment"
    SYSTEM = "system"


@dataclass
class ArtifactInfo:
    """Metadata for an artifact produced by a tool call."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    action: str = "create"
    filename: str | None = None
    mime_type: str | None = None
    created_by_tool_call_id: str | None = None


@dataclass
class AgentMessage:
    """
    Rich message wrapper for the dual-layer architecture.

    Carries both the LLM-compatible payload and optional application-layer
    metadata (artifacts, attachment info, semantic tags).  The ``llm_dict``
    property strips away everything the LLM cannot understand.
    """

    role: str
    content: Any
    msg_type: MessageType = MessageType.TEXT
    metadata: dict[str, Any] = field(default_factory=dict)

    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    reasoning_content: str | None = None

    artifact: ArtifactInfo | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def llm_dict(self) -> dict[str, Any]:
        """Convert to LLM-compatible dict, dropping application metadata."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_name:
            msg["name"] = self.tool_name
        if self.reasoning_content is not None:
            msg["reasoning_content"] = self.reasoning_content
        return msg

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentMessage:
        """Lift a plain LLM dict into an AgentMessage."""
        role = d["role"]
        if role == "tool":
            msg_type = MessageType.TOOL_RESULT
        elif d.get("tool_calls"):
            msg_type = MessageType.TOOL_CALL
        elif role == "system":
            msg_type = MessageType.SYSTEM
        else:
            msg_type = MessageType.TEXT

        return cls(
            role=role,
            content=d.get("content"),
            msg_type=msg_type,
            tool_calls=d.get("tool_calls"),
            tool_call_id=d.get("tool_call_id"),
            tool_name=d.get("name"),
            reasoning_content=d.get("reasoning_content"),
        )

    @staticmethod
    def to_llm_list(messages: list[AgentMessage]) -> list[dict[str, Any]]:
        return [m.llm_dict for m in messages]

    @staticmethod
    def from_dict_list(messages: list[dict[str, Any]]) -> list[AgentMessage]:
        return [AgentMessage.from_dict(m) for m in messages]

    @staticmethod
    def filter_by_type(
        messages: list[AgentMessage], msg_type: MessageType,
    ) -> list[AgentMessage]:
        return [m for m in messages if m.msg_type == msg_type]

    @staticmethod
    def filter_by_tag(
        messages: list[AgentMessage], tag: str,
    ) -> list[AgentMessage]:
        return [m for m in messages if tag in m.tags]

    @staticmethod
    def get_artifacts(messages: list[AgentMessage]) -> list[AgentMessage]:
        """Return all messages that carry artifact metadata."""
        return [m for m in messages if m.artifact is not None]

    @staticmethod
    def get_latest_artifacts(
        messages: list[AgentMessage], n: int = 3,
    ) -> list[AgentMessage]:
        """Return the *n* most recent artifact messages."""
        return AgentMessage.get_artifacts(messages)[-n:]
