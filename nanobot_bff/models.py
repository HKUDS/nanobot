"""Pydantic models for Nanobot BFF API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TrajectoryTuple(BaseModel):
    """(s, a, o, r) tuple for a single conversation turn."""

    turn_id: int
    user_input: str = Field(default="", description="用户输入")
    agent_response: str = Field(default="", description="Agent回复")
    reward: float = Field(default=1.0, description="奖励值 r")
    iteration_traces: list = Field(default_factory=list, description="迭代级 (s,a,o,r) 轨迹")
    timestamp: datetime = Field(default_factory=datetime.now)


class ConversationCreate(BaseModel):
    """Request to create a new conversation."""

    title: str = Field(default="新对话", description="对话标题")
    model: str = Field(default="deepseek-chat", description="使用的模型")


class ConversationResponse(BaseModel):
    """Response containing conversation metadata."""

    id: int
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0


class MessageSend(BaseModel):
    """Request to send a message to the agent."""

    conversation_id: int
    content: str


class MessageResponse(BaseModel):
    """Response containing the agent's reply and trajectory data."""

    conversation_id: int
    turn_id: int
    content: str
    trajectory: TrajectoryTuple
    usage: dict[str, int] = Field(default_factory=dict)
    iteration_count: int = 0


class TraceResponse(BaseModel):
    """Response containing a single (s,a,o,r) trajectory tuple."""

    id: int
    conversation_id: int
    branch_id: str
    iteration: int
    s_t: dict[str, Any]
    a_t: dict[str, Any]
    o_t: dict[str, Any]
    r_t: float
    created_at: datetime


class BranchResponse(BaseModel):
    """Response containing branch information."""

    id: int
    conversation_id: int
    branch_id: str
    branch_name: str
    parent_branch_id: str | None
    created_at: datetime


class ForkBranchRequest(BaseModel):
    """Request to fork a new branch."""

    parent_branch_id: str
    new_branch_name: str


class ForkBranchResponse(BaseModel):
    """Response after forking a branch."""

    branch_id: str
    parent_branch_id: str
    branch_name: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    nanobot_connected: bool
    database: str
    active_conversations: int = 0
    active_branches: int = 0
